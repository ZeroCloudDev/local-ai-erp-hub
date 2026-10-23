"""Ledger helpers kept outside the line-frozen video source files."""

import math
import sqlite3
from decimal import Decimal


class ClosingConnection(sqlite3.Connection):
    """Preserve sqlite's connection API and transaction behavior; close on context exit."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def format_money(value, currency='USD'):
    if value is None or not math.isfinite(value):
        return 'N/A'
    code = str(currency or '').strip().upper() or 'Unknown currency'
    return f'${value:,.2f}' if code == 'USD' else f'{code} {value:,.2f}'


def format_approved_spend(rows):
    """Keep currencies separate; never infer USD for an unknown currency."""
    totals = {}
    for row in rows:
        value = row.get('line_total')
        if value is None or not math.isfinite(value):
            continue
        code = str(row.get('currency') or '').strip().upper() or 'Unknown currency'
        totals[code] = totals.get(code, Decimal(0)) + Decimal(str(value))
    if not totals:
        return '$0.00'
    if set(totals) == {'USD'}:
        return f'${totals["USD"]:,.2f}'
    return ' | '.join(f'{code} {total:,.2f}' for code, total in sorted(totals.items()))
