import logging
from typing import Dict, List, Any, Optional

from .base import DomainHandler
from ..core.odoo_connection import OdooConnectionProvider, SOURCE, DESTINATION
from ..core.database import DBConnectionProvider, find_id_by_old_id, find_record_by_old_id


_logger = logging.getLogger(__name__)


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
        self._dst_variant_key_cache: Dict[int, Dict[str, int]] = {}
        self._src_pav_to_dst_pav_cache: Dict[int, Optional[int]] = {}
        self._src_attribute_value_ids_cache: Dict[int, List[int]] = {}
        self._dst_product_product_fields_cache: Optional[Dict[str, Any]] = None

    def _dst_product_product_fields(self) -> Dict[str, Any]:
        if self._dst_product_product_fields_cache is not None:
            return self._dst_product_product_fields_cache
        try:
            self._dst_product_product_fields_cache = self.get_dst_model('product.product').fields_get() or {}
        except Exception:
            self._dst_product_product_fields_cache = {}
        return self._dst_product_product_fields_cache

    def _dst_product_has_field(self, field_name: str) -> bool:
        return field_name in (self._dst_product_product_fields() or {})

    def _src_variant_base_price(self, src_record: Any) -> Optional[float]:
        """Return a base price for the variant from source.

        We prefer variant-level values if present (common in customizations), otherwise fall back to
        the template list_price.
        """
        try:
            val = getattr(src_record, 'lst_price')
            if val is not None:
                return float(val)
        except Exception:
            pass
        try:
            val = getattr(src_record, 'list_price')
            if val is not None:
                return float(val)
        except Exception:
            pass
        try:
            tmpl = getattr(src_record, 'product_tmpl_id', None)
            val = getattr(tmpl, 'list_price', None) if tmpl else None
            if val is not None:
                return float(val)
        except Exception:
            pass
        return None


    def _resolve_dst_template_id(self, src_record) -> int:
        # Resolve destination product.template id using x_old_id mapping.
        conn = self._db_provider.get_connection(DESTINATION)
        dst_product_tmpl_id = find_id_by_old_id(conn, 'product_template', src_record.product_tmpl_id.id)
        if not dst_product_tmpl_id:
            raise ValueError(
                f"Product template '{src_record.product_tmpl_id.name}' "
                f"(old_id={src_record.product_tmpl_id.id}) not found in destination"
            )
        return dst_product_tmpl_id

    def _find_single_variant_for_template(self, dst_product_tmpl_id: int) -> Optional[Any]:
        """Find the single auto-created variant for a template (no attributes)."""
        model = self.get_dst_model('product.product')
        ids = model.search([('product_tmpl_id', '=', dst_product_tmpl_id)])
        if ids and len(ids) == 1:
            return model.browse(ids[0])
        return None

    def _find_any_variant_for_template(self, dst_product_tmpl_id: int) -> Optional[Any]:
        """Find any variant for a template. Used when we need to update an existing variant."""
        model = self.get_dst_model('product.product')
        ids = model.search([('product_tmpl_id', '=', dst_product_tmpl_id)], limit=1)
        if ids:
            return model.browse(ids[0])
        return None

    def _src_variant_key(self, src_record: Any) -> str:
        """Build a stable attribute-combination key for an Odoo 11 product.product.

        IMPORTANT: use destination product.attribute.value IDs (mapped via x_old_id) instead of names,
        to avoid mismatches due to translations/renames.
        """
        src_env = self._odoo_src.session.env
        pav_ids = self._src_attribute_value_ids(src_env, src_record.id)
        if not pav_ids:
            return ''

        conn = self._db_provider.get_connection(DESTINATION)
        dst_pav_ids = []
        for src_pav_id in pav_ids:
            cached = self._src_pav_to_dst_pav_cache.get(src_pav_id)
            if cached is None:
                cached = find_id_by_old_id(conn, 'product_attribute_value', src_pav_id)
                self._src_pav_to_dst_pav_cache[src_pav_id] = cached
            if not cached:
                # If attribute values weren't migrated/mapped, we cannot safely match variants.
                return ''
            dst_pav_ids.append(int(cached))

        dst_pav_ids.sort()
        return "|".join(str(x) for x in dst_pav_ids)

    def _src_attribute_value_ids(self, src_env: Any, src_product_id: int) -> List[int]:
        cached = self._src_attribute_value_ids_cache.get(src_product_id)
        if cached is not None:
            return cached
        model = self.get_src_model('product.product')
        rows = model.read([src_product_id], ['attribute_value_ids'])
        if not rows:
            self._src_attribute_value_ids_cache[src_product_id] = []
            return []
        pav_ids = rows[0].get('attribute_value_ids') or []
        pav_ids = [int(x) for x in pav_ids]
        self._src_attribute_value_ids_cache[src_product_id] = pav_ids
        return pav_ids

    def _canonical_src_default_code(self, src_record: Any) -> Optional[str]:
        """Odoo default_code standard:

        - For non-variant products (no attribute values), take default_code from product.template.
        - For variant products, take default_code from product.product.
        """
        src_env = self._odoo_src.session.env
        is_non_variant = not bool(self._src_attribute_value_ids(src_env, src_record.id))
        if is_non_variant:
            tmpl = getattr(src_record, 'product_tmpl_id', None)
            tmpl_code = getattr(tmpl, 'default_code', None) if tmpl else None
            return tmpl_code or src_record.default_code
        return src_record.default_code

    def _load_dst_variant_key_map(self, dst_product_tmpl_id: int) -> Dict[str, int]:
        """Cache destination variants for a template by combination key.

        Key is based on destination product.attribute.value IDs referenced by PTAV.
        """
        cached = self._dst_variant_key_cache.get(dst_product_tmpl_id)
        if cached is not None:
            return cached

        dst_env = self._odoo_dst.session.env
        pp_model = self.get_dst_model('product.product')
        variant_ids = pp_model.search([('product_tmpl_id', '=', dst_product_tmpl_id)])
        if not variant_ids:
            self._dst_variant_key_cache[dst_product_tmpl_id] = {}
            return {}

        variant_rows = pp_model.read(variant_ids, ['product_template_attribute_value_ids'])
        all_ptav_ids = set()
        for row in variant_rows:
            for ptav_id in row.get('product_template_attribute_value_ids') or []:
                all_ptav_ids.add(ptav_id)

        ptav_cache: Dict[int, str] = {}
        if all_ptav_ids:
            ptav_model =  self.get_dst_model('product.template.attribute.value')
            ptav_rows = ptav_model.read(list(all_ptav_ids), ['attribute_id', 'product_attribute_value_id'])
            for ptav in ptav_rows:
                pav = ptav.get('product_attribute_value_id')
                pav_id = pav[0] if pav and len(pav) > 0 else None
                if pav_id:
                    ptav_cache[ptav['id']] = str(pav_id)

        key_map: Dict[str, int] = {}
        for row in variant_rows:
            parts = []
            for ptav_id in row.get('product_template_attribute_value_ids') or []:
                token = ptav_cache.get(ptav_id)
                if token:
                    parts.append(token)
            parts.sort()
            key = "|".join(parts)
            key_map[key] = row['id']

        self._dst_variant_key_cache[dst_product_tmpl_id] = key_map
        return key_map

    def _find_dst_variant_by_key(self, dst_product_tmpl_id: int, key: str) -> Optional[Any]:
        key_map = self._load_dst_variant_key_map(dst_product_tmpl_id)
        dst_id = key_map.get(key)
        if not dst_id:
            return None
        return self.get_dst_model('product.product').browse(dst_id)

    def _abort(self, message: str, *args: Any):
        _logger.error(message, *args)
        raise SystemExit(1)

    def _enforce_default_code_policy(self, dst_record: Any, src_record: Any, vals: Dict[str, Any]):
        src_default_code = vals.get('default_code')
        if src_default_code:
            if dst_record.default_code and dst_record.default_code != src_default_code:
                self._abort(
                    "=" * 80 + "\n"
                    "MIGRATION ABORTED - DEFAULT_CODE MISMATCH (DATA LOSS RISK)!\n"
                    "src_id=%s src_default_code=%s template=%s\n"
                    "dst_id=%s dst_default_code=%s\n"
                    "Reason: destination variant already has a different default_code; multiple source products are collapsing into one destination variant.\n"
                    "Action required: adjust migration strategy (e.g., create attributes/variants) or clean destination data before retry.\n"
                    + "=" * 80,
                    src_record.id,
                    src_default_code,
                    src_record.product_tmpl_id.name,
                    dst_record.id,
                    dst_record.default_code,
                )
        else:
            vals.pop('default_code', None)

    def find_dst_product(self, src_record) -> Optional[Any]:
        """
        Find destination product by template mapping.
        
        Strategy:
        1. First try matching by attribute combination (PTAV) when possible.
        2. Then try exact match by (template + default_code) if default_code exists.
        3. If not found AND template has only one variant, return that variant
           (Odoo 17 auto-creates one variant with no attributes).
        4. If multiple variants exist and we cannot match uniquely, return None.
        
        Raises ValueError if template not found - migration will abort.
        """
        dst_product_tmpl_id = self._resolve_dst_template_id(src_record)
        model = self.get_dst_model('product.product')

        canonical_default_code = self._canonical_src_default_code(src_record)

        # Strategy 1: Match by attribute combination (avoids collapsing variants)
        src_key = self._src_variant_key(src_record)
        if src_key:
            dst_by_key = self._find_dst_variant_by_key(dst_product_tmpl_id, src_key)
            if dst_by_key:
                return dst_by_key

        # Strategy 1: Try exact match with default_code if present
        if canonical_default_code:
            domain = [('product_tmpl_id', '=', dst_product_tmpl_id), ('default_code', '=', canonical_default_code)]
            product_ids = model.search(domain, limit=1)
            if product_ids:
                return model.browse(product_ids[0])

        # Strategy 2: Find the single auto-created variant (common case)
        # This handles templates without attributes where Odoo 17 auto-creates one variant
        single_variant = self._find_single_variant_for_template(dst_product_tmpl_id)
        if single_variant:
            return single_variant

        # Multiple variants exist but we couldn't match by combination or default_code.
        return None

    def apply_transformations(self, src_record: Any) -> List[Dict]:
        # UPSERT logic:
        # 1) Prefer lookup by x_old_id (DB) for deterministic mapping.
        # 2) Fallback to template + default_code (RPC search).
        # 3) If not found, prepare a create payload.
        canonical_default_code = self._canonical_src_default_code(src_record)
        _logger.info(
            "Processing product.product src_id=%s default_code=%s canonical_default_code=%s",
            src_record.id,
            src_record.default_code,
            canonical_default_code,
        )
        conn = self._db_provider.get_connection(DESTINATION)

        existing_product = find_record_by_old_id(conn, 'product_product', src_record.id)

        dst_record = None
        dst_id = None

        # Resolve destination template first - ABORT if template not found
        try:
            dst_product_tmpl_id = self._resolve_dst_template_id(src_record)
        except ValueError as e:
            self._abort(
                "=" * 80 + "\n"
                "MIGRATION ABORTED - PRODUCT NOT MIGRATED!\n"
                "src_id=%s default_code=%s template=%s\n"
                "Reason: %s\n"
                "Action required: Ensure product.template is migrated before product.product\n"
                + "=" * 80,
                src_record.id,
                src_record.default_code,
                src_record.product_tmpl_id.name,
                e,
            )

        if existing_product:
            dst_id = existing_product['id']
            dst_record = self.get_dst_model('product.product').browse(dst_id)
            _logger.info(
                "Found destination product.product by x_old_id mapping src_id=%s -> dst_id=%s",
                src_record.id,
                dst_id,
            )
        else:
            dst_record = self.find_dst_product(src_record)
            if dst_record:
                dst_id = dst_record.id
                _logger.info(
                    "Found destination product.product by fallback lookup src_id=%s default_code=%s -> dst_id=%s",
                    src_record.id,
                    src_record.default_code,
                    dst_id,
                )


        data: Dict[str, Any] = {
            # Required for create
            'product_tmpl_id': dst_product_tmpl_id,

            # Fields to sync
            'default_code': canonical_default_code,
            'product_description': src_record.product_description,
            'description_sale': src_record.description_sale,

            # Tracking
            'x_old_id': src_record.id,
        }

        transformed_record = {
            'action': 'update' if dst_id else 'create',
            'model': 'product.product',
            'src_record': src_record,
            'dst_record': dst_record if dst_id else None,
            'data': data,
        }

        # Safety: if we somehow have a dst_record, always force update.
        if transformed_record['dst_record'] is not None:
            transformed_record['action'] = 'update'

        return [transformed_record]

    def save_into_destination(self, transformed_records: List[Dict]):
        """
        Save the transformed records in the destination system.
        This handles creating/updating product.product in destination Odoo 17.
        """
        for transformed_record in transformed_records:
            model_name = transformed_record['model']
            data = transformed_record['data']
            action = transformed_record['action']
            src_record = transformed_record['src_record']
            canonical_default_code = data.get('default_code')
            _logger.info(
                "Persisting product.product action=%s src_id=%s default_code=%s canonical_default_code=%s",
                action,
                src_record.id,
                src_record.default_code,
                canonical_default_code,
            )

            if action not in ['create', 'update']:
                continue

            try:
                dst_model = self.get_dst_model('product.product')

                vals = dict(data)

                if action == 'create':
                    # Odoo 17 variants are uniquely identified by (product_tmpl_id, combination_indices).
                    # If the destination template has a variant, attempting to create additional variants
                    # without specifying a combination will violate the unique constraint.
                    # In that case, resolve the existing variant and update it.
                    dst_record = self.find_dst_product(src_record)

                    if dst_record:
                        # Check if this is a collapse scenario (multiple source products -> one dest variant)
                        existing_old_id = dst_record.x_old_id
                        
                        if existing_old_id and existing_old_id != src_record.id:
                            _logger.warning(
                                "Multiple source products collapsing to same destination variant: "
                                "dst_id=%s already has x_old_id=%s, now processing src_id=%s default_code=%s",
                                dst_record.id,
                                existing_old_id,
                                src_record.id,
                                src_record.default_code,
                            )
                            vals.pop('x_old_id', None)
                        
                        _logger.info(
                            "Writing existing product.product (update-on-create) dst_id=%s src_id=%s default_code=%s canonical_default_code=%s",
                            dst_record.id,
                            src_record.id,
                            src_record.default_code,
                            canonical_default_code,
                        )
                        self._enforce_default_code_policy(dst_record, src_record, vals)
                        dst_record.write(vals)
                        x_new_id = dst_record.id
                    else:
                        # If the destination template has multiple variants, creating a new variant without an
                        # explicit combination (PTAV ids) will collapse or violate the uniqueness constraint.
                        # We require the variant structure (attribute lines/PTAV) to exist and match.
                        dst_product_tmpl_id = data['product_tmpl_id']
                        model_ids = dst_model.search([('product_tmpl_id', '=', dst_product_tmpl_id)], limit=2)
                        if model_ids and len(model_ids) > 1:
                            src_env = self._odoo_src.session.env
                            pav_ids = self._src_attribute_value_ids(src_env, src_record.id)
                            if not pav_ids:
                                _logger.warning(
                                    "Skipping source product.product src_id=%s template=%s: source has no attribute values/default_code "
                                    "but destination template has multiple variants (likely placeholder/min-price product).",
                                    src_record.id,
                                    src_record.product_tmpl_id.name,
                                )
                                continue
                            self._abort(
                                "=" * 80 + "\n"
                                "MIGRATION ABORTED - PRODUCT NOT MIGRATED!\n"
                                "src_id=%s default_code=%s template=%s\n"
                                "Reason: destination template has multiple variants but no matching variant was found by attribute combination (PTAV).\n"
                                "Action required: ensure product.attribute/value/line migration ran and variants were generated (product_template_attribute_value).\n"
                                + "=" * 80,
                                src_record.id,
                                src_record.default_code,
                                src_record.product_tmpl_id.name,
                            )
                        _logger.info(
                            "Creating product.product src_id=%s default_code=%s canonical_default_code=%s product_tmpl_id=%s",
                            src_record.id,
                            src_record.default_code,
                            canonical_default_code,
                            data['product_tmpl_id'],
                        )
                        try:
                            x_new_id = dst_model.create(data)
                        except Exception as create_ex:
                            # If we still hit the unique constraint, treat it as "already exists" and update.
                            if 'product_product_combination_unique' in str(create_ex):
                                # Use _find_any_variant_for_template as ultimate fallback
                                dst_record = self._find_any_variant_for_template(data['product_tmpl_id'])
                                if dst_record:
                                    _logger.info(
                                        "Writing existing product.product after duplicate-combination error dst_id=%s src_id=%s default_code=%s canonical_default_code=%s",
                                        dst_record.id,
                                        src_record.id,
                                        src_record.default_code,
                                        canonical_default_code,
                                    )
                                    existing_old_id = dst_record.x_old_id
                                    if existing_old_id and existing_old_id != src_record.id:
                                        vals.pop('x_old_id', None)
                                    self._enforce_default_code_policy(dst_record, src_record, vals)
                                    dst_record.write(vals)
                                    x_new_id = dst_record.id
                                else:
                                    self._abort(
                                        "=" * 80 + "\n"
                                        "MIGRATION ABORTED - PRODUCT NOT MIGRATED!\n"
                                        "src_id=%s default_code=%s template=%s\n"
                                        "Reason: product_product_combination_unique and no existing destination variant found for template_id=%s\n"
                                        + "=" * 80,
                                        src_record.id,
                                        src_record.default_code,
                                        src_record.product_tmpl_id.name,
                                        data['product_tmpl_id'],
                                    )
                            else:
                                raise

                else:
                    dst_record = transformed_record['dst_record']

                    # Defensive re-resolve if missing for some reason.
                    if not dst_record:
                        dst_record = self.find_dst_product(src_record)

                    if not dst_record:
                        dst_product_tmpl_id = data.get('product_tmpl_id')
                        if dst_product_tmpl_id:
                            model_ids = dst_model.search([('product_tmpl_id', '=', dst_product_tmpl_id)], limit=2)
                            if model_ids and len(model_ids) > 1:
                                src_env = self._odoo_src.session.env
                                pav_ids = self._src_attribute_value_ids(src_env, src_record.id)
                                if not pav_ids:
                                    _logger.warning(
                                        "Skipping source product.product src_id=%s template=%s: source has no attribute values/default_code "
                                        "but destination template has multiple variants (likely placeholder/min-price product).",
                                        src_record.id,
                                        src_record.product_tmpl_id.name,
                                    )
                                    continue
                        self._abort(
                            "=" * 80 + "\n"
                            "MIGRATION ABORTED - PRODUCT NOT MIGRATED!\n"
                            "src_id=%s default_code=%s template=%s\n"
                            "Reason: destination record not found for update\n"
                            + "=" * 80,
                            src_record.id,
                            src_record.default_code,
                            src_record.product_tmpl_id.name,
                        )

                    _logger.info(
                        "Writing product.product dst_id=%s src_id=%s default_code=%s canonical_default_code=%s",
                        dst_record.id,
                        src_record.id,
                        src_record.default_code,
                        canonical_default_code,
                    )
                    existing_old_id = dst_record.x_old_id
                    if existing_old_id and existing_old_id != src_record.id:
                        vals.pop('x_old_id', None)
                    self._enforce_default_code_policy(dst_record, src_record, vals)
                    dst_record.write(vals)
                    x_new_id = dst_record.id

                # Update tracking ids. For product variants, multiple source variants can
                # collapse into the same destination variant; in that case, don't overwrite
                # the destination x_old_id (it would become non-deterministic).
                self._update_tracking_id(
                    connection_type=SOURCE,
                    model_name=self.src_model_name,
                    field_name='x_new_id',
                    field_value=x_new_id,
                    record_id=src_record.id,
                )

                dst_old_id = dst_model.browse(x_new_id).x_old_id

                if not dst_old_id or dst_old_id == src_record.id:
                    _logger.info(
                        "Saving tracking mapping in DB for product.product: src_id=%s -> dst_id=%s (x_old_id)",
                        src_record.id,
                        x_new_id,
                    )
                    self._update_tracking_id(
                        connection_type=DESTINATION,
                        model_name=self.get_dst_model_name(),
                        field_name='x_old_id',
                        field_value=src_record.id,
                        record_id=x_new_id,
                    )
                    _logger.info(
                        "Saved tracking mapping in DB for product.product: src_id=%s -> dst_id=%s (x_old_id)",
                        src_record.id,
                        x_new_id,
                    )
                else:
                    _logger.warning(
                        "Not setting destination x_old_id for product.product dst_id=%s: already mapped to old_id=%s (skipping src_id=%s default_code=%s)",
                        x_new_id,
                        dst_old_id,
                        src_record.id,
                        src_record.default_code,
                    )

            except SystemExit:
                raise
            except Exception as e:
                _logger.exception(
                    "=" * 80 + "\n"
                    "MIGRATION ABORTED - PRODUCT NOT MIGRATED!\n"
                    "src_id=%s default_code=%s template=%s\n"
                    "Reason: %s\n"
                    + "=" * 80,
                    src_record.id,
                    src_record.default_code,
                    src_record.product_tmpl_id.name,
                    e,
                )
                raise SystemExit(1)
