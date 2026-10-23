# Episode 5 — Local document intake into a real POS table structure

Episode 5 connects the four previous modules into one local service that enters
articles and prices into a POS database:

| Source document | Reused module | What EP05 adds |
|---|---|---|
| messy register message (`.txt`) | **EP01** local model with grammar-locked JSON (Ollama `format=`) | a small POS line schema, **one SKU line per model call**; the SKU itself is read by a regex, never by the model |
| approved retail price update (`.pdf`) | **EP02** pdfplumber table geometry | deterministic header mapping (no model needed for a clean table) |
| phone photo of a synthetic shelf-update sheet (`.jpg`) | **EP03** OpenCV + RapidOCR + `sort_ocr_boxes_into_rows` | straightening tilted box coordinates before the row sorter; restoring spaces OCR dropped (`OatMilk64oz`) |
| drop into a folder | **EP04** watch-folder idea | readiness check, start-up scan, replay guard, archive after commit |

Then: **validation against the target structure → transactional write into
`artikli` + one selected `artcjenik` row → quarantine → operator decision → SQL proof.**

This is **one concrete adapter example** for one MySQL/MariaDB POS table
structure, tested against an independent local test database (`kasa_ep05`)
with synthetic data. It is not a universal installer for every POS, it does
not talk to a live cash register, and it does nothing related to fiscalization.
Some POS systems must be integrated through their own API or import function
instead of direct SQL.

## What makes it safe

* **The model proposes, the source decides.** Every SKU, name and price the
  model returns must be found on the same source line / PDF row / OCR row.
  A value that is not there never reaches the POS: the item is quarantined
  (SKU/name/price) or the value is discarded (tax class/unit, which then must
  come from the existing article or the item is quarantined).
* **Independent completeness check.** A plain regex lists every SKU occurrence
  in the source; an occurrence the extractor skipped becomes
  `UNRESOLVED_EXTRACTION` instead of silently disappearing. (Limit: it cannot
  see a SKU the OCR engine itself never read.)
* **No guessing of tax class or unit.** A new article needs both from the
  source or from the approved map in the config. An existing article only gets
  a price change; tax class and unit stay as they are.
* **Identity conflicts stop.** Same SKU with a different name → review.
* **Money is `Decimal`** from the source text to `DECIMAL(18,4)`.
  `artcjenik.cijena` is `DOUBLE` in the original structure, so it is compared at
  2 decimals.
* **One transaction per document**, behind a single-row writer lock shared by
  the service and the operator CLI. Any technical error rolls back everything.
* **Replay guard:** the SHA-256 of the file is `UNIQUE`; the same bytes are never
  written twice, whatever the file name.
* **Archive after commit:** if moving the file fails, only the archiving is retried.
* **Least privilege:** `ep05_demo` has `SELECT, INSERT, UPDATE` on `kasa_ep05` only.

## Files

| File | Role |
|---|---|
| `demo_db/01_schema.sql`, `02_seed.sql`, `03_user.sql` | the five POS tables (structure only), the fictional *Maple Street Market* seed, the least-privilege user |
| `setup_demo_db.py` | runs the setup (separate from processing: DDL causes implicit commits) |
| `pos_adapter_config.example.toml` | connection, SKU range, tax/unit maps, price-list selector, test POS values — every `ADAPT HERE` |
| `adapter_config.py` | loads the config; the single definition of "the selected price-list row" |
| `catalog_candidate.py` | `CatalogCandidate` + per-field provenance |
| `source_extractors.py` | TXT / PDF / photo → candidates, anchored to the source line |
| `completeness_check.py` | independent SKU scanner |
| `pos_validation.py` | the validation rules and the INSERT / UPDATE / NO_CHANGE / QUARANTINE decision |
| `mysql_pos_adapter.py` | lock, transaction, price-list selector, audit, resolver, failure injection |
| `pos_watch_service.py` | watch folder service (and `--once` for a single file) |
| `quarantine_cli.py` | `list` / `resolve` / `reject` |
| `export_pos_csv.py` | documented example CSV export (not a universal format) |
| `snapshot_demo_state.py`, `verify_demo.py` | content-hash snapshot; PASS/FAIL against `demo_inputs/expected_results.json` |
| `make_demo_inputs.py` | regenerates the demo PDFs byte-for-byte |
| `probe_model_lines.py` | diagnostic check of the real local model on the demo lines (no database) |
| `run_ep05_rehearsal.ps1` | full rehearsal on Windows with XAMPP MariaDB + Ollama + the real photo |
| `demo_inputs/` | the synthetic documents and the expected results written before the first run |

`fiscal_ingest_service.py` and `app_streamlit.py` are the earlier prototype of
this folder and are not used by the EP05 adapter.

## Run it (Windows, XAMPP MariaDB, Ollama)

```powershell
# once
.\.venv\Scripts\python.exe -m pip install "PyMySQL>=1.1.0,<2.0.0"
$env:EP05_DB_PASSWORD = "any-local-password"      # ep05_demo user, never stored in a file
$env:EP05_ADMIN_PASSWORD = ""                       # XAMPP root (empty by default)
.\.venv\Scripts\python.exe ep05_fiscal_ingest_robot\setup_demo_db.py --reset

# service: drop files into data\ep05_incoming\
.\.venv\Scripts\python.exe ep05_fiscal_ingest_robot\pos_watch_service.py

# operator
.\.venv\Scripts\python.exe ep05_fiscal_ingest_robot\quarantine_cli.py list
.\.venv\Scripts\python.exe ep05_fiscal_ingest_robot\quarantine_cli.py resolve sku:95012 --price 3.49 --operator Eldar --confirm "price confirmed by Mike"

# proof
.\.venv\Scripts\python.exe ep05_fiscal_ingest_robot\verify_demo.py --phase after_resolution
.\.venv\Scripts\python.exe ep05_fiscal_ingest_robot\export_pos_csv.py --show
```

Full rehearsal (two runs, different document order):

```powershell
powershell -ExecutionPolicy Bypass -File ep05_fiscal_ingest_robot\run_ep05_rehearsal.ps1 -Order Normal
powershell -ExecutionPolicy Bypass -File ep05_fiscal_ingest_robot\run_ep05_rehearsal.ps1 -Order Reverse
```

The supplied `demo_inputs/shelf_tags_photo.jpg` is a phone photograph of a
displayed synthetic sheet, not proof of a printed-paper capture. Describe that
source accurately in the video. To demonstrate paper capture, print
`demo_inputs/shelf_tags_to_print.pdf`, photograph the paper, replace the JPG and
repeat both rehearsals. `tests/fixtures/ep05_simulated_shelf_photo.jpg` is a
rendered, clearly labelled **simulated** image used only by automated tests.

## Expected truth

| Phase | Articles 95001–95099 | Open quarantine |
|---|---|---|
| seed | 5 | 0 |
| after message + PDF + photo | 27 | 3 (95003 identity conflict, 95012 missing price, 95033 unknown tax class) |
| after operator sets 95012 = 3.49 | 28 | 2 |
| after the message is dropped again | 28 | 2 |
| after the injected-failure probe | 28, identical content hash | 2 |

The sales tax rate 8.25 % in `tarifa` is an invented demo value, not the rate of
any real state or city. Prices are USD before sales tax by the rule of this
test database.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_ep05*.py" -v
# destructive for kasa_ep05, opt-in:
$env:EP05_DB_TESTS = "1"; .\.venv\Scripts\python.exe -m unittest tests.test_ep05_db -v
```

The automated tests replace the model with a scripted stand-in (and make it
misbehave on purpose). The real local model is exercised only by the rehearsal.

## Owner decision — EP05 adapter scope (2026-10-22)

EP05 development stays in `ep05_fiscal_ingest_robot/`. Do not create another standalone demo application or a parallel episode project.

The published code is the adapter used in this specific POS integration example, not a universal installer for arbitrary POS software. Reuse the text, PDF, OCR and folder-processing components from Episodes 1–4. The example targets the MySQL POS structure supplied for this episode; private database contents and credentials must never be published.

Code must be well commented and self-explanatory. Explain source-to-target field mappings, business keys, price semantics, tax/unit lookups, transaction boundaries, quarantine and retry/deduplication behavior. Clearly mark configuration and mapping rules that must change for another POS. Explain why decisions exist, not just what each Python statement does. Do not claim compatibility with other POS software without a tested integration; some systems require their supported API or import mechanism.

Ship reproducible synthetic fixtures and example configuration without secrets. Final narration must describe this as one concrete adapter example. Existing recorded code references and accepted episode assets must be preserved; integration changes need to respect the repository's recorded-line checks.

## Source extraction is deliberately hybrid

The local model returns a proposal; it is not the sole authority for every
field. The adapter scans SKUs, reads explicit unit/tax columns and anchors
complete names to supported source structures. Corrections keep the raw model
answer and explain their source in the audit notes. Unknown or ambiguous
structures must remain review items. Never describe deterministic recovery as
a perfect model answer. No product-specific answer table is used.

The failure demonstration must prove three actual INSERT/UPDATE operations
inside a transaction, reaching the configured injection point, and then an
identical before/after content snapshot. A safety rollback before that point
is not a successful demonstration of rollback after three writes.
