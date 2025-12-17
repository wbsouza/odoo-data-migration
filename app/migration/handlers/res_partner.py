import logging

from typing import Dict, List, Optional, Any

from .base import DomainHandler
from ..core.odoo_connection import OdooConnectionProvider, DESTINATION
from ..core.database import DBConnectionProvider, find_record_by_old_id

try:
    from odoorpc.error import RPCError
except Exception:  # pragma: no cover
    RPCError = Exception



_logger = logging.getLogger(__name__)


class ResPartnerHandler(DomainHandler):

    def __init__(
            self,
            odoo_provider: OdooConnectionProvider,
            db_provider: DBConnectionProvider,
            model_name: str
    ):
        super().__init__(odoo_provider, db_provider, model_name)


    def find_dest_partner_by_old_id(self, src_record):
        """Find partner in destination using x_old_id (more reliable than name-based lookup)"""
        conn = self._db_provider.get_connection(DESTINATION)
        dst_record = find_record_by_old_id(conn, 'res_partner', src_record.id)
        if dst_record:
            # Return the Odoo record object, including archived records
            model = self.get_dst_model('res.partner')
            return model.browse(dst_record['id'])
        return None

    def find_dest_country_by_name(self, src_country):
        """Find destination country by name"""
        if not src_country:
            return None
        country_model = self.get_dst_model('res.country')
        countries = country_model.search([('name', '=', src_country.name)], limit=1)
        return countries[0] if countries else None

    def find_dest_state_by_name(self, src_state):
        """Find destination state by name and country"""
        if not src_state:
            return None
        state_model = self.get_dst_model('res.country.state')
        domain = [('name', '=', src_state.name)]
        # If we have country info, add it to make the search more precise
        if src_state.country_id:
            country_id = self.find_dest_country_by_name(src_state.country_id)
            if country_id:
                domain.append(('country_id', '=', country_id))
        states = state_model.search(domain, limit=1)
        return states[0] if states else None

    def apply_transformations(self, src_record: Any) -> List[Dict]:
        _logger.info(
            "Processing res.partner src_id=%s name=%s ref=%s",
            src_record.id,
            src_record.name,
            src_record.ref,
        )
        dst_record = self.find_dest_partner_by_old_id(src_record)
        if dst_record:
            _logger.info(
                "Found destination res.partner by x_old_id mapping src_id=%s -> dst_id=%s",
                src_record.id,
                dst_record.id,
            )
        result = [{
            'action': 'update' if dst_record else 'create',
            'model': 'res.partner',
            'src_record': src_record,
            'dst_record': dst_record,
            'data': {
                'name': src_record.name,
                'display_name': src_record.display_name,
                'active': src_record.active,
                'date': src_record.date,
                'ref': src_record.ref,
                'lang': src_record.lang,
                'tz': src_record.tz,
                'vat': src_record.vat,
                'website': src_record.website,
                'comment': src_record.comment,
                'function': src_record.function,
                'type': src_record.type,
                'street': src_record.street,
                'street2': src_record.street2,
                'zip': src_record.zip,
                'city': src_record.city,
                'email': src_record.email,
                'phone': src_record.phone,
                'mobile': src_record.mobile,
                'is_company': src_record.is_company,
                'company_id': src_record.company_id.id if src_record.company_id else None,
                'x_old_id': src_record.id,

                # Foreign key fields with lookup strategies
                'country_id': self.find_dest_country_by_name(src_record.country_id),
                'state_id': self.find_dest_state_by_name(src_record.state_id),

                # Note: parent_id will be handled in a separate two-phase handler
            }
        }]
        return result

    def save_into_destination(self, transformed_records: List[Dict]):
        """
        Save the transformed records in the destination system.
        This handles creating res.partner in the destination Odoo (Odoo 16).
        """
        for transformed_record in transformed_records:

            model_name = transformed_record['model']
            data = transformed_record['data']
            action = transformed_record['action']
            src_record = transformed_record['src_record']

            if action in ['create', 'update']:
                try:
                    if action == 'create':
                        dst_model = self.get_dst_model()
                        _logger.info(
                            "Creating res.partner src_id=%s name=%s ref=%s",
                            src_record.id,
                            src_record.name,
                            src_record.ref,
                        )
                        try:
                            x_new_id = dst_model.create(data)
                        except RPCError as rpc_ex:
                            msg = str(rpc_ex) or ''
                            if 'VAT' in msg or 'GST/HST' in msg:
                                _logger.warning(
                                    "VAT validation failed on create src_id=%s name=%s vat=%s err=%s",
                                    src_record.id,
                                    src_record.name,
                                    data.get('vat'),
                                    (msg[:300] if msg else 'RPCError'),
                                )
                                data_retry = dict(data)
                                data_retry['vat'] = None
                                _logger.warning(
                                    "Retrying res.partner create without vat due to validation error src_id=%s name=%s vat=%s",
                                    src_record.id,
                                    src_record.name,
                                    data.get('vat'),
                                )
                                x_new_id = dst_model.create(data_retry)
                                _logger.info(
                                    "Retry succeeded (vat cleared) src_id=%s -> dst_id=%s",
                                    src_record.id,
                                    x_new_id,
                                )
                            else:
                                _logger.error(
                                    "RPCError on create res.partner src_id=%s name=%s err=%s",
                                    src_record.id,
                                    src_record.name,
                                    (msg[:300] if msg else 'RPCError'),
                                )
                                raise

                    elif action == 'update':
                        dst_record = transformed_record['dst_record']
                        _logger.info(
                            "Updating res.partner dst_id=%s src_id=%s name=%s ref=%s",
                            dst_record.id,
                            src_record.id,
                            src_record.name,
                            src_record.ref,
                        )
                        try:
                            dst_record.write(data)
                        except RPCError as rpc_ex:
                            msg = str(rpc_ex) or ''
                            if 'VAT' in msg or 'GST/HST' in msg:
                                _logger.warning(
                                    "VAT validation failed on update src_id=%s dst_id=%s name=%s vat=%s err=%s",
                                    src_record.id,
                                    dst_record.id,
                                    src_record.name,
                                    data.get('vat'),
                                    (msg[:300] if msg else 'RPCError'),
                                )
                                data_retry = dict(data)
                                data_retry['vat'] = None
                                _logger.warning(
                                    "Retrying res.partner update without vat due to validation error src_id=%s dst_id=%s name=%s vat=%s",
                                    src_record.id,
                                    dst_record.id,
                                    src_record.name,
                                    data.get('vat'),
                                )
                                dst_record.write(data_retry)
                                _logger.info(
                                    "Retry succeeded (vat cleared) src_id=%s dst_id=%s",
                                    src_record.id,
                                    dst_record.id,
                                )
                            else:
                                _logger.error(
                                    "RPCError on update res.partner src_id=%s dst_id=%s name=%s err=%s",
                                    src_record.id,
                                    dst_record.id,
                                    src_record.name,
                                    (msg[:300] if msg else 'RPCError'),
                                )
                                raise
                        x_new_id = dst_record.id

                    _logger.info(
                        "Saving tracking mapping: src_id=%s -> dst_id=%s",
                        src_record.id,
                        x_new_id,
                    )
                    self.update_tracking_ids(
                        x_new_id=x_new_id,
                        record=src_record
                    )
                except Exception:
                    _logger.exception(
                        "Error processing res.partner action=%s src_id=%s name=%s ref=%s",
                        action,
                        src_record.id,
                        src_record.name,
                        src_record.ref,
                    )
                    continue
