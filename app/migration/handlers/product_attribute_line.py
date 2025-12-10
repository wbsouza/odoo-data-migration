import logging
from typing import Dict, Generic, List, Optional, Type, TypeVar, Union, Any
from .base import DomainHandler, ResourceNotFoundException
from ..core.mapping import MappingProvider
from ..core.mapping import MappingProvider
from ..core.odoo_connection import OdooConnectionProvider, SOURCE, DESTINATION
from ..core.database import DBConnectionProvider

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
        # Support dict records from optimized fetch: product_tmpl_id -> [id, name]
        pt_field = record.get('product_tmpl_id') if isinstance(record, dict) else None
        pt_name = pt_field[1] if pt_field and len(pt_field) > 1 else (record.product_tmpl_id.name if hasattr(record, 'product_tmpl_id') else None)
        model = self._odoo_dst.session.env['product.template']
        ids = model.search([('name', '=', pt_name)], limit=1)
        return model.browse(ids[0]) if ids else None

    def find_dst_attribute(self, record):
        # Support dict records from optimized fetch: attribute_id -> [id, name]
        attr_field = record.get('attribute_id') if isinstance(record, dict) else None
        attr_name = attr_field[1] if attr_field and len(attr_field) > 1 else (record.attribute_id.name if hasattr(record, 'attribute_id') else None)
        model = self._odoo_dst.session.env['product.attribute']
        ids = model.search([('name', '=', attr_name)], limit=1)
        if not ids and attr_name:
            ids = model.search([('name', 'ilike', attr_name)], limit=1)
        return model.browse(ids[0]) if ids else None

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
        # Extract source ids from dict
        src_pt_field = src_record.get('product_tmpl_id')
        src_attr_field = src_record.get('attribute_id')
        src_pt_id = src_pt_field[0] if src_pt_field else None
        src_attr_id = src_attr_field[0] if src_attr_field else None

        # Find all existing product.product variants in Odoo 11 for this template (IDs only)
        pp_model = self._odoo_src.session.env['product.product']
        src_product_ids = pp_model.search([('product_tmpl_id', '=', src_pt_id)])
        if not src_product_ids:
            return []

        # Read only attribute_value_ids from variants
        variants = pp_model.read(src_product_ids, ['attribute_value_ids'])
        value_id_set = set()
        for row in variants:
            val_ids = row.get('attribute_value_ids') or []
            for vid in val_ids:
                value_id_set.add(vid)

        if not value_id_set:
            return []

        # Read attribute values to filter by the specific attribute
        pav_model = self._odoo_src.session.env['product.attribute.value']
        pav_rows = pav_model.read(list(value_id_set), ['attribute_id', 'name'])
        used_value_names = set()
        for pav in pav_rows:
            attr = pav.get('attribute_id')
            attr_id = attr[0] if attr and len(attr) > 0 else None
            if attr_id == src_attr_id:
                name = pav.get('name')
                if name:
                    used_value_names.add(name)

        # Find corresponding values in destination Odoo 17
        dst_attribute = self.find_dst_attribute(src_record)
        dst_value_ids = []

        for value_name in used_value_names:
            domain = [('attribute_id', '=', dst_attribute.id), ('name', '=', value_name)]
            dst_value_ids_found = self._odoo_dst.session.env['product.attribute.value'].search(domain, limit=1)
            if dst_value_ids_found:
                dst_value_ids.append(dst_value_ids_found[0])

        pt_name = src_pt_field[1] if src_pt_field and len(src_pt_field) > 1 else 'unknown'
        attr_name = src_attr_field[1] if src_attr_field and len(src_attr_field) > 1 else 'unknown'
        logging.info(f"Template {pt_name}, Attribute {attr_name}: Found {len(dst_value_ids)} specific values: {list(used_value_names)}")

        return dst_value_ids

    def sync_variant_default_codes(self, src_record, dst_template_id):
        """
        After creating attribute lines, sync default_code from Odoo 11 variants 
        to the corresponding Odoo 17 variants that were auto-generated.
        """
        # Get all source variants for this template
        src_variant_ids = self._odoo_src.session.env['product.product'].search([
            ('product_tmpl_id', '=', src_record.product_tmpl_id.id)
        ])
        src_variants = self._odoo_src.session.env['product.product'].browse(src_variant_ids)
        
        # Get all destination variants for this template
        dst_variant_ids = self._odoo_dst.session.env['product.product'].search([
            ('product_tmpl_id', '=', dst_template_id)
        ])
        dst_variants = self._odoo_dst.session.env['product.product'].browse(dst_variant_ids)
        
        logging.info(f"Syncing default_code for {len(src_variants)} source variants to {len(dst_variants)} destination variants")
        
        # Create mapping based on attribute value combinations
        for src_variant in src_variants:
            if not src_variant.default_code:
                continue
                
            # Build attribute combination key for source variant
            src_attr_combo = self._build_attribute_combination_key(src_variant)
            
            # Find matching destination variant
            matching_dst_variant = None
            for dst_variant in dst_variants:
                dst_attr_combo = self._build_attribute_combination_key_v17(dst_variant)
                if src_attr_combo == dst_attr_combo:
                    matching_dst_variant = dst_variant
                    break
            
            # Update default_code if match found
            if matching_dst_variant:
                if not matching_dst_variant.default_code:  # Only update if empty
                    matching_dst_variant.write({'default_code': src_variant.default_code})
                    logging.info(f"Updated variant {matching_dst_variant.id} default_code: {src_variant.default_code}")
                else:
                    logging.info(f"Skipped variant {matching_dst_variant.id} - already has default_code: {matching_dst_variant.default_code}")
            else:
                logging.warning(f"No matching destination variant found for source variant {src_variant.id} with combo: {src_attr_combo}")

    def _build_attribute_combination_key(self, variant):
        """Build a key representing the attribute combination for Odoo 11 variant"""
        attr_values = []
        for attr_value in variant.attribute_value_ids:
            attr_values.append(f"{attr_value.attribute_id.name}:{attr_value.name}")
        return "|".join(sorted(attr_values))
    
    def _build_attribute_combination_key_v17(self, variant):
        """Build a key representing the attribute combination for Odoo 17 variant"""
        attr_values = []
        # In Odoo 17, variants use product_template_attribute_value_ids
        for ptav in variant.product_template_attribute_value_ids:
            attr_name = ptav.attribute_id.name
            value_name = ptav.product_attribute_value_id.name
            attr_values.append(f"{attr_name}:{value_name}")
        return "|".join(sorted(attr_values))

    def apply_transformations(self, src_record: Any) -> List[Dict]:
        dst_attribute = self.find_dst_attribute(src_record)
        # Get only the specific attribute values used in existing Odoo 11 variants
        values_ids = self.get_specific_attribute_values_for_template(src_record)
        product_tmpl = self.find_dst_product_tmpl(src_record)
        
        # Skip if no specific values found (prevents empty attribute lines)
        if not values_ids:
            pt_field = src_record.get('product_tmpl_id')
            at_field = src_record.get('attribute_id')
            pt_name = pt_field[1] if pt_field and len(pt_field) > 1 else 'unknown'
            at_name = at_field[1] if at_field and len(at_field) > 1 else 'unknown'
            logging.warning(f"No specific attribute values found for template {pt_name}, attribute {at_name}. Skipping.")
            return []
        transformed_record = {
            'action': 'create',
            'dst_model': self.get_dst_model_name(),
            'src_record': src_record,
            'dst_record': self.find_dst_attribute_line_by_attribute_and_product_tmpl(dst_attribute, product_tmpl),
            'data': {
                'attribute_id': dst_attribute.id,
                'product_tmpl_id': product_tmpl.id,
                'x_old_id': src_record.get('id'),
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
                x_old_id = data.pop('x_old_id')
                src_record = src_model.browse(x_old_id)
                dst_model = self._odoo_dst.session.env[self.get_dst_model_name()]

                if action == 'create':
                    logging.info(f"Creating attribute line \"{src_record.product_tmpl_id.name, src_record.attribute_id.name}\" ...")
                    x_new_id = dst_model.create(data)
                    self.update_tracking_ids(x_new_id, src_record)
                    
                    # After creating attribute line, sync variant default codes
                    dst_template_id = data['product_tmpl_id']
                    self.sync_variant_default_codes(src_record, dst_template_id)

                elif action == 'update':
                    logging.info(f"Updating attribute line \"{src_record.product_tmpl_id.name, src_record.attribute_id.name}\" ...")
                    dst_record = record['dst_record']
                    dst_record.write(data)
                    self.update_tracking_ids(dst_record.id, src_record)
                    
                    # After updating attribute line, sync variant default codes
                    dst_template_id = data['product_tmpl_id']
                    self.sync_variant_default_codes(src_record, dst_template_id)
