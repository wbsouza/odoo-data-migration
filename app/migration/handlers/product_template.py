import logging

from typing import Dict, List, Optional, Any

from .base import DomainHandler
from ..core.mapping import MappingProvider
from ..core.odoo_connection import OdooConnectionProvider, DESTINATION, SOURCE
from ..core.database import DBConnectionProvider, find_id_by_old_id, find_id_by_name


_logger = logging.getLogger(__name__)


class ProductTemplateHandler(DomainHandler):

    def __init__(
            self,
            odoo_provider: OdooConnectionProvider,
            db_provider: DBConnectionProvider,
            model_name: str
    ):
        super().__init__(odoo_provider, db_provider, model_name)
        self._odoo_src = odoo_provider.get_odoo_connection(SOURCE)
        self._odoo_dst = odoo_provider.get_odoo_connection(DESTINATION)
        self._dst_attachment_fields_cache: Optional[Dict[str, Any]] = None
        self._dst_template_fields_cache: Optional[Dict[str, Any]] = None

    def _dst_model_fields(self, model_name: str) -> Dict[str, Any]:
        if model_name == 'ir.attachment':
            if self._dst_attachment_fields_cache is None:
                self._dst_attachment_fields_cache = self.get_dst_model('ir.attachment').fields_get()
            return self._dst_attachment_fields_cache
        if model_name == 'product.template':
            if self._dst_template_fields_cache is None:
                self._dst_template_fields_cache = self.get_dst_model('product.template').fields_get()
            return self._dst_template_fields_cache
        return self.get_dst_model(model_name).fields_get()

    def _dst_has_field(self, model_name: str, field_name: str) -> bool:
        try:
            return field_name in (self._dst_model_fields(model_name) or {})
        except Exception:
            return False

    def _dst_has_model(self, model_name: str) -> bool:
        try:
            self.get_dst_model(model_name)
            return True
        except Exception:
            return False

    def _map_src_template_res_field(self, src_res_field: Optional[str]) -> Optional[str]:
        if not src_res_field:
            return None
        if src_res_field == 'image':
            if self._dst_has_field('product.template', 'image_1920'):
                return 'image_1920'
            return 'image'
        if src_res_field == 'image_medium':
            if self._dst_has_field('product.template', 'image_1024'):
                return 'image_1024'
            return 'image_medium'
        if src_res_field == 'image_small':
            if self._dst_has_field('product.template', 'image_512'):
                return 'image_512'
            return 'image_small'
        return src_res_field

    def _attachment_exists_in_dst(self, dst_template_id: int, name: Optional[str], res_field: Optional[str]) -> bool:
        try:
            dst_attach = self.get_dst_model('ir.attachment')
            domain = [('res_model', '=', 'product.template'), ('res_id', '=', dst_template_id)]
            if name:
                domain.append(('name', '=', name))
            if res_field:
                domain.append(('res_field', '=', res_field))
            else:
                domain.append(('res_field', '=', False))
            ids = dst_attach.search(domain, limit=1)
            return bool(ids)
        except Exception:
            return False

    def _product_image_exists_in_dst(self, dst_template_id: int, name: Optional[str]) -> bool:
        try:
            model = self.get_dst_model('product.image')
            domain = [('product_tmpl_id', '=', dst_template_id)]
            if name:
                domain.append(('name', '=', name))
            ids = model.search(domain, limit=1)
            return bool(ids)
        except Exception:
            return False

    def _migrate_template_attachments(self, src_template_id: int, dst_template_id: int):
        try:
            src_env = self._odoo_src.session.env
            dst_env = self._odoo_dst.session.env
            src_attach = src_env['ir.attachment'].with_context(active_test=False)
            dst_attach = dst_env['ir.attachment'].with_context(active_test=False)

            src_ids = src_attach.search([('res_model', '=', 'product.template'), ('res_id', '=', src_template_id)])
            if not src_ids:
                return

            _logger.info(
                "Migrating %s attachment(s) for product.template src_id=%s -> dst_id=%s",
                len(src_ids),
                src_template_id,
                dst_template_id,
            )

            read_fields = ['name', 'datas', 'datas_fname', 'mimetype', 'description', 'res_field', 'public', 'type', 'url', 'company_id']
            rows = src_attach.read(src_ids, read_fields)
            if not rows:
                return

            dst_attach_fields = set((self._dst_model_fields('ir.attachment') or {}).keys())
            can_create_product_images = self._dst_has_model('product.image')
            dst_product_image_fields = set((self._dst_model_fields('product.image') or {}).keys()) if can_create_product_images else set()
            created = 0
            skipped_existing = 0
            skipped_empty = 0
            created_gallery = 0
            for row in rows:
                try:
                    src_name = row.get('name')
                    mapped_res_field = self._map_src_template_res_field(row.get('res_field'))

                    # In Odoo 11, many "extra" product images are stored as ir.attachment with res_field=NULL.
                    # In Odoo 17, product gallery images are typically stored in product.image.
                    if not mapped_res_field and can_create_product_images and row.get('type') in (None, 'binary') and row.get('datas'):
                        if self._product_image_exists_in_dst(dst_template_id, src_name):
                            skipped_existing += 1
                            continue
                        vals_img: Dict[str, Any] = {
                            'product_tmpl_id': dst_template_id,
                        }
                        if 'name' in dst_product_image_fields and src_name:
                            vals_img['name'] = src_name
                        if 'image_1920' in dst_product_image_fields:
                            vals_img['image_1920'] = row.get('datas')
                        elif 'image' in dst_product_image_fields:
                            vals_img['image'] = row.get('datas')
                        else:
                            # Destination doesn't expose a compatible binary field; fall back to attachments
                            vals_img = {}

                        if vals_img:
                            self.get_dst_model('product.image').create(vals_img)
                            created_gallery += 1
                            continue

                    if self._attachment_exists_in_dst(dst_template_id, src_name, mapped_res_field):
                        skipped_existing += 1
                        continue

                    vals: Dict[str, Any] = {
                        'name': src_name,
                        'res_model': 'product.template',
                        'res_id': dst_template_id,
                        'type': row.get('type') or 'binary',
                    }

                    if vals['type'] == 'binary' and not row.get('datas'):
                        skipped_empty += 1
                        _logger.warning(
                            "Skipping empty binary attachment for product.template src_id=%s dst_id=%s name=%s res_field=%s (no datas returned by RPC)",
                            src_template_id,
                            dst_template_id,
                            src_name,
                            mapped_res_field,
                        )
                        continue
                    if vals['type'] == 'url' and not row.get('url'):
                        skipped_empty += 1
                        _logger.warning(
                            "Skipping empty url attachment for product.template src_id=%s dst_id=%s name=%s res_field=%s (no url)",
                            src_template_id,
                            dst_template_id,
                            src_name,
                            mapped_res_field,
                        )
                        continue

                    if mapped_res_field:
                        vals['res_field'] = mapped_res_field

                    for k in ['datas', 'datas_fname', 'mimetype', 'description', 'public', 'url', 'company_id']:
                        if k in dst_attach_fields and row.get(k) is not None:
                            if k == 'company_id':
                                company = row.get('company_id')
                                if isinstance(company, (list, tuple)) and company:
                                    vals[k] = company[0]
                                elif isinstance(company, int):
                                    vals[k] = company
                            else:
                                vals[k] = row.get(k)

                    dst_attach.create(vals)
                    created += 1
                except Exception:
                    _logger.exception(
                        "Failed migrating attachment for product.template src_id=%s dst_id=%s attachment_name=%s",
                        src_template_id,
                        dst_template_id,
                        row.get('name'),
                    )
                    continue

            _logger.info(
                "Attachment migration finished for product.template src_id=%s dst_id=%s created=%s created_gallery=%s skipped_existing=%s skipped_empty=%s",
                src_template_id,
                dst_template_id,
                created,
                created_gallery,
                skipped_existing,
                skipped_empty,
            )
        except Exception:
            _logger.exception(
                "Failed migrating attachments for product.template src_id=%s dst_id=%s",
                src_template_id,
                dst_template_id,
            )

    def apply_transformations(self, src_record: Any) -> List[Dict]:
        _logger.info(
            "Processing product.template src_id=%s default_code=%s",
            src_record.id,
            src_record.default_code,
        )
        db_conn = self._db_provider.get_connection(DESTINATION)
        table_name = self.get_dst_model_name().replace('.', '_')
        dst_id = find_id_by_old_id(db_conn, table_name, src_record.id)

        if dst_id:
            _logger.info(
                "Found destination product.template by DB mapping src_id=%s -> dst_id=%s",
                src_record.id,
                dst_id,
            )

        # Fallback: if destination was pre-populated, try to locate the existing template by RPC
        # and set x_old_id so downstream migrations (e.g., product.attribute.line) can resolve it.
        if not dst_id:
            try:
                dst_model = self.get_dst_model('product.template')
                domain = [('name', '=', src_record.name)]
                if src_record.default_code:
                    domain.append(('default_code', '=', src_record.default_code))

                _logger.info(
                    "No DB mapping for product.template src_id=%s; trying RPC lookup with domain=%s",
                    src_record.id,
                    domain,
                )
                ids = dst_model.search(domain, limit=2)
                if ids and len(ids) == 1:
                    dst_id = ids[0]
                    _logger.info(
                        "Found existing destination product.template by name/default_code dst_id=%s src_id=%s name=%s",
                        dst_id,
                        src_record.id,
                        src_record.name,
                    )
                elif ids and len(ids) > 1:
                    _logger.warning(
                        "Multiple destination product.template candidates found by name/default_code for src_id=%s name=%s; will create a new record to avoid wrong mapping",
                        src_record.id,
                        src_record.name,
                    )
                else:
                    _logger.info(
                        "No destination product.template match by name/default_code for src_id=%s name=%s; will create",
                        src_record.id,
                        src_record.name,
                    )
            except Exception:
                # If lookup fails, we'll fall back to create.
                _logger.exception(
                    "RPC lookup failed for product.template src_id=%s name=%s; will create",
                    src_record.id,
                    src_record.name,
                )
                pass
        website_meta_title = src_record.website_meta_title or None
        website_meta_description = src_record.website_meta_description or None
        website_meta_keywords = src_record.website_meta_keywords or None
        seo_auto_update = False
        if not src_record.website_meta_title or not src_record.website_meta_description or not src_record.website_meta_keywords:
            src_record.seo_auto_update = True

        # Resolve UoMs directly via RPC to avoid DB JSON name mismatch on uom_uom
        uom_name = src_record.uom_id.name if src_record.uom_id else None
        uom_po_name = src_record.uom_po_id.name if src_record.uom_po_id else None
        uom_id = self._resolve_uom_id(uom_name)
        uom_po_id = self._resolve_uom_id(uom_po_name)

        # Images: write main image fields directly on product.template so they show in Odoo 17 UI.
        image_vals: Dict[str, Any] = {}
        try:
            if self._dst_has_field('product.template', 'image_1920'):
                image_vals['image_1920'] = getattr(src_record, 'image', None) or None
            elif self._dst_has_field('product.template', 'image'):
                image_vals['image'] = getattr(src_record, 'image', None) or None

            if self._dst_has_field('product.template', 'image_1024'):
                image_vals['image_1024'] = getattr(src_record, 'image_medium', None) or None
            elif self._dst_has_field('product.template', 'image_medium'):
                image_vals['image_medium'] = getattr(src_record, 'image_medium', None) or None

            if self._dst_has_field('product.template', 'image_512'):
                image_vals['image_512'] = getattr(src_record, 'image_small', None) or None
            elif self._dst_has_field('product.template', 'image_small'):
                image_vals['image_small'] = getattr(src_record, 'image_small', None) or None
        except Exception:
            image_vals = {}

        transformed_record = {
            'action': 'update' if dst_id else 'create',
            'model': 'product.template',
            'src_record': src_record,
            'dst_record': self.get_dst_model().browse(dst_id) if dst_id else None,
            'data': {
                'name': src_record.name,
                'active': src_record.active,
                'default_code': src_record.default_code,
                'categ_id': find_id_by_old_id(db_conn, 'product_category', src_record.categ_id.id),
                'uom_id': uom_id,
                'uom_po_id': uom_po_id,
                'detailed_type': src_record.type,
                'sale_ok': src_record.sale_ok,
                'purchase_ok': src_record.purchase_ok,
                'list_price': src_record.list_price or None,
                'volume': src_record.volume or None,
                'weight': src_record.weight or None,
                'invoice_policy': src_record.invoice_policy or None,
                'expense_policy': src_record.expense_policy or None,
                'tracking': src_record.tracking or None,
                'description': src_record.description or None,
                'description_purchase': src_record.description_purchase or None,
                'description_sale': src_record.description_sale or None,
                'website_meta_title': website_meta_title,
                'website_meta_description': website_meta_description,
                'website_meta_keywords': website_meta_keywords,
                'seo_auto_update': seo_auto_update,
                'product_summary': src_record.product_summary,
                'x_old_id': src_record.id,
            }
        }

        if image_vals:
            transformed_record['data'].update(image_vals)

        # already exists ...
        if transformed_record['dst_record'] is not None:
            transformed_record['action'] = 'update'

        _logger.info(
            "Prepared product.template action=%s src_id=%s dst_id=%s name=%s default_code=%s",
            transformed_record['action'],
            src_record.id,
            dst_id,
            src_record.name,
            src_record.default_code,
        )

        return [transformed_record]

    def save_into_destination(self, transformed_records: List[Dict]):
        """
        Save the transformed records in the destination system.
        This handles creating product.template in the destination Odoo (Odoo 16).
        """
        for transformed_record in transformed_records:

            model_name = transformed_record['model']
            data = transformed_record['data']
            action = transformed_record['action']
            src_record = transformed_record['src_record']

            if action in ['create', 'update']:

                if action == 'create':
                    dst_model = self.get_dst_model()
                    _logger.info(
                        "Creating product.template src_id=%s default_code=%s name=%s",
                        src_record.id,
                        src_record.default_code,
                        src_record.name,
                    )
                    x_new_id = dst_model.create(data)

                elif action == 'update':
                    _logger.info(
                        "Updating product.template dst_id=%s src_id=%s default_code=%s name=%s",
                        transformed_record['dst_record'].id,
                        src_record.id,
                        src_record.default_code,
                        src_record.name,
                    )
                    dst_record = transformed_record['dst_record']
                    dst_record.write(data)
                    x_new_id = dst_record.id

                _logger.info(
                    "Saving tracking mapping in DB for product.template: src_id=%s -> dst_id=%s (x_old_id)",
                    src_record.id,
                    x_new_id,
                )
                self.update_tracking_ids(
                    x_new_id=x_new_id,
                    record=src_record
                )
                _logger.info(
                    "Saved tracking mapping in DB for product.template: src_id=%s -> dst_id=%s (x_old_id)",
                    src_record.id,
                    x_new_id,
                )

                self._migrate_template_attachments(src_record.id, x_new_id)

    def _resolve_uom_id(self, name: Optional[str]) -> Optional[int]:
        """
        Resolve a UoM id on the destination via RPC by name with safe fallbacks.
        Returns None if not found (Odoo will error if mandatory but we log upstream).
        """
        try:
            if not name:
                return self._fallback_uom()
            model = self.get_dst_model('uom.uom')
            # Try exact name match first
            ids = model.search([('name', '=', name)], limit=1)
            if not ids:
                # Then ilike
                ids = model.search([('name', 'ilike', name)], limit=1)
            if ids:
                return ids[0]
            return self._fallback_uom()
        except Exception:
            return self._fallback_uom()

    def _fallback_uom(self) -> Optional[int]:
        """Best-effort fallback to a common unit of measure in destination (e.g., Unit(s))."""
        try:
            model = self.get_dst_model('uom.uom')
            # Prefer reference unit in 'Unit' category if present
            ids = model.search([('name', 'ilike', 'unit')], limit=1)
            if ids:
                return ids[0]
            # Last resort: pick any UoM
            ids = model.search([], limit=1)
            return ids[0] if ids else None
        except Exception:
            return None
