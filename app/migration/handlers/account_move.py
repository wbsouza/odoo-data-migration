import logging
from typing import Dict, Generic, List, Optional, Type, TypeVar, Union, Any
from .base import DomainHandler, ResourceNotFoundException
from ..core.mapping import MappingProvider
from ..core.odoo import OdooConnection
import json


class AccountMoveHandler(DomainHandler):

    def __init__(self, src_odoo: OdooConnection, dst_odoo: OdooConnection, mapping_provider: MappingProvider):
        """
        Initialize the ResGroupsHandler with the source and destination Odoo connections, and the MappingProvider.
        :param src_odoo: OdooConnection instance for the source Odoo.
        :param dst_odoo: OdooConnection instance for the destination Odoo.
        :param mapping_provider: An instance of MappingProvider to handle ID mappings.
        """
        super().__init__(src_odoo, dst_odoo, 'account.invoice')
        self.language = dst_odoo.language
        self.company_id = dst_odoo.company_id
        self.mapping_provider = mapping_provider

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
            resp = self.dst_odoo.fetch_ids('res.groups', domain=domain, limit=1)
            if resp is not None and len(resp) > 0:
                return resp[0]
        return None

    def find_account_move_by_name(self, name):
        domain = [('name', '=', name)]
        model = self.dst_odoo.session.env['account.move']
        ids = model.search(domain, limit=1)
        if ids is not None and len(ids):
            return model.browse(ids[0])[0]
        return None

    def find_partner_by_name(self, name) -> bool:
        domain = [('name', '=', name)]
        model = self.dst_odoo.session.env['res.partner']
        ids = model.search(domain, limit=1)
        if ids is not None and len(ids):
            return model.browse(ids[0])[0]
        return None


    def apply_transformations(self, src_record: Any) -> List[Dict]:
        if src_record.partner_id:
            dst_partner = self.find_partner_by_name(src_record.partner_id.name)
        else:
            dst_partner = None
        transformed_record = {
            'action': 'create',
            'model': 'account.move',
            'src_record': src_record,
            'dst_record': self.find_account_move_by_name(src_record.name),
            'data': {
                'name': src_record.name,
                'tax_cash_basis_rec_id': src_record.tax_cash_basis_rec_id.id,
                'company_id': src_record.company_id.id,
                'narration': src_record.narration,
                'amount_total': src_record.amount,
                'partner_id': dst_partner.id if dst_partner is not None else None,
                # 'state': src_record.state,
                'currency_id': src_record.currency_id.id,
                'journal_id': src_record.journal_id.id,
                'date': str(src_record.date),
                'ref': src_record.ref,
                'old_id': src_record.id,
            }
        }

        # already exists ...
        if transformed_record['dst_record'] is not None:
            transformed_record['action'] = 'update'

        return [transformed_record]

    def save_into_destination(self, transformed_records: List[Dict]):
        """
        Save the transformed records in the destination system.
        This handles creating account.move in the destination Odoo (Odoo 16).
        """
        for transformed_record in transformed_records:

            model_name = transformed_record['model']
            data = transformed_record['data']
            action = transformed_record['action']
            src_record = transformed_record['src_record']

            if action == 'create':
                dst_model = self.dst_odoo.session.env['account.move']
                logging.info(f"Creating move \"{src_record.name}\" ...")
                new_id = dst_model.create(data)
                src_record.write({'new_id': new_id})
            elif action == 'update':
                logging.info(f"Updating move \"{src_record.name}\" ...")
                dst_record = transformed_record['dst_record']
                dst_record.write(data)
                src_record.write({'new_id': dst_record.id})
