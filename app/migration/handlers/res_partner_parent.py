import logging
from typing import Dict, List, Optional, Any

from .base import DomainHandler
from ..core.odoo_connection import OdooConnectionProvider, DESTINATION
from ..core.database import DBConnectionProvider, find_id_by_old_id


class ResPartnerParentHandler(DomainHandler):
    """
    Second-phase handler for updating res.partner parent relationships.
    This runs after all partners have been migrated to handle parent_id dependencies.
    """

    def __init__(
            self,
            odoo_provider: OdooConnectionProvider,
            db_provider: DBConnectionProvider,
            model_name: str
    ):
        super().__init__(odoo_provider, db_provider, 'res.partner')

    def find_dest_partner_by_old_id(self, src_partner_id):
        """Find destination partner by old_id"""
        if not src_partner_id:
            return None
        conn = self._db_provider.get_connection(DESTINATION)
        partner_id = find_id_by_old_id(conn, 'res_partner', src_partner_id)
        if partner_id:
            model = self.get_dst_model()
            return model.browse(partner_id)
        return None

    def apply_transformations(self, src_record: Any) -> List[Dict]:
        """
        Only process records that have a parent_id to update.
        Find both the destination record and its parent.
        """
        # Skip records without parent_id
        if not src_record.parent_id:
            return []

        # Find the destination partner record
        dst_record = self.find_dest_partner_by_old_id(src_record.id)
        if not dst_record:
            logging.warning(f"Destination partner not found for source ID {src_record.id}. Skipping parent update.")
            return []

        # Find the destination parent record
        dst_parent = self.find_dest_partner_by_old_id(src_record.parent_id.id)
        if not dst_parent:
            logging.warning(f"Destination parent partner not found for source parent ID {src_record.parent_id.id}. Skipping parent update for partner '{src_record.name}'.")
            return []

        result = [{
            'action': 'update',
            'model': 'res.partner',
            'src_record': src_record,
            'dst_record': dst_record,
            'data': {
                'parent_id': dst_parent.id,
            }
        }]
        return result

    def save_into_destination(self, transformed_records: List[Dict]):
        """
        Update partner records with parent relationships.
        """
        for transformed_record in transformed_records:
            data = transformed_record['data']
            src_record = transformed_record['src_record']
            dst_record = transformed_record['dst_record']

            logging.info(f"Updating parent relationship for partner \"{src_record.name}\" (parent_id: {data['parent_id']})...")
            dst_record.write(data)

            # Note: No need to update tracking IDs since the record already exists
