import logging
from typing import Dict, Generic, List, Optional, Type, TypeVar, Union, Any

from .base import DomainHandler, ResourceNotFoundException
from ..core.mapping import MappingProvider
from ..core.odoo import OdooConnection

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
            resp = self.dst_odoo.fetch_ids('res.groups', domain=domain, limit=1)
            if resp is not None and len(resp) > 0:
                result = resp[0]
                # update the cache with the respective id
                self.mapping_provider.set_mapping('res.groups', src_group.id, result)
        return result

    def user_exists(self, login: str) -> bool:
        domain = [('login', '=', login)]
        model = self.dst_odoo.session.env[self.model_name]
        ids = model.search(domain, limit=1)
        return ids is not None and len(ids) > 0

    def apply_transformations(self, res_user_record: Any) -> List[Dict]:

        transformed_records = []
        if self.user_exists(res_user_record.login):
            user_dst_data = {
                'login': res_user_record.login,
                'old_id': res_user_record.id,
                'name': res_user_record.name
            }
            transformed_records.append({'action': 'update', 'model': self.model_name, 'data': user_dst_data})

        else:

            # TODO: Fix the data inconsistencies on the source
            # dst_group_ids = []
            # for src_group in res_user_record.groups_id:
            #     dst_group_id = self.find_dest_group_id(src_group)
            #     if dst_group_id is not None:
            #         dst_group_ids.append(dst_group_id)

            user_dst_data = {
                'name': res_user_record.name,
                'login': res_user_record.login,
                'email': res_user_record.email,
                'company_id': res_user_record.company_id.id,
                'lang': res_user_record.lang,
                'tz': res_user_record.tz,
                #'groups_id': [(6, 0, dst_group_ids)],
                'old_id': res_user_record.id
            }
            transformed_records.append({'action': 'create', 'model': self.model_name, 'data': user_dst_data})

        return transformed_records

    def save_into_destination(self, transformed_records: List[Dict]):
        """
        Save the transformed records in the destination system.
        This handles creating res.users in the destination Odoo (Odoo 16).
        """
        for record in transformed_records:

            model_name = record['model']
            data = record['data']
            action = record['action']

            src_model = self.src_odoo.session.env[self.model_name]
            dst_model = self.dst_odoo.session.env[model_name]

            src_record = src_model.browse(data['old_id'])

            if action == 'create':
                logging.info(f"Creating user \"{src_record.login}\" ...")
                new_id = dst_model.create(data)
                src_record.write({'new_id': new_id})
            elif action == 'update':
                logging.info(f"Updating user \"{src_record.login}\" ...")
                dst_record = None
                if src_record.new_id is not None and src_record.new_id > 0:
                    dst_record = dst_model.browse(src_record.new_id)
                else:
                    domain = [('login', '=', src_record.login)]
                    result = dst_model.search(domain=domain, limit=1)
                    if result is not None and len(result) > 0:
                        dst_record = dst_model.browse(result[0])

                if dst_record is not None:
                    src_record.write({'new_id': dst_record.id})
                    dst_record.write(data)

