import logging
from typing import Dict, List, Optional, Any
from .base import DomainHandler, DESTINATION, SOURCE
from ..core.mapping import MappingProvider
from ..core.odoo_connection import OdooConnectionProvider
from ..core.database import DBConnectionProvider


class ProductAttributeValueHandler(DomainHandler):

    def __init__(
            self,
            odoo_provider: OdooConnectionProvider,
            db_provider: DBConnectionProvider,
            model_name: str,
            fields: List[str]
    ):
        """
        Initialize the ProductAttributeValueHandler with the provider pattern.
        :param odoo_provider: OdooConnectionProvider instance.
        :param db_provider: DBConnectionProvider instance.
        :param model_name: The model name to migrate.
        """
        super().__init__(odoo_provider, db_provider, model_name)
        self.fields = fields

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
        model = self._odoo_provider.get_odoo_connection(DESTINATION).get_model(self.src_model_name)
        ids = model.search(domain, limit=1)
        return ids is not None and len(ids) > 0

    def find_dst_attribute_by_name(self, src_record):
        # Expect dicts from optimized fetch: attribute_id -> [id, name]
        attr_field = src_record.get('attribute_id')
        attr_name = attr_field[1] if attr_field and len(attr_field) > 1 else None
        if not attr_name:
            logging.warning(
                "Cannot resolve destination product.attribute for attribute.value src_id=%s: missing attribute_id/name in src_record",
                src_record.get('id'),
            )
            return None
        model = self._odoo_provider.get_odoo_connection(DESTINATION).get_model('product.attribute')
        logging.info(
            "Searching destination product.attribute for attribute.value src_id=%s with name=%s",
            src_record.get('id'),
            attr_name,
        )
        attribute_ids = model.search([('name', '=', attr_name)], limit=1)
        if not attribute_ids:
            attribute_ids = model.search([('name', 'ilike', attr_name)], limit=1)
        if attribute_ids:
            logging.info(
                "Resolved destination product.attribute id=%s for attribute.value src_id=%s attribute_name=%s",
                attribute_ids[0],
                src_record.get('id'),
                attr_name,
            )
        else:
            logging.warning(
                "No destination product.attribute found for attribute.value src_id=%s attribute_name=%s",
                src_record.get('id'),
                attr_name,
            )
        return model.browse(attribute_ids[0]) if attribute_ids else None

    def find_dst_attribute_value(self, src_record):
        domain = [('name', '=', src_record.name)]
        model = self._odoo_provider.get_odoo_connection(DESTINATION).get_model('product.attribute.value')
        attribute_id = model.search(domain)
        attribute_value = model.browse(attribute_id)
        if attribute_id is not None and len(attribute_id):
            return model.browse(attribute_id[0])[0]
        return None

    def find_dst_attribute_value_by_name(self, name) -> bool:
        domain = [('name', '=', name)]
        model = self._odoo_provider.get_odoo_connection(DESTINATION).get_model(self.src_model_name)
        ids = model.search(domain, limit=1)
        if ids is not None and len(ids):
            return model.browse(ids[0])[0]
        return None

    def find_dst_value_by_attr_and_name(self, attribute_id: int, name: str):
        model = self._odoo_provider.get_odoo_connection(DESTINATION).get_model('product.attribute.value')
        if not attribute_id or not name:
            logging.warning(
                "Cannot lookup destination product.attribute.value: missing attribute_id=%s or name=%s",
                attribute_id,
                name,
            )
            return None
        domain = [('attribute_id', '=', attribute_id), ('name', '=', name)]
        logging.info(
            "Searching destination product.attribute.value with domain=%s",
            domain,
        )
        ids = model.search(domain, limit=1)
        if ids:
            logging.info(
                "Found destination product.attribute.value id=%s for attribute_id=%s name=%s",
                ids[0],
                attribute_id,
                name,
            )
        return model.browse(ids[0])[0] if ids else None

    def apply_transformations(self, src_record: Any) -> List[Dict]:
        # Expect dicts from optimized fetch
        src_id = src_record.get('id')
        src_name = src_record.get('name')
        src_seq = src_record.get('sequence') or 0

        logging.info(
            "Processing product.attribute.value src_id=%s name=%s",
            src_id,
            src_name,
        )

        dst_attribute = self.find_dst_attribute_by_name(src_record)
        dst_attr_id = dst_attribute.id if dst_attribute else None

        # Try to find existing destination value by (attribute, name) to avoid duplicates
        dst_existing = self.find_dst_value_by_attr_and_name(dst_attr_id, src_name)

        transformed_record = {
            'action': 'update' if dst_existing else 'create',
            'model': 'product.attribute.value',
            'src_record': src_record,
            'dst_record': dst_existing,
            'data': {
                'name': src_name,
                'attribute_id': dst_attr_id,
                'sequence': src_seq,
                'x_old_id': src_id,
            }
        }

        logging.info(
            "Prepared product.attribute.value action=%s src_id=%s dst_id=%s attribute_id=%s name=%s",
            transformed_record['action'],
            src_id,
            dst_existing.id if dst_existing else None,
            dst_attr_id,
            src_name,
        )

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
                    label = data.get('name') or data.get('x_old_id') or 'unknown'
                    logging.info(f"Creating attribute value \"{label}\" ...")
                    x_new_id = dst_model.create(data)
                    logging.info(
                        "Created product.attribute.value dst_id=%s src_id=%s name=%s",
                        x_new_id,
                        data.get('x_old_id'),
                        data.get('name'),
                    )

                elif action == 'update':
                    label = data.get('name') or data.get('x_old_id') or 'unknown'
                    logging.info(f"Updating attribute value \"{label}\" ...")
                    dst_record = transformed_record['dst_record']
                    dst_record.write(data)
                    x_new_id = dst_record.id
                    logging.info(
                        "Updated product.attribute.value dst_id=%s src_id=%s name=%s",
                        x_new_id,
                        data.get('x_old_id'),
                        data.get('name'),
                    )

                # Direct tracking updates without building an object
                src_id = transformed_record['data'].get('x_old_id')
                logging.info(
                    "Updating tracking for product.attribute.value src_id=%s -> dst_id=%s",
                    src_id,
                    x_new_id,
                )
                self._update_tracking_id(
                    connection_type='source',
                    model_name=self.src_model_name,
                    record_id=src_id,
                    field_name='x_new_id',
                    field_value=x_new_id
                )
                self._update_tracking_id(
                    connection_type='destination',
                    model_name=self.get_dst_model_name(),
                    record_id=x_new_id,
                    field_name='x_old_id',
                    field_value=src_id
                )
