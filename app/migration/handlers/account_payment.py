import logging
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
        company_id = dst_odoo.company_id
        
        data = {
            'amount': src_record.amount or 0.0,
            'partner_id': partner_id,
            'partner_type': getattr(src_record, 'partner_type', 'customer'),
            'payment_type': getattr(src_record, 'payment_type', 'inbound'),
            'journal_id': journal_id,
            'payment_method_id': payment_method_id,
            'company_id': company_id,  # Use destination company
            'x_old_id': src_record.id,
            # Keep payment in draft; posting/reconciliation will be a later step
            'state': 'draft',
        }

        # Add currency if available
        if hasattr(src_record, 'currency_id') and src_record.currency_id:
            # For currency, we can try name-based lookup as currency codes are standard
            dst_model = self.get_dst_model('res.currency')
            currency_ids = dst_model.search([('name', '=', src_record.currency_id.name)], limit=1)
            if currency_ids:
                data['currency_id'] = currency_ids[0]

        # Add optional fields
        if hasattr(src_record, 'date') and src_record.date:
            data['date'] = src_record.date
        
        base_ref = getattr(src_record, 'ref', None)
        # Mark source invoice IDs in ref for later reconciliation
        src_inv_ids = []
        try:
            invs = getattr(src_record, 'invoice_ids', [])
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
