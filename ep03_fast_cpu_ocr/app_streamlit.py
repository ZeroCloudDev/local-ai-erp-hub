"""
Episode 3 Streamlit Dashboard:
Zero-Cloud ERP Engine on a Laptop — Fast CPU Receipt OCR & 12-Line Y-Coordinate Row Sorter.
Demonstrates why 80-second Vision LLMs on CPU are obsolete and how a sub-second ONNX OCR pass
coupled with geometric row alignment solves tilted receipts for $0.00/mo API fees.
"""

from pathlib import Path
import sys
import cv2
import pandas as pd
from PIL import Image
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.ledger_tools import format_money
from core.database import save_extraction, fetch_all_line_items_flat
from ep03_fast_cpu_ocr.ocr_pipeline import (
    draw_ocr_debug_overlay,
    extract_naive_unsorted_ocr,
    get_ocr_engine,
    preprocess_receipt_image,
    process_receipt_image_to_erp,
    sort_ocr_boxes_into_rows,
)

IMG_DIR = Path(__file__).resolve().parent.parent / "data" / "samples_ep3_images"

st.set_page_config(
    page_title="Receipt OCR — Zero-Cloud ERP Engine",
    layout="wide",
)

st.title("📸 Zero-Cloud ERP Engine (Part 3: 20x Faster Receipt OCR on Pure CPU)")
st.caption(
    "**100% Offline Business Automation** • Two-Stage Pipeline: `RapidOCR (ONNX CPU)` + "
    "`12-Line Y-Coordinate Sorter` + `qwen2.5:3b` • `$0.00/mo API Fees`"
)

samples = {
    "Fastenal Industrial Supply (Tilted -2.1° Thermal Receipt)": IMG_DIR / "tilted_fastenal_receipt.png",
}

col_left, col_right = st.columns([1, 1])

with col_left:
    st.subheader("📥 1. Select or Upload Field Receipt Photo")
    selected_name = st.selectbox("Choose Receipt Sample:", list(samples.keys()) + ["Upload Custom Image..."])

    if selected_name == "Upload Custom Image...":
        uploaded_file = st.file_uploader("Upload Receipt Image:", type=["png", "jpg", "jpeg"])
        if uploaded_file is not None:
            custom_path = IMG_DIR / f"uploaded_{uploaded_file.name}"
            custom_path.write_bytes(uploaded_file.get_buffer())
            current_image = custom_path
        else:
            current_image = samples["Fastenal Industrial Supply (Tilted -2.1° Thermal Receipt)"]
    else:
        current_image = samples[selected_name]

    st.image(str(current_image), caption=f"Field Receipt: {current_image.name}", use_container_width=True)

    c1, c2, c3 = st.columns(3)
    run_naive = c1.button("💥 Run Naive Top-Down OCR", use_container_width=True)
    run_xray = c2.button("🔬 Visual Y-Center X-Ray", use_container_width=True)
    run_engine = c3.button("🛡️ Run Zero-Cloud ERP", type="primary", use_container_width=True)

with col_right:
    st.subheader("⚙️ 2. Geometric Alignment & Layer 2 ERP Verification")

    if run_naive:
        st.markdown("#### ❌ Standard Top-to-Bottom Unsorted OCR Output")
        engine = get_ocr_engine()
        preprocessed = preprocess_receipt_image(current_image)
        raw_boxes, _ = engine(preprocessed)
        naive_text = extract_naive_unsorted_ocr(raw_boxes)
        st.code(naive_text, language="text")
        st.error(
            "🚨 CRITICAL FAILURE MODE: Notice how the slight 2-degree paper tilt broke table integrity! "
            "Because sorting strictly by top-Y processes bounding boxes in top-to-bottom sequence, "
            "quantities, item descriptions, and line totals are scattered across disjoint lines. "
            "Passing this broken sequence to an LLM causes severe field hallucination!"
        )

    elif run_xray:
        st.markdown("#### 🔬 Visual Y-Center Geometry X-Ray (12-Line Row Sorter)")
        engine = get_ocr_engine()
        preprocessed = preprocess_receipt_image(current_image)
        raw_boxes, _ = engine(preprocessed)
        debug_img = IMG_DIR / "temp_ocr_debug_overlay.png"
        draw_ocr_debug_overlay(current_image, raw_boxes, out_path=debug_img)

        if debug_img.exists():
            st.image(
                str(debug_img),
                caption="Visual X-Ray: Green Boxes (RapidOCR ONNX), Red Dots (Y-Centers), Cyan Lines (Grouped Table Rows)",
                use_container_width=True,
            )

        st.info(
            "💡 How it works: For every bounding box, we compute `Y_center = sum(y)/4.0`. "
            "Boxes within `y_tolerance_px = 24.0` are grouped into the same row and sorted left-to-right by `x_left`. "
            "This deterministically neutralizes tilts up to 10° in under 2 milliseconds!"
        )

    elif run_engine:
        st.markdown("#### 🛡️ Two-Stage Sovereign ERP Pipeline Live Run")
        with st.spinner("Processing receipt with RapidOCR (ONNX CPU) + Qwen 2.5 3B..."):
            aligned_text, po, metrics = process_receipt_image_to_erp(current_image)

            # Save to SQLite ledger with idempotency
            po_id = save_extraction(
                po=po,
                source_type="ep03_image_ocr",
                source_name=current_image.name,
                raw_content=current_image.read_bytes(),
                wall_time_ms=metrics["total_pipeline_ms"],
            )

        # Performance Comparison Gauges
        st.markdown("### ⚡ Hardware Performance Benchmark (Pure CPU)")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Stage 1 (RapidOCR ONNX)", f"{metrics['ocr_duration_ms']} ms", "Sub-second")
        m2.metric("Stage 2 (Qwen 3B LLM)", f"{metrics['wall_time_ms']} ms", f"{metrics['tokens_per_sec']} tok/s")
        m3.metric("Total End-to-End", f"{metrics['total_pipeline_ms']} ms", "Pure CPU")
        m4.metric("Vs Vision LLM (84.2s)", "20x FASTER", "Zero Cloud / $0.00", delta_color="normal")

        st.markdown("#### 📋 Reconstructed Horizontal Rows (Fed into LLM):")
        st.code(aligned_text, language="markdown")

        st.markdown("#### 🛡️ Layer 2 Pydantic Validation & Audit Status:")
        if po.needs_human_review:
            st.warning(f"⚠️ **NEEDS HUMAN REVIEW** — Quarantine triggered for PO ID #{po_id}")
            for r in po.review_reasons:
                st.write(f"- {r}")
        else:
            st.success(f"✅ **AUTO-APPROVED** — Order successfully committed to SQLite Ledger (PO ID #{po_id})")

        # Line items dataframe
        if po.items:
            items_data = [
                {
                    "Item Name": it.item_name,
                    "SKU / Part No": it.sku_or_part_no or "—",
                    "Qty": it.quantity,
                    f"Unit Price ({po.currency})": format_money(it.unit_price, po.currency),
                    f"Line Total ({po.currency})": format_money(it.line_total, po.currency),
                }
                for it in po.items
            ]
            st.dataframe(pd.DataFrame(items_data), use_container_width=True)

        st.caption(f"**Vendor:** {po.vendor_name} | **Job/PO:** {po.job_or_po_number} | **Total:** {format_money(po.stated_total, po.currency)}")

# SQLite Live Ledger Table
st.divider()
st.subheader("📊 Live Local SQLite Accounting Ledger (`data/erp_procurement.db`)")
try:
    rows = fetch_all_line_items_flat()
    if rows:
        df_ledger = pd.DataFrame(rows)
        st.dataframe(df_ledger.tail(10), use_container_width=True, hide_index=True)
    else:
        st.info("Ledger is currently empty. Run an extraction above to populate rows.")
except Exception as e:
    st.warning(f"Could not read SQLite database: {e}")
