"""
EP05 — independent completeness check.

WHY
    A language model can silently skip a line. If nobody notices, that
    product simply never reaches the POS and the operator believes the
    document was fully processed.

HOW
    A plain regex, independent of the model, lists every SKU occurrence in
    every source segment (message line, PDF table row or note line, OCR row).
    Each occurrence must end with an outcome. An occurrence that no candidate
    covers becomes a QUARANTINE candidate with reason UNRESOLVED_EXTRACTION.

LIMITS (said honestly in the video too)
    This covers our controlled demo package. It cannot find a SKU that the
    OCR engine itself did not read, or misread into another number, and it
    does not promise to catch every omission in arbitrary free text.
"""

from __future__ import annotations

from dataclasses import dataclass

from ep05_fiscal_ingest_robot.catalog_candidate import SOURCE, CatalogCandidate, FieldSource
from ep05_fiscal_ingest_robot.source_extractors import ExtractedDocument, sku_tokens


@dataclass(frozen=True)
class Occurrence:
    locator: str
    sku: int
    text: str


def scan_occurrences(doc: ExtractedDocument, sku_min: int, sku_max: int) -> list[Occurrence]:
    """Every (segment, SKU) pair in the source, in document order.

    All five-digit SKU-shaped tokens must be accounted for. Outside-range
    occurrences are retained for review, never silently discarded.
    """
    out: list[Occurrence] = []
    for seg in doc.segments:
        for sku in dict.fromkeys(sku_tokens(seg.text)):  # same SKU twice on one line = one occurrence
            out.append(Occurrence(seg.locator, sku, seg.text))
    return out


def unrecognized_document_candidate(source_text: str = "") -> CatalogCandidate:
    """No recognized rows is a visible review item, never a green empty commit."""
    return CatalogCandidate(
        sku=None, name=None, sales_unit=None, tax_class=None,
        retail_price=None, retail_price_raw=None, currency=None, price_basis=None,
        effective=None, locator="document:unrecognized", source_segment=source_text,
        issues=["DOCUMENT_UNRECOGNIZED"],
        notes=["No catalog candidates could be recognized; inspect the original document before retrying."],
    )


def reconcile(doc: ExtractedDocument, sku_min: int, sku_max: int) -> list[CatalogCandidate]:
    """Return the candidates plus one quarantine candidate per uncovered occurrence."""
    covered = {(c.locator, c.sku) for c in doc.candidates}
    result = list(doc.candidates)
    for occ in scan_occurrences(doc, sku_min, sku_max):
        if (occ.locator, occ.sku) in covered:
            continue
        c = CatalogCandidate(
            sku=occ.sku, name=None, sales_unit=None, tax_class=None,
            retail_price=None, retail_price_raw=None, currency=None, price_basis=None,
            effective=None, locator=occ.locator, source_segment=occ.text,
            field_sources={"sku": FieldSource(SOURCE, occ.locator)},
            issues=["UNRESOLVED_EXTRACTION"],
            notes=["SKU found in the source by the independent scanner, but the extractor returned no item for it"],
        )
        result.append(c)
    if not result:
        result.append(unrecognized_document_candidate(
            "\n".join(segment.text for segment in doc.segments)))
    # Keep document order: sort by position of the locator in the segment list.
    order = {s.locator: i for i, s in enumerate(doc.segments)}
    result.sort(key=lambda c: order.get(c.locator, len(order)))
    return result
