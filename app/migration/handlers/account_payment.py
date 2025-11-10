import logging
from datetime import date as _date
from typing import Dict, List, Optional, Any

from .base import DomainHandler
from ..core.odoo_connection import OdooConnectionProvider, DESTINATION
from ..core.database import DBConnectionProvider, find_id_by_old_id, find_record_by_old_id


class AccountPaymentHandler(DomainHandler):

    def __init__(
            self,
            odoo_provider: OdooConnectionProvider,
            db_provider: DBConnectionProvider,
            model_name: str
    ):
        super().__init__(odoo_provider, db_provider, model_name)

    def find_journal_by_name(self, name):
        """Find journal in destination by name"""
        if not name:
            return None
        domain = [('name', '=', name)]
        dst_model = self.get_dst_model('account.journal')
        ids = dst_model.search(domain, limit=1)
        if ids:
            return ids[0]
        return None

    def find_payment_method_by_name(self, name):
        """Find payment method in destination by name"""
        if not name:
            return None
        domain = [('name', '=', name)]
        dst_model = self.get_dst_model('account.payment.method')
        ids = dst_model.search(domain, limit=1)
        if ids:
            return ids[0]
        return None

    def apply_transformations(self, src_record: Any) -> List[Dict]:
        conn = self._db_provider.get_connection(DESTINATION)
        
        # Use x_old_id lookup for partner
        partner_id = None
        if src_record.partner_id:
            partner_id = find_id_by_old_id(conn, 'res_partner', src_record.partner_id.id)
            if not partner_id:
                logging.warning(f"Partner with x_old_id {src_record.partner_id.id} not found for payment {src_record.id}")

        # Use name-based lookup for journal
        journal_id = None
        if hasattr(src_record, 'journal_id') and src_record.journal_id:
            journal_id = self.find_journal_by_name(src_record.journal_id.name)
        elif hasattr(src_record, 'destination_journal_id') and src_record.destination_journal_id:
            journal_id = self.find_journal_by_name(src_record.destination_journal_id.name)
        
        if not journal_id:
            logging.warning(f"Journal not found for payment {src_record.id}")

        # Use name-based lookup for payment method
        payment_method_id = None
        if hasattr(src_record, 'payment_method_id') and src_record.payment_method_id:
            payment_method_id = self.find_payment_method_by_name(src_record.payment_method_id.name)

        # Check if record already exists using x_old_id
        existing_record = find_record_by_old_id(conn, 'account_payment', src_record.id)
        browsed_dst_record = None
        if existing_record:
            browsed_dst_record = self.get_dst_model('account.payment').browse(existing_record['id'])
        
        # Get destination company_id from the Odoo connection
        dst_odoo = self._odoo_provider.get_odoo_connection(DESTINATION)
        company_id = dst_odoo.get_company_id()

        # Helpers to sanitize values before RPC
        def _safe_str(val, default=False):
            return val if isinstance(val, (str, int, float)) else default

        def _to_date_str(val):
            if val is None:
                return False
            if callable(val):
                return False
            if isinstance(val, str):
                s = val.strip()
                if len(s) == 10 and s[4] == '-' and s[7] == '-':
                    return s
                return False
            try:
                return val.strftime('%Y-%m-%d')
            except Exception:
                try:
                    s = val.isoformat()
                    if len(s) >= 10 and s[4] == '-' and s[7] == '-':
                        return s[:10]
                except Exception:
                    pass
            return False

        partner_type = _safe_str(getattr(src_record, 'partner_type', None), default='customer')
        payment_type = _safe_str(getattr(src_record, 'payment_type', None), default='inbound')

        data = {
            'amount': float(src_record.amount),
            'partner_id': partner_id,
            'partner_type': partner_type,
            'payment_type': payment_type,
            'journal_id': journal_id,
            # Odoo 17 requires payment_method_line_id to be set for the selected journal/direction
            'company_id': company_id,  # Use destination company
            'x_old_id': src_record.id,
            # Keep payment in draft; posting/reconciliation will be a later step
            'state': 'draft',
        }

        # Resolve payment_method_line_id from the journal and payment direction (inbound/outbound)
        # Try to match the source payment method by name; otherwise pick the first available line.
        try:
            if journal_id:
                journal = self.get_dst_model('account.journal').browse(journal_id)
                method_name = None
                try:
                    method_name = src_record.payment_method_id.name if src_record.payment_method_id else False
                except Exception:
                    method_name = None

                if payment_type == 'inbound':
                    lines = getattr(journal, 'inbound_payment_method_line_ids', []) or []
                elif payment_type == 'outbound':
                    lines = getattr(journal, 'outbound_payment_method_line_ids', []) or []
                else:
                    # For transfers, fall back to outbound then inbound
                    lines = getattr(journal, 'outbound_payment_method_line_ids', []) or getattr(journal, 'inbound_payment_method_line_ids', []) or []

                chosen_line_id = None
                if method_name and lines:
                    for line in lines:
                        try:
                            pm_name = getattr(getattr(line, 'payment_method_id', None), 'name', None)
                            if pm_name == method_name or getattr(line, 'name', None) == method_name:
                                chosen_line_id = line.id
                                break
                        except Exception:
                            continue
                if not chosen_line_id and lines:
                    # Default to the first available method line for the journal/direction
                    first = lines[0]
                    chosen_line_id = getattr(first, 'id', first if isinstance(first, int) else None)

                if chosen_line_id:
                    data['payment_method_line_id'] = chosen_line_id
                else:
                    logging.warning(f"No payment method line available for journal {journal_id} and payment_type {payment_type} (payment {getattr(src_record, 'id', None)})")
            else:
                logging.warning(f"Cannot resolve payment_method_line_id: missing journal for payment {getattr(src_record, 'id', None)}")
        except Exception as e:
            logging.warning(f"Failed to resolve payment_method_line_id for payment {getattr(src_record, 'id', None)}: {e}")

        # Add currency if available
        if hasattr(src_record, 'currency_id') and src_record.currency_id:
            # For currency, we can try name-based lookup as currency codes are standard
            dst_model = self.get_dst_model('res.currency')
            currency_ids = dst_model.search([('name', '=', src_record.currency_id.name)], limit=1)
            if currency_ids:
                data['currency_id'] = currency_ids[0]

        # Add optional fields
        if hasattr(src_record, 'date') and src_record.date:
            data['date'] = _to_date_str(src_record.date)
        # Ensure mandatory date is set (fallback to today)
        if not data.get('date'):
            data['date'] = _date.today().isoformat()
        
        base_ref = _safe_str(getattr(src_record, 'ref', None), default=False)
        # Mark source invoice IDs in ref for later reconciliation
        src_inv_ids = []
        try:
            invs = getattr(src_record, 'invoice_ids', [])
            if callable(invs):
                invs = []
            # invoice_ids might be a recordset; try to iterate and extract .id
            for inv in invs or []:
                inv_id = getattr(inv, 'id', None)
                if inv_id:
                    src_inv_ids.append(inv_id)
        except Exception:
            src_inv_ids = []

        marker = ''
        if src_inv_ids:
            marker = f" [SRC_INV: {','.join(str(i) for i in src_inv_ids)}]"
        if base_ref:
            data['ref'] = f"{base_ref}{marker}"
        elif marker:
            data['ref'] = marker.strip()

        # Do NOT link to account.move yet; invoices are draft and will change.
        # Reconciliation will occur in a later pass using the [SRC_INV: ids] marker above.

        transformed_record = {
            'action': 'update' if existing_record else 'create',
            'model': 'account.payment',
            'src_record': src_record,
            'dst_record': browsed_dst_record,
            'data': data
        }

        return [transformed_record]

    def save_into_destination(self, transformed_records: List[Dict]):
        """
        Save the transformed records in the destination system.
        This handles creating/updating account.payment in the destination Odoo.
        """
        self.save_records(
            transformed_records=transformed_records,
            default_model_name='account.payment',
            entity_label='payment',
            name_field='ref',
        )
