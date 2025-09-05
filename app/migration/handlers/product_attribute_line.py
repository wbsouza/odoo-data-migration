import logging
from typing import Dict, Generic, List, Optional, Type, TypeVar, Union, Any
from .base import DomainHandler, ResourceNotFoundException
from ..core.mapping import MappingProvider
from ..core.mapping import MappingProvider
from ..core.odoo_connection import OdooConnectionProvider, SOURCE, DESTINATION
from ..core.db_connection import DBConnectionProvider

class ProductAttributeLineHandler(DomainHandler):

    def __init__(
            self,
            odoo_provider: OdooConnectionProvider,
            db_provider: DBConnectionProvider,
            model_name: str
    ):
        """
        Initialize the ProductAttributeValueHandler with the provider pattern.
        :param odoo_provider: OdooConnectionProvider instance.
        :param db_provider: DBConnectionProvider instance.
        :param model_name: The model name to migrate.
        """
        super().__init__(odoo_provider, db_provider, model_name)
        self._odoo_src = odoo_provider.get_odoo_connection(SOURCE)
        self._odoo_dst = odoo_provider.get_odoo_connection(DESTINATION)

    # overriding the get_dst_model_name method
    def get_dst_model_name(self) -> str:
        return 'product.template.attribute.line'

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
            resp = self._odoo_dst.fetch_ids('res.groups', domain=domain, limit=1)
            if resp is not None and len(resp) > 0:
                return resp[0]
        return None

    def find_dst_product_tmpl(self, record):
        domain = [('name', '=', record.product_tmpl_id.name)]
        model = self._odoo_dst.session.env['product.template']
        product_tmpl_id = model.search(domain)
        product_tmpl = model.browse(product_tmpl_id[0])
        return product_tmpl

    def find_dst_attribute(self, record):
        domain = [('name', '=', record.attribute_id.name)]

        model = self._odoo_dst.session.env['product.attribute']
        attribute_id = model.search(domain)
        attribute = model.browse(attribute_id[0])
        return attribute

    def find_attribute_values(self, attribute):
        domain = [('attribute_id', '=', attribute.id)]
        model = self._odoo_dst.session.env['product.attribute.value']
        attribute_values = model.search(domain)
        return attribute_values

    def find_dst_attribute_line_by_attribute_and_product_tmpl(self, attribute, product_tmpl) -> bool:
        domain = ['&', ('attribute_id', '=', attribute.id),
                      ('product_tmpl_id', '=', product_tmpl.id),]
        model = self._odoo_dst.session.env['product.template.attribute.line']
        ids = model.search(domain, limit=1)
        if ids is not None and len(ids):
            return model.browse(ids[0])[0]
        return None

    def find_dst_product_by_product_tmpl(self, product_tmpl_id: int) -> bool:
        domain = [('product_tmpl_id', '=', product_tmpl_id)]
        model = self._odoo_dst.session.env['product.product']
        ids = model.search(domain, order='id desc')
        if ids is not None and len(ids):
            return ids
        return None

    def find_src_product_by_product_tmpl(self, product_tmpl_id: int) -> bool:
        domain = [('product_tmpl_id', '=', product_tmpl_id)]
        model = self._odoo_src.session.env['product.product']
        ids = model.search(domain, order='id desc')
        if ids is not None and len(ids):
            return ids
        return None

    def get_specific_attribute_values_for_template(self, src_record):
        """
        Get only the attribute values that are actually used in existing Odoo 11 variants
        for this specific template and attribute combination.
        This prevents cartesian product creation and migrates EXACTLY what exists.
        """
        # Find all existing product.product variants in Odoo 11 for this template
        src_product_ids = self._odoo_src.session.env['product.product'].search([
            ('product_tmpl_id', '=', src_record.product_tmpl_id.id)
        ])
        
        # Browse the records to get actual record objects
        src_products = self._odoo_src.session.env['product.product'].browse(src_product_ids)
        
        # Collect attribute values used by these specific variants for this attribute
        used_value_names = set()
        for product in src_products:
            # Get attribute values for this product and this specific attribute
            for attr_value in product.attribute_value_ids:
                if attr_value.attribute_id.id == src_record.attribute_id.id:
                    used_value_names.add(attr_value.name)
        
        # Find corresponding values in destination Odoo 17
        dst_attribute = self.find_dst_attribute(src_record)
        dst_value_ids = []
        
        for value_name in used_value_names:
            domain = [('attribute_id', '=', dst_attribute.id), ('name', '=', value_name)]
            dst_value_ids_found = self._odoo_dst.session.env['product.attribute.value'].search(domain, limit=1)
            if dst_value_ids_found:
                dst_value_ids.append(dst_value_ids_found[0])
        
        logging.info(f"Template {src_record.product_tmpl_id.name}, Attribute {src_record.attribute_id.name}: "
                    f"Found {len(dst_value_ids)} specific values: {list(used_value_names)}")
        
        return dst_value_ids

    def apply_transformations(self, src_record: Any) -> List[Dict]:
        dst_attribute = self.find_dst_attribute(src_record)
        # Get only the specific attribute values used in existing Odoo 11 variants
        values_ids = self.get_specific_attribute_values_for_template(src_record)
        product_tmpl = self.find_dst_product_tmpl(src_record)
        
        # Skip if no specific values found (prevents empty attribute lines)
        if not values_ids:
            logging.warning(f"No specific attribute values found for template {src_record.product_tmpl_id.name}, "
                          f"attribute {src_record.attribute_id.name}. Skipping.")
            return []
        transformed_record = {
            'action': 'create',
            'dst_model': self.get_dst_model_name(),
            'src_record': src_record,
            'dst_record': self.find_dst_attribute_line_by_attribute_and_product_tmpl(dst_attribute, product_tmpl),
            'data': {
                'attribute_id': dst_attribute.id,
                'product_tmpl_id': product_tmpl.id,
                'x_old_id': src_record.id,  # This field will be set via update_tracking_ids method
                'value_ids': [(6, 0, values_ids)],
            }
        }

        # already exists ...
        if transformed_record['dst_record'] is not None:
            transformed_record['action'] = 'update'

        return [transformed_record]

    def save_into_destination(self, transformed_records: List[Dict]):
        """
        Save the transformed records in the destination system.
        This handles creating product.template in the destination Odoo (Odoo 16).
        """
        for record in transformed_records:

            data = record['data']
            action = record['action']
            src_model = self._odoo_src.session.env[self.src_model_name]

            if 'x_old_id' in data:
                old_id = data.pop('x_old_id')
                src_record = src_model.browse(old_id)
                dst_model = self._odoo_dst.session.env[self.get_dst_model_name()]

                if action == 'create':
                    logging.info(f"Creating attribute value \"{src_record.product_tmpl_id.name, src_record.attribute_id.name, }\" ...")
                    new_id = dst_model.create(data)
                    self.update_tracking_ids(new_id, src_record)

                elif action == 'update':
                    logging.info(f"Updating attribute value \"{src_record.product_tmpl_id.name, src_record.attribute_id.name, }\" ...")
                    dst_record = record['dst_record']
                    dst_record.write(data)
                    self.update_tracking_ids(dst_record.id, dst_record)
