import logging
from typing import Dict, List, Optional, Any
from .base import DomainHandler, DESTINATION, SOURCE
from ..core.mapping import MappingProvider
from ..core.odoo_connection import OdooConnectionProvider
from ..core.db_connection import DBConnectionProvider


class ProductAttributeValueHandler(DomainHandler):

    def __init__(
            self,
            odoo_provider: OdooConnectionProvider,
            db_provider: DBConnectionProvider,
            mapping_provider: MappingProvider,
            model_name: str
    ):
        """
        Initialize the ProductAttributeValueHandler with the provider pattern.
        :param odoo_provider: OdooConnectionProvider instance.
        :param db_provider: DBConnectionProvider instance.
        :param mapping_provider: An instance of MappingProvider to handle ID mappings.
        :param model_name: The model name to migrate.
        """
        super().__init__(odoo_provider, db_provider, 'product.attribute.value')
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

    def template_attribute_value_exists(self, src_record: Any) -> bool:
        domain = [('name', '=', src_record.name)]
        model = self._odoo_provider.get_odoo_connection(DESTINATION).session.env[self.src_model_name]
        ids = model.search(domain, limit=1)
        return ids is not None and len(ids) > 0

    def find_dst_attribute_by_name(self, src_record):
        domain = [('name', '=', src_record.attribute_id.name)]
        model = self._odoo_provider.get_odoo_connection(DESTINATION).session.env['product.attribute']
        attribute_id = model.search(domain)
        attribute = model.browse(attribute_id[0])
        return attribute

    def find_dst_attribute_value(self, src_record):
        domain = [('name', '=', src_record.name)]
        model = self._odoo_provider.get_odoo_connection(DESTINATION).session.env['product.attribute.value']
        attribute_id = model.search(domain)
        attribute_value = model.browse(attribute_id)
        if attribute_id is not None and len(attribute_id):
            return model.browse(attribute_id[0])[0]
        return None

    def find_dst_attribute_value_by_name(self, name) -> bool:
        domain = [('name', '=', name)]
        model = self._odoo_provider.get_odoo_connection(DESTINATION).session.env[self.src_model_name]
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
            # 'x_old_id': src_record.id,  # This field will be set via update_tracking_ids method
            }
        }

        # already exists ...
        if transformed_record['dst_record'] is not None:
            transformed_record['action'] = 'update'

        return [transformed_record]

    def save_into_destination(self, transformed_records: List[Dict]):
        """
        Save the transformed records in the destination system.
        This handles creating product.attribute.value in the destination Odoo (Odoo 16).
        """
        for transformed_record in transformed_records:
            model_name = transformed_record['model']
            data = transformed_record['data']
            action = transformed_record['action']
            src_record = transformed_record['src_record']

            if action in ['create', 'update']:

                if action == 'create':
                    dst_model = self.get_dst_model()
                    logging.info(f"Creating attribute value \"{src_record.name}\" ...")
                    new_id = dst_model.create(data)

                elif action == 'update':
                    logging.info(f"Updating attribute value \"{src_record.name}\" ...")
                    dst_record = transformed_record['dst_record']
                    dst_record.write(data)
                    new_id = dst_record.id

                self.update_tracking_ids(
                    new_id=new_id,
                    src_record=src_record
                )
