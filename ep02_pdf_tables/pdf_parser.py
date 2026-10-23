"""
Episode 2 Adapter: Digital PDF Table Extraction & Visual X-Ray Debugger
Replaces naive `pypdf` stream reading with geometry-aware `pymupdf4llm` and `pdfplumber`
before feeding clean Markdown tables into the shared Episode 1 Core Engine (`core/llm_client.py`).
"""

from pathlib import Path
import sys
from typing import Dict, Any, Tuple
from pypdf import PdfReader
import pymupdf4llm
import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.llm_client import extract_structured_erp, DEFAULT_MODEL
from core.schemas import PurchaseOrderExtraction


def extract_broken_pypdf(pdf_path: Path) -> str:
    """
    Demonstrates the classic PDF failure mode: `pypdf` flattens multi-column tables
    into unreadable text where quantities and unit prices merge or lose row alignment.
    """
    reader = PdfReader(str(pdf_path))
    pages_text = [page.extract_text() or "" for page in reader.pages]
    return "\n--- PAGE BREAK ---\n".join(pages_text)


def extract_clean_markdown_pymupdf(pdf_path: Path) -> str:
    """
    Uses MuPDF C-level layout geometry (`pymupdf4llm`) to convert bordered PDF tables
    into strict Markdown pipes (`| Part No | Description | Qty | Unit Price | Line Total |`).
    """
    return pymupdf4llm.to_markdown(str(pdf_path))


def extract_whitespace_table_pdfplumber(
    pdf_path: Path, debug_image_out: Path | None = None
) -> str:
    """
    Fallback / Visual X-Ray for modern borderless (whitespace-aligned) invoices (e.g., Stripe, DigiKey):
    Uses `pdfplumber` text-alignment strategy and optionally saves a visual debug PNG showing detected cells.
    """
    markdown_blocks = []
    table_settings = {
        "vertical_strategy": "text",
        "horizontal_strategy": "text",
        "snap_tolerance": 4,
    }
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            if debug_image_out and page_idx == 0:
                im = page.to_image(resolution=150)
                im.debug_tablefinder(table_settings)
                im.save(str(debug_image_out))

            tables = page.extract_tables(table_settings)
            for table in tables:
                for row in table:
                    cleaned = [str(cell).strip().replace("\n", " ") if cell else "" for cell in row]
                    if any(cleaned):
                        markdown_blocks.append("| " + " | ".join(cleaned) + " |")

            # Preserve footer/summary lines (e.g. Overall Invoice Total) that sit outside the table grid
            raw_page_text = page.extract_text() or ""
            for line in raw_page_text.splitlines():
                if "total" in line.lower() or "vendor:" in line.lower():
                    markdown_blocks.append(line.strip())
    return "\n".join(markdown_blocks)


def process_pdf_to_erp(
    pdf_path: Path, use_whitespace_strategy: bool = False, model: str = DEFAULT_MODEL
) -> Tuple[str, PurchaseOrderExtraction, Dict[str, Any]]:
    """
    Full Episode 2 pipeline: PDF -> Clean Markdown Table -> Shared Core Engine (Pydantic + Ollama).
    Automatically falls back to `pdfplumber` whitespace geometry if `pymupdf4llm` finds no bordered table.
    """
    if use_whitespace_strategy:
        md_text = extract_whitespace_table_pdfplumber(pdf_path)
    else:
        md_text = extract_clean_markdown_pymupdf(pdf_path)
        if "|---" not in md_text:
            ws_text = extract_whitespace_table_pdfplumber(pdf_path)
            if "|" in ws_text:
                md_text = ws_text

    po, metrics = extract_structured_erp(md_text, model=model)
    return md_text, po, metrics
