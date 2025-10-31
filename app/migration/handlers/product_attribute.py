import logging
from typing import Dict, List, Optional, Any

from .base import DomainHandler
from ..core.mapping import MappingProvider
from ..core.odoo_connection import OdooConnectionProvider, DESTINATION, SOURCE
from ..core.database import DBConnectionProvider



class ProductAttributeHandler(DomainHandler):

    def __init__(
            self,
            odoo_provider: OdooConnectionProvider,
            db_provider: DBConnectionProvider,
            mapping_provider: MappingProvider,
            model_name: str
    ):
        super().__init__(odoo_provider, db_provider, model_name)
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
                self._mapping_provider.set_mapping('res.groups', src_group.id, result)
        return result

    def find_dst_attribute(self, record):
        domain = [('name', '=', record.attribute_id.name)]
        odoo_dst = self._odoo_provider.get_odoo_connection(DESTINATION)
        model = odoo_dst.session.env['product.attribute']
        attribute_id = model.search(domain)
        attribute = model.browse(attribute_id[0])
        return attribute

    def find_product_attribute_by_name(self, name: str) -> bool:
        domain = [('name', '=', name)]
        odoo_dst = self._odoo_provider.get_odoo_connection(DESTINATION)
        model = odoo_dst.session.env[self.src_model_name]
        ids = model.search(domain, limit=1)
        if ids is not None and len(ids):
            return model.browse(ids[0])[0]
        return None

    def get_src_model(self, model_name: str = None) -> Any:
        if model_name is None:
            model_name = self.src_model_name
        odoo_conn = self._odoo_provider.get_odoo_connection(SOURCE)
        return odoo_conn.session.env[model_name]

    def get_dst_model(self, model_name: str = None) -> Any:
        if model_name is None:
            model_name = self.get_dst_model_name()
        odoo_conn = self._odoo_provider.get_odoo_connection(DESTINATION)
        return odoo_conn.session.env[model_name]

    def apply_transformations(self, src_record: Any) -> List[Dict]:
        transformed_record = {
            'action': 'create',
            'model': 'product.attribute',
            'src_record': src_record,
            'dst_record': self.find_product_attribute_by_name(src_record.name),
            'data': {
                'name': src_record.name,
                'sequence': src_record.sequence,
                'x_old_id': src_record.id,
                # 'display_type': src_record.type,
            }
        }
        if src_record.create_variant:
            transformed_record['data']['create_variant'] = 'always'

        # already exists ...
        if transformed_record['dst_record'] is not None:
            transformed_record['action'] = 'update'

        return [transformed_record]

    def save_into_destination(self, transformed_records: List[Dict]):
        """
        Save the transformed records in the destination system.
        This handles creating product.attribute in the destination Odoo (Odoo 16).
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
                    x_new_id = dst_model.create(data)

                elif action == 'update':
                    logging.info(f"Updating attribute \"{src_record.name}\" ...")
                    dst_record = transformed_record['dst_record']
                    dst_record.write(data)
                    x_new_id = dst_record.id

                self.update_tracking_ids(
                    x_new_id=x_new_id,
                    record=src_record
                )
