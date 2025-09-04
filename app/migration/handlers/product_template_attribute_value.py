import logging
from typing import Dict, Generic, List, Optional, Type, TypeVar, Union, Any
from .base import DomainHandler, ResourceNotFoundException
from ..core.mapping import MappingProvider
from ..core.odoo_connection import OdooConnection
import json


class ProductTemplateAttributeValueHandler(DomainHandler):

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

    def find_dst_template_attribute_value(self, product_attribute_value_id: Any, attribute_line_id: Any,
                                          product_tmpl_id: Any, attribute_id: Any, ) -> bool:
        domain = ['&', '&', '&',
                  ('product_attribute_value_id', '=', product_attribute_value_id),
                  ('attribute_line_id', '=', attribute_line_id),
                  ('product_tmpl_id', '=', product_tmpl_id),
                  ('attribute_id', '=', attribute_id)]
        model = self._dst_odoo.session.env['product.template.attribute.value']
        ids = model.search(domain, limit=1)
        if ids is not None and len(ids):
            return model.browse(ids[0])[0]
        return None

    def find_dst_product_tmpl(self, src_record):
        domain = [('name', '=', src_record.product_tmpl_id.name)]
        model = self._dst_odoo.session.env['product.template']
        product_tmpl_id = model.search(domain)
        product_tmpl = model.browse(product_tmpl_id[0])
        return product_tmpl

    def find_dst_attribute_line_by_attribute_and_product_tmpl(self, attribute, product_tmpl) -> bool:
        domain = ['&', ('attribute_id', '=', attribute.id),
                  ('product_tmpl_id', '=', product_tmpl.id), ]
        model = self._dst_odoo.session.env['product.template.attribute.line']
        ids = model.search(domain, limit=1)
        if ids is not None and len(ids):
            return model.browse(ids[0])[0]
        return None

    def find_dst_attribute(self, src_record):
        domain = [('name', '=', src_record.attribute_id.name)]
        model = self._dst_odoo.session.env['product.attribute']
        attribute_id = model.search(domain)
        attribute = model.browse(attribute_id[0])
        return attribute

    def find_dst_product_attribute_value(self, src_record):
        domain = [('name', '=', src_record.product_attribute_value_id.name)]
        model = self._dst_odoo.session.env['product.attribute.value']
        attribute_value_id = model.search(domain)
        attribute_value = model.browse(attribute_value_id)
        return attribute_value

    def apply_transformations(self, src_record: Any) -> List[Dict]:
        dst_attribute = self.find_dst_attribute(src_record)
        dst_product_tmpl = self.find_dst_product_tmpl(src_record)
        dst_attribute_line = self.find_dst_attribute_line_by_attribute_and_product_tmpl(dst_attribute, dst_product_tmpl)
        dst_product_attribute_value = self.find_dst_product_attribute_value(src_record)
        transformed_record = {
            'action': 'create',
            'dst_model': 'product.template.attribute.value',
            'model': 'product.attribute.value',
            'src_record': src_record,
            'dst_record': self.find_dst_template_attribute_value(
                dst_attribute.id, dst_product_tmpl.id, dst_attribute_line.id, dst_product_attribute_value.id),
            'data': {
            'product_attribute_value_id': dst_product_attribute_value.id,
            'attribute_line_id': dst_attribute.id,
            'product_tmpl_id': dst_attribute.id,
            'attribute_id': dst_attribute.id ,
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
        This handles creating product.template.attribute.value in the destination Odoo (Odoo 16).
        """
        for transformed_record in transformed_records:

            model_name = transformed_record['model']
            data = transformed_record['data']
            action = transformed_record['action']
            src_record = transformed_record['src_record']

            if action == 'create':
                dst_model = self._dst_odoo.session.env['product.template.attribute.value']
                logging.info(f"Creating attribute \"{src_record.product_tmpl_id.name, src_record.attribute_id.name, src_record.product_attribute_value_id.name,}\" ...")
                new_id = dst_model.create(data)
                src_record.write({'x_new_id': new_id})
            elif action == 'update':
                logging.info(f"Updating attribute \"{src_record.product_tmpl_id.name, src_record.attribute_id.name, src_record.product_attribute_value_id.name, }\" ...")
                dst_record = transformed_record['dst_record']
                dst_record.write(data)
                src_record.write({'x_new_id': dst_record.id})

