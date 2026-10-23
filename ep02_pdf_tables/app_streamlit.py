"""
Episode 2 Streamlit Dashboard:
Zero-Cloud ERP Engine on a Laptop — Multi-Column PDF Invoices & Visual X-Ray Debugger.
Demonstrates why standard `pypdf` destroys vendor tables (Mouser, DigiKey) and how
our Dual-Strategy PDF Adapter (`pymupdf4llm` + `pdfplumber` Visual X-Ray) feeds clean Markdown
directly into our shared Episode 1 Core Engine (`core/llm_client.py` + `core/schemas.py`).
"""

from pathlib import Path
import sys
import pandas as pd
import fitz  # PyMuPDF
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.database import save_extraction, fetch_all_line_items_flat
from ep02_pdf_tables.pdf_parser import (
    extract_broken_pypdf,
    extract_clean_markdown_pymupdf,
    extract_whitespace_table_pdfplumber,
    process_pdf_to_erp,
)

PDF_DIR = Path(__file__).resolve().parent.parent / "data" / "samples_ep2_pdf"

st.set_page_config(
    page_title="PDF Table X-Ray — Zero-Cloud ERP Engine",
    layout="wide",
)

st.title("📑 Zero-Cloud ERP Engine (Part 2: Visual Table X-Ray for PDF Invoices)")
st.caption(
    "**100% Offline Business Automation** • Dual Adapter: `pymupdf4llm` + `pdfplumber` X-Ray • "
    "Engine: `qwen2.5:3b` on CPU • `$0.00/mo API Fees`"
)

# Invoice Presets
samples = {
    "Mouser Electronics (Bordered B2B Commercial Invoice)": PDF_DIR / "mouser_bordered_invoice.pdf",
    "DigiKey Electronics (Borderless Whitespace Invoice)": PDF_DIR / "digikey_borderless_invoice.pdf",
}

col_left, col_right = st.columns([1, 1])

with col_left:
    st.subheader("📥 1. Select or Upload B2B PDF Invoice")
    selected_name = st.selectbox("Choose Invoice Sample:", list(samples.keys()) + ["Upload Custom PDF..."])
    
    if selected_name == "Upload Custom PDF...":
        uploaded_file = st.file_uploader("Upload PDF Document:", type=["pdf"])
        if uploaded_file is not None:
            custom_path = PDF_DIR / f"uploaded_{uploaded_file.name}"
            custom_path.write_bytes(uploaded_file.get_buffer())
            current_pdf = custom_path
        else:
            current_pdf = samples["Mouser Electronics (Bordered B2B Commercial Invoice)"]
    else:
        current_pdf = samples[selected_name]

    # Render PDF first page to visual image
    try:
        doc = fitz.open(str(current_pdf))
        pix = doc[0].get_pixmap(dpi=130)
        img_bytes = pix.tobytes("png")
        doc.close()
        st.image(img_bytes, caption=f"PDF Preview: {current_pdf.name} (Page 1)", use_container_width=True)
    except Exception as e:
        st.warning(f"Could not render PDF preview: {e}")

    c1, c2, c3 = st.columns(3)
    run_broken = c1.button("💥 Run Broken pypdf", use_container_width=True)
    run_xray = c2.button("🔬 Visual X-Ray", use_container_width=True)
    run_engine = c3.button("🛡️ Run ERP Engine", type="primary", use_container_width=True)

with col_right:
    st.subheader("⚙️ 2. Table Geometry & Layer 2 ERP Verification")

    if run_broken:
        st.markdown("#### ❌ Standard `pypdf.extract_text()` Output")
        raw_broken = extract_broken_pypdf(current_pdf)
        st.code(raw_broken, language="text")
        st.error(
            "🚨 FAILURE MODE: Notice how column alignment is completely lost. "
            "SKUs, component descriptions, quantities, and prices smash into single strings. "
            "Feeding this to a 3B model causes silent quantity hallucinations or missing price errors!"
        )

    elif run_xray:
        st.markdown("#### 🔬 `pdfplumber` Visual Cell X-Ray (Invisible Column Projection)")
        debug_png = PDF_DIR / "temp_xray_preview.png"
        extract_whitespace_table_pdfplumber(current_pdf, debug_image_out=debug_png)
        if debug_png.exists():
            st.image(str(debug_png), caption="Visual X-Ray: Virtual Cell Bounding Boxes Cast Across Whitespace Gutters", use_container_width=True)
        st.info(
            "💡 How it works: When invoices have zero vertical grid lines, the engine inspects character bounding boxes, "
            "identifies column gaps, and projects virtual cell grids in < 250 milliseconds."
        )

    elif run_engine:
        with st.spinner("Processing PDF -> Markdown Table -> Qwen 2.5 3B -> Pydantic Layer 2 Audit..."):
            md_text, po, metrics = process_pdf_to_erp(current_pdf)
            po_id = save_extraction(
                po=po,
                source_type="ep02_pdf_tables",
                source_name=current_pdf.name,
                raw_content=current_pdf.read_bytes(),
                wall_time_ms=metrics["wall_time_ms"],
            )

        st.markdown(f"#### 📄 Clean Markdown Table Passed to LLM ({metrics['wall_time_ms']} ms | {metrics['tokens_per_sec']} tok/s)")
        st.code(md_text, language="markdown")

        if po.needs_human_review:
            st.error(f"⚠️ QUARANTINED FOR HUMAN REVIEW (DB Record #{po_id})")
            for reason in po.review_reasons:
                st.markdown(f"- 🔴 **{reason}**")
        else:
            st.success(f"✅ AUTO-APPROVED & COMMITTED TO SQLITE ERP (DB Record #{po_id})")

        st.json(po.model_dump())

st.divider()

# Bottom Section: Relational SQLite Ledger Viewer
st.subheader("🗄️ 3. Live Idempotent SQLite ERP Ledger (`data/erp_procurement.db`)")
try:
    rows = fetch_all_line_items_flat()
    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)
        csv_data = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Export Ledger to Accounting CSV (QuickBooks / Excel)",
            data=csv_data,
            file_name="accounting_erp_export.csv",
            mime="text/csv",
        )
    else:
        st.info("SQLite database is initialized but currently empty. Run an extraction above to populate rows.")
except Exception as exc:
    st.warning(f"Could not load SQLite ledger: {exc}")
