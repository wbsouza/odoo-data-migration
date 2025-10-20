import logging
from typing import Dict, List, Optional, Any

from .base import DomainHandler

from ..core.odoo_connection import OdooConnectionProvider, DESTINATION
from ..core.database import DBConnectionProvider, find_id_by_old_id, find_record_by_old_id


class AccountMoveHandler(DomainHandler):

    def __init__(
            self,
            odoo_provider: OdooConnectionProvider,
            db_provider: DBConnectionProvider,
            model_name: str
    ):
        super().__init__(odoo_provider, db_provider, model_name)

    def get_new_product_id_from_old_id(self, old_id: Optional[int]) -> Optional[int]:
        if not old_id:
            return None
        conn = self._db_provider.get_connection(DESTINATION)
        return find_id_by_old_id(conn, 'product_product', old_id)

    # --- Mapping helpers (source old_id -> destination new id) ---
    def get_new_user_id_from_old_id(self, old_id: Optional[int]) -> Optional[int]:
        """Map source res.users.id to destination id via x_old_id."""
        if not old_id:
            return None
        conn = self._db_provider.get_connection(DESTINATION)
        return find_id_by_old_id(conn, 'res_users', old_id)

    def get_new_partner_id_from_old_id(self, old_id: Optional[int]) -> Optional[int]:
        """Map source res.partner.id to destination id via x_old_id."""
        if not old_id:
            return None
        conn = self._db_provider.get_connection(DESTINATION)
        return find_id_by_old_id(conn, 'res_partner', old_id)

    def get_new_partner_shipping_id_from_old_id(self, old_id: Optional[int]) -> Optional[int]:
        """Map shipping partner; if no separate shipping mapping, fallback to partner mapping."""
        return self.get_new_partner_id_from_old_id(old_id)

    def _get_invoice_journal(self, company):
        journal_domain = [('type', '=', 'sale'), ('company_id', '=', company.id)]
        journal = self.env['account.journal'].search(journal_domain, limit=1)
        if not journal:
            raise Exception('Please define a sale journal for the company "%s".') % (company.name or '',)
        return journal


    def _get_product_taxes(self, fiscal_position, company, partner, product):
        taxes_by_company = product.taxes_id.filtered(lambda r: r.company_id == company)
        product_taxes = fiscal_position.map_tax(taxes_by_company, product=product, partner=partner)
        return product_taxes

    def _get_invoice_line_data(self, invoice_data, company, partner, line):

        product = self.get_new_product_id_from_old_id(line.product_id.id)
        account = product.property_account_income_id
        if not account:
            account = product.categ_id.property_account_income_categ_id
        fiscal_pos = self.env['account.fiscal.position'].browse(invoice_data['fiscal_position_id'])
        account_id = fiscal_pos.map_account(account).id
        product_taxes = self._get_product_taxes(fiscal_pos, company, partner, product)
        result = {
            'account_id': account_id,
            'subscription_id': self.id,
            'name': line.name,
            'product_id': product.id,
            'uom_id': product.uom_id.id,
            'price_unit': line.unit_price,
            'quantity': line.quantity,
            'discount': line.discount,
            'discount_type': line.discount_type,
            'tax_ids': [(6, 0, product_taxes.ids)],
        }
        return result

    def _get_invoice_data(self, company, partner, src_record):
        dst_odoo = self._odoo_provider.get_odoo_connection(DESTINATION)
        user_id = self.get_new_user_id_from_old_id(src_record.user_id.id)
        payment_term = self.env.ref('account.account_payment_term_immediate')
        partner_shipping = self.get_new_partner_shipping_id_from_old_id(src_record.partner_id.id)
        currency = partner.currency_id or company.currency_id
        journal = self._get_invoice_journal(company)
        fiscal_position = self.env['account.fiscal.position']._get_fiscal_position(partner)
        fiscal_position_id = fiscal_position.id if fiscal_position else False
        invoice_data = {
            'move_type': 'out_invoice',
            'company_id': company.id,
            'partner_id': partner.id,
            'partner_shipping_id': partner_shipping.id,
            'currency_id': currency.id,
            'journal_id': journal.id,
            'invoice_origin': src_record.code,
            'invoice_payment_term_id': payment_term.id,
            'user_id': user_id,
            'invoice_date': src_record.date_invoice,
            'start_date': src_record.start_date,
            'end_date': src_record.end_date,
            'fiscal_position_id': fiscal_position_id,
        }
        return invoice_data




    def apply_transformations(self, src_record: Any) -> List[Dict]:
        # Get database connection for lookups
        dst_odoo = self._db_provider.get_connection(DESTINATION)
        company = dst_odoo.company_id
        partner = self.get_new_partner_id_from_old_id(src_record.partner_id.id)

        invoice_head = self._get_invoice_data(company, partner, src_record)

        # Check if record already exists using x_old_id
        existing_record = find_record_by_old_id(dst_odoo, 'account_move', src_record.id)

        invoice_data = {
            'action': 'update' if existing_record else 'create',
            'model': 'account.move',
            'src_record': src_record,
            'dst_record': existing_record,
            'data': invoice_head
        }

        invoice_lines_data = []
        for line in src_record.invoice_line:
            invoice_lines_data.append(self._get_invoice_line_data(invoice_data, company, partner, line))

        invoice_data['invoice_line_ids'] = [(0, 0, line) for line in invoice_lines_data]


        return [invoice_data]


    def save_into_destination(self, transformed_records: List[Dict]):
        """
        Save the transformed records in the destination system.
        This handles creating/updating account.move in the destination Odoo.
        """
        dst_model = self.get_dst_model('account.move')

        for transformed_record in transformed_records:
            data = transformed_record['data']
            action = transformed_record['action']
            src_record = transformed_record['src_record']

            try:
                if action == 'create':
                    logging.info(f"Creating account move '{src_record.name}'...")
                    
                    # Create the move first without lines
                    move_data = data.copy()
                    new_id = dst_model.create(move_data)
                    
                    # Create move lines separately if they exist
                    if hasattr(src_record, 'line_ids') and src_record.line_ids:
                        dst_line_model = self.get_dst_model('account.move.line')
                        for line in src_record.line_ids:
                            line_data = self.transform_move_line(line, new_id)
                            if line_data.get('account_id'):  # Only create lines with valid accounts
                                dst_line_model.create(line_data)
                    
                    logging.info(f"Created account move with ID {new_id}")
                    
                elif action == 'update':
                    logging.info(f"Updating account move '{src_record.name}'...")
                    dst_record = transformed_record['dst_record']
                    move_data = data.copy()
                    move_data.pop('invoice_line_ids')
                    dst_record.write(move_data)
                    logging.info(f"Updated account move with ID {dst_record.id}")

                    dst_move_line_model = self.get_dst_model('account.move.line')

                    for line in data['invoice_line_ids']:
                        line_data = line.copy()
                        line_data['move_id'] = dst_record.id

                        # check if it already exists (by product_id, quantity, discount, etc)
                        # if does not exist, create it otherwise update it
                        if not self._move_line_exists(line_data):
                            dst_move_line_model.create(line_data)
                        else:
                            dst_move_line_model.write(line_data)


                    
            except Exception as e:
                logging.error(f"Error processing account move '{src_record.name}': {str(e)}")
                # Continue with next record instead of failing completely
                continue

