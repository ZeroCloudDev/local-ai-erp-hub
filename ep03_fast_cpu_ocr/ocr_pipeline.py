"""
Episode 3 Adapter: Fast CPU Receipt OCR + 12-Line Y-Coordinate Row Sorter
Replaces 80-second CPU Vision LLMs (`llama3.2-vision:11b`) with a sub-second ONNX OCR engine
(`RapidOCR`) + geometric row alignment before passing structured lines to `qwen2.5:3b`.
"""

from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Tuple
import cv2
from rapidocr_onnxruntime import RapidOCR

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.llm_client import extract_structured_erp, DEFAULT_MODEL
from core.schemas import PurchaseOrderExtraction

_ocr_engine: RapidOCR | None = None


def get_ocr_engine() -> RapidOCR:
    global _ocr_engine
    if _ocr_engine is None:
        _ocr_engine = RapidOCR()
    return _ocr_engine


def preprocess_receipt_image(image_path: Path) -> Any:
    """
    4-line OpenCV pre-filter for faded thermal receipts taken under poor lighting.
    """
    img = cv2.imread(str(image_path))
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    denoised = cv2.GaussianBlur(gray, (3, 3), 0)
    return denoised


def extract_naive_unsorted_ocr(ocr_result: List[Any]) -> str:
    """
    Demonstrates the classic tilted-receipt bug: sorting strictly by top-Y coordinate
    causes right-edge prices on a tilted receipt to split onto separate lines from left-edge item names.
    """
    if not ocr_result:
        return ""
    sorted_by_top = sorted(ocr_result, key=lambda r: min(pt[1] for pt in r[0]))
    return "\n".join(text for _box, text, _score in sorted_by_top)


def sort_ocr_boxes_into_rows(ocr_result: List[Any], y_tolerance_px: float = 24.0) -> str:
    """
    THE 12-LINE ENGINEERING SECRET SAUCE:
    When a receipt photo is slightly tilted, standard OCR outputs left-side item names and
    right-side prices on separate lines. This function groups bounding boxes by their vertical
    Y-center (within `y_tolerance_px`) and sorts them left-to-right by X-coordinate.
    """
    if not ocr_result:
        return ""
    items = []
    for box, text, _score in ocr_result:
        y_center = sum(pt[1] for pt in box) / 4.0
        x_left = min(pt[0] for pt in box)
        items.append((y_center, x_left, text))

    items.sort(key=lambda x: x[0])
    rows: List[List[Tuple[float, float, str]]] = []
    for item in items:
        if not rows or abs(item[0] - rows[-1][0][0]) > y_tolerance_px:
            rows.append([item])
        else:
            rows[-1].append(item)

    return "\n".join(
        " | ".join(cell[2] for cell in sorted(row, key=lambda c: c[1])) for row in rows
    )


def process_receipt_image_to_erp(
    image_path: Path, model: str = DEFAULT_MODEL
) -> Tuple[str, PurchaseOrderExtraction, Dict[str, Any]]:
    """
    Two-Stage CPU Pipeline:
    Stage 1: OpenCV + RapidOCR (ONNX CPU) + Geometric Y-Row Sorter (~0.5 - 0.8s)
    Stage 2: Qwen 2.5 3B Grammar-Locked Pydantic Extraction (~2.5 - 3.5s)
    """
    t0 = time.perf_counter()
    engine = get_ocr_engine()
    img = preprocess_receipt_image(image_path)
    ocr_result, _ = engine(img)
    aligned_text = sort_ocr_boxes_into_rows(ocr_result)
    ocr_ms = round((time.perf_counter() - t0) * 1000, 1)

    po, llm_metrics = extract_structured_erp(aligned_text, model=model)
    llm_metrics["ocr_duration_ms"] = ocr_ms
    llm_metrics["total_pipeline_ms"] = round(ocr_ms + llm_metrics["wall_time_ms"], 1)
    return aligned_text, po, llm_metrics


def draw_ocr_debug_overlay(
    image_path: Path, ocr_result: List[Any], y_tolerance_px: float = 24.0, out_path: Path | None = None
) -> Any:
    """
    Renders an engineering debug visual showing:
    1. Neon green bounding boxes around detected text
    2. Red anchor dots at (x_left, y_center)
    3. Cyan connecting lines linking items resolved into the same horizontal table row
    """
    import numpy as np
    img = cv2.imread(str(image_path))
    if img is None:
        return None

    overlay = img.copy()
    items = []
    for box, _text, _score in ocr_result:
        pts = np.array(box, dtype=np.int32).reshape((-1, 1, 2))
        cv2.polylines(overlay, [pts], isClosed=True, color=(0, 255, 100), thickness=2)
        y_center = int(sum(pt[1] for pt in box) / 4.0)
        x_left = int(min(pt[0] for pt in box))
        items.append((y_center, x_left, box))
        cv2.circle(overlay, (x_left, y_center), radius=4, color=(0, 0, 255), thickness=-1)

    items.sort(key=lambda x: x[0])
    rows: List[List[Tuple[int, int, Any]]] = []
    for item in items:
        if not rows or abs(item[0] - rows[-1][0][0]) > y_tolerance_px:
            rows.append([item])
        else:
            rows[-1].append(item)

    for row in rows:
        if len(row) > 1:
            sorted_row = sorted(row, key=lambda c: c[1])
            for i in range(len(sorted_row) - 1):
                pt1 = (sorted_row[i][1], sorted_row[i][0])
                pt2 = (sorted_row[i + 1][1], sorted_row[i + 1][0])
                cv2.line(overlay, pt1, pt2, color=(255, 200, 0), thickness=2)

    blended = cv2.addWeighted(overlay, 0.85, img, 0.15, 0)
    if out_path:
        cv2.imwrite(str(out_path), blended)
    return blended

