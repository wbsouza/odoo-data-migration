import logging
from typing import Dict, List, Optional, Any

from .base import DomainHandler
from ..core.odoo_connection import OdooConnectionProvider, DESTINATION
from ..core.database import DBConnectionProvider, find_id_by_old_id



class ResUsersHandler(DomainHandler):

    def __init__(
            self,
            odoo_provider: OdooConnectionProvider,
            db_provider: DBConnectionProvider,
            model_name: str
    ):
        super().__init__(odoo_provider, db_provider, model_name)


    def find_dest_user_by_login(self, src_record):
        """Find user in destination using login field (primary method for users)"""
        # Include both active and inactive users in search
        domain = [('login', '=', src_record.login)]
        existing_user_id = self.get_dst_model().search(domain, limit=1)
        existing_user = None
        if existing_user_id:
            existing_user = self.get_dst_model().browse(existing_user_id[0])
        return existing_user

    def find_dest_partner_by_old_id(self, src_record):
        """
        Find destination partner by x_old_id first, then fallback to name search.
        Raises exception if not found by either method.
        """
        # First try: lookup by x_old_id (from migration)
        conn = self._db_provider.get_connection(DESTINATION)
        partner_id = find_id_by_old_id(conn, 'res_partner', src_record.partner_id.id)
        if partner_id is not None:
            return partner_id

        # Fallback: search by name in case partner already exists in destination
        partner_name = src_record.partner_id.name
        partner_model = self.get_dst_model('res.partner')
        existing_partners = partner_model.search([('name', '=', partner_name)], limit=1)
        if existing_partners:
            return existing_partners[0].id
            
        # If neither method finds the partner, raise exception
        raise ValueError(f"Partner '{partner_name}' (source ID {src_record.partner_id.id}) "
                         f"not found in destination by x_old_id or name. "
                         f"Ensure res.partner migration completed successfully or partner exists in destination.")

    def apply_transformations(self, src_record: Any) -> List[Dict]:
        # Primary lookup using login field (natural unique identifier for users)
        dst_record = self.find_dest_user_by_login(src_record)
        
        # Find the corresponding partner in destination (strict requirement)
        dst_partner_id = self.find_dest_partner_by_old_id(src_record)
        
        result = [{
            'action': 'update' if dst_record else 'create',
            'model': self.get_dst_model_name(),
            'src_record': src_record,
            'dst_record': dst_record,
            'data': {
                'name': src_record.name,
                'login': src_record.login,
                'email': src_record.email,
                'partner_id': dst_partner_id,  # Link to migrated partner
                'company_id': src_record.company_id.id,
                'lang': src_record.lang,
                'tz': src_record.tz,
            }
        }]
        return result

    def save_into_destination(self, transformed_records: List[Dict]):
        """
        Save the transformed records in the destination system.
        This handles creating res.users in the destination Odoo (Odoo 17).
        """
        for transformed_record in transformed_records:
            model_name = transformed_record['model']
            data = transformed_record['data']
            action = transformed_record['action']
            src_record = transformed_record['src_record']
            dst_record = transformed_record['dst_record']
            new_id = None

            if action == 'create':
                dst_model = self.get_dst_model(model_name)
                logging.info(f"Creating user \"{src_record.name}\" ...")
                new_id = dst_model.create(data)

            elif action == 'update':
                logging.info(f"Updating user \"{src_record.name}\" ...")
                dst_record.write(data)
                new_id = dst_record.id

            if new_id is not None:
                self.update_tracking_ids(
                    new_id=new_id,
                    record=src_record
                )
