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
                # 'line_ids': [(0, 0, line) for line in src_record.line_ids],
                'old_id': src_record.id,
            }
        }

        # already exists ...
        if transformed_record['dst_record'] is not None:
            transformed_record['action'] = 'update'

        return [transformed_record]

    def dict_invoice_lines(self, src_record):
        data = {
            'account_id': src_record.line_ids.account_id.id,
            'amount_currency': src_record.line_ids.amount_currency,
            'amount_residual': src_record.line_ids.amount_residual,
            'amount_residual_currency': src_record.line_ids.amount_residual_currency,
            # 'analytic_account_id': src_record.line_ids.analytic_account_id.id,
            # 'analytic_line_ids': src_record.line_ids.analytic_line_ids,
            # 'analytic_tag_ids': src_record.line_ids.analytic_tag_ids,
            'balance': src_record.line_ids.balance,
            # 'balance_cash_basis': src_record.line_ids.balance_cash_basis,
            'blocked': src_record.line_ids.blocked,
            'company_currency_id': src_record.line_ids.company_currency_id.id,
            'company_id': src_record.line_ids.company_id.id,
            # 'counterpart': src_record.line_ids.counterpart,
            'credit': src_record.line_ids.credit,
            # 'credit_cash_basis': src_record.line_ids.credit_cash_basis,
            'currency_id': src_record.line_ids.currency_id.id,
            # 'date': src_record.line_ids.date,
            # 'date_maturity': src_record.line_ids.date_maturity,
            'debit': src_record.line_ids.debit,
            # 'debit_cash_basis': src_record.line_ids.debit_cash_basis,
            'display_name': src_record.line_ids.display_name,
            'full_reconcile_id': src_record.line_ids.full_reconcile_id.id,
            'id': src_record.line_ids.id,
            # 'ids': src_record.line_ids.ids,
            # 'invoice_id': src_record.id,
            # 'is_unaffected_earnings_line': src_record.line_ids.is_unaffected_earnings_line,
            'journal_id': src_record.line_ids.journal_id.id,
            # 'matched_credit_ids': src_record.line_ids.matched_credit_ids,
            # 'matched_debit_ids': src_record.line_ids.matched_debit_ids,
            'name': src_record.line_ids.name,
            # 'narration': src_record.line_ids.narration,
            # 'parent_state': src_record.line_ids.name,
            'partner_id': src_record.line_ids.partner_id.id,
            'payment_id': src_record.line_ids.payment_id.id,
            'product_id': src_record.line_ids.product_id.id,
            'product_uom_id': src_record.line_ids.product_uom_id.id,
            'quantity': src_record.line_ids.quantity,
            'reconciled': src_record.line_ids.reconciled,
            'ref': src_record.line_ids.ref,
            'statement_id': src_record.line_ids.statement_id.id,
            'statement_line_id': src_record.line_ids.statement_line_id.id,
            'tax_base_amount': src_record.line_ids.tax_base_amount,
            # 'tax_exigible': src_record.line_ids.tax_exigible,
            # 'tax_ids': src_record.line_ids.tax_ids,
            'tax_line_id': src_record.line_ids.tax_line_id.id,
            # 'user_type_id': src_record.line_ids.user_type_id.id,

        }

        return data

    def save_into_destination(self, transformed_records: List[Dict]):
        """
        Save the transformed records in the destination system.
        This handles creating account.move in the destination Odoo (Odoo 16).
        """
        dst_model = self.dst_odoo.session.env['account.move']
        dst_line_model = self.dst_odoo.session.env['account.move.line']

        for transformed_record in transformed_records:

            data = transformed_record['data']
            action = transformed_record['action']
            src_record = transformed_record['src_record']

            if action == 'create':

                logging.info(f"Creating move \"{src_record.name}\" ...")
                # move_lines = self.dict_invoice_lines(src_record)
                # data['line_ids'] = [(0, 0, move_lines)],
                new_id = dst_model.create(data)
                # for move_line in move_lines:
                #     move_lines['move_id'] = new_id
                #     dst_line_model.create(move_lines)


                src_record.write({'new_id': new_id})
                # dst_move = self.find_account_move_by_name(src_record.name)
                # dst_move.action_post()
            elif action == 'update':
                logging.info(f"Updating move \"{src_record.name}\" ...")
                dst_record = transformed_record['dst_record']
                dst_record.write(data)
                src_record.write({'new_id': dst_record.id})

