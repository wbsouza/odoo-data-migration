import logging
from typing import Dict, Generic, List, Optional, Type, TypeVar, Union, Any
from .base import DomainHandler, ResourceNotFoundException
from ..core.mapping import MappingProvider
from ..core.odoo_connection import OdooConnection
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
            resp = self._dst_odoo.fetch_ids('res.groups', domain=domain, limit=1)
            if resp is not None and len(resp) > 0:
                return resp[0]
        return None

    def find_account_move_by_name(self, name):
        domain = [('name', '=', name)]
        model = self._dst_odoo.session.env['account.move']
        ids = model.search(domain, limit=1)
        if ids is not None and len(ids):
            return model.browse(ids[0])[0]
        return None

    def find_partner_by_name(self, name) -> bool:
        domain = [('name', '=', name)]
        model = self._dst_odoo.session.env['res.partner']
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
                # 'currency_id': src_record.currency_id.id,
                'journal_id': src_record.journal_id.id,
                'date': str(src_record.date),
                'ref': src_record.ref,
                # 'line_ids': [(0, 0, line) for line in src_record.line_ids],
                'x_old_id': src_record.id,
            }
        }

        # already exists ...
        if transformed_record['dst_record'] is not None:
            transformed_record['action'] = 'update'

        return [transformed_record]

    def find_dst_product_by_default_code(self, product_tmpl_id: int, default_code: str) -> bool:
        domain = ['&', ('product_tmpl_id', '=', product_tmpl_id), ('default_code', '=', default_code)]
        model = self._dst_odoo.session.env['product.product']
        ids = model.search(domain, limit=1)
        if ids is not None and len(ids):
            return model.browse(ids[0])[0]
        return None

    def dict_invoice_lines(self, line):
        product = self.find_dst_product_by_default_code(line.product_id.product_tmpl_id.id, line.product_id.default_code)
        data = {
            'account_id': line.account_id.id,
            'amount_currency': line.amount_currency,
            'amount_residual': line.amount_residual,
            'amount_residual_currency': line.amount_residual_currency,
            # 'analytic_account_id': line.analytic_account_id.id,
            # 'analytic_line_ids': line.analytic_line_ids,
            # 'analytic_tag_ids': line.analytic_tag_ids,
            'balance': line.balance,
            # 'balance_cash_basis': line.balance_cash_basis,
            'blocked': line.blocked,
            'company_currency_id': line.company_currency_id.id,
            'company_id': line.company_id.id,
            # 'counterpart': line.counterpart,
            'credit': line.credit,
            # 'credit_cash_basis': line.credit_cash_basis,
            # 'currency_id': line.currency_id.id,
            # 'date': line.date,
            # 'date_maturity': line.date_maturity,
            'debit': line.debit,
            # 'debit_cash_basis': line.debit_cash_basis,
            'display_name': line.display_name,
            # 'full_reconcile_id': line.full_reconcile_id.id,
            'id': line.id,
            # 'ids': line.ids,
            # 'invoice_id': src_record.id,
            # 'is_unaffected_earnings_line': line.is_unaffected_earnings_line,
            'journal_id': line.journal_id.id,
            # 'matched_credit_ids': line.matched_credit_ids,
            # 'matched_debit_ids': line.matched_debit_ids,
            'name': line.name,
            # 'narration': line.narration,
            # 'parent_state': line.name,
            'partner_id': line.partner_id.id,
            'payment_id': line.payment_id.id,
            'product_id': product.id if product is not None else line.product_id.id,
            'product_uom_id': line.product_uom_id.id,
            'quantity': line.quantity,
            'reconciled': line.reconciled,
            'ref': line.ref,
            'statement_id': line.statement_id.id,
            'statement_line_id': line.statement_line_id.id,
            'tax_base_amount': line.tax_base_amount,
            # 'tax_exigible': line.tax_exigible,
            # 'tax_ids': line.tax_ids,
            'tax_line_id': line.tax_line_id.id,
            # 'user_type_id': line.user_type_id.id,

        }

        return data

    def save_into_destination(self, transformed_records: List[Dict]):
        """
        Save the transformed records in the destination system.
        This handles creating account.move in the destination Odoo (Odoo 16).
        """
        dst_model = self._dst_odoo.session.env['account.move']
        dst_line_model = self._dst_odoo.session.env['account.move.line']

        for transformed_record in transformed_records:

            data = transformed_record['data']
            action = transformed_record['action']
            src_record = transformed_record['src_record']

            if action == 'create':

                logging.info(f"Creating move \"{src_record.name}\" ...")
                move_lines = []
                products = []
                for line in src_record.line_ids:
                    same_tmpl_products = self.find_dst_product_by_product_tmpl(line.product_id.product_tmpl_id.id)
                    for product in same_tmpl_products:
                        products.append(product)
                    move_lines.append(self.dict_invoice_lines(line))
                data['line_ids'] = [(0, 0, move_lines)],
                new_id = dst_model.create(data)
                for move_line in move_lines:
                    move_line['move_id'] = new_id
                    dst_line_model.create(move_line)


                src_record.write({'x_new_id': new_id})
                dst_move = self.find_account_move_by_name(src_record.name)
                # dst_move.action_post()
            elif action == 'update':
                logging.info(f"Updating move \"{src_record.name}\" ...")
                dst_record = transformed_record['dst_record']
                dst_record.write(data)
                src_record.write({'x_new_id': dst_record.id})

