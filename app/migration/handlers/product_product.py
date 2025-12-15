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

    def _dst_model_including_archived(self, model_name: str = 'product.product'):
        # Include both active and archived records in searches/updates.
        model = self.get_dst_model(model_name)
        try:
            return model.with_context(active_test=False)
        except Exception:
            return model

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
        model = self._dst_model_including_archived('product.product')
        ids = model.search([('product_tmpl_id', '=', dst_product_tmpl_id)])
        if ids and len(ids) == 1:
            return model.browse(ids[0])
        return None

    def find_dst_product(self, src_record) -> Optional[Any]:
        # Fallback lookup by (mapped template + default_code if present).
        dst_product_tmpl_id = self._resolve_dst_template_id(src_record)

        domain = [('product_tmpl_id', '=', dst_product_tmpl_id)]
        if src_record.default_code:
            domain.append(('default_code', '=', src_record.default_code))

        model = self._dst_model_including_archived('product.product')
        product_ids = model.search(domain, limit=1)
        if product_ids:
            return model.browse(product_ids[0])
        return None

    def apply_transformations(self, src_record: Any) -> List[Dict]:
        # UPSERT logic:
        # 1) Prefer lookup by x_old_id (DB) for deterministic mapping.
        # 2) Fallback to template + default_code (RPC search).
        # 3) If not found, prepare a create payload.
        _logger.info(
            "Processing product.product src_id=%s default_code=%s",
            getattr(src_record, 'id', None),
            getattr(src_record, 'default_code', None),
        )
        conn = self._db_provider.get_connection(DESTINATION)

        existing_product = find_record_by_old_id(conn, 'product_product', src_record.id)

        dst_record = None
        dst_id = None

        if existing_product:
            dst_id = existing_product['id']
            dst_record = self._dst_model_including_archived('product.product').browse(dst_id)
            _logger.info(
                "Found destination product.product by x_old_id mapping src_id=%s -> dst_id=%s",
                getattr(src_record, 'id', None),
                dst_id,
            )
        else:
            dst_record = self.find_dst_product(src_record)
            if dst_record:
                dst_id = dst_record.id
                _logger.info(
                    "Found destination product.product by fallback lookup src_id=%s default_code=%s -> dst_id=%s",
                    getattr(src_record, 'id', None),
                    getattr(src_record, 'default_code', None),
                    dst_id,
                )

        dst_product_tmpl_id = self._resolve_dst_template_id(src_record)


        data = {
            # Required for create
            'product_tmpl_id': dst_product_tmpl_id,

            # Fields to sync
            'default_code': src_record.default_code,
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
            _logger.info(
                "Persisting product.product action=%s src_id=%s default_code=%s",
                action,
                getattr(src_record, 'id', None),
                getattr(src_record, 'default_code', None),
            )

            if action not in ['create', 'update']:
                continue

            try:
                dst_model = self._dst_model_including_archived('product.product')

                vals = dict(data)

                if action == 'create':
                    # Odoo 17 variants are uniquely identified by (product_tmpl_id, combination_indices).
                    # If the destination template has a single (empty-combination) variant, attempting to
                    # create additional variants without specifying a combination will always violate the
                    # unique constraint. In that case, resolve the existing variant and update it.
                    dst_record = self.find_dst_product(src_record)
                    if not dst_record:
                        dst_record = self._find_single_variant_for_template(data['product_tmpl_id'])

                    if dst_record:
                        _logger.info(
                            "Writing existing product.product (update-on-create) dst_id=%s src_id=%s default_code=%s",
                            getattr(dst_record, 'id', None),
                            getattr(src_record, 'id', None),
                            getattr(src_record, 'default_code', None),
                        )
                        # Avoid overwriting an existing x_old_id when multiple source variants
                        # collapse into a single destination variant.
                        try:
                            existing_old_id = getattr(dst_record, 'x_old_id', None)
                        except Exception:
                            existing_old_id = None
                        if existing_old_id and existing_old_id != src_record.id:
                            vals.pop('x_old_id', None)
                        dst_record.write(vals)
                        x_new_id = dst_record.id
                    else:
                        _logger.info(
                            "Creating product.product src_id=%s default_code=%s product_tmpl_id=%s",
                            getattr(src_record, 'id', None),
                            getattr(src_record, 'default_code', None),
                            data.get('product_tmpl_id'),
                        )
                        try:
                            x_new_id = dst_model.create(data)
                        except Exception as create_ex:
                            # If we still hit the unique constraint, treat it as "already exists" and update.
                            if 'product_product_combination_unique' in str(create_ex):
                                dst_record = self._find_single_variant_for_template(data['product_tmpl_id'])
                                if dst_record:
                                    _logger.info(
                                        "Writing existing product.product after duplicate-combination error dst_id=%s src_id=%s default_code=%s",
                                        getattr(dst_record, 'id', None),
                                        getattr(src_record, 'id', None),
                                        getattr(src_record, 'default_code', None),
                                    )
                                    try:
                                        existing_old_id = getattr(dst_record, 'x_old_id', None)
                                    except Exception:
                                        existing_old_id = None
                                    if existing_old_id and existing_old_id != src_record.id:
                                        vals.pop('x_old_id', None)
                                    dst_record.write(vals)
                                    x_new_id = dst_record.id
                                else:
                                    _logger.warning(
                                        "Skipping create for product.product due to duplicate combination src_id=%s default_code=%s product_tmpl_id=%s",
                                        getattr(src_record, 'id', None),
                                        getattr(src_record, 'default_code', None),
                                        data.get('product_tmpl_id'),
                                    )
                                    continue
                            else:
                                raise

                else:
                    dst_record = transformed_record['dst_record']

                    # Defensive re-resolve if missing for some reason.
                    if not dst_record:
                        dst_record = self.find_dst_product(src_record)

                    if not dst_record:
                        _logger.warning(
                            "Skipping update for product.product: destination record not found src_id=%s default_code=%s",
                            getattr(src_record, 'id', None),
                            getattr(src_record, 'default_code', None),
                        )
                        continue

                    _logger.info(
                        "Writing product.product dst_id=%s src_id=%s default_code=%s",
                        getattr(dst_record, 'id', None),
                        getattr(src_record, 'id', None),
                        getattr(src_record, 'default_code', None),
                    )
                    try:
                        existing_old_id = getattr(dst_record, 'x_old_id', None)
                    except Exception:
                        existing_old_id = None
                    if existing_old_id and existing_old_id != src_record.id:
                        vals.pop('x_old_id', None)
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

                try:
                    dst_old_id = getattr(dst_model.browse(x_new_id), 'x_old_id', None)
                except Exception:
                    dst_old_id = None

                if not dst_old_id or dst_old_id == src_record.id:
                    _logger.info(
                        "Saving tracking mapping in DB for product.product: src_id=%s -> dst_id=%s (x_old_id)",
                        getattr(src_record, 'id', None),
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
                        getattr(src_record, 'id', None),
                        x_new_id,
                    )
                else:
                    _logger.warning(
                        "Not setting destination x_old_id for product.product dst_id=%s: already mapped to old_id=%s (skipping src_id=%s default_code=%s)",
                        x_new_id,
                        dst_old_id,
                        getattr(src_record, 'id', None),
                        getattr(src_record, 'default_code', None),
                    )

            except Exception as e:
                _logger.exception(
                    "Error saving product.product src_id=%s default_code=%s: %s",
                    getattr(src_record, 'id', None),
                    getattr(src_record, 'default_code', None),
                    e,
                )
                continue
