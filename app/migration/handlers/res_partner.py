import logging

from typing import Dict, Generic, List, Optional, Type, TypeVar, Union, Any

from .base import DomainHandler, ResourceNotFoundException
from ..core.mapping import MappingProvider
from ..core.odoo_connection import OdooConnection, OdooConnectionProvider
from ..core.db_connection import DBConnectionProvider

import json


class ResPartnerHandler(DomainHandler):

    def find_dest_group_id(self, src_group: Any) -> Optional[int]:
        """
        Find the matching category ID in the destination Odoo (Odoo 16) based on the source category ID from Odoo 11.
        First check the mappings cache, and if not found, perform a lookup.
        :param src_group: The source category
        :return: The destination category ID.
        """

        if src_group is not None:
            domain = [('name', '=', src_group['name'])]
            resp = self._dst_odoo.fetch_ids('res.groups', domain=domain, limit=1)
            if resp is not None and len(resp) > 0:
                return resp[0]
        return None

    def __init__(self, odoo_provider: OdooConnectionProvider, db_provider: DBConnectionProvider, model_name: str):
        super().__init__(odoo_provider, db_provider, 'res.partner')

    def find_dest_partner_by_name(self, name) -> bool:
        domain = [('name', '=', name)]
        model = self.get_dst_model()
        ids = model.search(domain, limit=1)
        if ids is not None and len(ids):
            return model.browse(ids[0])[0]
        return None

    def apply_transformations(self, src_record: Any) -> List[Dict]:
        transformed_record = {
            'action': 'create',
            'model': 'res.partner',
            'src_record': src_record,
            'dst_record': self.find_dest_partner_by_name(src_record.name),
            'data': {
                'name': src_record.name,
                'display_name': src_record.display_name,
                'email': src_record.email,
                'company_id': src_record.company_id.id,
                'lang': src_record.lang,
                'tz': src_record.tz,
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
                    src_record=src_record
                )
