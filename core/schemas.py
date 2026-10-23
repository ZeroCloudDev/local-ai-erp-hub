"""
Two-Layer Defense Schema for Local ERP Extraction:
- Layer 1: Passed to Ollama `format=PurchaseOrderExtraction.model_json_schema()` for C++ GBNF grammar locking.
- Layer 2: Post-generation Pydantic `@model_validator` that checks arithmetic consistency and missing fields,
  preventing silent LLM value hallucinations from entering SQLite unflagged.
"""

from typing import List, Optional
from pydantic import BaseModel, Field, model_validator
from pydantic.json_schema import SkipJsonSchema
from core.schema_rules import checked_line_total, checked_sum, recover_quantity, validate_fiscal_item, parse_tax_rate

class LineItem(BaseModel):
    item_name: str = Field(
        description="Clean name of the purchased item or part (without quantity prefix)."
    )
    sku_or_part_no: Optional[str] = Field(
        default=None,
        description="Exact SKU or manufacturer part number if written in text (e.g. BR120, RC0805FR-0710KL), else null.",
    )
    quantity: Optional[float] = Field(
        default=None, gt=0, allow_inf_nan=False,
        description="Explicit count of items purchased. Set to null if quantity is omitted, plural without a number, or vague ('a bunch of', 'forgot how many'). Never use electrical specs like '10k Ohm', '20A', '24V' as quantity.",
    )
    unit_price: Optional[float] = Field(
        default=None, ge=0, allow_inf_nan=False,
        description="Price for 1 single unit if explicitly stated (e.g. '$14.50 each'->14.5). Null if only total is given.",
    )
    line_total: Optional[float] = Field(
        default=None, ge=0, allow_inf_nan=False,
        description="Total cost for this specific line item if explicitly stated in text, otherwise null.",
    )


class PurchaseOrderExtraction(BaseModel):
    vendor_name: Optional[str] = Field(
        default=None,
        description="Supplier or store name mentioned in text (e.g. Home Depot, Lowe's, DigiKey Electronics, Grainger, AutoZone), else null.",
    )
    job_or_po_number: Optional[str] = Field(
        default=None,
        description="Job number or PO code mentioned (e.g. 'Job #402'->'402', 'PO-8821'->'PO-8821'). If corrected in speech, use the final corrected job number.",
    )
    currency: str = Field(
        default="USD",
        description="3-letter currency code. Use 'USD' when '$' or dollars are used.",
    )
    items: List[LineItem] = Field(
        default_factory=list,
        description="All purchased items mentioned in the message.",
    )
    stated_total: Optional[float] = Field(
        default=None, ge=0, allow_inf_nan=False,
        description="Overall receipt or invoice bottom-line total if explicitly stated for the whole order (e.g. 'Total on receipt is $207.00'->207.0). Do NOT copy a single item's line total here if other items have missing prices.",
    )
    needs_human_review: SkipJsonSchema[bool] = Field(
        default=False,
        description="Populated deterministically by Layer 2 Python validator.",
    )
    review_reasons: SkipJsonSchema[List[str]] = Field(
        default_factory=list,
        description="Populated deterministically by Layer 2 Python validator.",
    )

    @model_validator(mode="after")
    def verify_math_and_completeness(self) -> "PurchaseOrderExtraction":
        """
        Layer 2 Defense: Deterministic Python business rules.
        Never trust a 3B LLM to do arithmetic or flag its own missing fields reliably.
        """
        reasons = list(self.review_reasons)

        if not self.items:
            reasons.append("No line items were extracted.")

        computed_sum = 0.0
        all_lines_have_totals = True

        import re

        for idx, item in enumerate(self.items, start=1):
            # Deterministic recovery if OCR glued '4x' or '2x' onto item_name
            if item.quantity is None and item.item_name:
                m_qty = re.match(r"^\s*(\d+(?:\.\d+)?)\s*[xX]\b\s*(.+)$", item.item_name)
                if m_qty:
                    item.quantity = recover_quantity(m_qty.group(1))
                    item.item_name = m_qty.group(2).strip()

            # Check missing critical fields
            if item.quantity is None:
                reasons.append(f"Row {idx} ({item.item_name}): Missing quantity.")
            if item.unit_price is None and item.line_total is None:
                reasons.append(f"Row {idx} ({item.item_name}): Both unit_price and line_total are null.")

            # Back-calculate or verify line_total when both qty and unit_price exist
            if item.quantity is not None and item.unit_price is not None:
                expected_line = checked_line_total(item.quantity, item.unit_price)
                if item.line_total is None:
                    item.line_total = expected_line
                elif abs(item.line_total - expected_line) > 0.05:
                    reasons.append(
                        f"Row {idx} ({item.item_name}): Math mismatch! "
                        f"qty ({item.quantity}) * unit_price ({item.unit_price}) = {expected_line}, "
                        f"but line_total is {item.line_total}."
                    )

            if item.line_total is not None:
                computed_sum = checked_sum(computed_sum, item.line_total)
            else:
                all_lines_have_totals = False

        # Compare sum of line totals against stated invoice total
        if self.stated_total is not None and all_lines_have_totals and self.items:
            if abs(computed_sum - self.stated_total) > 0.05:
                reasons.append(
                    f"Invoice total mismatch: sum of lines is {computed_sum:.2f}, "
                    f"but stated_total is {self.stated_total:.2f} (difference may be tax/shipping or OCR error)."
                )

        if reasons:
            self.needs_human_review = True
            # Deduplicate while preserving order
            self.review_reasons = list(dict.fromkeys(reasons))

        return self


class FiscalItem(BaseModel):
    """
    Standardized fiscal item model for retail cash registers and POS databases.
    Ingested autonomously from Viber/WhatsApp text, supplier PDF price lists, or paper OCR.
    """
    sifra: Optional[str] = Field(default=None, description="Item code or SKU")
    barkod: Optional[str] = Field(default=None, description="EAN/UPC barcode if present")
    naziv: str = Field(description="Clean item description")
    jedinica_mjere: str = Field(default="kom", description="Unit of measure (kom, kg, m, usl)")
    porezna_stopa: str = Field(default="17%", description="Tax bracket (e.g. 17% PDV, E, K)")
    cijena_sa_pdv: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False, description="Retail price with tax")
    cijena_bez_pdv: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False, description="Wholesale price without tax")
    status_validacije: str = Field(default="APPROVED", description="APPROVED or QUARANTINE_*")
    razlog_karantina: Optional[str] = Field(default=None, description="Reason if quarantined")

    @model_validator(mode="after")
    def validate_fiscal_integrity(self) -> "FiscalItem":
        """
        Derive missing prices from an explicit tax rate and validate arithmetic.
        Unsupported fiscal letter codes require local specification and review.
        Finite source values must also produce finite calculated prices.
        Keep pre-existing quarantine decisions supplied by the source parser.
        Expanded rules live separately to preserve the recorded video lines.
        """
        return validate_fiscal_item(self)
