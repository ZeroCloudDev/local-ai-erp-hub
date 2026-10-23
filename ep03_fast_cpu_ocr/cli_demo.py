"""
Episode 3 CLI Demo:
Demonstrates the Two-Stage CPU OCR Pipeline (OpenCV + RapidOCR ONNX + 12-line Y-Coordinate Row Sorter)
on a tilted receipt photo, contrasting naive top-to-bottom OCR vs. geometry-aligned rows.
"""

from pathlib import Path
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.database import save_extraction
from ep03_fast_cpu_ocr.ocr_pipeline import (
    extract_naive_unsorted_ocr,
    get_ocr_engine,
    preprocess_receipt_image,
    process_receipt_image_to_erp,
)

IMG_DIR = Path(__file__).resolve().parent.parent / "data" / "samples_ep3_images"


def run_ep03_demo() -> None:
    receipt_img = IMG_DIR / "tilted_fastenal_receipt.png"
    print(f"=== EPISODE 3 DEMO: Fast CPU OCR + Y-Coordinate Row Sorter ({receipt_img.name}) ===\n")

    engine = get_ocr_engine()
    preprocessed = preprocess_receipt_image(receipt_img)
    raw_ocr_boxes, _ = engine(preprocessed)

    print("--- 1. Naive Unsorted OCR (Splits tilted rows across different lines!) ---")
    print(extract_naive_unsorted_ocr(raw_ocr_boxes))

    print("\n--- 2. Our 12-Line Y-Coordinate Row Sorter + Qwen 2.5 3B ---")
    aligned_text, po, metrics = process_receipt_image_to_erp(receipt_img)
    print("[Aligned Horizontal Rows]:")
    print(aligned_text)

    po_id = save_extraction(
        po=po,
        source_type="ep03_image_ocr",
        source_name=receipt_img.name,
        raw_content=receipt_img.read_bytes(),
        wall_time_ms=metrics["total_pipeline_ms"],
    )
    status_str = "⚠️ NEEDS HUMAN REVIEW" if po.needs_human_review else "✅ AUTO-APPROVED"
    print(
        f"\nDB Record #{po_id} | Status: {status_str}\n"
        f"Timing: RapidOCR={metrics['ocr_duration_ms']} ms | "
        f"LLM={metrics['wall_time_ms']} ms ({metrics['tokens_per_sec']} tok/s) | "
        f"Total Pipeline={metrics['total_pipeline_ms']} ms"
    )
    print(po.model_dump_json(indent=2))


if __name__ == "__main__":
    run_ep03_demo()
