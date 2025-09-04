import logging
from typing import Dict, Generic, List, Optional, Type, TypeVar, Union, Any
from .base import DomainHandler, ResourceNotFoundException
from ..core.mapping import MappingProvider
from ..core.odoo_connection import OdooConnection
import json


class ProductAttributeValueHandler(DomainHandler):

    def __init__(self, src_odoo: OdooConnection, dst_odoo: OdooConnection, mapping_provider: MappingProvider):
        """
        Initialize the ResGroupsHandler with the source and destination Odoo connections, and the MappingProvider.
        :param src_odoo: OdooConnection instance for the source Odoo.
        :param dst_odoo: OdooConnection instance for the destination Odoo.
        :param mapping_provider: An instance of MappingProvider to handle ID mappings.
        """
        super().__init__(src_odoo, dst_odoo, 'product.attribute.value')
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
            resp = self._dst_odoo.fetch_ids('res.groups', domain=domain, limit=1)
            if resp is not None and len(resp) > 0:
                return resp[0]
        return None

    def template_attribute_value_exists(self, src_record: Any) -> bool:
        domain = [('name', '=', src_record.name)]
        model = self._dst_odoo.session.env[self.model_name]
        ids = model.search(domain, limit=1)
        return ids is not None and len(ids) > 0

    def find_dst_attribute_by_name(self, src_record):
        domain = [('name', '=', src_record.attribute_id.name)]
        model = self._dst_odoo.session.env['product.attribute']
        attribute_id = model.search(domain)
        attribute = model.browse(attribute_id[0])
        return attribute

    def find_dst_attribute_value(self, src_record):
        domain = [('name', '=', src_record.name)]
        model = self._dst_odoo.session.env['product.attribute.value']
        attribute_id = model.search(domain)
        attribute_value = model.browse(attribute_id)
        if attribute_id is not None and len(attribute_id):
            return model.browse(attribute_id[0])[0]
        return None

    def find_dst_attribute_value_by_name(self, name) -> bool:
        domain = [('name', '=', name)]
        model = self._dst_odoo.session.env[self.model_name]
        ids = model.search(domain, limit=1)
        if ids is not None and len(ids):
            return model.browse(ids[0])[0]
        return None

    def apply_transformations(self, src_record: Any) -> List[Dict]:
        dst_attribute = self.find_dst_attribute_by_name(src_record)
        transformed_record = {
            'action': 'create',
            'model': 'product.attribute.value',
            'src_record': src_record,
            'dst_record': self.find_dst_attribute_value_by_name(src_record.name),
            'data': {
            'name': src_record.name,
            'attribute_id': dst_attribute.id,
            'x_old_id': src_record.id,
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
        for record in transformed_records:
            model_name = record['model']
            data = record['data']
            # secondary_data = record['secondary_data']
            action = record['action']
            src_model = self._src_odoo.session.env[self.model_name]
            src_record = src_model.browse(data['x_old_id'])
            dst_model = self._dst_odoo.session.env[model_name]
            # dst_template_attribute_value_model = self._dst_odoo.session.env['product.template.attribute.value']

            if action == 'create':
                logging.info(f"Creating attribute value \"{src_record.name}\" ...")
                product_attribute_value = dst_model.create(data)
                # product_template_attribute_value = product_attribute_value = dst_template_attribute_value_model.create(secondary_data)
                src_record.write({'x_new_id': product_attribute_value})

            elif action == 'update':
                logging.info(f"Updating attribute value \"{src_record.name}\" ...")
                dst_record = record['dst_record']
                src_record.write({'x_new_id': dst_record.id})
                dst_record.write(data)
