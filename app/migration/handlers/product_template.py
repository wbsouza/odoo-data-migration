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

    def apply_transformations(self, src_record: Any) -> List[Dict]:
        _logger.info(
            "Processing product.template src_id=%s default_code=%s",
            getattr(src_record, 'id', None),
            getattr(src_record, 'default_code', None),
        )
        db_conn = self._db_provider.get_connection(DESTINATION)
        table_name = self.get_dst_model_name().replace('.', '_')
        dst_id = find_id_by_old_id(db_conn, table_name, src_record.id)
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

        # already exists ...
        if transformed_record['dst_record'] is not None:
            transformed_record['action'] = 'update'

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
                        getattr(src_record, 'id', None),
                        getattr(src_record, 'default_code', None),
                        getattr(src_record, 'name', None),
                    )
                    x_new_id = dst_model.create(data)

                elif action == 'update':
                    _logger.info(
                        "Updating product.template dst_id=%s src_id=%s default_code=%s name=%s",
                        getattr(transformed_record.get('dst_record'), 'id', None) if transformed_record.get('dst_record') else None,
                        getattr(src_record, 'id', None),
                        getattr(src_record, 'default_code', None),
                        getattr(src_record, 'name', None),
                    )
                    dst_record = transformed_record['dst_record']
                    dst_record.write(data)
                    x_new_id = dst_record.id

                _logger.info(
                    "Saving tracking mapping in DB for product.template: src_id=%s -> dst_id=%s (x_old_id)",
                    getattr(src_record, 'id', None),
                    x_new_id,
                )
                self.update_tracking_ids(
                    x_new_id=x_new_id,
                    record=src_record
                )
                _logger.info(
                    "Saved tracking mapping in DB for product.template: src_id=%s -> dst_id=%s (x_old_id)",
                    getattr(src_record, 'id', None),
                    x_new_id,
                )

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
