import logging
from typing import Dict, Generic, List, Optional, Type, TypeVar, Union, Any
from .base import DomainHandler, ResourceNotFoundException
from ..core.mapping import MappingProvider
from ..core.odoo_connection import OdooConnectionProvider, SOURCE, DESTINATION
from ..core.db_connection import DBConnectionProvider

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

    def find_dst_product_tmpl(self, src_record):
        """Find the corresponding product template in destination"""
        domain = [('name', '=', src_record.product_tmpl_id.name)]
        model = self._odoo_dst.session.env['product.template']
        template_ids = model.search(domain)
        if not template_ids:
            raise ValueError(f"Product template '{src_record.product_tmpl_id.name}' not found in destination")
        return model.browse(template_ids[0])

    def find_dst_product_by_template_and_code(self, template_id, default_code):
        """Check if product already exists in destination"""
        domain = [('product_tmpl_id', '=', template_id), ('default_code', '=', default_code)]
        model = self._odoo_dst.session.env['product.product']
        product_ids = model.search(domain, limit=1)
        if product_ids:
            return model.browse(product_ids[0])
        return None

    def apply_transformations(self, src_record: Any) -> List[Dict]:
        """Transform source record for destination, focusing only on CREATE operations"""
        dst_product_tmpl = self.find_dst_product_tmpl(src_record)
        
        # Check if product already exists in destination
        existing_product = self.find_dst_product_by_template_and_code(
            dst_product_tmpl.id, 
            src_record.default_code
        )
        
        transformed_record = {
            'action': 'update' if existing_product else 'create',
            'dst_model': 'product.product',
            'src_record': src_record,
            'dst_record': existing_product,
            'data': {
                'product_tmpl_id': dst_product_tmpl.id,
                'default_code': src_record.default_code,
                'x_old_id': src_record.id,  # This field will be set via update_tracking_ids method
            }
        }
        
        # Set action based on whether record already exists
        if existing_product:
            transformed_record['action'] = 'update'
        else:
            transformed_record['action'] = 'create'

        return [transformed_record]

    def save_into_destination(self, transformed_records: List[Dict]):
        """
        Save the transformed records in the destination system.
        This handles creating/updating product.product in the destination Odoo 17.
        """
        for record in transformed_records:
            data = record['data']
            action = record['action']
            src_model = self._odoo_src.session.env[self.src_model_name]

            if 'x_old_id' in data:
                old_id = data.pop('x_old_id')
                src_record = src_model.browse(old_id)
                dst_model = self._odoo_dst.session.env[record['dst_model']]

                if action == 'create':
                    logging.info(f"Creating product \"{src_record.default_code or 'No Code'}\" ...")
                    new_id = dst_model.create(data)
                    self.update_tracking_ids(new_id, src_record)

                elif action == 'update':
                    logging.info(f"Updating product \"{src_record.default_code or 'No Code'}\" ...")
                    dst_record = record['dst_record']
                    dst_record.write(data)
                    self.update_tracking_ids(dst_record.id, src_record)
