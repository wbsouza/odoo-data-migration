import logging
from typing import Dict, Generic, List, Optional, Type, TypeVar, Union, Any
from .base import DomainHandler
from ..core.odoo_connection import OdooConnectionProvider, SOURCE, DESTINATION
from ..core.database import DBConnectionProvider, find_id_by_old_id

class ProductProductHandler(DomainHandler):

    def __init__(
            self,
            odoo_provider: OdooConnectionProvider,
            db_provider: DBConnectionProvider,
            model_name: str
    ):
        """
        Initialize the ProductProductHandler with the provider pattern.
        :param odoo_provider: OdooConnectionProvider instance.
        :param db_provider: DBConnectionProvider instance.
        :param model_name: The model name to migrate.
        """
        super().__init__(odoo_provider, db_provider, model_name)
        self._odoo_src = odoo_provider.get_odoo_connection(SOURCE)
        self._odoo_dst = odoo_provider.get_odoo_connection(DESTINATION)

    def find_dst_product(self, src_record):
        conn = self._db_provider.get_connection(DESTINATION)
        dst_product_tmpl_id = find_id_by_old_id(conn, 'product_template', src_record.product_tmpl_id.id)
        if not dst_product_tmpl_id or dst_product_tmpl_id is None:
            raise ValueError(f"Product template '{src_record.product_tmpl_id.name}' not found in destination")

        # Include both active and archived records in search
        domain = [('product_tmpl_id', '=', dst_product_tmpl_id)]
        if src_record.default_code is not None and src_record.default_code and src_record.default_code != '':
            domain.append(('default_code', '=', src_record.default_code))

        model = self.get_dst_model()
        product_ids = model.search(domain, limit=1)
        if product_ids:
            return model.browse(product_ids[0])
        return None


    def apply_transformations(self, src_record: Any) -> List[Dict]:
        result = []
        existing_product = self.find_dst_product(src_record)
        if existing_product:
            result = [{
                'action': 'update' if existing_product else 'create',
                'dst_model': 'product.product',
                'src_record': src_record,
                'dst_record': existing_product,
                'data': {
                    'default_code': src_record.default_code,
                }
            }]
        return result

    def save_into_destination(self, transformed_records: List[Dict]):
        """
        Save the transformed records in the destination system.
        This handles creating/updating product.product in the destination Odoo 17.
        """
        for record in transformed_records:
            data = record['data']
            action = record['action']
            if 'src_record' in data:
                if action == 'update':
                    src_record = data['src_record']
                    dst_record = data['dst_record']
                    dst_record.write(data)
                    self.update_tracking_ids(dst_record.id, src_record)
