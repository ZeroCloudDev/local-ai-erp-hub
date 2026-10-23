"""
Episode 1 Streamlit Dashboard:
Zero-Cloud ERP Engine on a Laptop — Field Expense & Procurement Ingestion.
Demonstrates why naive LLM prompts crash production accounting pipelines (`JSONDecodeError` / hallucinated prices)
and how our Two-Layer Defense (Ollama C++ GBNF + Pydantic Math Audit) produces clean SQLite & CSV records.
"""

import json
from pathlib import Path
import sys
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.llm_client import (
    extract_naive_unstructured,
    extract_structured_erp,
)
from core.database import save_extraction, fetch_all_line_items_flat
from core.ledger_tools import format_approved_spend
SAMPLES_FILE = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "samples_ep1_text"
    / "chaotic_messages.json"
)

st.set_page_config(
    page_title="Zero-Cloud ERP Engine (Local CPU)",
    layout="wide",
)

st.title("🏢 Zero-Cloud ERP Engine on a Laptop — Field Expense & Invoice Ingestion")
st.caption(
    "**100% Offline Business Automation** • Engine: `qwen2.5:3b` on AMD Ryzen 7 PRO 7840U CPU • `$0.00/mo API Fees`"
)

samples = json.loads(SAMPLES_FILE.read_text(encoding="utf-8"))
sample_titles = [s["title"] for s in samples]

col_left, col_right = st.columns([1, 1])

with col_left:
    st.subheader("📥 1. Incoming Field Purchase / Receipt Text")
    selected_title = st.selectbox("Select Real-World Field Scenario:", sample_titles)
    selected_sample = next(s for s in samples if s["title"] == selected_title)
    raw_input = st.text_area(
        "Raw Employee / Vendor Input (SMS, WhatsApp, Voice Note, Email):",
        value=selected_sample["text"],
        height=135,
    )

    c1, c2 = st.columns(2)
    run_naive = c1.button(
        "💥 Run Naive LLM Prompt (Unsafe)", use_container_width=True
    )
    run_strict = c2.button(
        "🛡️ Run Zero-Cloud ERP Engine (2-Layer Defense)",
        type="primary",
        use_container_width=True,
    )

with col_right:
    st.subheader("⚙️ 2. Extraction & Deterministic Accounting Audit")
    if run_naive:
        with st.spinner("Running unstructured 3B LLM prompt..."):
            raw_out, metrics = extract_naive_unstructured(raw_input)
        st.warning(
            f"Unstructured LLM Output ({metrics['wall_time_ms']} ms | {metrics['tokens_per_sec']} tok/s)"
        )
        st.code(raw_out, language="markdown")
        try:
            json.loads(raw_out)
            st.error(
                "⚠️ FINANCIAL RISK: No Pydantic validation! Missing Job/SKU fields or silent price hallucinations can enter ERP."
            )
        except Exception as exc:
            st.error(
                f"❌ PRODUCTION PIPELINE CRASH (`json.loads` failed): `{type(exc).__name__}: {exc}`"
            )

    if run_strict:
        with st.spinner("Enforcing C++ Grammar Lock + Layer 2 Pydantic Math Audit..."):
            po, metrics = extract_structured_erp(raw_input)
            save_extraction(
                po=po,
                source_type="ep01_text",
                source_name=selected_sample["source_name"],
                raw_content=raw_input,
                wall_time_ms=metrics["wall_time_ms"],
            )

        if po.needs_human_review:
            st.error(
                f"⚠️ QUARANTINED FOR HUMAN REVIEW ({metrics['wall_time_ms']} ms | {metrics['tokens_per_sec']} tok/s)"
            )
            for reason in po.review_reasons:
                st.markdown(f"- **Audit Trigger:** `{reason}`")
        else:
            st.success(
                f"✅ AUTO-APPROVED & POSTED TO ERP ({metrics['wall_time_ms']} ms | {metrics['tokens_per_sec']} tok/s)"
            )

        st.json(po.model_dump())

st.divider()
st.subheader("🗄️ 3. Live Local SQLite Accounting Ledger (`erp_procurement.db`)")
rows = fetch_all_line_items_flat()
if rows:
    df = pd.DataFrame(rows)
    total_rows = int(df["item_name"].notna().sum())
    status_col = "audit_status" if "audit_status" in df.columns else ("status" if "status" in df.columns else None)
    if status_col:
        approved_df = df[df[status_col].astype(str).str.contains("APPROVED|OK", case=False, na=False)]
        review_df = df[~df[status_col].astype(str).str.contains("APPROVED|OK", case=False, na=False)]
    else:
        approved_df = df
        review_df = pd.DataFrame()
    approved_sum = format_approved_spend(approved_df.to_dict("records"))

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Line Items", total_rows)
    m2.metric("Auto-Approved Items", int(approved_df["item_name"].notna().sum()))
    m3.metric("Quarantined Documents", review_df["po_id"].nunique())
    m4.metric("Verified Approved Spend", approved_sum)

    st.dataframe(df, use_container_width=True)

    csv_bytes = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Export Ledger to Accounting CSV (QuickBooks / Excel)",
        data=csv_bytes,
        file_name="zero_cloud_erp_ledger.csv",
        mime="text/csv",
    )
else:
    st.info("No records in SQLite yet. Click '🛡️ Run Zero-Cloud ERP Engine' above.")
