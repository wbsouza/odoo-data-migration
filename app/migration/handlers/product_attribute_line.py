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

    def apply_transformations(self, src_record: Any) -> List[Dict]:
        dst_attribute = self.find_dst_attribute(src_record)
        values_ids = self.find_attribute_values(dst_attribute)
        product_tmpl = self.find_dst_product_tmpl(src_record)
        transformed_record = {
            'action': 'create',
            'dst_model': self.get_dst_model_name(),
            'src_record': src_record,
            'dst_record': self.find_dst_attribute_line_by_attribute_and_product_tmpl(dst_attribute, product_tmpl),
            'data': {
                'attribute_id': dst_attribute.id,
                'product_tmpl_id': product_tmpl.id,
                # 'groups_id': [(6, 0, dst_group_ids)],
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

                    # dst_product_attribute_value = dst_model.browse(dst_record.id)
                    # src_product_attribute_value = src_model.browse(src_record.id)
                    # product_ids = self.find_dst_product_by_product_tmpl(dst_product_attribute_value.product_tmpl_id.id)
                    # src_product_ids = self.find_src_product_by_product_tmpl(src_product_attribute_value.product_tmpl_id.id)
                    # products = []
                    # src_products = []
                    # for product in product_ids:
                    #     products.append(odoo_provider.get_odoo_connection(DESTINATION).session.env['product.product'].browse(product))
                    # for product in src_product_ids:
                    #     src_product = self._odoo_provider.get_odoo_connection(SOURCE).session.env['product.product'].browse(product)
                    #     if src_product:
                    #         src_products.append(src_product)
                    #
                    # for i in range(len(products)):
                    #     products[i].default_code = src_products[i].default_code