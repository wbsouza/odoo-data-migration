import logging

from typing import Dict, List, Optional, Any

from .base import DomainHandler
from ..core.mapping import MappingProvider
from ..core.odoo_connection import OdooConnectionProvider, DESTINATION
from ..core.database import DBConnectionProvider


class ProductCategoryHandler(DomainHandler):

    def __init__(
            self,
            odoo_provider: OdooConnectionProvider,
            db_provider: DBConnectionProvider,
            mapping_provider: MappingProvider,
            model_name: str
    ):
        super().__init__(odoo_provider, db_provider, 'product.category')
        self._mapping_provider = mapping_provider

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

    def find_category_by_name(self, name) -> bool:
        domain = [('name', '=', name)]
        odoo_dst = self._odoo_provider.get_odoo_connection(DESTINATION)
        model = odoo_dst.session.env[self.src_model_name]
        ids = model.search(domain, limit=1)
        if ids is not None and len(ids):
            return model.browse(ids[0])[0]
        return None

    def find_dst_parent_by_old_name(self, name):
        domain = [('name', '=', name)]
        odoo_dst = self._odoo_provider.get_odoo_connection(DESTINATION)
        model = odoo_dst.session.env[self.src_model_name]
        ids = model.search(domain, limit=1)
        if ids is not None and len(ids):
            return model.browse(ids[0])[0]
        return None

    def create_parent_path(self, record):
        parent_path = ''
        divisions_number = record.complete_name.count('/')
        if divisions_number == 0:
            parent= self.find_dst_parent_by_old_name(record.name)
            if parent is None:
                parent_path = f'{record.id}/'
            if parent:
                parent_path = f'{parent.id}/'
        else:
            names = record.complete_name.replace('/', ' ').split()
            ids = []
            for name in names:
                parent = self.find_dst_parent_by_old_name(name)
                if parent is not None:
                    parent_path += f'{parent.id}/'
                else:
                    parent_path = None
        return parent_path


    def apply_transformations(self, src_record: Any) -> List[Dict]:
        dst_parent = None
        if src_record.parent_id is not None:
            dst_parent = self.find_dst_parent_by_old_name(src_record.parent_id.name)
        transformed_record = {
            'action': 'create',
            'model': 'product.category',
            'src_record': src_record,
            'dst_record': self.find_category_by_name(src_record.name),
            'data': {
                'parent_id': dst_parent.id if dst_parent is not None else dst_parent,
                'name': src_record.name,
                'complete_name': src_record.complete_name,
                'parent_path': self.create_parent_path(src_record)
                # 'groups_id': [(6, 0, dst_group_ids)],
                # 'x_old_id': src_record.id  # This field will be set via update_tracking_ids method
            }
        }

        # already exists ...
        if transformed_record['dst_record'] is not None:
            transformed_record['action'] = 'update'

        return [transformed_record]

    def save_into_destination(self, transformed_records: List[Dict]):
        """
        Save the transformed records in the destination system.
        This handles creating product.category in the destination Odoo (Odoo 16).
        """
        for transformed_record in transformed_records:

            model_name = transformed_record['model']
            data = transformed_record['data']
            action = transformed_record['action']
            src_record = transformed_record['src_record']

            if action in ['create', 'update']:

                if action == 'create':
                    dst_model = self.get_dst_model()
                    logging.info(f"Creating {self.get_dst_model_name()} \"{src_record.name}\" ...")
                    new_id = dst_model.create(data)

                elif action == 'update':
                    logging.info(f"Updating category \"{src_record.name}\" ...")
                    dst_record = transformed_record['dst_record']
                    dst_record.write(data)
                    new_id = dst_record.id

                self.update_tracking_ids(
                    new_id=new_id,
                    record=src_record
                )
