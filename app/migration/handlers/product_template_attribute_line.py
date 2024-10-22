import logging

from typing import Dict, Generic, List, Optional, Type, TypeVar, Union, Any

from .base import DomainHandler, ResourceNotFoundException
from ..core.mapping import MappingProvider
from ..core.odoo import OdooConnection

import json

class ProductTemplateAttributeLineHandler(DomainHandler):

    def __init__(self, src_odoo: OdooConnection, dst_odoo: OdooConnection, mapping_provider: MappingProvider):
        """
        Initialize the ResGroupsHandler with the source and destination Odoo connections, and the MappingProvider.
        :param src_odoo: OdooConnection instance for the source Odoo.
        :param dst_odoo: OdooConnection instance for the destination Odoo.
        :param mapping_provider: An instance of MappingProvider to handle ID mappings.
        """
        super().__init__(src_odoo, dst_odoo, 'product.attribute.line')
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
            resp = self.dst_odoo.fetch_ids('res.groups', domain=domain, limit=1)
            if resp is not None and len(resp) > 0:
                return resp[0]
        return None

    def find_dst_product_tmpl(self, record):
        domain = [('name', '=', record.product_tmpl_id.name)]
        model = self.dst_odoo.session.env['product.template']
        product_tmpl_id = model.search(domain)
        product_tmpl = model.browse(product_tmpl_id[0])
        return product_tmpl

    def find_dst_attribute(self, record):
        domain = [('name', '=', record.attribute_id.name)]
        model = self.dst_odoo.session.env['product.attribute']
        attribute_id = model.search(domain)
        attribute = model.browse(attribute_id[0])
        return attribute

    def dst_template_attribute_line_exists(self, record: Any) -> bool:
        attribute = self.find_dst_attribute(record)
        product_tmpl = self.find_dst_product_tmpl(record)
        domain = []
        if attribute and product_tmpl:
            domain = ['&', ('attribute_id', '=', attribute.id),
                      ('product_tmpl_id', '=', product_tmpl.id),]
        else:
            domain = ['&', ('attribute_id', '=', record.attribute_id.id),
                      ('product_tmpl_id', '=', record.product_tmpl_id.id),]
        model = self.dst_odoo.session.env['product.template.attribute.line']
        ids = model.search(domain, limit=1)
        return ids is not None and len(ids) > 0

    def apply_transformations(self, record: Any) -> List[Dict]:

        transformed_records = []
        attribute = self.find_dst_attribute(record)
        product_tmpl = self.find_dst_product_tmpl(record)
        if self.dst_template_attribute_line_exists(record):
            template_attribute_line_dst_data = {
                'attribute_id': attribute.id,
                'product_tmpl_id': product_tmpl.id,
                'old_id': record.id,
            }
            transformed_records.append({ 'action': 'update', 'model': 'product.template.attribute.line', 'data': template_attribute_line_dst_data})

        else:

            # dst_group_ids = []
            # for src_group in record.groups_id:
            #     dst_group_id = self.find_dest_group_id(src_group)
            #     if dst_group_id is not None:
            #         dst_group_ids.append(dst_group_id)

            # data = record.read()[0]
            # sdata = json.dumps(data)
            # print(sdata)

            template_attribute_line_dst_data = {
                'attribute_id': attribute.id,
                'product_tmpl_id': product_tmpl.id,
                # 'groups_id': [(6, 0, dst_group_ids)],
                'old_id': record.id
            }
            transformed_records.append({'action': 'create', 'model': 'product.template.attribute.line', 'data': template_attribute_line_dst_data})

        return transformed_records

    def save_into_destination(self, transformed_records: List[Dict]):
        """
        Save the transformed records in the destination system.
        This handles creating product.template in the destination Odoo (Odoo 16).
        """
        for record in transformed_records:
            model_name = record['model']
            data = record['data']
            action = record['action']

            src_model = self.src_odoo.session.env[self.model_name]
            src_record = src_model.browse(data['old_id'])

            dst_model = self.dst_odoo.session.env['product.template.attribute.line']

            if action == 'create':
                logging.info(f"Creating attribute line \"{src_record.old_id}\" ...")
                new_id = dst_model.create(data)
                src_record.write({'new_id': new_id})
            elif action == 'update':
                logging.info(f"Updating attribute line \"{src_record.old_id}\" ...")
                dst_record = None
                if src_record.new_id is not None and src_record.new_id > 0:
                    dst_record = dst_model.browse(src_record.new_id)
                else:
                    domain = [('name', '=', src_record.old_id
                               )]
                    result = dst_model.search(domain=domain, limit=1)
                    if result is not None and len(result) > 0:
                        dst_record = dst_model.browse(result[0])

                if dst_record is not None:
                    src_record.write({'new_id': dst_record.id})
                    dst_record.write(data)

