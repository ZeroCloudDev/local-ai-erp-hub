"""
EP05 — turn the three source documents into CatalogCandidates.

This is where Episodes 1-3 are reused, not rewritten:

    message (.txt)  -> EP01 mechanism: local Ollama model with a JSON schema
                       enforced at generation time (format=...), temperature 0.
                       Same helpers as core/llm_client.py, but with a small
                       POS line schema, and ONE line per call: the independent
                       SKU scanner picks the lines, the regex reads the SKU, the
                       model only reads name / unit / tax class / price.
                       (A first rehearsal with qwen2.5:3b on the whole message
                       skipped two of four lines and returned no SKUs; one
                       short line per call is the reliable shape for a 3B model.)
    PDF (.pdf)      -> EP02 geometry: pdfplumber finds the table cells.
                       The header is mapped deterministically; no model is
                       needed for a clean table (decision D4).
    photo (.jpg)    -> EP03: preprocess_receipt_image + RapidOCR +
                       sort_ocr_boxes_into_rows, then the same model step as
                       the message. EP05 adds two things: it straightens tilted
                       box coordinates before EP03's row sorter, and it restores
                       spaces OCR dropped ("OatMilk64oz" -> "Oat Milk 64 oz").

THE MOST IMPORTANT RULE IN THIS FILE: the model proposes, the source decides.
Whatever the model returns is anchored back to the exact source line:
the SKU, the name and the price must literally be in that line. A value the
model "saw" that is not in the source is either discarded (tax/unit, which
then must come from the POS or quarantine) or makes the item a quarantine
case (SKU/name/price). Explicit name cells and supported command name spans
are anchored deterministically and logged as such. These checks are safeguards,
not a claim that arbitrary source documents or OCR are infallible.
"""

from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field

from ep05_fiscal_ingest_robot.catalog_candidate import (COLUMN_HEADER, DOCUMENT_NOTE, SOURCE, CatalogCandidate,
                               FieldSource)

# ---------------------------------------------------------------------------
# Shared text rules
# ---------------------------------------------------------------------------

SKU_TOKEN_RE = re.compile(r"(?<!\d)(\d{5})(?!\d)")

# A size such as "16.9 oz" or "1.5 oz" is not a price.
_UNIT_WORDS = r"(?:oz|fl|lb|lbs|ct|gal|in|pk|roll|ml|l|g|kg|qt|pt)\b"
# First consume an ENTIRE money-like lexeme, including signs and malformed
# separators. Searching only for a valid-looking substring would turn -$4.79
# into +4.79, or $4,79 into $4. No source repair is allowed for those amounts.
MONEY_RE = re.compile(
    r"(?<![\w.$,])(?P<marked>[+\-−]?\s*(?:\$|USD\b)\s*[+\-−]?\s*"
    r"\d(?:[\d.,]*\d)?(?:\s*USD\b)?)(?![\w,%+\-−])"
    r"|(?<![\w.$,])(?P<bare>[+\-−]?\s*\d[\d,]*\.\d[\d.,]*\d|[+\-−]?\s*\d[\d,]*\.\d)"
    r"(?![\w,%+\-−])",
    re.IGNORECASE,
)
# Commas must be proper US thousands groups, never a decimal-comma repair.
# The full cell must be unsigned and have no more than two decimal places.
FULL_PRICE_CELL_RE = re.compile(
    r"^\s*(?:\$|USD\s*)?\s*((?:\d{1,3}(?:,\d{3})+|\d{1,6})(?:\.\d{1,2})?)\s*(?:USD)?\s*$", re.I)

USD_RE = re.compile(r"\$|\bUSD\b", re.I)
FOREIGN_CURRENCY_RE = re.compile(r"€|£|\b(?:EUR|GBP|KM|BAM|CAD|MXN)\b", re.I)
BEFORE_TAX_RE = re.compile(r"before\s+(?:sales\s+)?tax|pre-?tax|excl(?:\.|uding)?\s+(?:sales\s+)?tax", re.I)
TAX_INCLUDED_RE = re.compile(r"incl(?:\.|ude[sd]?|uding)?\s+(?:sales\s+)?tax|tax[- ]inclusive|tax\s+included"
                             r"|with\s+(?:sales\s+)?tax\b", re.I)

_FUTURE_WORDS = (r"tomorrow|next\s+\w+|monday|tuesday|wednesday|thursday|friday|saturday|sunday"
                 r"|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?|later|soon|tbd|pending")
EFFECTIVE_PHRASE_RE = re.compile(
    r"\b(?:effective|starting|as\s+of|beginning|valid\s+from|from)\b\s+([^.,;|]+)", re.I)
FUTURE_RE = re.compile(r"\b(?:" + _FUTURE_WORDS + r")\b", re.I)
TODAY_RE = re.compile(r"\b(?:today|immediately|right\s+away|now)\b", re.I)


def norm_text(s: str) -> str:
    """Case-fold and collapse whitespace/dashes so '$4.79 ' and '$4.79' compare equal."""
    s = s.replace("–", "-").replace("—", "-").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip().casefold()


def _source_money(segment: str) -> tuple[list[Decimal], list[str]]:
    """Return valid amounts AND rejected source lexemes, without losing signs.

    Bare package sizes are not prices. Parenthesized amounts are rejected too:
    in accounting they can mean a negative amount, not a positive shelf price.
    """
    out: list[Decimal] = []
    invalid: list[str] = []
    for match in MONEY_RE.finditer(segment):
        raw = match.group("marked") or match.group("bare")
        if match.group("bare") and re.match(r"\s*" + _UNIT_WORDS, segment[match.end():], re.I):
            continue
        parenthesized = (segment[:match.start()].rstrip().endswith("(")
                         and segment[match.end():].lstrip().startswith(")"))
        # A split decimal such as "$4. 79" must not become a valid $4.
        split_decimal = re.match(r"\s*[.,]\s*\d", segment[match.end():])
        value = None if parenthesized or split_decimal else parse_price_text(raw)
        if value is None:
            invalid.append(raw)
        elif value not in out:
            out.append(value)
    return out, invalid


def money_tokens(segment: str) -> list[Decimal]:
    """Distinct valid whole source amounts, never positive slices of bad ones."""
    return _source_money(segment)[0]


def parse_price_text(raw: str | None) -> Decimal | None:
    """'$4.79' -> Decimal('4.79'). Returns None for anything that is not a plain amount."""
    if raw is None:
        return None
    m = FULL_PRICE_CELL_RE.fullmatch(raw)
    if not m:
        return None
    try:
        return Decimal(m.group(1).replace(",", ""))
    except InvalidOperation:
        return None


def sku_tokens(segment: str) -> list[int]:
    return [int(t) for t in SKU_TOKEN_RE.findall(segment)]


def has_word(segment: str, word: str) -> bool:
    return re.search(r"(?<![A-Za-z0-9])" + re.escape(word) + r"(?![A-Za-z0-9])", segment, re.I) is not None


def detect_effective(text: str, today: date | None = None) -> str | None:
    """'today' if the text says the change applies today; the phrase if it is
    future/unclear; None if the text says nothing about timing."""
    today = today or date.today()
    m = EFFECTIVE_PHRASE_RE.search(text)
    if m:
        phrase = m.group(1).strip()
        if phrase.lower().startswith(today.isoformat()):
            return "today"
        if TODAY_RE.match(phrase) and not FUTURE_RE.search(phrase):
            return "today"
        return phrase  # e.g. "Monday", "next week" -> must be reviewed
    if FUTURE_RE.search(text):
        return FUTURE_RE.search(text).group(0)
    if TODAY_RE.search(text):
        return "today"
    return None


def detect_price_basis(text: str) -> str | None:
    if TAX_INCLUDED_RE.search(text):
        return "tax_included"
    if BEFORE_TAX_RE.search(text):
        return "before_tax"
    return None


def detect_currency(text: str) -> str | None:
    if FOREIGN_CURRENCY_RE.search(text):
        return "FOREIGN:" + FOREIGN_CURRENCY_RE.search(text).group(0).upper()
    if USD_RE.search(text):
        return "USD"
    return None


# ---------------------------------------------------------------------------
# Document container
# ---------------------------------------------------------------------------

@dataclass
class Segment:
    locator: str
    text: str
    is_note: bool = False                 # a document-level line (no table row / not an item line)
    min_ocr_score: float | None = None    # only for OCR rows


@dataclass
class ExtractedDocument:
    kind: str                             # text | pdf | image
    path: Path
    segments: list[Segment]
    candidates: list[CatalogCandidate]
    doc_notes: list[str]
    model_name: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    log: list[str] = field(default_factory=list)


def _document_level(notes: list[str], today: date | None) -> tuple[str | None, str | None, str | None, str]:
    """Currency, price basis and effective date stated once for the whole document."""
    joined = "\n".join(notes)
    effects = [detect_effective(n, today) for n in notes]
    effects = [e for e in effects if e is not None]
    if any(e != "today" for e in effects):
        effective = next(e for e in effects if e != "today")
    else:
        effective = "today" if effects else None
    return detect_currency(joined), detect_price_basis(joined), effective, joined


def _apply_context(c: CatalogCandidate, segment: str, doc_currency, doc_basis, doc_effective,
                   doc_note_text: str, today: date | None) -> None:
    """Fill currency / price basis / effective date: the segment wins over the document note."""
    seg_cur = detect_currency(segment)
    if seg_cur:
        c.currency, c.field_sources["currency"] = seg_cur, FieldSource(SOURCE, c.locator)
    elif doc_currency:
        c.currency, c.field_sources["currency"] = doc_currency, FieldSource(DOCUMENT_NOTE, doc_note_text)
    seg_basis = detect_price_basis(segment)
    if seg_basis:
        c.price_basis, c.field_sources["price_basis"] = seg_basis, FieldSource(SOURCE, c.locator)
    elif doc_basis:
        c.price_basis, c.field_sources["price_basis"] = doc_basis, FieldSource(DOCUMENT_NOTE, doc_note_text)
    seg_eff = detect_effective(segment, today)
    if seg_eff:
        c.effective, c.field_sources["effective"] = seg_eff, FieldSource(SOURCE, c.locator)
    elif doc_effective:
        c.effective, c.field_sources["effective"] = doc_effective, FieldSource(DOCUMENT_NOTE, doc_note_text)


# ---------------------------------------------------------------------------
# EP01 mechanism with a POS-catalog schema
# ---------------------------------------------------------------------------

class PosLineItem(BaseModel):
    """What the model returns for ONE source line. The SKU is not asked for:
    it is read from the line by a regex, which is exact and cannot hallucinate."""
    # All four keys are REQUIRED (no default): with optional keys the grammar
    # let qwen2.5:3b simply leave out unit and tax class (first real probe).
    name: Optional[str] = Field(..., description="Product name exactly as written, without SKU number, unit, tax class or price, never containing |")
    sales_unit: Optional[str] = Field(..., description="Sales unit code exactly as written (EA, LB, GAL) or null")
    tax_class: Optional[str] = Field(..., description="Tax class exactly as written (T, E, Taxable) or null")
    retail_price: Optional[str] = Field(..., description="Price exactly as written, e.g. $4.79, or null if the line has no price")


POS_SYSTEM_PROMPT = """You read ONE line from a store document and return the product on that line.
The line may separate columns with |, for example: SKU | name | unit | tax class | price.
Rules:
1. name = the product name exactly as written. Do not include the SKU number, the unit, the tax class, the price, any | character, or command words such as "Set".
2. retail_price = the price exactly as written including the $ sign. If the line has no price, return null.
3. sales_unit and tax_class only if they are written on the line, otherwise null. Never guess.
4. Copy, do not correct or invent.
"""

# (line_text, model) -> (raw_json of PosLineItem, metrics)
LlmFn = Callable[[str, str], tuple[str, dict]]


def ollama_pos_llm(line_text: str, model: str) -> tuple[str, dict]:
    """The real model call: same mechanism as core.llm_client.extract_structured_erp
    (JSON schema enforced at generation time, temperature 0), one line per call."""
    import ollama
    from core.llm_client import _ensure_ollama_running, _parse_ollama_metrics

    _ensure_ollama_running()
    t0 = time.perf_counter()
    response = ollama.chat(
        model=model,
        messages=[{"role": "system", "content": POS_SYSTEM_PROMPT},
                  {"role": "user", "content": line_text}],
        format=PosLineItem.model_json_schema(),  # grammar-locked JSON (EP01)
        options={"temperature": 0.0},
        keep_alive="30m",
    )
    wall_ms = round((time.perf_counter() - t0) * 1000, 1)
    return response["message"]["content"], _parse_ollama_metrics(response, wall_ms)


# OCR engines often drop spaces: "OatMilk64oz", "1.5oz". These purely
# typographic fixes run on the OCR row BEFORE anything else, so the source
# segment, the model input and the written name all use the same text.
# The raw OCR row is kept in the report.                       # ADAPT HERE (English shelf tags)
_OCR_SPACING_RULES = [
    (re.compile(r"(?<=[a-z]{2})(?=[A-Z][a-z])"), " "),               # OatMilk -> Oat Milk (not "UsD")
    (re.compile(r"(?<=[A-Za-z])(?=\d)(?<!\$)"), " "),                 # Milk64 -> Milk 64
    (re.compile(r"(?<=\d)(?=[A-Z][a-z])"), " "),                       # 95010Oat -> 95010 Oat
    (re.compile(r"(?<=\d)(?=(?:oz|fl|lb|lbs|ct|gal|in|pk|ml|kg|qt)\b)", re.I), " "),  # 64oz -> 64 oz
]


def fix_ocr_spacing(text: str) -> str:
    cells = []
    for cell in text.split(" | "):
        if re.fullmatch(r"\s*\$?\s*[\d.,]+\s*", cell) or SKU_TOKEN_RE.fullmatch(cell.strip()):
            cells.append(cell)           # never touch numbers, prices or SKUs
            continue
        for rx, rep in _OCR_SPACING_RULES:
            cell = rx.sub(rep, cell)
        cells.append(re.sub(r"\s+", " ", cell).strip())
    return " | ".join(cells)


COMMAND_VERB_RE = re.compile(r"^\s*(set|change|update|make|put)\b", re.I)   # ADAPT HERE (English messages)


def compact(s: str) -> str:
    """Letters and digits only, lower case: 'Oat Milk 64 oz' == 'OatMilk64oz'."""
    return re.sub(r"[^0-9a-z.]", "", norm_text(s))


def _source_name_span(text: str, sku: int) -> tuple[int, int, str] | None:
    """Locate a COMPLETE item-name field in two explicitly supported layouts.

    This does not know product names or look them up by SKU. A pipe delimits
    a name cell; a command delimits it between the command verb and ', SKU n,'.
    Arbitrary prose has no independently known name boundary and stays reviewable.
    """
    if "|" in text:
        cells = list(re.finditer(r"[^|]*", text))
        cells = [cell for cell in cells if cell.group().strip()]
        # Supported records have four columns (SKU+name in cell one) or
        # five (separate SKU and name). Fewer cells may mean OCR merged a
        # unit/tax column into the name; that is not a complete-name boundary.
        if len(cells) in (4, 5):
            first = cells[0]
            match = re.fullmatch(r"\s*(?:SKU\s+)?(?P<sku>\d{5})\s+(?P<name>.+?)\s*", first.group(), re.I)
            if match and len(cells) == 4 and int(match.group("sku")) == sku:
                return first.start() + match.start("name"), first.start() + match.end("name"), "pipe_item_cell"
            if len(cells) == 5 and re.fullmatch(r"\s*(?:SKU\s+)?" + re.escape(str(sku)) + r"\s*", first.group(), re.I):
                cell = cells[1]
                left = len(cell.group()) - len(cell.group().lstrip())
                right = len(cell.group().rstrip())
                return cell.start() + left, cell.start() + right, "pipe_item_cell"
    command = re.fullmatch(
        r"\s*(?:set|change|update)\s+(?P<name>[^,|\r\n]+?),\s*SKU\s+(?P<sku>\d{5}),"
        r"\s*to\s+(?:\$|USD\b)[^|\r\n]+", text, re.I)
    if command and int(command.group("sku")) == sku:
        start, end = command.span("name")
        while end > start and text[end - 1].isspace():
            end -= 1
        return start, end, "command_name"
    return None


def _explicit_sales_unit(residual: str, value: str) -> bool:
    """A sales unit is a separate cell or a labelled field, not pack-size prose."""
    if "|" in residual and any(norm_text(cell) == norm_text(value) for cell in residual.split("|")):
        return True
    return re.search(r"\b(?:sales\s+unit|unit|uom)\s*[:=]?\s*" + re.escape(value)
                     + r"(?![A-Za-z0-9])", residual, re.I) is not None


def _line_candidates(seg: Segment, raw_json: str, today: date | None, doc_ctx: tuple,
                     sku_min: int, sku_max: int, codes: tuple | None = None) -> list[CatalogCandidate]:
    """Anchor the model's answer for ONE line back to that line (the core safety step)."""
    skus = [s for s in dict.fromkeys(sku_tokens(seg.text)) if sku_min <= s <= sku_max]
    try:
        data = json.loads(raw_json)
        if not isinstance(data, dict):
            raise ValueError("not a JSON object")
        for key in PosLineItem.model_fields:   # a missing key means "not on the line"
            data.setdefault(key, None)
        it = PosLineItem.model_validate(data)
    except Exception as exc:  # malformed output is a quarantine reason, not a crash
        it = PosLineItem(name=None, sales_unit=None, tax_class=None, retail_price=None)
        bad = f"model output not valid JSON for this line: {exc}"
    else:
        bad = None
    out: list[CatalogCandidate] = []
    for sku in skus:
        text = seg.text
        c = CatalogCandidate(sku=sku, name=(it.name or "").strip() or None,
                             sales_unit=None, tax_class=None,
                             retail_price=None, retail_price_raw=it.retail_price,
                             currency=None, price_basis=None, effective=None,
                             locator=seg.locator, source_segment=text,
                             field_sources={"sku": FieldSource(SOURCE, seg.locator)})
        if bad:
            c.issues.append("MODEL_OUTPUT_INVALID")
            c.notes.append(bad)
        if len(skus) > 1:
            c.issues.append("MULTIPLE_SKUS_ON_LINE")
            c.notes.append(f"line contains several SKUs {skus}; cannot tell which values belong to which")
        # A POS name never contains the column separator. The model sometimes
        # runs into the next column ("Blueberry Muffin | EA"): cut at the separator.
        if c.name and "|" in c.name:
            trimmed = c.name.split("|")[0].strip() or None
            c.notes.append(f"model name {c.name!r} crossed a column separator; trimmed to {trimmed!r}")
            c.name = trimmed
        # A command sentence "Set Cane Sugar 4 lb, SKU 95002, to $4.79" starts
        # with a verb that is not part of the product name (seen in a real run).
        verb = COMMAND_VERB_RE.match(text)
        if c.name and verb and c.name.lower().startswith(verb.group(1).lower() + " "):
            trimmed = c.name[len(verb.group(1)):].strip()
            c.notes.append(f"leading command word {verb.group(1)!r} removed from model name")
            c.name = trimmed
        # A model may omit a package size from its name and mislabel it as a
        # sales unit. Use the WHOLE source field only when its boundaries are
        # independently explicit; never expand a name from arbitrary prose.
        name_span = _source_name_span(text, sku)
        if c.name:
            if SKU_TOKEN_RE.search(c.name):
                c.issues.append("NAME_NOT_IN_SOURCE")
                c.notes.append("model put a number that looks like a SKU into the name")
            elif name_span:
                start, end, layout = name_span
                complete_name = text[start:end]
                if compact(c.name) and compact(c.name) in compact(complete_name):
                    if c.name != complete_name:
                        c.notes.append(f"deterministic complete-name anchor ({layout}): raw model name {it.name!r} -> {complete_name!r}")
                    c.name = complete_name
                    c.field_sources["name"] = FieldSource(
                        SOURCE, f"{seg.locator}/chars:{start}-{end}; deterministic complete_name from {layout}")
                else:
                    c.issues.append("NAME_NOT_IN_SOURCE")
                    c.notes.append(f"model name {c.name!r} is not in the complete source name field")
            else:
                c.issues.append("NAME_BOUNDARY_UNCERTAIN")
                c.notes.append("no explicit complete-name field in free-form source; operator review required")
                if norm_text(c.name) not in norm_text(text) and compact(c.name) not in compact(text):
                    c.issues.append("NAME_NOT_IN_SOURCE")
        # An empty/broken model answer is NOT filled from a fixture or name map.
        # Source amounts are lexed whole so a negative/malformed source cannot
        # ground a positive amount proposed by the model.
        tokens, invalid_money = _source_money(text)
        if invalid_money:
            c.issues.append("INVALID_PRICE")
            c.notes.append(f"unsupported or signed source price lexeme(s): {invalid_money!r}")
        if it.retail_price is not None:
            value = parse_price_text(it.retail_price)
            if value is None or value not in tokens:
                c.issues.append("PRICE_NOT_IN_SOURCE")
                c.notes.append(f"price {it.retail_price!r} is not a price on this source line")
            elif len(tokens) > 1:
                c.issues.append("AMBIGUOUS_PRICE")
                c.notes.append(f"line contains several amounts {', '.join(map(str, tokens))}")
            else:
                c.retail_price = value
                c.field_sources["retail_price"] = FieldSource(SOURCE, seg.locator)
        elif tokens:
            c.notes.append(f"line contains amount(s) {', '.join(map(str, tokens))} the model did not take")
        # Tax class / unit: keep only if literally on the line OUTSIDE the name,
        # otherwise discard. ("Cane Sugar 4 lb" must not turn into unit LB.)
        residual = text
        if name_span:
            start, end, _ = name_span
            residual = text[:start] + " " + text[end:]
        elif c.name and norm_text(c.name) in norm_text(text):
            residual = re.sub(re.escape(c.name), " ", text, count=1, flags=re.I)
        tax_value = it.tax_class
        if tax_value:  # a small model may answer "tax T" or "Tax class: T" for "tax T"
            tax_value = re.sub(r"^\s*tax\b(?:\s+class\b)?\s*[:=-]?\s*(?=\S)", "", tax_value, flags=re.I)
        for attr, value in (("tax_class", tax_value), ("sales_unit", it.sales_unit)):
            if (value and has_word(residual, value.strip())
                    and (attr != "sales_unit" or _explicit_sales_unit(residual, value.strip()))):
                setattr(c, attr, value.strip().upper())
                c.field_sources[attr] = FieldSource(SOURCE, seg.locator)
            elif value:
                c.notes.append(f"model {attr} {value!r} not on source line; discarded")
        # Column codes are LOOKED UP, not interpreted: if the line has | columns
        # and exactly one column is a known unit code (or "tax <code>"/a known tax
        # code), that literal cell is used when the model left the field empty.
        if "|" in text and codes is not None:
            tax_codes, unit_codes = codes
            name_key = compact(c.name or "")
            cells = [x.strip() for x in text.split("|")]
            cells = [x for x in cells if x and not SKU_TOKEN_RE.fullmatch(x)
                     and not money_tokens(x) and (not name_key or compact(x) != name_key)]
            units = [x.upper() for x in cells if x.upper() in unit_codes]
            taxes = []
            for x in cells:
                m = re.fullmatch(r"tax\s+(\S+)", x, re.I)
                if m:
                    taxes.append(m.group(1).upper())
                elif x.upper() in tax_codes:
                    taxes.append(x.upper())
            for attr, found in (("sales_unit", units), ("tax_class", taxes)):
                if getattr(c, attr) is None and len(set(found)) == 1:
                    setattr(c, attr, found[0])
                    c.field_sources[attr] = FieldSource(SOURCE, seg.locator)
                    c.notes.append(f"{attr} {found[0]!r} read from its column by code table")
        if seg.min_ocr_score is not None:
            c.notes.append(f"lowest OCR confidence on row: {seg.min_ocr_score:.2f}")
        _apply_context(c, text, *doc_ctx, today)
        out.append(c)
    return out


def _extract_lines(segments: list[Segment], model: str, llm: LlmFn, today: date | None,
                   doc_ctx: tuple, sku_min: int, sku_max: int, codes: tuple | None = None):
    """One model call per line that contains a managed SKU."""
    cands: list[CatalogCandidate] = []
    log: list[str] = []
    metrics = {"model_calls": 0, "wall_time_ms": 0.0, "load_duration_ms": None}
    for seg in segments:
        if not any(sku_min <= s <= sku_max for s in sku_tokens(seg.text)):
            continue
        raw_json, m = llm(seg.text, model)
        metrics["model_calls"] += 1
        metrics["wall_time_ms"] = round(metrics["wall_time_ms"] + m.get("wall_time_ms", 0.0), 1)
        if metrics["load_duration_ms"] is None:
            metrics["load_duration_ms"] = m.get("load_duration_ms", 0.0)  # first call = cold load
        log.append(f"model [{seg.locator}] {seg.text!r} -> {raw_json}")
        cands.extend(_line_candidates(seg, raw_json, today, doc_ctx, sku_min, sku_max, codes))
    metrics["load_duration_ms"] = metrics["load_duration_ms"] or 0.0
    return cands, log, metrics


# ---------------------------------------------------------------------------
# 1) Message (.txt)
# ---------------------------------------------------------------------------

def extract_text(path: Path, model: str, llm: LlmFn = ollama_pos_llm,
                 today: date | None = None, sku_min: int = 95001,
                 sku_max: int = 95099, codes: tuple | None = None) -> ExtractedDocument:
    text = path.read_bytes().decode("utf-8-sig", errors="strict")
    lines = text.splitlines()
    segments = [Segment(f"line:{i + 1}", ln, is_note=not sku_tokens(ln)) for i, ln in enumerate(lines)]
    notes = [s.text for s in segments if s.is_note and s.text.strip()]
    ctx = _document_level(notes, today)
    cands, log, metrics = _extract_lines(segments, model, llm, today, ctx, sku_min, sku_max, codes)
    return ExtractedDocument("text", path, segments, cands, notes, model, metrics, log)


# ---------------------------------------------------------------------------
# 2) PDF (.pdf) — EP02 geometry + deterministic header mapping
# ---------------------------------------------------------------------------

# Which header text means which field. A column is mapped only if its header
# clearly says so. "Retail price" is required: a cost/wholesale column is
# never accepted as a shelf price.
HEADER_RULES = {                                       # ADAPT HERE for another document layout
    "sku": re.compile(r"^(sku|item\s*(no|#|number)|code)$", re.I),
    "name": re.compile(r"^(description|item|product|name)$", re.I),
    "sales_unit": re.compile(r"^(sales\s+unit|unit|uom)$", re.I),
    "tax_class": re.compile(r"^(tax\s+class|tax)$", re.I),
    "retail_price": re.compile(r"^retail\s+price\b", re.I),
}
FORBIDDEN_PRICE_HEADER = re.compile(r"cost|wholesale|purchase|margin|net\s+price", re.I)


def map_pdf_header(header: list[str | None]) -> tuple[dict[str, int], list[str]]:
    mapping: dict[str, int] = {}
    problems: list[str] = []
    duplicate_fields: set[str] = set()
    for idx, cell in enumerate(header):
        h = re.sub(r"\s+", " ", (cell or "")).strip()
        for fld, rule in HEADER_RULES.items():
            if rule.search(h):
                if fld == "retail_price" and FORBIDDEN_PRICE_HEADER.search(h):
                    problems.append(f"column {h!r} looks like a cost price; not mapped")
                    continue
                if fld in duplicate_fields:
                    continue
                if fld in mapping:
                    problems.append(f"two columns map to {fld}")
                    duplicate_fields.add(fld)
                    del mapping[fld]  # never pick the last of two conflicting columns
                    continue
                mapping[fld] = idx
    for required in ("sku", "name", "retail_price"):
        if required not in mapping:
            problems.append(f"no column for {required}")
    return mapping, problems


def extract_pdf(path: Path, today: date | None = None) -> ExtractedDocument:
    import pdfplumber

    t0 = time.perf_counter()
    segments: list[Segment] = []
    candidates: list[CatalogCandidate] = []
    notes: list[str] = []
    log: list[str] = []
    tables_found: list[tuple[int, int, list[list[str | None]]]] = []

    with pdfplumber.open(str(path)) as pdf:
        for p_idx, page in enumerate(pdf.pages, start=1):
            tables = page.find_tables()
            outside = page
            for t_idx, table in enumerate(tables, start=1):
                tables_found.append((p_idx, t_idx, table.extract()))
                outside = outside.outside_bbox(table.bbox)
            # Lines outside any table are document notes (currency, effective date...).
            for l_idx, line in enumerate((outside.extract_text() or "").splitlines(), start=1):
                if line.strip():
                    notes.append(line.strip())
                    segments.append(Segment(f"page:{p_idx}/text:{l_idx}", line.strip(), is_note=True))

    cur, basis, eff, note_text = _document_level(notes, today)
    for p_idx, t_idx, rows in tables_found:
        if not rows:
            continue
        header = [re.sub(r"\s+", " ", c or "").strip() for c in rows[0]]
        mapping, problems = map_pdf_header(header)
        log.append(f"page {p_idx} table {t_idx} header {header} -> {mapping} {problems}")
        price_header = header[mapping["retail_price"]] if "retail_price" in mapping else ""
        for r_idx, row in enumerate(rows[1:], start=1):
            cells = [re.sub(r"\s+", " ", c or "").strip() for c in row]
            loc = f"page:{p_idx}/table:{t_idx}/row:{r_idx}"
            seg_text = " | ".join(cells)
            segments.append(Segment(loc, seg_text))
            if any(p.startswith(("no column", "two columns")) for p in problems):
                continue  # completeness_check will quarantine every SKU in this table
            get = lambda f: cells[mapping[f]] if f in mapping and mapping[f] < len(cells) else None
            sku_cell, price_cell = get("sku"), get("retail_price")
            sku = int(sku_cell) if sku_cell and re.fullmatch(r"\d{5}", sku_cell) else None
            c = CatalogCandidate(
                sku=sku, name=get("name") or None,
                sales_unit=(get("sales_unit") or "").upper() or None,
                tax_class=(get("tax_class") or "").upper() or None,
                retail_price=None, retail_price_raw=price_cell,
                currency=None, price_basis=None, effective=None,
                locator=loc, source_segment=seg_text)
            for f in ("sku", "name", "sales_unit", "tax_class"):
                if getattr(c, f) is not None:
                    c.field_sources[f] = FieldSource(SOURCE, loc)
            if sku is None:
                c.issues.append("INVALID_SKU")
            value = parse_price_text(price_cell)
            if value is None:
                c.issues.append("INVALID_PRICE" if price_cell else "MISSING_PRICE")
            else:
                c.retail_price = value
                c.field_sources["retail_price"] = FieldSource(SOURCE, loc)
            # The header itself may state currency and basis: "(USD, before sales tax)".
            _apply_context(c, seg_text, cur, basis, eff, note_text, today)
            # A currency/basis written in the row itself wins; otherwise the
            # column header beats a general document note.
            if detect_currency(price_header) and c.field_sources.get("currency", FieldSource(DOCUMENT_NOTE)).origin != SOURCE:
                c.currency = detect_currency(price_header)
                c.field_sources["currency"] = FieldSource(COLUMN_HEADER, price_header)
            if detect_price_basis(price_header) and c.field_sources.get("price_basis", FieldSource(DOCUMENT_NOTE)).origin != SOURCE:
                c.price_basis = detect_price_basis(price_header)
                c.field_sources["price_basis"] = FieldSource(COLUMN_HEADER, price_header)
            candidates.append(c)

    metrics = {"wall_time_ms": round((time.perf_counter() - t0) * 1000, 1), "model": None}
    return ExtractedDocument("pdf", path, segments, candidates, notes, None, metrics, log)


# ---------------------------------------------------------------------------
# 3) Photo (.jpg/.png) — EP03 OCR + row sorter, then the EP01 model step
# ---------------------------------------------------------------------------

def _skew_degrees(ocr_result: list[Any]) -> float:
    """Median angle of the top edge of wide text boxes (a printed page is a set
    of parallel lines). Used to straighten coordinates before row grouping."""
    angles = []
    for box, _text, _score in ocr_result:
        (x0, y0), (x1, y1) = box[0], box[1]
        width = math.hypot(x1 - x0, y1 - y0)
        height = math.hypot(box[3][0] - x0, box[3][1] - y0)
        if width > 2 * height and width > 20:
            angles.append(math.degrees(math.atan2(y1 - y0, x1 - x0)))
    if not angles:
        return 0.0
    angles.sort()
    return angles[len(angles) // 2]


def _rotate_boxes(ocr_result: list[Any], degrees: float) -> list[Any]:
    rad = math.radians(-degrees)
    cos, sin = math.cos(rad), math.sin(rad)
    out = []
    for box, text, score in ocr_result:
        new_box = [[x * cos - y * sin, x * sin + y * cos] for x, y in box]
        out.append((new_box, text, score))
    return out


def _group_rows(ocr_result: list[Any], y_tol: float) -> list[list[tuple]]:
    """Same grouping as EP03 sort_ocr_boxes_into_rows, but it keeps each box,
    so every row has its bounding box and lowest confidence for the audit."""
    items = []
    for idx, (box, text, score) in enumerate(ocr_result):
        items.append((sum(pt[1] for pt in box) / 4.0, min(pt[0] for pt in box), text, score, idx))
    items.sort(key=lambda x: x[0])
    rows: list[list[tuple]] = []
    for item in items:
        if not rows or abs(item[0] - rows[-1][0][0]) > y_tol:
            rows.append([item])
        else:
            rows[-1].append(item)
    return [sorted(r, key=lambda c: c[1]) for r in rows]


def extract_image(path: Path, model: str, llm: LlmFn = ollama_pos_llm, y_tol: float = 24.0,
                  min_conf: float = 0.6, today: date | None = None, sku_min: int = 95001,
                  sku_max: int = 95099, codes: tuple | None = None) -> ExtractedDocument:
    from ep03_fast_cpu_ocr.ocr_pipeline import (get_ocr_engine, preprocess_receipt_image,
                                                 sort_ocr_boxes_into_rows)
    t0 = time.perf_counter()
    engine = get_ocr_engine()
    img = preprocess_receipt_image(path)
    ocr_result, _ = engine(img)
    ocr_result = ocr_result or []
    skew = _skew_degrees(ocr_result)
    straight = _rotate_boxes(ocr_result, skew)
    # EP03's own row sorter produces the text. Our _group_rows must agree with it.
    ep03_text = sort_ocr_boxes_into_rows(straight, y_tolerance_px=y_tol)
    rows = _group_rows(straight, y_tol)
    our_text = "\n".join(" | ".join(c[2] for c in r) for r in rows)
    if our_text != ep03_text:
        raise RuntimeError("row grouping differs from EP03 sort_ocr_boxes_into_rows")
    ocr_ms = round((time.perf_counter() - t0) * 1000, 1)

    segments: list[Segment] = []
    for i, r in enumerate(rows, start=1):
        orig_pts = [pt for c in r for pt in ocr_result[c[4]][0]]
        xs, ys = [p[0] for p in orig_pts], [p[1] for p in orig_pts]
        bbox = f"{int(min(xs))},{int(min(ys))},{int(max(xs))},{int(max(ys))}"
        text = fix_ocr_spacing(" | ".join(c[2] for c in r))
        segments.append(Segment(f"ocr_row:{i}/bbox:{bbox}", text, is_note=not sku_tokens(text),
                                min_ocr_score=min(float(c[3]) for c in r)))
    notes = [s.text for s in segments if s.is_note]
    ctx = _document_level(notes, today)
    cands, log, metrics = _extract_lines(segments, model, llm, today, ctx, sku_min, sku_max, codes)
    for c in cands:
        seg = next(s for s in segments if s.locator == c.locator)
        if seg.min_ocr_score is not None and seg.min_ocr_score < min_conf:
            c.issues.append("OCR_UNCERTAIN")
    metrics = dict(metrics, ocr_duration_ms=ocr_ms, skew_degrees=round(skew, 2))
    return ExtractedDocument("image", path, segments, cands, notes, model, metrics,
                             [f"skew corrected: {skew:.2f} deg", f"raw ocr rows (EP03):\n{ep03_text}",
                              "rows after spacing fix:\n" + "\n".join(s.text for s in segments)] + log)


def extract_any(path: Path, model: str, llm: LlmFn = ollama_pos_llm, y_tol: float = 24.0,
                min_conf: float = 0.6, today: date | None = None, sku_min: int = 95001,
                sku_max: int = 95099, codes: tuple | None = None) -> ExtractedDocument:
    ext = path.suffix.lower()
    if ext in {".txt", ".md"}:
        return extract_text(path, model, llm, today, sku_min, sku_max, codes)
    if ext == ".pdf":
        return extract_pdf(path, today)
    if ext in {".jpg", ".jpeg", ".png"}:
        return extract_image(path, model, llm, y_tol, min_conf, today, sku_min, sku_max, codes)
    raise ValueError(f"unsupported file type {ext}")
