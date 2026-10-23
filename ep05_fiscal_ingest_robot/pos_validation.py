"""
EP05 — validation contract: CatalogCandidate -> outcome.

Two stages, on purpose:

1. static_reasons()   — rules that need only the candidate and the config
                        (format, range, currency, price basis, effective date,
                        approved tax/unit maps). Pure functions, no database.
2. decide()           — rules that need the CURRENT POS state (does the SKU
                        exist, same name?, same price?). The adapter calls this
                        inside the write transaction, after taking the writer
                        lock, so the decision and the write see the same state.

Outcomes: INSERT | UPDATE | NO_CHANGE | QUARANTINE.
The rules (numbering matches the episode notes):
  1  SKU is an integer inside the managed range.
  2  Name present, max 50 characters, never truncated.
  3  Price is Decimal > 0, max 2 decimals, currency USD, basis "before tax".
  4  SKU, name and price are on the same source line (checked in source_extractors).
  5  A NEW article needs tax class and unit from the source or an approved map.
  6  An EXISTING article: only the price may change automatically; tax/unit stay.
  7  Same SKU with a different name -> identity conflict -> review.
  8  Effective date must be "today"; future/unclear -> review.
  9  Same name and same price -> NO_CHANGE.
  10 Every SKU occurrence gets an outcome (completeness_check).
  11 An operator price is accepted only through the resolver (value_source=operator).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from ep05_fiscal_ingest_robot.adapter_config import AdapterConfig
from ep05_fiscal_ingest_robot.catalog_candidate import CatalogCandidate
from ep05_fiscal_ingest_robot.source_extractors import compact, norm_text

INSERT, UPDATE, NO_CHANGE, QUARANTINE = "INSERT", "UPDATE", "NO_CHANGE", "QUARANTINE"

# Reasons an operator can fix by typing a price (rule 11). Anything else can
# only be rejected, or fixed in the source document and sent again.
PRICE_REASONS = {"MISSING_PRICE", "INVALID_PRICE", "AMBIGUOUS_PRICE", "PRICE_NOT_IN_SOURCE"}

CENT = Decimal("0.01")


def to_cents(value: Any) -> Decimal:
    """Compare money at 2 decimals. artcjenik.cijena is DOUBLE in the original
    structure, so 4.79 may come back as 4.7899999...; we round, never truncate."""
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class Decision:
    outcome: str
    reason: str | None = None
    detail: str = ""
    tarifa_id: int | None = None
    jmjera_id: int | None = None
    old_price: Decimal | None = None
    art_id: str | None = None
    price_row_id: str | None = None


def static_reasons(c: CatalogCandidate, cfg: AdapterConfig) -> list[str]:
    """All reasons this candidate cannot be written, independent of POS state."""
    reasons: list[str] = list(dict.fromkeys(c.issues))          # extraction problems first
    if isinstance(c.sku, bool) or not isinstance(c.sku, int):
        reasons.append("INVALID_SKU")
    elif not (cfg.sku_min <= c.sku <= cfg.sku_max):
        reasons.append("SKU_OUT_OF_RANGE")
    if not c.name or not c.name.strip():
        reasons.append("MISSING_NAME")
    elif len(c.name) > cfg.name_max_len:
        reasons.append("NAME_TOO_LONG")                       # no silent truncation
    if c.retail_price is None:
        if not PRICE_REASONS & set(reasons):
            reasons.append("MISSING_PRICE")
    else:
        if (not isinstance(c.retail_price, Decimal) or not c.retail_price.is_finite()
                or c.retail_price <= 0 or c.retail_price.as_tuple().exponent < -2):
            reasons.append("INVALID_PRICE")
        elif c.retail_price > cfg.max_price:
            reasons.append("PRICE_ABOVE_LIMIT")
    if c.currency is None:
        reasons.append("CURRENCY_UNKNOWN")
    elif c.currency != cfg.currency:
        reasons.append("CURRENCY_CONFLICT")
    if c.price_basis is None:
        reasons.append("PRICE_BASIS_UNKNOWN")
    elif c.price_basis != "before_tax":
        reasons.append("PRICE_BASIS_CONFLICT")                # POS cij is before tax (D1)
    if c.effective is None:
        reasons.append("EFFECTIVE_DATE_MISSING")
    elif c.effective != "today":
        reasons.append("EFFECTIVE_DATE_NOT_TODAY")            # no price scheduling in EP05
    if c.tax_class is not None and c.tax_class.upper() not in cfg.tax_class_map:
        reasons.append("UNKNOWN_TAX_CLASS")
    if c.sales_unit is not None and c.sales_unit.upper() not in cfg.sales_unit_map:
        reasons.append("UNKNOWN_SALES_UNIT")
    return list(dict.fromkeys(reasons))


def mark_in_document_conflicts(cands: list[CatalogCandidate]) -> None:
    """The same SKU twice in one document with different values: neither may
    win silently. Identical repeats are fine (the second becomes NO_CHANGE)."""
    by_sku: dict[int, list[CatalogCandidate]] = {}
    for c in cands:
        if c.sku is not None:
            by_sku.setdefault(c.sku, []).append(c)
    for group in by_sku.values():
        if len(group) < 2:
            continue
        sigs = {(compact(c.name or ""), c.retail_price, c.tax_class, c.sales_unit) for c in group}
        if len(sigs) > 1:
            for c in group:
                c.issues.append("CONFLICT_IN_DOCUMENT")
                c.notes.append("same SKU appears again in this document with different values")


def canonical_unit_id(jedmjer: Any) -> int | None:
    """artikli.jedmjer is TEXT holding jmjera.id. Accept only canonical '1', '2'...
    A value like ' 1', '01' or 'kom' is treated as invalid, never cast."""
    s = "" if jedmjer is None else str(jedmjer)
    return int(s) if s.isdigit() and int(s) > 0 and str(int(s)) == s else None


def decide(c: CatalogCandidate, existing: list[dict], price_rows: list[dict],
           cfg: AdapterConfig, static: list[str] | None = None) -> Decision:
    """Final outcome against the current POS state (called under the writer lock)."""
    static = static_reasons(c, cfg) if static is None else static
    if static:
        return Decision(QUARANTINE, static[0], "; ".join(static + c.notes))
    tarifa_id = cfg.tax_class_map[c.tax_class.upper()] if c.tax_class else None
    jmjera_id = cfg.sales_unit_map[c.sales_unit.upper()] if c.sales_unit else None

    if len(existing) > 1:
        return Decision(QUARANTINE, "DUPLICATE_ART_BROJ_IN_POS",
                        f"{len(existing)} active articles already use art_broj {c.sku}")
    if not existing:                                       # ---- new article (rule 5)
        if tarifa_id is None:
            return Decision(QUARANTINE, "MISSING_TAX_CLASS", "new article needs a tax class from the source")
        if jmjera_id is None:
            return Decision(QUARANTINE, "MISSING_SALES_UNIT", "new article needs a sales unit from the source")
        return Decision(INSERT, tarifa_id=tarifa_id, jmjera_id=jmjera_id)

    art = existing[0]                                      # ---- existing article
    # rule 7 - compared without spaces/punctuation: "Oat Milk 64 oz" == "OatMilk 64oz"
    if compact(art["naziv"] or "") != compact(c.name):
        return Decision(QUARANTINE, "IDENTITY_CONFLICT",
                        f"POS has {art['art_broj']} = {art['naziv']!r}, source says {c.name!r}")
    pos_unit = canonical_unit_id(art["jedmjer"])
    if pos_unit is None:
        return Decision(QUARANTINE, "POS_DATA_INVALID", f"artikli.jedmjer {art['jedmjer']!r} is not canonical")
    pos_tax = canonical_unit_id(art["tarifa"])
    if pos_tax is None:
        return Decision(QUARANTINE, "POS_DATA_INVALID", f"artikli.tarifa {art['tarifa']!r} is not a positive reference")
    if tarifa_id is not None and tarifa_id != pos_tax:   # rule 6
        return Decision(QUARANTINE, "ATTRIBUTE_CHANGE", f"tax class change {art['tarifa']} -> {tarifa_id} needs review")
    if jmjera_id is not None and jmjera_id != pos_unit:
        return Decision(QUARANTINE, "ATTRIBUTE_CHANGE", f"sales unit change {pos_unit} -> {jmjera_id} needs review")
    if len(price_rows) > 1:
        return Decision(QUARANTINE, "PRICE_LIST_AMBIGUOUS",
                        f"{len(price_rows)} selected price-list rows for one article")

    try:
        # DECIMAL is exact: do not hide a four-decimal catalog discrepancy by
        # rounding it into NO_CHANGE. Only the legacy DOUBLE list needs cents.
        old = Decimal(str(art["cij"]))
        if not old.is_finite() or old <= 0:
            raise ValueError("invalid existing article price")
        row = price_rows[0] if price_rows else None
        if row is not None:
            list_value = Decimal(str(row["cijena"]))
            if not list_value.is_finite() or list_value <= 0:
                raise ValueError("invalid existing price-list amount")
        same_list = row is not None and to_cents(row["cijena"]) == c.retail_price
    except (InvalidOperation, ValueError, TypeError):
        return Decision(QUARANTINE, "POS_DATA_INVALID", "existing article or selected price-list amount is invalid")
    if old == c.retail_price and same_list:                # rule 9
        return Decision(NO_CHANGE, old_price=old, art_id=art["id"], price_row_id=row["id"],
                        tarifa_id=pos_tax, jmjera_id=pos_unit)
    return Decision(UPDATE, old_price=old, art_id=art["id"],
                    price_row_id=row["id"] if row else None,
                    tarifa_id=pos_tax, jmjera_id=pos_unit)
