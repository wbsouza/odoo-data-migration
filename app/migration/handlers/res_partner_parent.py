import logging
from typing import Dict, List, Optional, Any

from .base import DomainHandler
from ..core.odoo_connection import OdooConnectionProvider, DESTINATION
from ..core.database import DBConnectionProvider, find_id_by_old_id


_logger = logging.getLogger(__name__)


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
        # Cache for partner ID lookups to avoid repeated database queries
        self._partner_id_cache: Dict[int, int] = {}

    def find_dest_partner_by_old_id(self, src_partner_id):
        """Find destination partner by x_old_id with caching"""
        if not src_partner_id:
            return None
        
        # Check cache first
        if src_partner_id in self._partner_id_cache:
            cached_id = self._partner_id_cache[src_partner_id]
            if cached_id:  # Only return if we found a valid ID
                model = self.get_dst_model()
                return model.browse(cached_id)
            return None  # Cached as None (not found)
        
        # Not in cache, perform database lookup
        conn = self._db_provider.get_connection(DESTINATION)
        partner_id = find_id_by_old_id(conn, 'res_partner', src_partner_id)
        
        # Cache the result (even if None to avoid repeated lookups)
        self._partner_id_cache[src_partner_id] = partner_id
        
        if partner_id:
            model = self.get_dst_model()
            return model.browse(partner_id)
        return None

    def apply_transformations(self, src_record: Any) -> List[Dict]:
        """
        Only process records that have a parent_id to update.
        Find both the destination record and its parent.
        """
        _logger.info(
            "Processing res.partner parent relationship src_id=%s name=%s parent_id=%s",
            src_record.id,
            src_record.name,
            src_record.parent_id.id if src_record.parent_id else None,
        )
        
        # Skip records without parent_id
        if not src_record.parent_id:
            _logger.debug(
                "Skipping res.partner src_id=%s (no parent_id)",
                src_record.id,
            )
            return []

        # Find the destination partner record
        dst_record = self.find_dest_partner_by_old_id(src_record.id)
        if not dst_record:
            _logger.warning(
                "Destination partner not found for source ID %s. Skipping parent update.",
                src_record.id,
            )
            return []

        # Find the destination parent record
        dst_parent = self.find_dest_partner_by_old_id(src_record.parent_id.id)
        if not dst_parent:
            _logger.warning(
                "Destination parent partner not found for source parent ID %s. Skipping parent update for partner '%s'.",
                src_record.parent_id.id,
                src_record.name,
            )
            return []

        result = [{
            'action': 'update',
            'model': 'res.partner',
            'src_record': src_record,
            'dst_record': dst_record,
            'data': {
                'parent_id': dst_parent.id,
                'x_old_id': src_record.id,
            }
        }]
        
        _logger.info(
            "Prepared parent relationship update: src_id=%s -> dst_id=%s, parent_src_id=%s -> parent_dst_id=%s",
            src_record.id,
            dst_record.id,
            src_record.parent_id.id,
            dst_parent.id,
        )
        
        return result

    def save_into_destination(self, transformed_records: List[Dict]):
        """
        Update partner records with parent relationships.
        """
        for transformed_record in transformed_records:
            try:
                data = transformed_record['data']
                src_record = transformed_record['src_record']
                dst_record = transformed_record['dst_record']

                _logger.info(
                    "Updating parent relationship for partner dst_id=%s src_id=%s name=%s parent_id=%s",
                    dst_record.id,
                    src_record.id,
                    src_record.name,
                    data['parent_id'],
                )
                
                dst_record.write(data)
                
                _logger.info(
                    "Successfully updated parent relationship for partner dst_id=%s src_id=%s name=%s",
                    dst_record.id,
                    src_record.id,
                    src_record.name,
                )
                
            except Exception as e:
                _logger.exception(
                    "Error updating parent relationship for partner src_id=%s name=%s: %s",
                    src_record.id,
                    src_record.name,
                    str(e),
                )
                continue  # Don't stop the entire parent migration for one error

        # Note: No need to update tracking IDs since the record already exists
