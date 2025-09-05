import logging
from typing import Dict, List, Optional, Any

from .base import DomainHandler
from ..core.mapping import MappingProvider
from ..core.odoo_connection import OdooConnectionProvider, DESTINATION
from ..core.database import DBConnectionProvider

import json


class ResUsersHandler(DomainHandler):

    def __init__(
            self,
            odoo_provider: OdooConnectionProvider,
            db_provider: DBConnectionProvider,
            mapping_provider: MappingProvider,
            model_name: str
    ):
        super().__init__(odoo_provider, db_provider, 'res.users')
        self._mapping_provider = mapping_provider

    def find_dest_group_id(self, src_group: Any) -> Optional[int]:
        """
        Find the matching category ID in the destination Odoo (Odoo 16) based on the source category ID from Odoo 11.
        First check the mappings cache, and if not found, perform a lookup.
        :param src_group: The source category
        :return: The destination category ID.
        """
        if src_group is None or len(src_group) < 1:
            return None

        # try to find the source id in the cache first ...
        result = self._mapping_provider.get_mapping('res.groups', src_group.id)
        if not result:
            domain = [('name', '=', src_group['name'])]
            odoo_dst = self._odoo_provider.get_odoo_connection(DESTINATION)
            resp = odoo_dst.fetch_ids('res.groups', domain=domain, limit=1)
            if resp is not None and len(resp) > 0:
                result = resp[0]
                # update the cache with the respective id
                self.mapping_provider.set_mapping('res.groups', src_group.id, result)
        return result

    def find_product_attribute_by_login(self, login) -> bool:
        domain = [('login', '=', login)]
        odoo_dst = self._odoo_provider.get_odoo_connection(DESTINATION)
        model = odoo_dst.session.env[self.src_model_name]
        ids = model.search(domain, limit=1)
        if ids is not None and len(ids):
            return model.browse(ids[0])[0]
        return None

    def apply_transformations(self, src_record: Any) -> List[Dict]:
        transformed_record = {
            'action': 'create',
            'model': 'res.users',
            'src_record': src_record,
            'dst_record': self.find_product_attribute_by_login(src_record.login),
            'data': {
                'name': src_record.name,
                'login': src_record.login,
                'email': src_record.email,
                'company_id': src_record.company_id.id,
                'lang': src_record.lang,
                'tz': src_record.tz,
            }
        }

        # already exists ...
        if transformed_record['dst_record'] is not None:
            transformed_record['action'] = 'update'

        return [transformed_record]

    def save_into_destination(self, transformed_records: List[Dict]):
        """
        Save the transformed records in the destination system.
        This handles creating res.users in the destination Odoo (Odoo 16).
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