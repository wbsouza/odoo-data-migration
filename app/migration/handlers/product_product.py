import logging
from typing import Dict, Generic, List, Optional, Type, TypeVar, Union, Any
from .base import DomainHandler
from ..core.odoo_connection import OdooConnectionProvider, SOURCE, DESTINATION
from ..core.database import DBConnectionProvider, find_id_by_old_id, find_record_by_old_id

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
        # We only update existing variants. Variants are auto-generated from
        # product_template_attribute_line in Odoo 17. If not found, we skip.
        conn = self._db_provider.get_connection(DESTINATION)
        # Prefer lookup by x_old_id first
        existing_product = find_record_by_old_id(conn, 'product_product', src_record.id)
        dst_record = None
        if existing_product:
            dst_record = self.get_dst_model('product.product').browse(existing_product['id'])
        else:
            # Fallback: try to resolve by template + default_code
            dst_record = self.find_dst_product(src_record)

        if not dst_record:
            return []

        result = [{
            'action': 'update',
            'model': 'product.product',
            'src_record': src_record,
            'dst_record': dst_record,
            'data': {
                'default_code': src_record.default_code,
                # 'lst_price': src_record.lst_price or None,
                # 'esp_price': src_record.esp_price or None,
                'x_old_id': src_record.id,
            }
        }]

        return result

    def save_into_destination(self, transformed_records: List[Dict]):
        """
        Save the transformed records in the destination system.
        This handles creating/updating product.product in the destination Odoo 17.
        """
        # Delegate to generic create/update+tracking routine
        self.save_records(
            transformed_records=transformed_records,
            default_model_name=self.get_dst_model_name(),
            entity_label='product',
            name_field='name',
        )
