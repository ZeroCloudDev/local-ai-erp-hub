# Zero-Cloud ERP Engine on a Laptop (Local AI + Python)

Deterministic, **100% offline business automation pipeline** that turns messy field texts, multi-column B2B PDF invoices, and crooked phone receipt photos into strictly validated SQLite & Accounting CSV rows — running on a **standard laptop CPU** (tested on AMD Ryzen 7 PRO 7840U, zero cloud fees, zero OpenAI API keys).

> 📖 **Looking for in-depth source code explanations?**
> Because source file line numbers are strictly locked to match the recorded YouTube video series, complete architectural and module explanations are documented in **[CODE_WALKTHROUGH.md](./CODE_WALKTHROUGH.md)** without displacing any source lines.

> 🧾 **Season 1 ERRATA (measured 2026-10-23 to 26):** what works, what breaks and what you still have to build yourself is in **[ERRATA.md](./ERRATA.md)**. In that test the series model `qwen2.5:3b` approved one wrong row and is non-commercial; `granite4:3b` (Apache-2.0) passed every rule. The episode code is unchanged; the benchmark is in [`benchmarks/`](./benchmarks/).

---

## ⚡ Fast Track: Run the Experiment in 60 Seconds

### Option A: One-Line PowerShell Command (Git Users)
Open Windows PowerShell, paste this single line, and press Enter:
```powershell
git clone https://github.com/ZeroCloudDev/local-ai-erp-hub.git ; cd local-ai-erp-hub ; powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

### Option B: Download ZIP & Double-Click (No Git Required)
1. Click the green **Code** button at the top right of this GitHub page → **Download ZIP**.
2. Extract the ZIP archive to your Desktop or working folder.
3. Double-click **`run.bat`** in the extracted folder.
   *(Automatically bootstraps the environment, pulls the 1.9 GB model, and opens an interactive menu to launch any episode immediately)*.

### Option C: Linux & macOS (Bash)
```bash
git clone https://github.com/ZeroCloudDev/local-ai-erp-hub.git
cd local-ai-erp-hub
chmod +x setup.sh && ./setup.sh
```

---

## 🎯 Series Architecture: *"Zero-Cloud ERP Engine on a Laptop"*

Most AI tutorials stop at toy chatbots or fragile regex prompts that hallucinate financial numbers. This repository builds a **single modular back-office ingestion engine (`core/`)** across 5 progressive modules (4 core video episodes + 1 extended Capstone Fiscal Robot):

| Episode | Folder | Title & Focus | Business Problem Solved | Engineering Architecture |
| :--- | :--- | :--- | :--- | :--- |
| **Ep 01** | [`ep01_structured_text/`](ep01_structured_text/) | **Part 1: Deterministic Local AI Schema Lock** | Field technicians send messy SMS/WhatsApp expense notes with missing prices or wrong totals | **Two-Layer Defense**: Ollama C++ GBNF Grammar Mask (`SkipJsonSchema`) + Deterministic Pydantic Math & Null Audit |
| **Ep 02** | [`ep02_pdf_tables/`](ep02_pdf_tables/) | **Part 2: Visual X-Ray for Multi-Column PDF Invoices** | Standard `pypdf` destroys B2B vendor tables (Mouser, DigiKey) and merges prices with part numbers | **Visual Table X-Ray**: `pymupdf4llm` vector grids + `pdfplumber` whitespace cell projection → Shared Core Engine |
| **Ep 03** | [`ep03_fast_cpu_ocr/`](ep03_fast_cpu_ocr/) | **Part 3: 10x Faster Receipt OCR Pipeline on CPU** | Local 11B Vision LLMs take 80+ seconds per receipt photo on a laptop CPU and mix up tilted rows | **Two-Stage CPU Pipeline**: `RapidOCR` (ONNX, `435 ms`) + **12-Line Y-Coordinate Row Sorter** → `qwen2.5:3b` |
| **Ep 04** | [`ep04_watchdog_daemon/`](ep04_watchdog_daemon/) | **Part 4: Autonomous Watch-Folder Back-Office Robot** | Office staff don't want to click upload buttons 50 times a day in a web UI | **Zero-Click File Daemon (`watchdog`)**: Auto-routes `.txt`, `.pdf`, and `.png`, enforces SHA-256 deduplication, sorts into `approved/` vs `quarantine_review/` |
| **Ep 05** | [`ep05_fiscal_ingest_robot/`](ep05_fiscal_ingest_robot/) | **Part 5: Local Document Intake into a Real POS Table Structure** | Store staff retype items and prices from messages, price lists and paper sheets into the POS | **Concrete MySQL/MariaDB POS adapter example**: EP01–EP04 → validation → transactional write into `artikli` + `artcjenik` → quarantine → operator CLI, proven with SQL on a local test database |

---

## 🏗️ Repository Structure (70% Shared Core)

```text
local_ai_erp_hub/
├── core/                         # Shared core engine used across all episodes
│   ├── schemas.py                # Pydantic v2 models + Layer 2 arithmetic & completeness audit
│   ├── llm_client.py             # Ollama auto-starter + C++ GBNF structured output + telemetry
│   └── database.py               # SQLite idempotent ledger (SHA-256 hash) + flat accounting export
├── data/                         # Reproducible generators & synthetically generated test samples
│   ├── generate_test_assets.py   # Generates Mouser/DigiKey PDFs, X-Ray PNGs, and tilted receipts
│   ├── generate_studio_visuals.py# Renders 1920x1080 thumbnails & architecture slides
│   ├── samples_ep1_text/         # 5 chaotic field technician messages & traps
│   ├── samples_ep2_pdf/          # Bordered & borderless B2B PDF invoices + X-Ray debug image
│   ├── samples_ep3_images/       # Tilted thermal receipt photo (-2.1 deg)
│   ├── incoming_watch/           # Drop-folder for Episode 4 autonomous daemon
│   └── processed_watch/          # Auto-sorted `approved/` and `quarantine_review/` folders
├── ep01_structured_text/         # Part 1: CLI Benchmark + Streamlit Accounting Dashboard
├── ep02_pdf_tables/              # Part 2: PDF Table X-Ray Parser + CLI Demo
├── ep03_fast_cpu_ocr/            # Part 3: Sub-Second CPU OCR + 12-Line Y-Row Sorter + CLI Demo
├── ep04_watchdog_daemon/         # Part 4: Zero-UI Watch-Folder Service
├── ep05_fiscal_ingest_robot/     # Ep 05: POS adapter example (MySQL/MariaDB test DB, quarantine CLI)
├── run.bat                       # Double-click zero-config launcher (Windows Batch)
├── setup.ps1                     # Interactive one-click installer & launcher (Windows PowerShell)
├── setup.sh                      # One-click automated setup script (Linux & macOS)
├── CODE_WALKTHROUGH.md           # In-depth architectural guide (preserves source line numbers)
├── LICENSE                       # MIT License
└── requirements.txt              # Locked dependencies for all episodes
```

---

## 📋 System Requirements & Prerequisites

This project is engineered to run on **standard consumer hardware** with zero external cloud dependencies.

| Prerequisite | Minimum Required | Recommended | Official Download Link |
| :--- | :--- | :--- | :--- |
| **Operating System** | Windows 10/11, Ubuntu 22.04+, or macOS 12+ | Windows 11 (PowerShell 7 or 5.1) | — |
| **Python** | Python `3.10` – `3.12` (3.13+ not yet supported by `rapidocr-onnxruntime`) | Python `3.12` | [python.org/downloads](https://www.python.org/downloads/) *(⚠️ Check "Add Python to PATH")* |
| **Local LLM Engine** | Ollama CLI & background daemon | Latest Ollama release | [ollama.com/download](https://ollama.com/download) |
| **Git** | Git 2.30+ *(Optional if using ZIP)* | Latest Git SCM | [git-scm.com](https://git-scm.com/) |
| **Hardware** | 4-Core CPU, 8 GB RAM | 8-Core CPU (e.g. AMD Ryzen 7 / Intel Core i7), 16 GB RAM | **Zero GPU required** (runs 100% on CPU) |

> [!NOTE]
> The default local model used is [`qwen2.5:3b`](https://ollama.com/library/qwen2.5), which occupies **~1.9 GB of disk space** and consumes only **~2.2 GB of system RAM** during inference, delivering 15–20 tokens/second on a standard laptop CPU.

---

## 🔍 Visual Proof: Input → Deterministic ERP Output

Here is what happens when a messy field technician message is processed by our two-layer defense pipeline:

### Scenario 1: Clean Match → Auto-Approved
```text
INPUT (SMS):
"Hey Sarah, picked up parts from Home Depot for Job #402: 12x Eaton 20A Circuit Breakers
(SKU: BR120) at $14.50 each (line total $174.00) and 4x Square D Junction Boxes
at $8.25 each (line total $33.00). Total on receipt is $207.00."

STATUS: ✅ AUTO-APPROVED
JSON OUTPUT:
{
  "vendor_name": "Home Depot",
  "job_or_po_number": "402",
  "items": [
    {"item_name": "Eaton 20A Circuit Breakers", "sku_or_part_no": "BR120", "quantity": 12.0, "unit_price": 14.50, "line_total": 174.00},
    {"item_name": "Square D Junction Boxes", "sku_or_part_no": null, "quantity": 4.0, "unit_price": 8.25, "line_total": 33.00}
  ],
  "stated_total": 207.00,
  "needs_human_review": false,
  "review_reasons": []
}
```

### Scenario 4: 35 USD Arithmetic Mismatch Trap → Quarantined
```text
INPUT (SMS):
"Bought from Grainger for Job #512: 5x Industrial DIN Rail Power Supplies 24V (SKU: SDR-120-24)
at $45.00 each, line total $225.00. Also 2x Omron Relays at $15.00 each, line total $30.00.
Overall invoice total written at bottom is $290.00."

STATUS: ⚠️ NEEDS HUMAN REVIEW (Quarantined)
REVIEW REASONS:
[
  "Invoice total mismatch: sum of lines is 255.00, but stated_total is 290.00 (difference may be tax/shipping or OCR error)."
]
```

---

## ⚡ Manual PowerShell Commands (Episode by Episode)

If you prefer running individual episode scripts directly:

```powershell
# 1. Run Part 1 CLI Benchmark (5 field messages -> SQLite)
.\.venv\Scripts\python.exe ep01_structured_text\cli_demo.py

# 2. Launch Part 1 Accounting Dashboard (http://127.0.0.1:8501)
.\.venv\Scripts\streamlit.exe run ep01_structured_text\app_streamlit.py

# 3. Run Part 2 B2B PDF Table X-Ray Demo
.\.venv\Scripts\python.exe ep02_pdf_tables\cli_demo.py

# 4. Run Part 3 Tilted Receipt CPU OCR + Y-Sorter Demo
.\.venv\Scripts\python.exe ep03_fast_cpu_ocr\cli_demo.py

# 5. Start Part 4 Zero-Click Watchdog Daemon
.\.venv\Scripts\python.exe ep04_watchdog_daemon\watcher_service.py
```

---

## 🔧 Troubleshooting Common Scenarios

| Symptom / Error | Root Cause | Immediate Fix |
| :--- | :--- | :--- |
| **`running scripts is disabled on this system`** | Windows PowerShell execution policy blocks `.ps1` | Run via `powershell -ExecutionPolicy Bypass -File .\setup.ps1` or double-click `run.bat`. |
| **`ConnectionError: Failed to connect to Ollama`** | Ollama background daemon is closed or stopped | Run `ollama serve` in a terminal or re-run `.\setup.ps1` (it auto-starts the daemon). |
| **`ModuleNotFoundError: No module named 'core'`** | Script executed from inside subfolder (`cd ep01...`) | Always run scripts from the **repository root** (e.g. `python ep01_structured_text/cli_demo.py`). |
| **First extraction is slower than the following ones** | Cold model load from NVMe/SSD into system RAM | Normal behavior; Ollama keeps `qwen2.5:3b` warm in RAM for subsequent requests. Warm extractions took ~9–10 s per document on a ThinkPad P16s Gen 2 (Ryzen 7 PRO 7840U, CPU only), mostly spent generating the JSON answer. |
| **No module named pip inside .venv** | Python venv created with `uv` without bundled pip | Run `.\.venv\Scripts\python.exe -m ensurepip --upgrade` or re-run `.\setup.ps1`. |

---

## 🎬 YouTube Video Tutorial Companion Guide (Working Workspace)

This repository is **not just a finished demo** — it is the exact, complete **companion workspace** built step-by-step during our educational video tutorial series:
**"Zero-Cloud ERP Engine on a Laptop (Local AI + Python)"**.

```
Series Architecture & Video Episode Roadmap
══════════════════════════════════════════════════════════════════════════════════
[Episode 01]  00:00 - 11:19  Structured Text Ingestion & Deterministic Schema Lock
              ├── Video Tutorial: Episode 01 (Series Companion)
              ├── Core File:  core/schemas.py          (Layer 2 arithmetic & audit logic)
              ├── Core File:  core/llm_client.py       (Ollama C++ GBNF grammar lock)
              └── App & Demo: ep01_structured_text/    (CLI demo & Streamlit ledger)

[Episode 02]  00:00 - 12:33  Borderless PDF Tables & Markdown Visual X-Ray
              ├── Video Tutorial: Episode 02 (Series Companion)
              ├── Engine:     ep02_pdf_tables/pdf_parser.py (pymupdf4llm + pdfplumber)
              └── App & Demo: ep02_pdf_tables/app_streamlit.py (Table inspector UI)

[Episode 03]  00:00 - 09:15  10x Faster Thermal Receipt CPU OCR Pipeline
              ├── Video Tutorial: Episode 03 (Series Companion)
              ├── Engine:     ep03_fast_cpu_ocr/ocr_pipeline.py (RapidOCR + Y-sorter)
              └── App & Demo: ep03_fast_cpu_ocr/app_streamlit.py (Receipt OCR viewer)

[Episode 04]  00:00 - 10:36  Autonomous File Watcher & Quarantine Daemon
              ├── Video Tutorial: Episode 04 (Series Companion)
              ├── Service:    ep04_watchdog_daemon/watcher_service.py (Watchdog loop)
              └── App & Demo: ep04_watchdog_daemon/app_streamlit.py (Live triage UI)

[Ep 05] Local document intake into a real POS table structure (one adapter example)
              ├── Architecture: EP01 text + EP02 PDF + EP03 OCR + EP04 watch folder -> MySQL adapter
              └── Service & proof: ep05_fiscal_ingest_robot/pos_watch_service.py, verify_demo.py
══════════════════════════════════════════════════════════════════════════════════
```

For complete function-by-function explanations without changing line numbers, see **[CODE_WALKTHROUGH.md](./CODE_WALKTHROUGH.md)**.

---

## 🔒 Security, Privacy & Architectural Boundaries

* **Zero Cloud Egress:** All LLM inference occurs strictly on `localhost` (port `11434`). No customer data, vendor details, or financial totals are ever transmitted over the Internet at runtime.
* **Deterministic Audit Trail:** Every transaction is hashed via SHA-256 and assigned an explicit status (`APPROVED` vs `NEEDS HUMAN REVIEW`) with machine-readable reasons stored in SQLite.
* **No Closed-Source Lock-In:** Built on standard open-source technologies: Python, SQLite, Ollama, Pydantic, RapidOCR, and PyMuPDF.

---

---

## ⚠️ Known Limitations & Edge Cases

This system is an engineering framework designed for offline back-office ingestion, not an infallible accounting oracle. Production deployers should understand its strict architectural boundaries:

1. **Arithmetic Audit vs Semantic Correctness:** The Layer 2 Pydantic validator verifies internal mathematical consistency (`quantity * unit_price = line_total` and `sum(line_totals) == stated_total`). It flags null values, missing prices, and arithmetic mismatches. However, if an OCR/LLM misreads a vendor name or swaps two line items with identical prices, pure arithmetic checks will not detect the error. Such records must be caught by vendor reconciliation or manual audit.
2. **Model Swappability & Latency:** Benchmarks in this repository (435 ms OCR, ~19 tok/s, 2.2 GB RAM footprint) were measured specifically with `qwen2.5:3b` on an AMD Ryzen 7 PRO CPU. The extraction architecture in `core/llm_client.py` uses standard Ollama endpoints and can be swapped with other models without code changes. Swapping is not a free upgrade: in the [ERRATA](./ERRATA.md) benchmark `qwen2.5:7b` was much weaker than `qwen2.5:3b`. Run [`benchmarks/`](./benchmarks/) on your own documents before switching.
3. **Synthetic Test Data vs Public Benchmarks:** Test assets provided in `data/` were synthetically generated (using `data/generate_test_assets.py`) to systematically stress-test specific arithmetic edge cases (e.g. unpriced items, tax rounding traps, skewed thermal scans). Formal character error rate (CER) and extraction accuracy metrics on public benchmark datasets (such as SROIE or CORD) have not been formally evaluated.

---

## 🛠️ Architectural Scope & Comparison with Existing Tools

| Architectural Concern | Existing Document Ecosystems (e.g. Paperless-ngx, Docling, invoice2data) | ZeroCloud ERP Ingestion Layer |
| :--- | :--- | :--- |
| **Primary Domain** | Document management/archival (DMS) or general multi-modal layout parsing | Specialized pre-database arithmetic audit and ERP ingestion gatekeeper |
| **Format Handling** | Document indexing, OCR archiving, or rich markdown/JSON document ASTs | Format-agnostic auto-router (.txt, .pdf, .png) tailored for transaction extraction |
| **Integrity Enforcement** | Upstream document capture without relational ledger validation | Two-layer defense: C++ GBNF grammar mask + Deterministic Pydantic arithmetic audit |
| **Handling Anomalies** | Archived as document text or rejected at import | Explicit routing into `quarantine_review/` with machine-readable reasons |
| **Deployment Footprint** | Multi-container Docker stacks (Redis, Postgres, Celery, web server) | Self-contained Python process + embedded SQLite ledger (zero cloud fees) |

> *Note: These tools solve complementary problems. Paperless-ngx is an outstanding Document Management System (DMS) for enterprise archival, and Docling is an advanced layout-parsing library. ZeroCloud acts specifically as the arithmetic integrity gatekeeper between unvetted incoming field data and your production accounting database.*

## ⚖️ Third-Party Licenses & Model Notices

This repository's source code is distributed under the **MIT License**. However, production deployment uses third-party components governed by their respective licenses:

* **Qwen 2.5 3B (`qwen2.5:3b`):** Governed by the [Qwen Research License Agreement](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct/raw/main/LICENSE) (free for research and evaluation; commercial production requires an Alibaba Cloud license request). All benchmark figures in this repo (435 ms, ~19 tok/s, 2.2 GB RAM) are measured specifically on the 3B model. For Apache 2.0 commercial deployments, another model can be set in `core/llm_client.py`; see [ERRATA.md](./ERRATA.md) for which models passed the benchmark rules (`granite4:3b`, `ministral-3:8b`).
* **PyMuPDF (`fitz` / `pymupdf4llm`):** Distributed under **AGPL-3.0** (or commercial license from Artifex Software, Inc.). Note: If building a networked commercial service incorporating PyMuPDF under AGPL-3.0, you may be required to disclose source code under the same terms.
* **RapidOCR (`rapidocr_onnxruntime`):** Distributed under the **Apache-2.0** License.
* **Pydantic & SQLite:** Distributed under the **MIT** and Public Domain licenses respectively.

---

## 📄 Project License

Source code in this repository is distributed under the **MIT License**. Commercial deployment of the complete pipeline depends on third-party licenses noted above (specifically Alibaba Qwen Research License for the 3B model weights and Artifex AGPL-3.0 for PyMuPDF). See [LICENSE](./LICENSE).
