"""
Episode 5 Streamlit Dashboard:
Fiscal Ingest Robot — Zero-Click POS Database Automation.
Provides a side-by-side 50/50 layout matching Episodes 1 & 2:
- Left Column: Drag & Drop Ingest Zone + Multi-Format Input Viewer (Text, PDF, Image).
- Right Column: Agentic Telemetry, Auto-Approved POS Catalog, and Inline 1-Click Quarantine Resolver.
- Bottom: Live SQLite Ledger Table with 1-Click Fiscal CSV Export.
"""

from pathlib import Path
import hashlib
import re
import shutil
import sqlite3
import sys
import pandas as pd
from PIL import Image
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.schemas import FiscalItem
from ep05_fiscal_ingest_robot.fiscal_ingest_service import (
    discover_schema,
    init_fiscal_db,
    parse_image_receipt,
    parse_pdf_catalog,
    parse_viber_text,
    commit_items_to_db,
    calculate_file_hash,
    is_file_already_processed,
)

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "erp_procurement.db"
INCOMING_DIR = BASE_DIR / "data" / "incoming_fiskal"
APPROVED_DIR = BASE_DIR / "data" / "processed_fiskal" / "approved"
QUARANTINE_DIR = BASE_DIR / "data" / "processed_fiskal" / "quarantine"

# Ensure DB & directories
init_fiscal_db()
INCOMING_DIR.mkdir(parents=True, exist_ok=True)
APPROVED_DIR.mkdir(parents=True, exist_ok=True)
QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)

st.set_page_config(
    page_title="Fiscal Ingest Robot — Zero-Cloud ERP",
    page_icon="🤖",
    layout="wide",
)

st.title("🤖 Zero-Cloud ERP Engine (Part 5: The Fiscal Ingest Robot)")
st.caption(
    "**100% Offline Business Automation** • Ingests messy Viber notes, PDF price lists, and mobile receipt photos • "
    "`SQLite Schema-Lock` + `Layer 2 Quarantine Logic` • `$0.00/mo Cloud Fees`"
)


def get_connection():
    return sqlite3.connect(str(DB_PATH))


# 50/50 Split Screen Layout matching Episodes 1, 2, and 3
col_left, col_right = st.columns([1, 1])

with col_left:
    st.subheader("📥 1. Drag & Drop Ingest & Input Viewer")

    # Sample Presets or Direct Upload
    sample_options = [
        "Viber poruka sa terena (viber_poruka.txt)",
        "B2B Veleprodajni cjenovnik (veleprodaja_cjenik.pdf)",
        "Fotografisana cedulja sa stola (papir_dopis.png)",
        "Prevuci i spusti svoj fajl (Upload custom file)...",
    ]
    selected_source = st.selectbox("Odaberi testni scenario ili ubaci svoj fajl:", sample_options)

    uploaded_file = None
    current_filepath = None
    input_type = None

    if selected_source == "Prevuci i spusti svoj fajl (Upload custom file)...":
        uploaded_file = st.file_uploader(
            "Prevuci i spusti dokument ovdje (TXT, PDF, PNG, JPG):",
            type=["txt", "pdf", "png", "jpg", "jpeg"],
        )
        if uploaded_file is not None:
            upload_dir = BASE_DIR / "data" / "fiscal_uploads"
            upload_dir.mkdir(parents=True, exist_ok=True)
            upload_hash = hashlib.sha256(uploaded_file.get_buffer()).hexdigest()
            dest_path = upload_dir / f"{upload_hash[:16]}_{Path(uploaded_file.name).name}"
            dest_path.write_bytes(uploaded_file.get_buffer())
            current_filepath = dest_path
            input_type = dest_path.suffix.lower()
    elif "viber" in selected_source.lower():
        current_filepath = INCOMING_DIR / "viber_poruka.txt"
        if not current_filepath.exists() and (APPROVED_DIR / "viber_poruka.txt").exists():
            current_filepath = APPROVED_DIR / "viber_poruka.txt"
        if not current_filepath.exists() and (QUARANTINE_DIR / "viber_poruka.txt").exists():
            current_filepath = QUARANTINE_DIR / "viber_poruka.txt"
        input_type = ".txt"
    elif "veleprodaja" in selected_source.lower():
        current_filepath = INCOMING_DIR / "veleprodaja_cjenik.pdf"
        if not current_filepath.exists() and (APPROVED_DIR / "veleprodaja_cjenik.pdf").exists():
            current_filepath = APPROVED_DIR / "veleprodaja_cjenik.pdf"
        if not current_filepath.exists() and (QUARANTINE_DIR / "veleprodaja_cjenik.pdf").exists():
            current_filepath = QUARANTINE_DIR / "veleprodaja_cjenik.pdf"
        input_type = ".pdf"
    elif "cedulja" in selected_source.lower():
        current_filepath = INCOMING_DIR / "papir_dopis.png"
        if not current_filepath.exists() and (APPROVED_DIR / "papir_dopis.png").exists():
            current_filepath = APPROVED_DIR / "papir_dopis.png"
        if not current_filepath.exists() and (QUARANTINE_DIR / "papir_dopis.png").exists():
            current_filepath = QUARANTINE_DIR / "papir_dopis.png"
        input_type = ".png"

    # Multi-Format Input Viewer
    st.markdown("#### 👁️ Preglednik Sirove Poruke / Dokumenta:")
    if current_filepath and current_filepath.exists():
        if input_type == ".txt":
            raw_text = current_filepath.read_text(encoding="utf-8", errors="ignore")
            st.info(f"📄 **Sirova poruka sa Vibera / WhatsAppa:** `{current_filepath.name}`")
            st.code(raw_text, language="text")
        elif input_type == ".pdf":
            st.info(f"📑 **B2B Veleprodajni PDF Cjenovnik:** `{current_filepath.name}`")
            # PDF preview visual
            st.code(f"[PDF dokument spreman za ekstrakciju: {current_filepath.name}]", language="text")
        elif input_type in [".png", ".jpg", ".jpeg"]:
            st.info(f"📸 **Fotografisana cedulja / nakošeni papir:** `{current_filepath.name}`")
            st.image(str(current_filepath), caption="Fizički račun sa terena", use_container_width=True)
    else:
        st.warning("Odabrana datoteka trenutno nije u folderu incoming_fiskal.")

    # Action Trigger Buttons
    c_btn1, c_btn2 = st.columns(2)
    run_ingest = c_btn1.button("🚀 Ingest & Process (Zero-Cloud Engine)", type="primary", use_container_width=True)
    reset_files = c_btn2.button("🔄 Resetuj testne fajlove u folder", use_container_width=True)

    if reset_files:
        # Restore samples into incoming_fiskal
        for src_dir in [APPROVED_DIR, QUARANTINE_DIR]:
            for f in src_dir.iterdir():
                if f.is_file():
                    shutil.copy(str(f), str(INCOMING_DIR / f.name))
        st.success("Testni fajlovi vraćeni u `data/incoming_fiskal/`!")
        st.rerun()

with col_right:
    st.subheader("⚙️ 2. Agentic Parser & Live Quarantine Gate")

    if run_ingest and current_filepath and current_filepath.exists():
        with st.spinner("Lokalni agent parsira dokument i provjerava integritet baze..."):
            items = []
            if input_type == ".txt":
                items = parse_viber_text(current_filepath.read_text(encoding="utf-8-sig", errors="replace"), current_filepath.name)
            elif input_type == ".pdf":
                items = parse_pdf_catalog(current_filepath)
            elif input_type in [".png", ".jpg", ".jpeg"]:
                items = parse_image_receipt(current_filepath)

            if not items:
                items = [FiscalItem(naziv=f"Prazna ekstrakcija: {current_filepath.name}", cijena_sa_pdv=None,
                                    status_validacije="QUARANTINE_EMPTY_EXTRACTION",
                                    razlog_karantina="Dokument nema prepoznatih artikala; potreban je pregled izvora.")]
            document_hash = calculate_file_hash(current_filepath)
            already_processed = is_file_already_processed(document_hash)
            approved_num, quar_num = commit_items_to_db(items, current_filepath.name, document_hash)

        # Telemetry Gauges
        m1, m2, m3 = st.columns(3)
        m1.metric("Izvučeno stavki", f"{len(items)}", "Ukupno detektovano")
        m2.metric("Odobreno u kasu", f"{approved_num}", "Validirano", delta_color="normal")
        m3.metric("Karantin", f"{quar_num}", "Nedostaje cijena", delta_color="inverse")

        if already_processed:
            st.info("Dokument je već evidentiran. Nisu dodani dupli artikli; postojeći rezultat je u bazi i karantinu ispod.")
        elif quar_num > 0:
            st.error(
                f"🚨 **KARANTIN AKTIVIRAN ({quar_num} spornih stavki):** "
                "Potrebna je provjera cijene, valute, poreske stope ili sadržaja dokumenta. "
                "Ove stavke su izolovane ispod kako ne bi narušile integritet baze fiskalnog sistema."
            )
        else:
            st.success(f"✅ **SVE STAVKE ODOBRENE:** Svih {approved_num} artikala upisano je direktno u bazu kase!")

    # Interactive Inline Quarantine Resolver
    conn = get_connection()
    try:
        df_quar_live = pd.read_sql_query("SELECT * FROM fiscal_quarantine ORDER BY id DESC", conn)
    except Exception:
        df_quar_live = pd.DataFrame()
    conn.close()

    if not df_quar_live.empty:
        st.markdown("#### ⚠️ Karantin na čekanju (Rješavanje u 1 klik):")
        for idx, row in df_quar_live.iterrows():
            with st.container(border=True):
                qc1, qc2, qc3 = st.columns([3, 2, 2])
                qc1.markdown(f"**Naziv artikla:** `{row['naziv']}`")
                qc1.caption(f"Razlog: **{row['razlog_karantina']}** | Izvor: `{row.get('source_doc', '—')}`")
                empty_document = str(row['naziv']).startswith(("Empty extraction:", "Prazna ekstrakcija:"))
                missing_name = "missing" in str(row['razlog_karantina']).lower() and "description" in str(row['razlog_karantina']).lower()
                resolved_name = qc1.text_input("Provjereni naziv artikla:", value="" if missing_name or empty_document else str(row['naziv']), key=f"inline_name_{row['id']}").strip()
                if empty_document:
                    qc1.info("Dokument nema prepoznatih artikala. Pregledaj izvor i ponovo ubaci čitljiv ili ispravljen dokument.")

                new_mpc = qc2.number_input(
                    "Upiši MPC cijenu (KM):",
                    min_value=0.01,
                    value=None,
                    step=0.01,
                    key=f"inline_mpc_{row['id']}",
                )

                selected_tax = qc2.selectbox("Potvrdi PDV stopu:", ["17%", "0%"], key=f"inline_tax_{row['id']}")
                qc2.caption("Unesi provjerenu cijenu u KM; strani iznos prethodno preračunaj i provjeri.")
                if qc3.button("✅ Odobri i Upisi", key=f"inline_btn_{row['id']}", type="primary", disabled=new_mpc is None or not resolved_name or empty_document):
                    resolved = FiscalItem(naziv=resolved_name, cijena_sa_pdv=new_mpc, porezna_stopa=selected_tax)
                    conn = get_connection()
                    cur = conn.cursor()
                    cur.execute("BEGIN IMMEDIATE")
                    if cur.execute("SELECT 1 FROM fiscal_quarantine WHERE id = ?", (int(row["id"]),)).fetchone() is None:
                        conn.close()
                        st.info("Drugi prozor je već riješio ovu stavku.")
                        st.rerun()
                    cur.execute(
                        """
                        INSERT INTO fiscal_items (sifra, barkod, naziv, jedinica_mjere, porezna_stopa, cijena_sa_pdv, cijena_bez_pdv, source_doc)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (row.get("sifra"), row.get("barkod"), resolved_name, row.get("jedinica_mjere", "kom"), selected_tax,
                         resolved.cijena_sa_pdv, resolved.cijena_bez_pdv, f"Resolved ({row.get('source_doc', '')})"),
                    )
                    cur.execute("DELETE FROM fiscal_quarantine WHERE id = ?", (int(row["id"]),))
                    conn.commit()
                    conn.close()
                    st.success(f"Artikal '{row['naziv']}' uspješno upisan u bazu kase!")
                    st.rerun()
    else:
        st.info("🎉 Nema artikala u karantinu. Sve stavke su odobrene.")

# Bottom Section: Live SQLite Ledger Table with CSV POS Export
st.divider()
st.subheader("📊 Live Baza Fiskalnog Sistema (`fiscal_items` u `data/erp_procurement.db`)")

conn = get_connection()
try:
    df_ledger = pd.read_sql_query("SELECT * FROM fiscal_items ORDER BY id DESC", conn)
except Exception:
    df_ledger = pd.DataFrame()
conn.close()

if not df_ledger.empty:
    cols_to_show = [c for c in ["id", "sifra", "barkod", "naziv", "jedinica_mjere", "porezna_stopa", "cijena_sa_pdv", "source_doc", "created_at"] if c in df_ledger.columns]
    st.dataframe(df_ledger[cols_to_show].head(15), use_container_width=True)

    c_csv, c_clear = st.columns([2, 1])
    csv_bytes = df_ledger[cols_to_show].to_csv(index=False, sep=";").encode("utf-8")
    c_csv.download_button(
        label="📥 Preuzmi Fiskalni CSV (1-Click Import u Fiskalnu Kasu)",
        data=csv_bytes,
        file_name="fiskalni_artikli_export.csv",
        mime="text/csv",
        type="primary",
        use_container_width=True,
    )

    if c_clear.button("🗑️ Očisti testnu bazu artikala", use_container_width=True):
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM fiscal_items;")
        cur.execute("DELETE FROM fiscal_quarantine;")
        cur.execute("DELETE FROM processed_fiscal_files;")
        conn.commit()
        conn.close()
        st.success("Testna baza očišćena!")
        st.rerun()
else:
    st.info("Baza je trenutno prazna. Pokrenite obradu fajlova iznad.")
