import logging
from datetime import date as _date
from typing import Dict, List, Optional, Any

from .base import DomainHandler
from ..core.odoo_connection import OdooConnectionProvider, DESTINATION
from ..core.database import DBConnectionProvider, find_id_by_old_id, find_record_by_old_id


class AccountPaymentHandler(DomainHandler):

    def __init__(
            self,
            odoo_provider: OdooConnectionProvider,
            db_provider: DBConnectionProvider,
            model_name: str
    ):
        super().__init__(odoo_provider, db_provider, model_name)

    def find_journal_by_name(self, name):
        """Find journal in destination by name"""
        if not name:
            return None
        domain = [('name', '=', name)]
        dst_model = self.get_dst_model('account.journal')
        ids = dst_model.search(domain, limit=1)
        if ids:
            return ids[0]
        return None

    def find_payment_method_by_name(self, name):
        """Find payment method in destination by name"""
        if not name:
            return None
        domain = [('name', '=', name)]
        dst_model = self.get_dst_model('account.payment.method')
        ids = dst_model.search(domain, limit=1)
        if ids:
            return ids[0]
        return None

    def apply_transformations(self, src_record: Any) -> List[Dict]:
        conn = self._db_provider.get_connection(DESTINATION)
        
        # Use x_old_id lookup for partner
        partner_id = None
        if src_record.partner_id:
            partner_id = find_id_by_old_id(conn, 'res_partner', src_record.partner_id.id)
            if not partner_id:
                logging.warning(f"Partner with x_old_id {src_record.partner_id.id} not found for payment {src_record.id}")

        # Use name-based lookup for journal
        journal_id = None
        if src_record.journal_id:
            journal_id = self.find_journal_by_name(src_record.journal_id.name)
        elif src_record.destination_journal_id:
            journal_id = self.find_journal_by_name(src_record.destination_journal_id.name)
        
        if not journal_id:
            logging.warning(f"Journal not found for payment {src_record.id}")

        # Use name-based lookup for payment method
        payment_method_id = None
        if src_record.payment_method_id:
            payment_method_id = self.find_payment_method_by_name(src_record.payment_method_id.name)

        # Check if record already exists using x_old_id
        existing_record = find_record_by_old_id(conn, 'account_payment', src_record.id)
        browsed_dst_record = None
        if existing_record:
            browsed_dst_record = self.get_dst_model('account.payment').browse(existing_record['id'])
        
        # Get destination company_id from the Odoo connection
        dst_odoo = self._odoo_provider.get_odoo_connection(DESTINATION)
        company_id = dst_odoo.get_company_id()

        # Helpers to sanitize values before RPC
        def _safe_str(val, default=False):
            return val if isinstance(val, (str, int, float)) else default

        def _to_date_str(val):
            if val is None:
                return False
            if callable(val):
                return False
            if isinstance(val, str):
                s = val.strip()
                if len(s) == 10 and s[4] == '-' and s[7] == '-':
                    return s
                return False
            try:
                return val.strftime('%Y-%m-%d')
            except Exception:
                try:
                    s = val.isoformat()
                    if len(s) >= 10 and s[4] == '-' and s[7] == '-':
                        return s[:10]
                except Exception:
                    pass
            return False

        partner_type = _safe_str(src_record.partner_type, default='customer')
        payment_type = _safe_str(src_record.payment_type, default='inbound')

        data = {
            'amount': float(src_record.amount),
            'partner_id': partner_id,
            'partner_type': partner_type,
            'payment_type': payment_type,
            'journal_id': journal_id,
            # Odoo 17 requires payment_method_line_id to be set for the selected journal/direction
            'company_id': company_id,  # Use destination company
            'x_old_id': src_record.id,
            # Keep payment in draft; posting/reconciliation will be a later step
            'state': 'draft',
        }

        # Resolve payment_method_line_id from the journal and payment direction (inbound/outbound)
        # Try to match the source payment method by name; otherwise pick the first available line.
        try:
            if journal_id:
                journal = self.get_dst_model('account.journal').browse(journal_id)
                method_name = None
                try:
                    method_name = src_record.payment_method_id.name if src_record.payment_method_id else False
                except Exception:
                    method_name = None

                if payment_type == 'inbound':
                    lines = journal.inbound_payment_method_line_ids or []
                elif payment_type == 'outbound':
                    lines = journal.outbound_payment_method_line_ids or []
                else:
                    # For transfers, fall back to outbound then inbound
                    lines = journal.outbound_payment_method_line_ids or journal.inbound_payment_method_line_ids or []

                chosen_line_id = None
                if method_name and lines:
                    for line in lines:
                        try:
                            pm_name = line.payment_method_id.name if line.payment_method_id else None
                            if pm_name == method_name or line.name == method_name:
                                chosen_line_id = line.id
                                break
                        except Exception:
                            continue
                if not chosen_line_id and lines:
                    # Default to the first available method line for the journal/direction
                    first = lines[0]
                    chosen_line_id = first.id

                if chosen_line_id:
                    data['payment_method_line_id'] = chosen_line_id
                else:
                    logging.warning(f"No payment method line available for journal {journal_id} and payment_type {payment_type} (payment {src_record.id})")
            else:
                logging.warning(f"Cannot resolve payment_method_line_id: missing journal for payment {src_record.id}")
        except Exception as e:
            logging.warning(f"Failed to resolve payment_method_line_id for payment {src_record.id}: {e}")

        # Add currency if available
        if src_record.currency_id:
            # For currency, we can try name-based lookup as currency codes are standard
            dst_model = self.get_dst_model('res.currency')
            currency_ids = dst_model.search([('name', '=', src_record.currency_id.name)], limit=1)
            if currency_ids:
                data['currency_id'] = currency_ids[0]

        # Add optional fields
        if src_record.date:
            data['date'] = _to_date_str(src_record.date)
        # Ensure mandatory date is set (fallback to today)
        if not data.get('date'):
            data['date'] = _date.today().isoformat()
        
        base_ref = _safe_str(src_record.ref, default=False)
        # Mark source invoice IDs in ref for later reconciliation
        src_inv_ids = []
        try:
            invs = src_record.invoice_ids or []
            for inv in invs:
                src_inv_ids.append(inv.id)
        except Exception:
            src_inv_ids = []

        marker = ''
        if src_inv_ids:
            marker = f" [SRC_INV: {','.join(str(i) for i in src_inv_ids)}]"
        if base_ref:
            data['ref'] = f"{base_ref}{marker}"
        elif marker:
            data['ref'] = marker.strip()

        # Do NOT link to account.move yet; invoices are draft and will change.
        # Reconciliation will occur in a later pass using the [SRC_INV: ids] marker above.

        transformed_record = {
            'action': 'update' if existing_record else 'create',
            'model': 'account.payment',
            'src_record': src_record,
            'dst_record': browsed_dst_record,
            'data': data
        }

        return [transformed_record]

    def save_into_destination(self, transformed_records: List[Dict]):
        """
        Save the transformed records in the destination system.
        This handles creating/updating account.payment in the destination Odoo.
        """
        self.save_records(
            transformed_records=transformed_records,
            default_model_name='account.payment',
            entity_label='payment',
            name_field='ref',
        )

    # Post-migration reconciliation-based details builder
    def finalize_payment_details(self, inbound_only: bool = True) -> None:
        """Rebuild account.payment.invoice.line from actual partial reconciliations in destination.

        - Searches posted payments (optionally inbound only)
        - For each payment, finds receivable/payable move lines and their partial reconciliations
        - Aggregates allocations per invoice and writes invoice_line_ids idempotently
        """
        try:
            pay_model = self.get_dst_model('account.payment')
            domain = [('state', '=', 'posted')]
            if inbound_only:
                domain.append(('payment_type', '=', 'inbound'))
            pay_ids = pay_model.search(domain, limit=0)
            if not pay_ids:
                return
            pays = pay_model.browse(pay_ids)
        except Exception as e:
            logging.error(f"Failed to browse destination payments: {e}")
            return

        move_model = self.get_dst_model('account.move')
        for pay in pays:
            try:
                move = getattr(pay, 'move_id', None)
                if not move:
                    continue
                # Collect receivable/payable lines for this payment's move
                try:
                    pay_lines = []
                    for ml in getattr(move, 'line_ids', []) or []:
                        try:
                            acct = getattr(ml, 'account_id', None)
                            atype = getattr(acct, 'account_type', None) if acct else None
                            if atype in ('asset_receivable', 'liability_payable'):
                                pay_lines.append(ml)
                        except Exception:
                            continue
                except Exception:
                    pay_lines = []

                allocations = {}
                for ml in pay_lines:
                    try:
                        # On a payment line, credit for inbound payments is usually > 0
                        # We aggregate both matched_credit_ids and matched_debit_ids safely
                        pr_recs = []
                        try:
                            for pr in getattr(ml, 'matched_credit_ids', []) or []:
                                pr_recs.append(pr)
                        except Exception:
                            pass
                        try:
                            for pr in getattr(ml, 'matched_debit_ids', []) or []:
                                pr_recs.append(pr)
                        except Exception:
                            pass
                        for pr in pr_recs:
                            try:
                                # Determine the counterpart invoice move line
                                inv_ml = None
                                try:
                                    if getattr(pr, 'credit_move_id', None) and getattr(pr.credit_move_id, 'id', None) == getattr(ml, 'id', None):
                                        inv_ml = getattr(pr, 'debit_move_id', None)
                                    elif getattr(pr, 'debit_move_id', None) and getattr(pr.debit_move_id, 'id', None) == getattr(ml, 'id', None):
                                        inv_ml = getattr(pr, 'credit_move_id', None)
                                except Exception:
                                    inv_ml = None
                                if not inv_ml:
                                    continue
                                inv = getattr(inv_ml, 'move_id', None)
                                inv_id = getattr(inv, 'id', None) if inv else None
                                if not inv_id:
                                    continue
                                amount = float(getattr(pr, 'amount', 0.0) or 0.0)
                                if amount <= 0.0:
                                    continue
                                if inv_id not in allocations:
                                    allocations[inv_id] = {
                                        'amount': 0.0,
                                        'move_line_id': getattr(ml, 'id', None),
                                    }
                                allocations[inv_id]['amount'] += amount
                            except Exception:
                                continue
                    except Exception:
                        continue

                if not allocations:
                    # Nothing to write for this payment
                    continue

                # Build O2M commands
                cmds = [(5, 0, 0)]
                for inv_id, info in allocations.items():
                    try:
                        inv = move_model.browse(inv_id)
                        inv_number = getattr(inv, 'name', False)
                        inv_date = getattr(inv, 'invoice_date', False)
                        inv_due = getattr(inv, 'invoice_date_due', False)
                        inv_currency_id = getattr(inv.currency_id, 'id', False) if getattr(inv, 'currency_id', None) else False
                        inv_amount_total = float(getattr(inv, 'amount_total', 0.0) or 0.0)
                        inv_residual = float(getattr(inv, 'amount_residual', 0.0) or 0.0)
                        allocation = float(info.get('amount', 0.0) or 0.0)
                        balance_amount = inv_residual + allocation

                        vals = {
                            'move_line_id': info.get('move_line_id'),
                            'invoice_id': inv_id,
                            'payment_id': False,
                            'invoice_number': inv_number or False,
                            'invoice_date': inv_date or False,
                            'due_date': inv_due or False,
                            'original_amount': int(inv_amount_total * 100) / 100.00,
                            'balance_amount': int(balance_amount * 100) / 100.00,
                            'remaining_amount': int(inv_residual * 100) / 100.00,
                            'currency_id': inv_currency_id or False,
                            'allocation': int(allocation * 100) / 100.00,
                            'full_reconcile': True if inv_residual == 0.0 else False,
                        }
                        cmds.append((0, 0, vals))
                    except Exception:
                        continue

                try:
                    pay_model.write([getattr(pay, 'id', None)], {'invoice_line_ids': cmds})
                except Exception as e:
                    logging.warning(f"Failed writing invoice lines for payment {getattr(pay, 'id', None)}: {e}")
            except Exception as e:
                logging.warning(f"Error finalizing payment {getattr(pay, 'id', None)}: {e}")
