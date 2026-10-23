# Release fixes and preservation of recorded code lines

The reference for recorded Episodes 1–4 is tag `v1.0-video`, commit `c34b9da2e9db74ed3f21ac2a5d7d92150efa7473`. The tag and existing recordings are preserved.

## What was verified about the preceding edits

The preceding claim that source line positions were unchanged was incorrect. Before these repairs, `LineItem` had moved from 13 to 15, `PurchaseOrderExtraction` from 35 to 44, and its validator from 66 to 77. In `database.py`, `init_db` moved from 24 to 29, hashing from 61 to 66, and saving from 67 to 72. The Episode 1 UI gained 21 lines; the Episode 3 caption moved from 153 to 154.

The recorded QA image, source-frame generator, narration and final subtitles independently match the original tag. In particular, the narration cites schema lines 81–106 and database lines 61/67. The claim that `LineItem` was on line 18 does not match the recorded source.

All these positions are restored. Original lines are preserved except for explicitly listed replacement lines that contain the actual fixes. Expanded rules live in `core/schema_rules.py` and `core/ledger_tools.py`; no padding, removed logging, or disabled validation is used. `export_to_csv` is appended after the original database module. Episode 5 was not part of the recorded line freeze.

`tests/video_line_manifest.json` stores hashes of the original individual lines of 13 recorded Python modules. The regression test checks their positions and disallows changes outside the explicitly repaired lines. Ep02 parsers, Ep03 OCR/sorter, Ep04 daemon and the shared Ollama client retain their original recorded text.

## Repairs

- Numeric schema fields reject NaN/infinity, invalid quantities and negative money. Recovered quantities and calculated products/sums also reject overflow.
- Empty procurement extractions remain visible through a purchase-order LEFT JOIN. CSV retains currency; dashboard spend is grouped by currency and empty documents are not counted as items.
- SQLite connections preserve the original raw connection API while closing on context exit. Content-based replacement is serialized with `BEGIN IMMEDIATE`.
- Explicit fiscal percentage rates drive gross/net calculations, with decimal half-up rounding. Unknown fiscal letter codes require review instead of an assumed E/K mapping.
- PDF fiscal parsing uses mapped description and unit-price columns. Specifications and line totals cannot silently become unit prices.
- OCR fiscal parsing iterates rows, preserves item names, uses unit-price fields, and quarantines missing prices or an empty extraction.
- Text fiscal parsing supports BOM, requires clear price/currency information, and quarantines model numbers, negative, zero and malformed prices.
- Fiscal initialization creates directories and safely upgrades the existing receipt schema. Item inserts and hash receipts commit atomically; retry/concurrent same-content processing cannot duplicate records. Distinct documents sharing a filename retain separate archives.
- The fiscal dashboard uses the same content receipts as the daemon. Uploaded dashboard documents are stored separately from the watched folder. Repeated ingestion is reported as already recorded. Manual resolution requires an entered price, a real item name and confirmed percentage rate; empty documents cannot become fabricated catalog items.
- USD/EUR or unlabelled fiscal prices require operator review/conversion before import into the KM catalog. No exchange conversion or currency substitution is invented.
- Linux/macOS smoke imports use the existing extraction API; both setup scripts check the exact model tag. The Windows smoke test works with the preserved connection API. Failed Windows data generation or database initialization stops setup.
- The four legacy `scratch/test_*_fix.py` entry points now run the isolated regression suites. Their former fiscal test wrote records into the project database; the new tests use temporary databases. Pre-existing test records are not deleted by these repairs.

## Verification

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

All 45 regression tests passed before applying the source repairs. The suite includes real supplied PDF/RapidOCR samples, actual Streamlit UI interactions, concurrent ingestion, transaction rollback, archive failure/retry, filename collisions, old receipt-schema migration and recorded-line preservation. It uses the standard-library `unittest` runner and existing application dependencies.

A separate live check ran all five original messages, both PDF procurement adapters and the OCR procurement adapter through local `qwen2.5:3b`, without writing to the project database. The five message review statuses matched expectations; the bordered PDF and OCR receipt were approved, and the borderless PDF's deliberate total mismatch was quarantined.

Schema validation and arithmetic checks do not establish semantic fidelity to the source document. In the live check, the small model still inferred quantity 1 for unspecified microcontrollers and copied a battery line total as an invoice total; those documents remained in quarantine because other fields were incomplete. Clean Linux/macOS installation was not executed on this Windows machine. Installation imports, model conditions and script parsing are checked separately.

No existing database, video, sample source document, git commit or tag is reset or overwritten by these source repairs. Release publication and GitHub push are separate from this local change.
