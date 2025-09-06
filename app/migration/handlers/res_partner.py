import logging

from typing import Dict, List, Optional, Any

from .base import DomainHandler
from ..core.odoo_connection import OdooConnectionProvider, DESTINATION
from ..core.database import DBConnectionProvider, find_id_by_old_id, find_record_by_old_id



class ResPartnerHandler(DomainHandler):

    def __init__(
            self,
            odoo_provider: OdooConnectionProvider,
            db_provider: DBConnectionProvider,
            model_name: str
    ):
        super().__init__(odoo_provider, db_provider, model_name)


    def find_dest_partner_by_old_id(self, src_record):
        """Find partner in destination using x_old_id (more reliable than name-based lookup)"""
        conn = self._db_provider.get_connection(DESTINATION)
        dst_record = find_record_by_old_id(conn, 'res_partner', src_record.id)
        if dst_record:
            # Return the Odoo record object, including archived records
            model = self.get_dst_model()
            # Use with_context to include archived records in browse operation
            return model.with_context(active_test=False).browse(dst_record['id'])
        return None

    def find_dest_country_by_name(self, src_country):
        """Find destination country by name"""
        if not src_country:
            return None
        country_model = self.get_dst_model('res.country')
        countries = country_model.search([('name', '=', src_country.name)], limit=1)
        return countries[0].id if countries else None

    def find_dest_state_by_name(self, src_state):
        """Find destination state by name and country"""
        if not src_state:
            return None
        state_model = self.get_dst_model('res.country.state')
        domain = [('name', '=', src_state.name)]
        # If we have country info, add it to make the search more precise
        if src_state.country_id:
            country_id = self.find_dest_country_by_name(src_state.country_id)
            if country_id:
                domain.append(('country_id', '=', country_id))
        states = state_model.search(domain, limit=1)
        return states[0].id if states else None

    def apply_transformations(self, src_record: Any) -> List[Dict]:
        dst_record = self.find_dest_partner_by_old_id(src_record)
        result = [{
            'action': 'update' if dst_record else 'create',
            'model': 'res.partner',
            'src_record': src_record,
            'dst_record': dst_record,
            'data': {
                'name': src_record.name,
                'display_name': src_record.display_name,
                'date': src_record.date,
                'ref': src_record.ref,
                'lang': src_record.lang,
                'tz': src_record.tz,
                'vat': src_record.vat,
                'website': src_record.website,
                'comment': src_record.comment,
                'active': src_record.active,
                'customer': src_record.customer,
                'supplier': src_record.supplier,
                'employee': src_record.employee,
                'function': src_record.function,
                'type': src_record.type,
                'street': src_record.street,
                'street2': src_record.street2,
                'zip': src_record.zip,
                'city': src_record.city,
                'email': src_record.email,
                'phone': src_record.phone,
                'mobile': src_record.mobile,
                'is_company': src_record.is_company,
                'company_id': src_record.company_id.id,

                # Foreign key fields with lookup strategies
                'country_id': self.find_dest_country_by_name(src_record.country_id),
                'state_id': self.find_dest_state_by_name(src_record.state_id),

                # Note: parent_id will be handled in a separate two-phase handler
            }
        }]
        return result

    def save_into_destination(self, transformed_records: List[Dict]):
        """
        Save the transformed records in the destination system.
        This handles creating res.partner in the destination Odoo (Odoo 16).
        """
        for transformed_record in transformed_records:

            model_name = transformed_record['model']
            data = transformed_record['data']
            action = transformed_record['action']
            src_record = transformed_record['src_record']

            if action in ['create', 'update']:

                if action == 'create':
                    dst_model = self.get_dst_model()
                    logging.info(f"Creating {self.get_dst_model()} \"{src_record.name}\" ...")
                    new_id = dst_model.create(data)

                elif action == 'update':
                    logging.info(f"Updating partner \"{src_record.name}\" ...")
                    dst_record = transformed_record['dst_record']
                    dst_record.write(data)
                    new_id = dst_record.id

                self.update_tracking_ids(
                    new_id=new_id,
                    record=src_record
                )
