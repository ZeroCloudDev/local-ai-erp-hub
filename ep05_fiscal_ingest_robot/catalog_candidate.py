"""
EP05 — CatalogCandidate: the small POS-catalog contract (decision D4).

WHY A NEW MODEL
    EP01's PurchaseOrderExtraction describes a purchase (quantities, totals).
    A POS catalog entry is something else: SKU, name, sales unit, tax class,
    shelf price. Reusing the purchase model would force us to invent tax
    classes and units. So EP05 adds this small model and keeps EP01-EP04
    untouched.

WHY Decimal AND NOT float
    Money is never a float here. 4.79 must stay exactly 4.79 from the source
    text to the DECIMAL(18,4) column.

WHY PER-FIELD PROVENANCE
    "Where did this value come from?" is asked per field, not per item:
    the price may come from the source line, the currency from a document
    note, the tax class from the existing POS article, a resolved price from
    an operator. field_sources records exactly that, and it is stored with
    every audit row.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any

# Allowed provenance labels for a single field.
SOURCE = "source"                  # literally present in the source segment
DOCUMENT_NOTE = "document_note"    # from a document-level note (e.g. "All prices USD")
COLUMN_HEADER = "column_header"    # from a PDF column header
EXISTING_ARTICLE = "existing_article"  # kept from the article already in the POS
OPERATOR = "operator"              # typed by an operator during quarantine resolution
PROVENANCE_LABELS = {SOURCE, DOCUMENT_NOTE, COLUMN_HEADER, EXISTING_ARTICLE, OPERATOR}


@dataclass
class FieldSource:
    origin: str          # one of PROVENANCE_LABELS
    detail: str = ""     # locator, note text, header text, or operator confirmation

    def __post_init__(self) -> None:
        if self.origin not in PROVENANCE_LABELS:
            raise ValueError(f"unknown provenance {self.origin!r}")


@dataclass
class CatalogCandidate:
    """One SKU occurrence in one source document, before any DB decision."""

    sku: int | None
    name: str | None
    sales_unit: str | None          # source code as written, e.g. "EA", "LB"
    tax_class: str | None           # source code as written, e.g. "T", "X"
    retail_price: Decimal | None    # None is allowed: a missing price is a valid
    retail_price_raw: str | None    #   reason for quarantine, never a zero
    currency: str | None
    price_basis: str | None         # "before_tax" | "tax_included" | None (unknown)
    effective: str | None           # "today", or the unclear/future text found
    locator: str                    # line:3 | page:1/table:1/row:5 | ocr_row:4/bbox:...
    source_segment: str             # the exact source text of that line / row
    field_sources: dict[str, FieldSource] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)   # extraction-time problems (codes)
    notes: list[str] = field(default_factory=list)    # human-readable explanations

    # --- serialization for the audit table -------------------------------
    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["retail_price"] = None if self.retail_price is None else str(self.retail_price)
        return d

    def to_json(self) -> str:
        d = self.to_dict()
        d.pop("field_sources")
        return json.dumps(d, ensure_ascii=False, sort_keys=True)

    def field_sources_json(self) -> str:
        return json.dumps({k: asdict(v) for k, v in sorted(self.field_sources.items())},
                          ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, candidate_json: str, field_sources_json: str) -> "CatalogCandidate":
        d = json.loads(candidate_json)
        price = d.pop("retail_price")
        fs = {k: FieldSource(**v) for k, v in json.loads(field_sources_json).items()}
        return cls(retail_price=None if price is None else Decimal(price), field_sources=fs, **d)

    def price_origin(self) -> str | None:
        fs = self.field_sources.get("retail_price")
        return fs.origin if fs else None
