"""
Episode 2 CLI Demo:
Shows side-by-side comparison of broken `pypdf` output vs. `pymupdf4llm` (bordered tables)
and `pdfplumber` Visual X-Ray (borderless whitespace tables) piped into our shared Pydantic + Ollama core.
"""

from pathlib import Path
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.database import save_extraction
from ep02_pdf_tables.pdf_parser import (
    extract_broken_pypdf,
    extract_whitespace_table_pdfplumber,
    process_pdf_to_erp,
)

PDF_DIR = Path(__file__).resolve().parent.parent / "data" / "samples_ep2_pdf"


def run_ep02_demo() -> None:
    bordered_pdf = PDF_DIR / "mouser_bordered_invoice.pdf"
    borderless_pdf = PDF_DIR / "digikey_borderless_invoice.pdf"
    xray_png = PDF_DIR / "digikey_xray_debug.png"

    print("=== EPISODE 2 DEMO: PDF Table Geometry & Visual X-Ray ===\n")

    print(f"--- 1. Bordered B2B Invoice ({bordered_pdf.name}) ---")
    print("[BROKEN pypdf raw stream]:")
    print(extract_broken_pypdf(bordered_pdf))

    md1, po1, m1 = process_pdf_to_erp(bordered_pdf, use_whitespace_strategy=False)
    po1_id = save_extraction(
        po=po1,
        source_type="ep02_pdf_bordered",
        source_name=bordered_pdf.name,
        raw_content= bordered_pdf.read_bytes(),
        wall_time_ms=m1["wall_time_ms"],
    )
    print("\n[CLEAN pymupdf4llm Markdown Table]:")
    print(md1)
    status1 = "⚠️ NEEDS HUMAN REVIEW" if po1.needs_human_review else "✅ AUTO-APPROVED"
    print(f"DB Record #{po1_id} | Status: {status1} | Wall: {m1['wall_time_ms']} ms ({m1['tokens_per_sec']} tok/s)")
    print(po1.model_dump_json(indent=2))
    print("\n" + "=" * 70 + "\n")

    print(f"--- 2. Borderless Whitespace Invoice ({borderless_pdf.name}) ---")
    extract_whitespace_table_pdfplumber(borderless_pdf, debug_image_out=xray_png)
    print(f"[Visual X-Ray Debug Image saved to: {xray_png.name}]")

    md2, po2, m2 = process_pdf_to_erp(borderless_pdf, use_whitespace_strategy=True)
    po2_id = save_extraction(
        po=po2,
        source_type="ep02_pdf_whitespace",
        source_name=borderless_pdf.name,
        raw_content=borderless_pdf.read_bytes(),
        wall_time_ms=m2["wall_time_ms"],
    )
    print("\n[CLEAN pdfplumber Whitespace Markdown]:")
    print(md2)
    status2 = "⚠️ NEEDS HUMAN REVIEW" if po2.needs_human_review else "✅ AUTO-APPROVED"
    print(f"DB Record #{po2_id} | Status: {status2} | Wall: {m2['wall_time_ms']} ms ({m2['tokens_per_sec']} tok/s)")
    print(po2.model_dump_json(indent=2))


if __name__ == "__main__":
    run_ep02_demo()
