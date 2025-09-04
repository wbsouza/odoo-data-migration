import logging

from typing import Dict, Generic, List, Optional, Type, TypeVar, Union, Any

from .base import DomainHandler, ResourceNotFoundException
from ..core.mapping import MappingProvider
from ..core.odoo_connection import OdooConnection

import json


class ProductTemplateHandler(DomainHandler):

    def __init__(self, src_odoo: OdooConnection, dst_odoo: OdooConnection, mapping_provider: MappingProvider):
        """
        Initialize the ResGroupsHandler with the source and destination Odoo connections, and the MappingProvider.
        :param src_odoo: OdooConnection instance for the source Odoo.
        :param dst_odoo: OdooConnection instance for the destination Odoo.
        :param mapping_provider: An instance of MappingProvider to handle ID mappings.
        """
        super().__init__(src_odoo, dst_odoo, 'product.template')
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

        if src_group is not None:
            domain = [('name', '=', src_group
            ['name'])]
            resp = self._odoo_provider.get_odoo_connection(DESTINATION).fetch_ids('res.groups', domain=domain, limit=1)
            if resp is not None and len(resp) > 0:
                return resp[0]
        return None

    def find_template_by_name(self, name) -> bool:
        domain = [('name', '=', name)]
        model = self._odoo_provider.get_odoo_connection(DESTINATION).session.env[self.src_model_name]
        ids = model.search(domain, limit=1)
        if ids is not None and len(ids):
            return model.browse(ids[0])[0]
        return None

    def apply_transformations(self, src_record: Any) -> List[Dict]:
        transformed_record = {
            'action': 'create',
            'model': 'product.template',
            'src_record': src_record,
            'dst_record': self.find_template_by_name(src_record.name),
            'data': {
                'name': src_record.name,
                'default_code': src_record.default_code,
                # 'groups_id': [(6, 0, dst_group_ids)],
            }
        }

        # already exists ...
        if transformed_record['dst_record'] is not None:
            transformed_record['action'] = 'update'

        return [transformed_record]

    def save_into_destination(self, transformed_records: List[Dict]):
        """
        Save the transformed records in the destination system.
        This handles creating product.template in the destination Odoo (Odoo 16).
        """
        for transformed_record in transformed_records:

            model_name = transformed_record['model']
            data = transformed_record['data']
            action = transformed_record['action']
            src_record = transformed_record['src_record']

            if action == 'create':
                dst_model = self._odoo_provider.get_odoo_connection(DESTINATION).session.env[model_name]
                logging.info(f"Creating template \"{src_record.name}\" ...")
                new_id = dst_model.create(data)
                self.update_tracking_ids('product.template', new_id, src_record)

            elif action == 'update':
                logging.info(f"Updating template \"{src_record.name}\" ...")
                dst_record = transformed_record['dst_record']
                dst_record.write(data)
                self.update_tracking_ids('product.template', dst_record.id, src_record)
