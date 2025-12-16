import logging
from typing import Dict, List, Any, Optional

from .base import DomainHandler, DESTINATION
from ..core.odoo_connection import OdooConnectionProvider
from ..core.database import DBConnectionProvider, find_id_by_old_id


class ProductAttributePriceHandler(DomainHandler):

    def __init__(
        self,
        odoo_provider: OdooConnectionProvider,
        db_provider: DBConnectionProvider,
        model_name: str,
        fields: List[str],
    ):
        """
        Handle migration of product.attribute.price (v11) into
        product.template.attribute.value custom pricing fields (v17/v16).
        Source fields expected:
          - product_tmpl_id
          - value_id (product.attribute.value)
          - price_plus (Float)
          - price_multiple (Float)
          - sequence_esp (Integer) — if present; default 0 otherwise
        Destination: product.template.attribute.value
          - product_tmpl_id
          - product_attribute_value_id
          - price_plus
          - price_multiple
          - sequence_esp
        """
        super().__init__(odoo_provider, db_provider, model_name)
        self.fields = fields

    def _find_dst_ptav_id(self, dst_template_id: int, dst_pav_id: int) -> Optional[int]:
        """Locate the PTAV id in destination by template and attribute value."""
        model = self.get_dst_model('product.template.attribute.value')
        logging.info(
            "Searching destination PTAV for product_tmpl_id=%s product_attribute_value_id=%s",
            dst_template_id,
            dst_pav_id,
        )
        ids = model.search([
            ('product_tmpl_id', '=', dst_template_id),
            ('product_attribute_value_id', '=', dst_pav_id),
        ], limit=1)
        if ids:
            logging.info(
                "Found destination PTAV id=%s for product_tmpl_id=%s product_attribute_value_id=%s",
                ids[0],
                dst_template_id,
                dst_pav_id,
            )
        return ids[0] if ids else None

    def apply_transformations(self, src_record: Any) -> List[Dict]:
        """Build an update for PTAV pricing fields. Supports dict rows from read()."""

        def _m2o_id(val: Any) -> Optional[int]:
            # Handles forms: [id, name], (id, name), int id, {'id': id, 'name': name}, recordset
            if val is None:
                return None
            if isinstance(val, (list, tuple)):
                return val[0] if val else None
            if isinstance(val, dict):
                return val.get('id')
            if isinstance(val, int):
                return val
            return val.id

        # Extract ids safely whether src_record is dict or recordset
        if isinstance(src_record, dict):
            src_tmpl_id = _m2o_id(src_record.get('product_tmpl_id'))
            src_pav_id = _m2o_id(src_record.get('value_id'))
            price_plus = src_record.get('price_plus') or 0.0
            price_multiple = src_record.get('price_multiple') or 0.0
            sequence_esp = src_record.get('sequence_esp')
            src_label = src_record.get('id', 'unknown')
        else:
            src_tmpl_id = _m2o_id(src_record.product_tmpl_id)
            src_pav_id = _m2o_id(src_record.value_id)
            price_plus = src_record.price_plus or 0.0
            price_multiple = src_record.price_multiple or 0.0
            sequence_esp = src_record.sequence_esp
            src_label = src_record.id

        # Resolve destination ids via x_old_id mappings
        conn = self._db_provider.get_connection(DESTINATION)
        dst_tmpl_id = find_id_by_old_id(conn, 'product_template', src_tmpl_id)
        if not dst_tmpl_id:
            logging.warning(
                "Skipping attribute price src_id=%s: no destination product.template mapping for src_tmpl_id=%s",
                src_label,
                src_tmpl_id,
            )
            return []

        if not src_pav_id:
            logging.warning(
                "Skipping attribute price src_id=%s: missing src value_id",
                src_label,
            )
            return []

        dst_pav_id = find_id_by_old_id(conn, 'product_attribute_value', src_pav_id)
        if not dst_pav_id:
            logging.warning(
                "Skipping attribute price src_id=%s: no destination product.attribute.value mapping for src_pav_id=%s",
                src_label,
                src_pav_id,
            )
            return []

        dst_ptav_id = self._find_dst_ptav_id(dst_tmpl_id, dst_pav_id)
        if not dst_ptav_id:
            logging.warning(
                "Skipping attribute price src_id=%s: no destination PTAV found for dst_tmpl_id=%s dst_pav_id=%s",
                src_label,
                dst_tmpl_id,
                dst_pav_id,
            )
            return []

        data = {
            'price_plus': price_plus,
            'price_multiple': price_multiple,
        }
        if sequence_esp is not None:
            data['sequence_esp'] = sequence_esp

        transformed_record = {
            'action': 'update',
            'model': 'product.template.attribute.value',
            'src_record': src_record,
            'dst_record': {'id': dst_ptav_id},
            'data': data,
        }
        logging.info(
            "Prepared PTAV price update src_id=%s dst_ptav_id=%s dst_tmpl_id=%s dst_pav_id=%s data=%s",
            src_label,
            dst_ptav_id,
            dst_tmpl_id,
            dst_pav_id,
            data,
        )
        return [transformed_record]

    def save_into_destination(self, transformed_records: List[Dict]):
        """Custom save to avoid tracking updates and recordset usage.
        We only perform updates on existing PTAV ids.
        """
        model_name = 'product.template.attribute.value'
        dst_model = self.get_dst_model(model_name)
        for tr in transformed_records:
            data = tr['data']
            dst_rec = tr.get('dst_record') or {}
            dst_id = None
            if isinstance(dst_rec, dict):
                dst_id = dst_rec.get('id')
            else:
                dst_id = dst_rec.id
            if not dst_id:
                continue
            try:
                logging.info(
                    "Updating destination PTAV id=%s with data=%s",
                    dst_id,
                    data,
                )
                dst_model.write([dst_id], data)
            except Exception as e:
                logging.error(f"Error processing attribute price (PTAV) 'unknown': {str(e)}")
                continue
