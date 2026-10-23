"""Numeric and fiscal checks kept outside the video-aligned schema module."""

import math
import re
from decimal import Decimal, ROUND_HALF_UP, localcontext
from typing import Any, Optional


def recover_quantity(value: str) -> float:
    quantity = float(value)
    if not math.isfinite(quantity) or quantity <= 0:
        raise ValueError("Recovered quantity must be finite and strictly positive.")
    return quantity


def checked_line_total(quantity: float, unit_price: float) -> float:
    total = quantity * unit_price
    if not math.isfinite(total):
        raise ValueError("Quantity multiplied by unit price exceeds the finite numeric range.")
    return round(total, 2)


def checked_sum(current: float, line_total: float) -> float:
    total = current + line_total
    if not math.isfinite(total):
        raise ValueError("Sum of line totals exceeds the finite numeric range.")
    return total


def parse_tax_rate(porezna_stopa: Optional[str]) -> Optional[float]:
    """Read an explicit percentage; fiscal letter codes have no assumed mapping."""
    if not porezna_stopa:
        return None
    match = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*%(?:\s*PDV)?\s*", porezna_stopa, re.IGNORECASE)
    if not match:
        return None
    percent = float(match.group(1).replace(",", "."))
    if not math.isfinite(percent) or not 0 <= percent <= 100:
        return None
    return percent / 100


def _decimal_amount(value: Any) -> Decimal:
    amount = Decimal(str(value))
    if not amount.is_finite():
        raise ValueError("Fiscal amount must be finite")
    return amount


def _rounded_fiscal_decimal(value: Any) -> Decimal:
    amount = _decimal_amount(value)
    with localcontext() as context:
        context.prec = max(34, amount.adjusted() + 34, len(amount.as_tuple().digits) + 34)
        return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def fiscal_money(value: Any) -> float:
    """Round fiscal money half up to cents and reject float overflow."""
    rounded = float(_rounded_fiscal_decimal(value))
    if not math.isfinite(rounded):
        raise ValueError("Fiscal calculation exceeds the finite numeric range")
    return rounded


def calculate_fiscal_price(value: Any, tax_rate: float, gross: bool = True) -> float:
    """Apply/remove a fractional tax rate before rounding the final money value."""
    amount = _decimal_amount(value)
    rate = _decimal_amount(tax_rate)
    if not 0 <= rate <= 1:
        raise ValueError("Fiscal tax rate must be between zero and one")
    with localcontext() as context:
        context.prec = max(34, amount.adjusted() + 34, len(amount.as_tuple().digits) + 34)
        factor = Decimal("1") + rate
        calculated = amount * factor if gross else amount / factor
    return fiscal_money(calculated)


def _quarantine(item: Any, status: str, reason: str) -> Any:
    if not item.status_validacije.startswith("QUARANTINE_"):
        item.status_validacije = status
    if item.razlog_karantina:
        if reason not in item.razlog_karantina:
            item.razlog_karantina += "; " + reason
    else:
        item.razlog_karantina = reason
    return item


def validate_fiscal_item(item: Any) -> Any:
    tax_rate = parse_tax_rate(item.porezna_stopa)
    if tax_rate is None:
        return _quarantine(item, "QUARANTINE_UNSUPPORTED_TAX", f"Unsupported or invalid tax bracket: '{item.porezna_stopa}'")

    gross = item.cijena_sa_pdv
    net = item.cijena_bez_pdv
    has_gross = gross is not None and math.isfinite(gross) and gross > 0
    has_net = net is not None and math.isfinite(net) and net > 0
    if not has_gross and not has_net:
        return _quarantine(item, "QUARANTINE_MISSING_PRICE", "Price missing or non-positive (requires human review)")

    if has_net:
        try:
            expected_gross = calculate_fiscal_price(net, tax_rate)
        except ValueError:
            return _quarantine(item, "QUARANTINE_INVALID_PRICE", "Tax calculation exceeds the finite numeric range")
        if expected_gross <= 0:
            return _quarantine(item, "QUARANTINE_INVALID_PRICE", "Calculated retail price rounds to zero")
        if not has_gross:
            item.cijena_sa_pdv = expected_gross
        elif abs(_rounded_fiscal_decimal(gross) - _rounded_fiscal_decimal(expected_gross)) > Decimal("0.05"):
            return _quarantine(item, "QUARANTINE_PRICE_MISMATCH", "Gross and net prices do not match the supplied tax rate")
    elif has_gross:
        inferred_net = calculate_fiscal_price(gross, tax_rate, gross=False)
        if inferred_net <= 0:
            return _quarantine(item, "QUARANTINE_INVALID_PRICE", "Calculated wholesale price rounds to zero")
        item.cijena_bez_pdv = inferred_net
    return item
