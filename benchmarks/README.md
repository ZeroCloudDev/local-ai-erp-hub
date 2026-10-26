# Model shootout (benchmarks/)

Runs the same synthetic EP01–EP05 documents through several local Ollama models and scores every model with the same validation the series uses. It does not edit any episode file, and it never writes to a database.

| Column (`*_summary.csv`) | Meaning |
|---|---|
| `license`, `license_url` | From `model_licenses.json`, checked on the official model page (re-check before publishing) |
| `passed_validation_pct` | Documents that were approved, with no quarantine |
| `quarantined` | Documents sent to human review |
| `correct_outcome_pct` | Documents whose outcome matches the expected truth: traps quarantined, clean documents approved **with the source values** |
| `wrongly_approved` | The dangerous case: approved although the document should be quarantined, or approved with values that differ from the source |
| `s_per_document` | Wall time per document, after one warm-up load (load time is in `load_s`) |
| `tokens_per_s` | Generated tokens ÷ generation time over all model calls |
| `model_ram_peak_gb` | Peak resident memory of the Ollama process holding the model (`llama-server`), not total system RAM |
| `ollama_reported_size_gb` | What `ollama ps` reports for the loaded model |

`*_detail.csv` has one row per document, so every BAD result can be traced.

Several documents are designed to be quarantined, so a high `passed_validation_pct` is **not** a good score by itself. Compare models on `correct_outcome_pct` and `wrongly_approved`.

The documents (11 per pass) are:

| Episode | Documents |
|---|---|
| EP01 | 5 field messages |
| EP02 | 2 PDF invoices |
| EP03 | 1 tilted receipt |
| EP05 | the register message, the fail probe and the shelf-tag photo (one model call per SKU line) |

EP04 has no documents of its own. The EP05 PDF is mapped without a model.

## Run it

```powershell
# from the repository root, with Ollama running and the models already pulled
ollama pull qwen2.5:3b
.\.venv\Scripts\python.exe benchmarks\model_shootout.py --models qwen2.5:3b,phi4-mini --machine p16s
```

| Option | Default | What it does |
|---|---|---|
| `--models` | (required) | Comma-separated Ollama tags. The script stops if one is not pulled; it never downloads. |
| `--repeat N` | 1 | Passes over all documents per model |
| `--machine NAME` | computer name | Label in the CSV file name and rows |
| `--out DIR` | `benchmarks/results/` | Output folder |

Each model starts cold: the script unloads every loaded model first, so RAM peaks are not mixed.

**Thinking models (`qwen3`).** Pass `--no-think qwen3:4b`. The runner then sends `think=False` with every chat call for that model, without editing the episode files, and the summary column `thinking` shows `off`. Measured on the ThinkPad with the first EP01 message:

| Thinking | Time | Tokens | JSON |
|---|---:|---:|---|
| on (model default) | 459 s | 4,450 | valid |
| off | 14 s | 143 | valid |

Thinking does not break the grammar-locked JSON, but it is about 33× slower.

## Accuracy night run (thresholds fixed 2026-10-23, before the run)

These rules were written down before any result of this run existed. They are not changed after seeing the results; a change gets a new dated section.

| Rule | Threshold |
|---|---|
| **Out** | A model is out if it has **even one** `wrongly_approved` (approved although it should be quarantined, or approved with values that differ from the source), over all documents and all runs. |
| **Recommended** | Only if it is not out, **and** `correct_outcome_pct` ≥ 90 % over all documents and runs, **and** its license is permissive (`Apache-2.0` or `MIT` in `model_licenses.json`). |
| **Passes** | Not out, but not recommended (below 90 % or a non-permissive or unconfirmed license). |
| Speed | Informative only (`s_per_document`, `tokens_per_s`); it never changes the verdict. |

The `verdict` column (`OUT` / `RECOMMENDED` / `PASSES`) applies these rules. `ministral-3:8b` is listed as "Apache-2.0 (per Ollama page; publisher card not checked)", so it cannot be `RECOMMENDED` until the publisher's own page is checked. `ERROR` (invalid JSON or a crash) writes nothing, so it never counts as an approval, but it is not a correct outcome either.

**Documents.** The 11 documents above, plus the 60 synthetic messages from `make_synthetic_set.py` (fixed seed 20261023, file `synthetic_set.json`): 20 easy, 40 hard (typos, two items in one sentence, missing quantity, unclear unit, price that differs from the catalog, unknown SKU). The expected outcome is written by the generator from the same numbers it uses to build the text, not by a model. Synthetic messages go through the EP01 extraction and then a catalog check that exists only in this benchmark (every line needs a catalog SKU, and the price per piece must match the catalog).

**Runs per document: 3.** Extraction runs at temperature 0 with no seed. A check on 2026-10-23 (qwen2.5:3b and granite4:3b, 3 identical calls on 3 EP01 messages) gave a different JSON on the first call of `msg_03` than on the next two for both models, so the output is not fully deterministic.

**Warm-up.** Before the measured runs, each model is loaded and then gets one extra message (`warmup` in `synthetic_set.json`). It is not scored; its time is in `warmup_document_s`.

**Recorded with every run:** Ollama version, `OLLAMA_MODELS` (the server log must show model blobs loaded from `E:\ollama\models`), Windows power plan, power mode on AC, and whether the charger is connected.

```powershell
.\.venv\Scripts\python.exe benchmarks\model_shootout.py --models granite4:3b,qwen2.5:3b,phi4-mini,qwen3:4b,ministral-3:8b,llama3.2:3b,qwen2.5:7b --no-think qwen3:4b --repeat 3 --synthetic --machine p16s
```

The CSV files are rewritten after every model, so a crash late in the night keeps the finished models.

### Addendum written 2026-10-23 17:40, before the run (owner's decision)

1. Every document runs 3 times. A silent error (`wrongly_approved`) in **any** of the 3 runs counts as a silent error of the model, so one is enough for `OUT`. `correct_outcome_pct` is computed over all runs (71 × 3 = 213 per model). The column `documents_outcome_differs_between_runs` counts documents whose outcome (status APPROVED / QUARANTINE / ERROR, or correct yes/no) was not the same in all 3 runs. `documents_with_silent_error` counts documents with a silent error in at least one run.
2. `ERROR` (invalid JSON or an exception) is not a silent error, and it is not a correct outcome either. It is shown on its own in the `errors` column.

### Addendum written 2026-10-24, before the Gemma 4 run

The rules above are unchanged. Two license entries in `model_licenses.json` were checked on the publishers' own pages:

- `ministral-3:8b` is Apache-2.0 per [Mistral's model docs](https://docs.mistral.ai/getting-started/models/), the [Mistral 3 launch post](https://mistral.ai/news/mistral-3) and the [Hugging Face card](https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512). Its verdict from the 2026-10-23 run is therefore re-read with the confirmed license; its measured numbers are not changed.
- `gemma4:e2b` and `gemma4:e4b` are Apache-2.0 per the Hugging Face cards ([E2B](https://huggingface.co/google/gemma-4-E2B-it), [E4B](https://huggingface.co/google/gemma-4-E4B-it)), which link to [Google's Gemma 4 license page](https://ai.google.dev/gemma/docs/gemma_4_license) containing the Apache License 2.0 text.

The two Gemma models run with the same `synthetic_set.json` (not regenerated), `--repeat 3 --synthetic`, Ollama 0.40.5, models on `E:\ollama\models`, on AC with "Best performance".

### Addendum written 2026-10-25, before the dropped-line run

The rules above are unchanged (`OUT` / `RECOMMENDED` / `PASSES`, same thresholds, same 71 documents, same `synthetic_set.json`). What is added is one deterministic check, and one new run that measures it.

**Why.** In the night run `qwen3:4b` approved `syn_hard_noqty_06` in 3 of 3 runs. On 2026-10-25 its raw JSON (ProBook, 3 calls) had only the first item: the line without a quantity was left out, and the message has no total, so the EP01 validation had nothing to compare (`results/qwen3_noqty06_raw_check_probook_2026-10-25.txt`).

**The check (`core/completeness.py`, `dropped_line_reasons`).** It counts the money amounts in the source text that are item prices, i.e. not totals. An amount counts as a total when a total word stands just before it (`total`, a misspelling starting with `tot`, `that's`, `comes to`, `=`) or `all in` / `total` follows it. If the extraction has fewer items than item prices in the text, the document goes to quarantine with the reason "possible dropped line". It never approves anything. It does not count items that have no price in the text at all.

**Where it runs.** On text messages only: the 5 EP01 messages and the 60 synthetic messages. Not on the EP02 PDFs, the EP03 OCR receipt or EP05 (their text is a table or OCR, not a message). The episode code is not changed: the runner calls the check after the EP01 extraction.

**How it is measured.** `--completeness-check` scores every document twice from **the same model answer**: once without the check (as in all earlier runs) and once with it. The detail CSV gets `actual_without_check` / `correct_without_check` / `wrongly_approved_without_check`; the summary gets the same totals without the check, so the effect of the check is not mixed with run-to-run differences of the model. The verdict uses the result **with** the check.

**Decision rules, fixed now:**
1. The check is **accepted** for the episode code (ADAPT HERE recommendation) only if, over all models in the run: (a) it removes at least one `wrongly_approved` caused by a dropped line, and (b) it adds **no** new `wrongly_approved`, and (c) for `granite4:3b` it raises "correct document, but quarantined" by **at most 2 percentage points** (39 clean documents: at most 1 more document).
2. Otherwise it is **rejected** and stays in the benchmark as a documented experiment.

**Known bias, written before the run.** The check was designed after reading the synthetic message templates (`make_synthetic_set.py`) and the failing message. The 60 synthetic messages are therefore a development set for this check, not an independent test; a low false-positive count on them proves little. The 5 EP01 messages were written before the check, by other templates. A fair test needs messages the check has never seen (real anonymized messages, `real_messages_FORMAT.md`).

**Run (ProBook, Ollama 0.40.7, models on `H:\ollama\models`, AC, "Best performance", `--repeat 1`).** Order by importance, so a late stop keeps the main models: `granite4:3b, ministral-3:8b, qwen3:4b (--no-think), qwen2.5:3b, llama3.2:3b, phi4-mini, qwen2.5:7b, gemma4:e2b`. `gemma4:e4b` (10.6 GB) is not run on the 16 GB machine. A model is stopped if free RAM stays below 1 GB or the pagefile grows by more than 200 MB.

### Experiment 2026-10-26, written before the run

**Hypothesis.** In `core/schemas.py` (EP01) the field `items` has `default_factory=list`, so the JSON schema sent to Ollama does not list it as required and a model may leave it out. If `items` becomes required (at least 1 line), models that left lines out should send fewer correct messages to quarantine. **Risk we measure:** when a model must write something, it may invent lines, so silent errors (`wrongly_approved`) may go up. Rules and thresholds are the same as in the night run (`OUT` / `RECOMMENDED` / `PASSES`).

**Variant A (strict schema).** `benchmarks/strict_schema.py` subclasses the EP01 schema: same fields, descriptions and Layer 2 validator; the only difference in the JSON schema is `"required": ["items"]` and `"minItems": 1`. `--schema strict` swaps the class that `core.llm_client` uses, so it is both the `format` sent to Ollama and the parser, for EP01, EP02, EP03 and the 60 synthetic messages. EP05 has its own per-line schema and is not affected. No episode file is changed (`tests/test_video_lines.py` passes). Checked before the run: `--schema default` gives the same outcome as night-run pass 1 on 3 documents (`granite4:3b`: `msg_01_clean_order`, `syn_easy_01`, `syn_hard_noqty_06`).

**Before** = pass 1 (`run = 1`) of the night runs on this machine (`shootout_p16s_2026-10-23_174028_detail.csv`, `shootout_p16s_2026-10-24_093835_detail.csv`). **After** = one strict run, `--repeat 1`, same `synthetic_set.json`, P16s, Ollama 0.40.5, models on `E:\ollama\models`, AC, "Best performance":

```powershell
.\.venv\Scripts\python.exe benchmarks\model_shootout.py --models gemma4:e4b,qwen2.5:7b,phi4-mini,gemma4:e2b,llama3.2:3b,granite4:3b --schema strict --repeat 1 --synthetic --machine p16s
```

`granite4:3b` is the control (it did not leave lines out in the night run). Compared per model: silent errors, correct outcome %, "correct but quarantined" %, `ERROR`, s/document. With one pass per variant, a difference of 1–2 documents is within the run-to-run noise noted above (temperature 0, no seed).

**Variant B (EP05 SKU scanner on the test set): not run.** `ep05_fiscal_ingest_robot/completeness_check.py` only finds five-digit numeric SKUs (`SKU_TOKEN_RE = (?<!\d)(\d{5})(?!\d)`) in EP05 `ExtractedDocument` segments and matches them to EP05 `CatalogCandidate`s. The synthetic SKUs are alphanumeric (`AGM-H6`, `ESP32-S3-WROOM-1`), so the scanner does not see `AGM-H6` at all; using it would mean a new SKU pattern and a new adapter, i.e. a new check, not the existing one. The dropped-line check that does apply to these messages (`core/completeness.py`, `--completeness-check`) was set up on 2026-10-25 (addendum above), but that ProBook run stopped during the second model and wrote no result CSV, so the check is **not measured** and is not recommended for the episode code.

## Second machine (e.g. HP ProBook 470, Intel i7, 16 GB)

1. **Same code.** Clone the repository, or copy the folder, at the same commit as the first machine (`git log -1`).
2. **Same software.** Install Python 3.10–3.12 and the same Ollama version. The first machine's version is in the `ollama_version` column; check yours with `ollama --version`.
3. **Install.** Run `setup.ps1`, or double-click `run.bat`. If `import psutil` fails, run `.\.venv\Scripts\python.exe -m pip install psutil`.
4. **Same models.** Pull exactly the same tags as on the first machine: `ollama pull <tag>` for each one.
5. **Same conditions.** Plug in the charger and use the "Best performance" power mode. Close browsers and other heavy apps.
6. **Run with the same model list and a different label:**
   ```powershell
   .\.venv\Scripts\python.exe benchmarks\model_shootout.py --models <same list> --machine probook --repeat 3
   ```
7. **Copy the results.** Copy both CSV files from `benchmarks\results\` back to the first machine.

Total RAM matters on a 16 GB machine. If a model is much larger than about half of free RAM, Windows may page to disk, and `s_per_document` will show it. Report that as a result; it is not an error.
