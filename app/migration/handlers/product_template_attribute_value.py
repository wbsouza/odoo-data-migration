import logging

from typing import Dict, Generic, List, Optional, Type, TypeVar, Union, Any

from .base import DomainHandler, ResourceNotFoundException
from ..core.mapping import MappingProvider
from ..core.odoo import OdooConnection

import json


class ProductTemplateAttributeValueHandler(DomainHandler):

    def __init__(self, src_odoo: OdooConnection, dst_odoo: OdooConnection, mapping_provider: MappingProvider):
        """
        Initialize the ResGroupsHandler with the source and destination Odoo connections, and the MappingProvider.
        :param src_odoo: OdooConnection instance for the source Odoo.
        :param dst_odoo: OdooConnection instance for the destination Odoo.
        :param mapping_provider: An instance of MappingProvider to handle ID mappings.
        """
        super().__init__(src_odoo, dst_odoo, 'product.template.attribute.value')
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

    def template_value_exists(self, name: str, default_code: str) -> bool:
        domain = ['&', ('name', '=', name), ('default_code', '=', default_code)]
        model = self.dst_odoo.session.env[self.model_name]
        ids = model.search(domain, limit=1)
        return ids is not None and len(ids) > 0

    def apply_transformations(self, record: Any) -> List[Dict]:

        transformed_records = []
        if self.template_value_exists(record.name, record.default_code):
            template_dst_data = {
                'name': record.name,
                'default_code': record.default_code,
                'old_id': record.id,
            }
            transformed_records.append({ 'action': 'update', 'model': self.model_name, 'data': template_dst_data})

        else:

            # dst_group_ids = []
            # for src_group in record.groups_id:
            #     dst_group_id = self.find_dest_group_id(src_group)
            #     if dst_group_id is not None:
            #         dst_group_ids.append(dst_group_id)

            # data = record.read()[0]
            # sdata = json.dumps(data)
            # print(sdata)

            template_value_dst_data = {
                'name': record.name,
                'default_code': record.default_code,
                # 'groups_id': [(6, 0, dst_group_ids)],
                'old_id': record.id
            }
            transformed_records.append({'action': 'create', 'model': self.model_name, 'data': template_value_dst_data})

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

            dst_model = self.dst_odoo.session.env[model_name]

            if action == 'create':
                logging.info(f"Creating template \"{src_record.name}\" ...")
                new_id = dst_model.create(data)
                src_record.write({'new_id': new_id})
            elif action == 'update':
                logging.info(f"Updating template \"{src_record.name}\" ...")
                dst_record = None
                if src_record.new_id is not None and src_record.new_id > 0:
                    dst_record = dst_model.browse(src_record.new_id)
                else:
                    domain = [('name', '=', src_record.name
                               )]
                    result = dst_model.search(domain=domain, limit=1)
                    if result is not None and len(result) > 0:
                        dst_record = dst_model.browse(result[0])

                if dst_record is not None:
                    src_record.write({'new_id': dst_record.id})
                    dst_record.write(data)

