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

    def find_account_by_code(self, code):
        """Find account in destination by code"""
        if not code:
            return None
        domain = [('code', '=', code)]
        dst_model = self.get_dst_model('account.account')
        ids = dst_model.search(domain, limit=1)
        if ids:
            return ids[0]
        return None


    def apply_transformations(self, src_record: Any) -> List[Dict]:
        # Get database connection for lookups
        conn = self._db_provider.get_connection(DESTINATION)
        
        # Use x_old_id lookup for partner
        partner_id = None
        if src_record.partner_id:
            partner_id = find_id_by_old_id(conn, 'res_partner', src_record.partner_id.id)
            if not partner_id:
                logging.warning(f"Partner with x_old_id {src_record.partner_id.id} not found for account move {src_record.name}")

        # Use name-based lookup for journal (journals typically don't change IDs between versions)
        journal_id = None
        if src_record.journal_id:
            journal_id = self.find_journal_by_name(src_record.journal_id.name)
            if not journal_id:
                logging.warning(f"Journal '{src_record.journal_id.name}' not found for account move {src_record.name}")

        # Check if record already exists using x_old_id
        existing_record = find_record_by_old_id(conn, 'account_move', src_record.id)
        
        # Get destination company_id from the Odoo connection
        dst_odoo = self._odoo_provider.get_odoo_connection(DESTINATION)
        company_id = dst_odoo.company_id
        
        data = {
            'name': src_record.name or '/',
            'ref': src_record.ref,
            'date': src_record.date,
            'journal_id': journal_id,
            'partner_id': partner_id,
            'narration': src_record.narration,
            'company_id': company_id,  # Use destination company
            'x_old_id': src_record.id,
        }

        # Add currency if available
        if hasattr(src_record, 'currency_id') and src_record.currency_id:
            # For currency, we can try name-based lookup as currency codes are standard
            dst_model = self.get_dst_model('res.currency')
            currency_ids = dst_model.search([('name', '=', src_record.currency_id.name)], limit=1)
            if currency_ids:
                data['currency_id'] = currency_ids[0]

        transformed_record = {
            'action': 'update' if existing_record else 'create',
            'model': 'account.move',
            'src_record': src_record,
            'dst_record': existing_record,
            'data': data
        }

        return [transformed_record]

    def transform_move_line(self, line, move_id=None):
        """Transform account move line from source to destination format"""
        # Get database connection for lookups
        conn = self._db_provider.get_connection(DESTINATION)
        
        # Use x_old_id lookup for partner
        partner_id = None
        if line.partner_id:
            partner_id = find_id_by_old_id(conn, 'res_partner', line.partner_id.id)

        # Use account code lookup for account
        account_id = None
        if line.account_id:
            account_id = self.find_account_by_code(line.account_id.code)
            if not account_id:
                logging.warning(f"Account with code '{line.account_id.code}' not found for move line")

        # Use x_old_id lookup for product if available
        product_id = None
        if line.product_id:
            product_id = find_id_by_old_id(conn, 'product_product', line.product_id.id)

        # Get destination company_id from the Odoo connection
        dst_odoo = self._odoo_provider.get_odoo_connection(DESTINATION)
        company_id = dst_odoo.company_id

        data = {
            'name': line.name or '/',
            'account_id': account_id,
            'partner_id': partner_id,
            'debit': line.debit or 0.0,
            'credit': line.credit or 0.0,
            'quantity': getattr(line, 'quantity', 1.0),
            'product_id': product_id,
            'company_id': company_id,
        }

        if move_id:
            data['move_id'] = move_id

        # Add optional fields if they exist
        if hasattr(line, 'date_maturity') and line.date_maturity:
            data['date_maturity'] = line.date_maturity
        
        if hasattr(line, 'ref') and line.ref:
            data['ref'] = line.ref

        return data

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
                    dst_record.write(data)
                    logging.info(f"Updated account move with ID {dst_record.id}")
                    
            except Exception as e:
                logging.error(f"Error processing account move '{src_record.name}': {str(e)}")
                # Continue with next record instead of failing completely
                continue

