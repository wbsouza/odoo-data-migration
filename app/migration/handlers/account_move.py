import logging
from typing import Dict, List, Optional, Any

from .base import DomainHandler

from ..core.odoo_connection import OdooConnectionProvider, DESTINATION, SOURCE
from ..core.database import DBConnectionProvider, find_id_by_old_id, find_record_by_old_id


class AccountMoveHandler(DomainHandler):

    def __init__(
            self,
            odoo_provider: OdooConnectionProvider,
            db_provider: DBConnectionProvider,
            model_name: str
    ):
        super().__init__(odoo_provider, db_provider, model_name)

    def get_new_product_id_from_old_id(self, x_old_id: Optional[int]) -> Optional[int]:
        if not x_old_id:
            return None
        conn = self._db_provider.get_connection(DESTINATION)
        return find_id_by_old_id(conn, 'product_product', x_old_id)

    # --- Mapping helpers (source x_old_id -> destination new id) ---
    def get_new_user_id_from_old_id(self, x_old_id: Optional[int]) -> Optional[int]:
        """Map source res.users.id to destination id via x_old_id."""
        if not x_old_id:
            return None
        conn = self._db_provider.get_connection(DESTINATION)
        return find_id_by_old_id(conn, 'res_users', x_old_id)

    def get_new_partner_id_from_old_id(self, x_old_id: Optional[int]) -> Optional[int]:
        """Map source res.partner.id to destination id via x_old_id."""
        if not x_old_id:
            return None
        conn = self._db_provider.get_connection(DESTINATION)
        return find_id_by_old_id(conn, 'res_partner', x_old_id)

    def get_new_partner_shipping_id_from_old_id(self, x_old_id: Optional[int]) -> Optional[int]:
        """Map shipping partner; if no separate shipping mapping, fallback to partner mapping."""
        return self.get_new_partner_id_from_old_id(x_old_id)

    def _get_invoice_journal(self, company, journal_type='sale'):
        """Return a browsed journal by type (sale/purchase) for the given company using destination env."""
        journal_model = self.get_dst_model('account.journal')
        ids = journal_model.search([('type', '=', journal_type), ('company_id', '=', company.id)], limit=1)
        if not ids:
            raise Exception('Please define a %s journal for the company "%s".' % (journal_type, company.name or ''))
        return journal_model.browse(ids[0])


    def _get_product_taxes(self, fiscal_position_id: Optional[int], company, partner, product):
        """Return taxes for product limited to company; map with fiscal position if provided.

        Note: Avoid using recordset.filtered(lambda ...) over RPC. Passing a Python function
        is not JSON-serializable. Instead, filter via a search on account.tax.
        """
        tax_ids = getattr(product.taxes_id, 'ids', []) if hasattr(product, 'taxes_id') else []
        if tax_ids:
            tax_model = self.get_dst_model('account.tax')
            ids = tax_model.search([('id', 'in', tax_ids), ('company_id', '=', company.id)], limit=0)
            taxes_by_company = tax_model.browse(ids)
        else:
            taxes_by_company = self.get_dst_model('account.tax').browse([])
        if fiscal_position_id:
            fpos = self.get_dst_model('account.fiscal.position').browse(fiscal_position_id)
            return fpos.map_tax(taxes_by_company, product=product, partner=partner)
        return taxes_by_company

    def _get_invoice_line_data(self, invoice_head: Dict[str, Any], company, partner, line):
        """Build an invoice line dict using destination models and safe derivations."""
        # Resolve product
        old_prod_id = getattr(getattr(line, 'product_id', None), 'id', None)
        product_id = self.get_new_product_id_from_old_id(old_prod_id)
        product = self.get_dst_model('product.product').browse(product_id) if product_id else None

        # Income/Expense account, optionally mapped by fiscal position
        account_id = None
        if product:
            account = product.property_account_income_id or product.categ_id.property_account_income_categ_id
            if account:
                fpos_id = invoice_head.get('fiscal_position_id')
                if fpos_id:
                    fpos = self.get_dst_model('account.fiscal.position').browse(fpos_id)
                    mapped = fpos.map_account(account)
                    account_id = mapped.id if mapped else account.id
                else:
                    account_id = account.id

        # Fallback: pick a default income/expense account if still missing
        if not account_id:
            acc_model = self.get_dst_model('account.account')
            mt = invoice_head.get('move_type')
            if mt in ('out_invoice', 'out_refund', 'out_receipt'):
                acc_ids = acc_model.search([('account_type', '=', 'income'), ('company_id', '=', company.id)], limit=1)
            else:
                acc_ids = acc_model.search([('account_type', '=', 'expense'), ('company_id', '=', company.id)], limit=1)
            account_id = acc_ids[0] if acc_ids else False

        # Derive price_unit and quantity
        price_unit = getattr(line, 'price_unit', None)
        if price_unit is None:
            price_unit = abs((getattr(line, 'credit', 0.0) or 0.0) or (getattr(line, 'debit', 0.0) or 0.0))
        quantity = getattr(line, 'quantity', 1.0)

        # Taxes
        taxes_rs = self._get_product_taxes(invoice_head.get('fiscal_position_id'), company, partner, product) if product else self.get_dst_model('account.tax').browse([])
        tax_ids = taxes_rs.ids if hasattr(taxes_rs, 'ids') else []

        result = {
            'account_id': account_id,
            'name': getattr(line, 'name', '/') or '/',
            'product_id': product.id if product else False,
            # In Odoo 17 invoice line, the unit of measure field is product_uom_id
            'product_uom_id': product.uom_id.id if product and product.uom_id else False,
            'price_unit': price_unit,
            'quantity': quantity,
            'tax_ids': [(6, 0, tax_ids)] if tax_ids else False,
            'x_old_id': line.id,
        }

        # Optional discounts if present on source line
        if hasattr(line, 'discount'):
            result['discount'] = line.discount
        # TODO: handle discount_type
        # if line.discount_type:
        #     result['discount_type'] = line.discount_type

        return result

    def _get_invoice_data(self, company, partner, src_record):
        """Build invoice head data using destination models only; no self.env."""
        # Map user (optional)
        old_user_id = getattr(getattr(src_record, 'user_id', None), 'id', None)
        user_id = self.get_new_user_id_from_old_id(old_user_id) or False

        # Partner shipping: map by old_id; browse as record
        old_partner_id = getattr(getattr(src_record, 'partner_id', None), 'id', None)
        partner_shipping_id = self.get_new_partner_shipping_id_from_old_id(old_partner_id) or partner.id
        partner_shipping = self.get_dst_model('res.partner').browse(partner_shipping_id)

        # Currency preference: partner then company
        currency = partner.currency_id or company.currency_id

        # Move type from source (Odoo 11: 'type' field)
        move_type = getattr(src_record, 'type', 'out_invoice') or 'out_invoice'

        # Journal by type
        journal_type = 'sale' if move_type in ('out_invoice', 'out_refund', 'out_receipt') else 'purchase'
        journal = self._get_invoice_journal(company, journal_type)

        # Fiscal position not computed here (no self.env compute); set False
        fiscal_position_id = False

        # Serialize invoice date safely
        def _to_date_str(val):
            if val is None:
                return False
            # Disallow callables or non-primitive objects
            if callable(val):
                return False
            # Already a proper string 'YYYY-MM-DD'
            if isinstance(val, str):
                s = val.strip()
                # Accept only exact YYYY-MM-DD; otherwise reject
                if len(s) == 10 and s[4] == '-' and s[7] == '-':
                    return s
                return False
            # date/datetime objects
            try:
                return val.strftime('%Y-%m-%d')
            except Exception:
                try:
                    s = val.isoformat()
                    # Try to truncate date part if full ISO datetime
                    if len(s) >= 10 and s[4] == '-' and s[7] == '-':
                        return s[:10]
                except Exception:
                    pass
            return False

        inv_date = _to_date_str(getattr(src_record, 'date_invoice', None) or getattr(src_record, 'date', None))

        # Guard helpers to avoid passing callables/records
        def _safe_str(val):
            return val if isinstance(val, (str, int, float)) else False

        invoice_data = {
            'move_type': move_type,
            'company_id': company.id,
            'partner_id': partner.id,
            'partner_shipping_id': partner_shipping.id,
            'currency_id': currency.id,
            'journal_id': journal.id,
            # Avoid using src_record.code (may be a method on this model). Keep False.
            'invoice_origin': False,
            'invoice_payment_term_id': False,
            'user_id': user_id,
            'invoice_date': inv_date or False,
            'start_date': _safe_str(getattr(src_record, 'start_date', False)) or False,
            'end_date': _safe_str(getattr(src_record, 'end_date', False)) or False,
            'fiscal_position_id': fiscal_position_id,
            'x_old_id': src_record.id,
        }
        # Optional textual fields
        invoice_data['ref'] = _safe_str(getattr(src_record, 'ref', False)) or False
        invoice_data['narration'] = _safe_str(getattr(src_record, 'narration', False)) or False
        return invoice_data




    def apply_transformations(self, src_record: Any) -> List[Dict]:
        # Destination company (via Odoo connection) and browsed records
        dst_odoo = self._odoo_provider.get_odoo_connection(DESTINATION)
        company_id = dst_odoo.get_company_id()
        company = self.get_dst_model('res.company').browse(company_id)

        partner_id = self.get_new_partner_id_from_old_id(getattr(getattr(src_record, 'partner_id', None), 'id', None))
        if not partner_id:
            logging.error(f"Skipping invoice old_id={src_record.id}: missing partner mapping")
            return []
        partner = self.get_dst_model('res.partner').browse(partner_id)

        invoice_head = self._get_invoice_data(company, partner, src_record)

        # Check if record already exists using old_id (via DB connection)
        conn = self._db_provider.get_connection(DESTINATION)
        existing_record = find_record_by_old_id(conn, 'account_move', src_record.id)

        invoice_data = {
            'action': 'update' if existing_record else 'create',
            'model': 'account.move',
            'src_record': src_record,
            # Defer browsing to save step to avoid RPC read errors at transform time
            'dst_record': existing_record if existing_record else None,
            'data': invoice_head
        }

        invoice_lines_data = []
        # Prefer Odoo 11 journal entry lines linked to the invoice, with robust recordset detection


        src_lines = []
        old_invoice_id = src_record.id
        if old_invoice_id:
            # Fetch account.move.line from SOURCE DB explicitly by move_id
            try:
                src_conn = self._odoo_provider.get_odoo_connection(SOURCE)
                aml_model = src_conn.get_model('account.invoice.line')
                line_ids = aml_model.search([('invoice_id', '=', old_invoice_id)], limit=0)
                src_lines = [aml_model.browse(lid) for lid in line_ids] if line_ids else []
                filtered = []
                for l in src_lines:
                    inv_field = getattr(l, 'invoice_id', None)
                    if not inv_field or (hasattr(inv_field, 'id') and inv_field.id == getattr(src_record, 'id', None)):
                        filtered.append(l)
                src_lines = filtered
            except Exception as e:
                logging.warning(f"Failed to fetch account.move.line by move_id for invoice {getattr(src_record, 'id', None)}: {e}")
                src_lines = []

        for src_line in src_lines:
            vals = self._get_invoice_line_data(invoice_head, company, partner, src_line)
            invoice_lines_data.append(vals)

        if src_line.id <= 11:
            print("debug it")

        # Important: put lines inside the payload under 'data', so create/write receives them
        if invoice_data['action'] == 'create':
            invoice_data['data']['invoice_line_ids'] = [(0, 0, vals) for vals in invoice_lines_data]
        elif invoice_data['action'] == 'update':
            # Build update commands using DB mapping: src_line.id -> dst account_move_line.id
            conn_dst = self._db_provider.get_connection(DESTINATION)
            commands = []
            for src_line in src_lines:
                vals = self._get_invoice_line_data(invoice_head, company, partner, src_line)
                dst_line_id = find_id_by_old_id(conn_dst, 'account_move_line', getattr(src_line, 'id', None))
                if dst_line_id:
                    commands.append((1, dst_line_id, vals))  # update in place
                else:
                    commands.append((0, 0, vals))  # create if mapping not found
            invoice_data['data']['invoice_line_ids'] = commands



        return [invoice_data]


    def save_into_destination(self, transformed_records: List[Dict]):
        """
        Save the transformed records in the destination system.
        This handles creating/updating account.move in the destination Odoo.
        """
        dst_model = self.get_dst_model('account.move')

        for transformed_record in transformed_records:
            if transformed_record['src_record'].invoice_line_ids['ids'][0] <= 11:
                print("debug it")
            data = transformed_record['data']
            action = transformed_record['action']
            src_record = transformed_record['src_record']
            dst_record = transformed_record.get('dst_record')
            x_new_id = None

            try:
                if action == 'create':
                    logging.info(f"Creating account move '{getattr(src_record, 'number', src_record.id)}'...")
                    x_new_id = dst_model.create(data)
                    logging.info(f"Created account move with ID {x_new_id}")
                elif action == 'update' and dst_record:
                    # Pure JSON-RPC: avoid browse()/recordsets; write by ids only
                    logging.info(f"Updating account move '{getattr(src_record, 'number', src_record.id)}'...")
                    dst_model.write([dst_record['id']], data)
                    x_new_id = dst_record['id']
                    logging.info(f"Updated account move with ID {dst_record['id']}")

                if x_new_id is not None:
                    self.update_tracking_ids(
                        x_new_id=x_new_id,
                        record=src_record
                    )

            except Exception as e:
                logging.error(f"Error processing account move '{src_record.name}': {str(e)}")
                # Continue with next record instead of failing completely
                continue


