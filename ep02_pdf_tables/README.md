# Episode 2 Implementation Plan: Why Local PDF Parsers Fail on Tables (Visual X-Ray Fix)

## 1. Engineering Objective
Show why 95% of local RAG tutorials fail on B2B invoices and electronics datasheets when using `pypdf`, and solve both **bordered tables** (`pymupdf4llm`) and **borderless whitespace-aligned tables** (`pdfplumber` with visual cell X-Ray debugging) while reusing 100% of the Episode 1 `core/` engine.

## 2. Files Included
- [`pdf_parser.py`](pdf_parser.py): Implements `extract_broken_pypdf()`, `extract_clean_markdown_pymupdf()`, `extract_whitespace_table_pdfplumber()`, and `process_pdf_to_erp()`.
- [`cli_demo.py`](cli_demo.py): Benchmark script running side-by-side Mouser (bordered) vs DigiKey (borderless) extraction into SQLite.
- [`app_streamlit.py`](app_streamlit.py): Full interactive Web Dashboard with drag-and-drop PDF ingestion, live Visual X-Ray preview, Pydantic math audit, and CSV export.

## 3. Verification Commands
```powershell
# Run CLI benchmark
.\.venv\Scripts\python.exe ep02_pdf_tables\cli_demo.py

# Launch interactive Web UI
.\.venv\Scripts\streamlit.exe run ep02_pdf_tables\app_streamlit.py
```

## 4. How It Connects to Episode 1
Once the PDF table is converted into a Markdown pipe table (`| SKU | Item | Qty | Unit Price |`), it is passed directly into `core.llm_client.extract_structured_erp()` and saved via `core.database.save_extraction()`.

