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
        This implementation avoids recordset browse() and uses read() with minimal fields
        to prevent RPC timeouts when accessing relational fields like attribute_value_ids.
        """
        src_env = self._odoo_src.session.env
        dst_env = self._odoo_dst.session.env

        # Read product_tmpl_id from source attribute line without dereferencing relations
        line_rows = src_env['product.attribute.line'].read([src_record.id], ['product_tmpl_id'])
        if not line_rows:
            return
        src_pt_id = line_rows[0]['product_tmpl_id'][0]

        # Source variants: ids only, then minimal fields
        src_pp = src_env['product.product']
        src_variant_ids = src_pp.search([('product_tmpl_id', '=', src_pt_id)])
        if not src_variant_ids:
            return
        src_rows = src_pp.read(src_variant_ids, ['attribute_value_ids', 'default_code'])

        # Build cache for source product.attribute.value names
        all_pav_ids = set()
        for row in src_rows:
            for vid in row.get('attribute_value_ids') or []:
                all_pav_ids.add(vid)
        pav_cache = {}
        if all_pav_ids:
            pav_rows = src_env['product.attribute.value'].read(list(all_pav_ids), ['attribute_id', 'name'])
            for r in pav_rows:
                attr = r.get('attribute_id')
                attr_name = attr[1] if attr and len(attr) > 1 else ''
                pav_cache[r['id']] = (attr_name, r.get('name') or '')

        # Destination variants: ids only, then minimal fields
        dst_pp = dst_env['product.product']
        dst_variant_ids = dst_pp.search([('product_tmpl_id', '=', dst_template_id)])
        if not dst_variant_ids:
            return
        dst_rows = dst_pp.read(dst_variant_ids, ['product_template_attribute_value_ids', 'default_code'])

        # Build cache for destination product.template.attribute.value names
        all_ptav_ids = set()
        for row in dst_rows:
            for vid in row.get('product_template_attribute_value_ids') or []:
                all_ptav_ids.add(vid)
        ptav_cache = {}
        if all_ptav_ids:
            ptav_rows = dst_env['product.template.attribute.value'].read(list(all_ptav_ids), ['attribute_id', 'product_attribute_value_id'])
            for r in ptav_rows:
                attr = r.get('attribute_id')
                pav = r.get('product_attribute_value_id')
                attr_name = attr[1] if attr and len(attr) > 1 else ''
                val_name = pav[1] if pav and len(pav) > 1 else ''
                ptav_cache[r['id']] = (attr_name, val_name)

        # Helpers to build combination keys from id lists using caches
        def key_from_pav_ids(pav_ids):
            parts = []
            for pid in pav_ids or []:
                names = pav_cache.get(pid)
                if names:
                    parts.append(f"{names[0]}:{names[1]}")
            parts.sort()
            return "|".join(parts)

        def key_from_ptav_ids(ptav_ids):
            parts = []
            for pid in ptav_ids or []:
                names = ptav_cache.get(pid)
                if names:
                    parts.append(f"{names[0]}:{names[1]}")
            parts.sort()
            return "|".join(parts)

        # Build maps
        src_map = {}
        for row in src_rows:
            code = row.get('default_code')
            if not code:
                continue
            key = key_from_pav_ids(row.get('attribute_value_ids'))
            if key:
                src_map[key] = code

        dst_map = {}
        for row in dst_rows:
            key = key_from_ptav_ids(row.get('product_template_attribute_value_ids'))
            if key:
                dst_map[key] = {'id': row['id'], 'default_code': row.get('default_code')}

        # Apply updates where destination default_code is empty
        updates = []
        for key, code in src_map.items():
            info = dst_map.get(key)
            if info and not info.get('default_code'):
                updates.append((info['id'], code))

        for vid, code in updates:
            dst_pp.write([vid], {'default_code': code})
            logging.info(f"Updated variant {vid} default_code: {code}")

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
