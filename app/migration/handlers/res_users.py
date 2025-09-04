import logging
from typing import Dict, Generic, List, Optional, Type, TypeVar, Union, Any

from .base import DomainHandler, ResourceNotFoundException
from ..core.mapping import MappingProvider
from ..core.odoo_connection import OdooConnection

import json


class ResUsersHandler(DomainHandler):

    def __init__(self, src_odoo: OdooConnection, dst_odoo: OdooConnection, mapping_provider: MappingProvider):
        """
        Initialize the ResGroupsHandler with the source and destination Odoo connections, and the MappingProvider.
        :param src_odoo: OdooConnection instance for the source Odoo.
        :param dst_odoo: OdooConnection instance for the destination Odoo.
        :param mapping_provider: An instance of MappingProvider to handle ID mappings.
        """
        super().__init__(src_odoo, dst_odoo, 'res.users')
        self.language = dst_odoo.language
        self.company_id = dst_odoo.company_id
        self.mapping_provider = mapping_provider

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
        result = self.mapping_provider.get_mapping('res.groups', src_group.id)
        if not result:
            domain = [('name', '=', src_group['name'])]
            resp = self._dst_odoo.fetch_ids('res.groups', domain=domain, limit=1)
            if resp is not None and len(resp) > 0:
                result = resp[0]
                # update the cache with the respective id
                self.mapping_provider.set_mapping('res.groups', src_group.id, result)
        return result

    def find_product_attribute_by_login(self, login) -> bool:
        domain = [('login', '=', login)]
        model = self._dst_odoo.session.env[self.model_name]
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

            if action == 'create':
                dst_model = self._dst_odoo.session.env[model_name]
                logging.info(f"Creating user \"{src_record.name}\" ...")
                new_id = dst_model.create(data)
                src_record.write({'x_new_id': new_id})
            elif action == 'update':
                logging.info(f"Updating user \"{src_record.name}\" ...")
                dst_record = transformed_record['dst_record']
                dst_record.write(data)
                src_record.write({'x_new_id': dst_record.id})
