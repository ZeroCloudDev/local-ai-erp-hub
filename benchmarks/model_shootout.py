"""
Model shootout: the same synthetic EP01-EP05 documents through several local
Ollama models, scored by the same validation the series uses.

Nothing here edits the recorded episode code (tests/test_video_lines.py) and
nothing is written to any database: the runner only calls the existing
extraction functions with a different `model=` argument.

    python benchmarks\\model_shootout.py --models qwen2.5:3b,phi4-mini
    python benchmarks\\model_shootout.py --models qwen2.5:3b --repeat 3 --machine probook

Documents (11 per pass; models must already be pulled with `ollama pull`):
  EP01  5 field messages            core.llm_client.extract_structured_erp
  EP02  2 PDF invoices              ep02_pdf_tables.pdf_parser.process_pdf_to_erp
  EP03  1 tilted receipt photo      ep03_fast_cpu_ocr.ocr_pipeline.process_receipt_image_to_erp
  EP05  message, fail probe, photo  ep05 source_extractors (one model call per SKU line)
EP04 has no documents of its own (it routes the same files), and the EP05 PDF
is mapped without a model, so neither is part of a model comparison.

With --synthetic, the 60 messages from make_synthetic_set.py are added (EP01
extraction, then a catalog check that exists only in this benchmark: unknown
SKU or a price that differs from the catalog goes to quarantine).

Why "correct outcome" and not only "% passed validation": several documents
are traps that MUST go to quarantine (missing price, wrong total). A model
that invents the missing price would "pass" more often. So every document has
an expected outcome written below, and the worst result is counted on its own:
WRONGLY_APPROVED = approved although it should be quarantined, or approved
with values that differ from the source.

Model RAM: peak resident memory (working set on Windows) of the Ollama runner
process that holds the model, sampled every 0.2 s while the model is used.
It is the model's own process, not total system RAM. Weights and KV cache are
both inside it; the context length therefore changes the number.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ollama
import psutil

from core.completeness import dropped_line_reasons
from core.llm_client import _ensure_ollama_running, extract_structured_erp
from ep02_pdf_tables.pdf_parser import process_pdf_to_erp
from ep03_fast_cpu_ocr.ocr_pipeline import process_receipt_image_to_erp
from ep05_fiscal_ingest_robot.adapter_config import load_config
from ep05_fiscal_ingest_robot.pos_validation import static_reasons
from ep05_fiscal_ingest_robot.probe_model_lines import EXPECTED as EP05_EXPECTED
from ep05_fiscal_ingest_robot.source_extractors import extract_image, extract_text

HERE = Path(__file__).resolve().parent
DATA = ROOT / "data"
EP05_INPUTS = ROOT / "ep05_fiscal_ingest_robot" / "demo_inputs"
LICENSES_FILE = HERE / "model_licenses.json"

APPROVED, REVIEW = "APPROVED", "QUARANTINE"

# Expected truth for EP01-EP03, taken from the synthetic sources themselves
# (data/samples_ep1_text/chaotic_messages.json, data/generate_test_assets.py).
# For APPROVED documents the values must match: stated total and every line
# as (quantity, unit_price, line_total).
EP01_03_TRUTH = {
    "msg_01_clean_order": (APPROVED, 207.00, [(12, 14.50, 174.00), (4, 8.25, 33.00)]),
    "msg_02_missing_unit_price": (REVIEW, None, None),     # no price per spool, no stripper price
    "msg_03_missing_quantity": (REVIEW, None, None),       # "forgot how many reels"
    "msg_04_math_mismatch_trap": (REVIEW, None, None),     # 255.00 vs stated 290.00
    "msg_05_chaotic_voice_note": (REVIEW, None, None),     # fluid has no price
    "mouser_bordered_invoice.pdf": (APPROVED, 242.50, [(10, 11.20, 112.00), (5, 14.50, 72.50), (2, 29.00, 58.00)]),
    "digikey_borderless_invoice.pdf": (REVIEW, None, None),  # 295.00 vs stated 310.00
    "tilted_fastenal_receipt.png": (APPROVED, 296.00, [(4, 12.50, 50.00), (2, 18.00, 36.00), (1, 210.00, 210.00)]),
}
# EP05: a document is APPROVED only if every SKU line passes the static checks.
# The register message must quarantine 95012 (no price); the others are clean.
EP05_TRUTH = {
    "register_update_message.txt": REVIEW,
    "fail_probe.txt": APPROVED,
    "shelf_tags_photo.jpg": APPROVED,
}


# ---------------------------------------------------------------------------
# Model RAM sampling
# ---------------------------------------------------------------------------

def _runner_processes() -> list[psutil.Process]:
    """Ollama starts one process per loaded model. Its name depends on the
    Ollama version: `llama-server` (0.40, checked), `ollama runner ...` or
    `ollama_llama_server` (older). The tray app and `ollama serve` are not counted."""
    procs = []
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            name = (p.info["name"] or "").lower()
            cmd = " ".join(p.info["cmdline"] or []).lower()
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
        if ("llama-server" in name or "ollama_llama_server" in name
                or ("ollama" in name and " runner" in cmd)):
            procs.append(p)
    return procs


class RamSampler:
    def __init__(self, interval_s: float = 0.2):
        self.interval_s = interval_s
        self.peak_bytes = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            total = 0
            for p in _runner_processes():
                try:
                    total += p.memory_info().rss
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    pass
            self.peak_bytes = max(self.peak_bytes, total)
            self._stop.wait(self.interval_s)

    def __enter__(self) -> "RamSampler":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._thread.join()


def unload_all_models() -> None:
    """Start every model from a cold, empty runner so RAM peaks are not mixed."""
    for m in ollama.ps().get("models", []):
        ollama.generate(model=m["model"], prompt="", keep_alive=0)
    for _ in range(50):
        if not _runner_processes():
            return
        time.sleep(0.2)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _close(a, b) -> bool:
    return a is not None and b is not None and abs(float(a) - float(b)) < 0.005


def score_po(doc_id: str, po) -> tuple[str, bool, str]:
    """(actual status, correct outcome?, note) for an EP01-EP03 extraction."""
    expected, total, lines = EP01_03_TRUTH[doc_id]
    actual = REVIEW if po.needs_human_review else APPROVED
    if expected == REVIEW:
        return actual, actual == REVIEW, "; ".join(po.review_reasons)[:200]
    if actual == REVIEW:
        return actual, False, "; ".join(po.review_reasons)[:200]
    got = sorted((i.quantity, i.unit_price, i.line_total) for i in po.items)
    want = sorted(lines)
    same = _close(po.stated_total, total) and len(got) == len(want) and all(
        all(_close(g, w) for g, w in zip(gl, wl)) for gl, wl in zip(got, want))
    return actual, same, "" if same else f"values differ from source: {got} total={po.stated_total}"


def _sku(s) -> str:
    return (s or "").strip().upper()


def catalog_reasons(po, catalog: dict) -> list[str]:
    """Benchmark-only layer after the EP01 validation: every line needs a SKU
    from the catalog, and its price per piece must match the catalog."""
    reasons = []
    for idx, item in enumerate(po.items, start=1):
        sku = _sku(item.sku_or_part_no)
        if not sku:
            reasons.append(f"Row {idx}: no SKU")
            continue
        if sku not in catalog:
            reasons.append(f"Row {idx}: SKU {sku} not in catalog")
            continue
        price = item.unit_price
        if price is None and item.line_total is not None and item.quantity:
            price = item.line_total / item.quantity
        if price is not None and not _close(price, catalog[sku]["unit_price"]):
            reasons.append(f"Row {idx}: {sku} price {price} != catalog {catalog[sku]['unit_price']}")
    return reasons


def score_synthetic(msg: dict, po, catalog: dict) -> tuple[str, bool, str]:
    """(actual status, correct outcome?, note) for one synthetic message."""
    extra = catalog_reasons(po, catalog)
    reasons = list(po.review_reasons) + extra
    actual = REVIEW if (po.needs_human_review or extra) else APPROVED
    if msg["expected"] == REVIEW or actual == REVIEW:
        return actual, actual == msg["expected"], "; ".join(reasons)[:200]
    got = sorted((_sku(i.sku_or_part_no), i.quantity, i.unit_price, i.line_total) for i in po.items)
    want = sorted((l["sku"], l["quantity"], l["unit_price"], l["line_total"]) for l in msg["lines"])
    lines_ok = len(got) == len(want) and all(
        g[0] == w[0] and all(_close(a, b) for a, b in zip(g[1:], w[1:])) for g, w in zip(got, want))
    total_ok = (po.stated_total is None if msg["stated_total"] is None
                else _close(po.stated_total, msg["stated_total"]))
    same = lines_ok and total_ok
    return actual, same, "" if same else f"values differ from source: {got} total={po.stated_total}"


def score_ep05(doc, cfg) -> tuple[str, bool, int, str]:
    """(actual status, correct outcome?, silently wrong lines, note).
    Line rule = probe_model_lines.py: name, price, unit and tax must match;
    a line with an expected price must also pass the static checks."""
    bad_lines, silent_wrong, notes = 0, 0, []
    any_reason = False
    for c in doc.candidates:
        reasons = static_reasons(c, cfg)
        any_reason = any_reason or bool(reasons)
        exp = EP05_EXPECTED.get(c.sku)
        ok = exp is not None and (c.name or "").casefold() == exp[0].casefold() and (
            (exp[1] is None and c.retail_price is None)
            or (exp[1] is not None and str(c.retail_price) == exp[1])
        ) and c.sales_unit == exp[2] and c.tax_class in exp[3]
        if exp and exp[1] is not None:
            ok = ok and not reasons
        if not ok:
            bad_lines += 1
            notes.append(f"{c.sku}:{c.name!r} {c.retail_price} {reasons}")
            if not reasons:
                silent_wrong += 1          # would have been written with a wrong value
    actual = REVIEW if any_reason or not doc.candidates else APPROVED
    expected = EP05_TRUTH[doc.path.name]
    correct = actual == expected and bad_lines == 0
    return actual, correct, silent_wrong, "; ".join(notes)[:300]


# ---------------------------------------------------------------------------
# One model, one pass over all documents
# ---------------------------------------------------------------------------

ERROR = "ERROR"


def with_check(expected: str, actual: str, correct: bool, note: str, extra: list[str]) -> tuple[str, bool, str]:
    """Outcome after the dropped-line check (README addendum 2026-10-25). The check
    can only move an approved document to quarantine."""
    if not extra or actual != APPROVED:
        return actual, correct, note
    return REVIEW, expected == REVIEW, "; ".join(extra)[:200]


def run_documents(model: str, cfg, synthetic: dict | None = None, check: bool = False,
                  on_row=None) -> list[dict]:
    """Score every document. `on_row(row)` is called as soon as each document is done,
    so progress is printed live instead of after the whole pass (~11 min)."""
    rows = []

    def add(episode, doc_id, expected, actual, correct, wrongly_approved, seconds,
            eval_tokens, eval_ms, model_calls, note, doc_set="original", without=None):
        # `without`: (actual, correct, wrongly_approved) from the same model answer, scored
        # without the dropped-line check; equal to the result when the check does not apply.
        base = without or (actual, correct, wrongly_approved)
        rows.append(dict(doc_set=doc_set, episode=episode, document=doc_id, expected=expected, actual=actual,
                         correct=int(correct), wrongly_approved=int(wrongly_approved),
                         actual_without_check=base[0], correct_without_check=int(base[1]),
                         wrongly_approved_without_check=int(base[2]),
                         seconds=round(seconds, 2), eval_tokens=eval_tokens,
                         eval_ms=round(eval_ms, 1), model_calls=model_calls, note=note))
        if on_row:
            on_row(rows[-1])

    def failed(episode, doc_id, expected, t0, exc, doc_set="original"):
        # Invalid JSON or a crash writes nothing, so it is never an approval;
        # it is still not the expected outcome.
        add(episode, doc_id, expected, ERROR, False, False, time.perf_counter() - t0, 0, 0.0, 0,
            f"{type(exc).__name__}: {exc}"[:200], doc_set)

    def from_po(episode, doc_id, po, metrics, seconds, source_text=None):
        expected = EP01_03_TRUTH[doc_id][0]
        actual, correct, note = score_po(doc_id, po)
        without = (actual, correct, actual == APPROVED and not correct)
        if check and source_text is not None:
            actual, correct, note = with_check(expected, actual, correct, note, dropped_line_reasons(source_text, po))
        wrong_ok = actual == APPROVED and not correct
        add(episode, doc_id, expected, actual, correct, wrong_ok, seconds,
            metrics.get("output_tokens", 0), metrics.get("eval_duration_ms", 0.0), 1, note, without=without)

    for sample in json.loads((DATA / "samples_ep1_text" / "chaotic_messages.json").read_text(encoding="utf-8")):
        t0 = time.perf_counter()
        try:
            po, m = extract_structured_erp(sample["text"], model=model)
        except Exception as exc:
            failed("EP01", sample["id"], EP01_03_TRUTH[sample["id"]][0], t0, exc)
            continue
        from_po("EP01", sample["id"], po, m, time.perf_counter() - t0, source_text=sample["text"])

    for name, whitespace in (("mouser_bordered_invoice.pdf", False), ("digikey_borderless_invoice.pdf", True)):
        t0 = time.perf_counter()
        try:
            _, po, m = process_pdf_to_erp(DATA / "samples_ep2_pdf" / name, use_whitespace_strategy=whitespace, model=model)
        except Exception as exc:
            failed("EP02", name, EP01_03_TRUTH[name][0], t0, exc)
            continue
        from_po("EP02", name, po, m, time.perf_counter() - t0)

    t0 = time.perf_counter()
    try:
        _, po, m = process_receipt_image_to_erp(DATA / "samples_ep3_images" / "tilted_fastenal_receipt.png", model=model)
        from_po("EP03", "tilted_fastenal_receipt.png", po, m, time.perf_counter() - t0)
    except Exception as exc:
        failed("EP03", "tilted_fastenal_receipt.png", APPROVED, t0, exc)

    # EP05 counts tokens per call through a wrapper around the real model call.
    from ep05_fiscal_ingest_robot import source_extractors as se
    for path in (EP05_INPUTS / "register_update_message.txt", EP05_INPUTS / "fail_probe.txt",
                 EP05_INPUTS / "shelf_tags_photo.jpg"):
        calls = {"tokens": 0, "eval_ms": 0.0}

        def counting_llm(line_text, mdl):
            raw, mm = se.ollama_pos_llm(line_text, mdl)
            calls["tokens"] += mm.get("output_tokens", 0)
            calls["eval_ms"] += mm.get("eval_duration_ms", 0.0)
            return raw, mm

        kw = dict(llm=counting_llm, sku_min=cfg.sku_min, sku_max=cfg.sku_max, codes=cfg.code_tables())
        t0 = time.perf_counter()
        try:
            if path.suffix == ".jpg":
                doc = extract_image(path, model, y_tol=cfg.ocr_y_tolerance_px, min_conf=cfg.ocr_min_confidence, **kw)
            else:
                doc = extract_text(path, model, **kw)
        except Exception as exc:
            failed("EP05", path.name, EP05_TRUTH[path.name], t0, exc)
            continue
        seconds = time.perf_counter() - t0
        actual, correct, silent_wrong, note = score_ep05(doc, cfg)
        add("EP05", path.name, EP05_TRUTH[path.name], actual, correct, silent_wrong > 0, seconds,
            calls["tokens"], calls["eval_ms"], doc.metrics.get("model_calls", 0), note)

    for msg in (synthetic or {}).get("messages", []):
        t0 = time.perf_counter()
        try:
            po, m = extract_structured_erp(msg["text"], model=model)
        except Exception as exc:
            failed("SYN", msg["id"], msg["expected"], t0, exc, "synthetic")
            continue
        seconds = time.perf_counter() - t0
        actual, correct, note = score_synthetic(msg, po, synthetic["catalog"])
        without = (actual, correct, actual == APPROVED and not correct)
        if check:
            actual, correct, note = with_check(msg["expected"], actual, correct, note,
                                               dropped_line_reasons(msg["text"], po))
        add("SYN", msg["id"], msg["expected"], actual, correct, actual == APPROVED and not correct, seconds,
            m.get("output_tokens", 0), m.get("eval_duration_ms", 0.0), 1, note, "synthetic", without=without)
    return rows


def disable_thinking(models: set[str]) -> None:
    """Send think=False for the given models. The episode code calls
    `ollama.chat(...)` through the module, so wrapping the module attribute
    switches thinking off for every call without editing the episode files.
    Needed for models with a thinking mode (qwen3): see benchmarks/README.md."""
    original = ollama.chat

    def chat(*args, **kwargs):
        if kwargs.get("model") in models:
            kwargs.setdefault("think", False)
        return original(*args, **kwargs)

    ollama.chat = chat


def use_strict_schema() -> None:
    """Experiment 2026-10-26: `items` required, at least one line. extract_structured_erp
    reads the class from its module for both `format=` and parsing, so swapping the
    module attribute changes EP01-EP03 and the synthetic messages without editing the
    episode files. EP05 has its own schema. See benchmarks/strict_schema.py."""
    import core.llm_client
    from benchmarks.strict_schema import StrictPurchaseOrderExtraction
    core.llm_client.PurchaseOrderExtraction = StrictPurchaseOrderExtraction


def warm_up(model: str, warmup_text: str | None = None) -> tuple[float, float]:
    """Load the model once, then (optionally) run one warm-up document through
    the EP01 extraction. Neither is counted. Returns (load s, warm-up document s)."""
    t0 = time.perf_counter()
    ollama.generate(model=model, prompt="OK", options={"num_predict": 1}, keep_alive="30m")
    load_s = time.perf_counter() - t0
    if not warmup_text:
        return load_s, 0.0
    t0 = time.perf_counter()
    try:
        extract_structured_erp(warmup_text, model=model)
    except Exception:
        pass                                # warm-up only; its result is never scored
    return load_s, time.perf_counter() - t0


def differing_documents(rows: list[dict]) -> set[str]:
    """Documents whose outcome (status APPROVED/QUARANTINE/ERROR, or correct
    yes/no) is not the same in every run."""
    seen: dict[str, set] = {}
    for r in rows:
        seen.setdefault(r["document"], set()).add((r["actual"], r["correct"]))
    return {doc for doc, outcomes in seen.items() if len(outcomes) > 1}


PERMISSIVE = {"Apache-2.0", "MIT"}


def verdict(row: dict) -> str:
    """Thresholds from benchmarks/README.md, fixed before the night run."""
    if row["wrongly_approved"] > 0:
        return "OUT"
    if row["correct_outcome_pct"] >= 90.0 and row["license"] in PERMISSIVE:
        return "RECOMMENDED"
    return "PASSES"


def power_info() -> dict:
    """Active Windows power plan and power-mode overlay; on AC or battery."""
    info = dict(power_plan="", power_mode_ac="", on_ac="")
    if sys.platform != "win32":
        return info
    try:
        out = subprocess.run(["powercfg", "/getactivescheme"], capture_output=True, text=True, timeout=10).stdout
        info["power_plan"] = out.split("(")[-1].rstrip(")\n ") if "(" in out else out.strip()
    except Exception:
        pass
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SYSTEM\CurrentControlSet\Control\Power\User\PowerSchemes") as k:
            guid = winreg.QueryValueEx(k, "ActiveOverlayAcPowerScheme")[0]
        info["power_mode_ac"] = {"ded574b5-45a0-4f42-8737-46345c09c238": "Best performance",
                                 "961cc777-2547-4f9d-8174-7d86181b8a7a": "Best power efficiency",
                                 "00000000-0000-0000-0000-000000000000": "Balanced"}.get(guid.lower(), guid)
    except OSError:
        pass
    plugged = getattr(psutil.sensors_battery(), "power_plugged", None) if hasattr(psutil, "sensors_battery") else None
    info["on_ac"] = "" if plugged is None else ("yes" if plugged else "NO (battery)")
    return info


# ---------------------------------------------------------------------------
# Machine info and output
# ---------------------------------------------------------------------------

def machine_info(label: str | None) -> dict:
    cpu = platform.processor()
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
                cpu = winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
        except OSError:
            pass
    try:
        ollama_version = ollama.Client()._client.get("/api/version").json().get("version", "")
    except Exception:
        ollama_version = ""
    return dict(machine=label or socket.gethostname(), cpu=cpu, logical_cpus=psutil.cpu_count(),
                ram_total_gb=round(psutil.virtual_memory().total / 2**30, 1),
                os=platform.platform(), ollama_version=ollama_version,
                ollama_models_env=os.environ.get("OLLAMA_MODELS", "(default)"), **power_info())


def load_licenses() -> dict:
    if LICENSES_FILE.exists():
        return json.loads(LICENSES_FILE.read_text(encoding="utf-8"))
    return {}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", required=True, help="comma-separated Ollama tags, already pulled")
    ap.add_argument("--repeat", type=int, default=1, help="passes over all documents per model")
    ap.add_argument("--machine", help="label for the CSV (default: computer name)")
    ap.add_argument("--out", type=Path, default=HERE / "results")
    ap.add_argument("--no-think", default="", help="comma-separated tags that get think=False (e.g. qwen3:4b)")
    ap.add_argument("--synthetic", type=Path, nargs="?", const=HERE / "synthetic_set.json",
                    help="add the 60 synthetic messages (default file: benchmarks/synthetic_set.json)")
    ap.add_argument("--completeness-check", action="store_true",
                    help="apply core/completeness.py to text messages; scores are also kept without it (README 2026-10-25)")
    ap.add_argument("--schema", choices=("default", "strict"), default="default",
                    help="strict: benchmarks/strict_schema.py, items required (README experiment 2026-10-26)")
    args = ap.parse_args()

    _ensure_ollama_running()
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    local = {m["model"] for m in ollama.list().get("models", [])}
    missing = [m for m in models if m not in local and f"{m}:latest" not in local]
    if missing:
        print(f"Not pulled: {', '.join(missing)}. Run `ollama pull <tag>` first (this script never downloads).")
        return 2

    no_think = {m.strip() for m in args.no_think.split(",") if m.strip()}
    if no_think:
        disable_thinking(no_think)
    if args.schema == "strict":
        use_strict_schema()
    info = machine_info(args.machine)
    licenses = load_licenses()
    cfg = load_config()
    synthetic = json.loads(args.synthetic.read_text(encoding="utf-8")) if args.synthetic else None
    warmup_text = synthetic["warmup"]["text"] if synthetic else None
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    args.out.mkdir(parents=True, exist_ok=True)
    base = args.out / f"shootout_{info['machine']}_{stamp}"
    print(f"Machine: {info}")

    def pct(rows, key="correct"):
        return round(100 * sum(r[key] for r in rows) / len(rows), 1) if rows else ""

    def clean_quarantined(rows, key):
        """Correct documents (expected APPROVED) that were sent to a human anyway, in %."""
        clean = [r for r in rows if r["expected"] == APPROVED]
        return round(100 * sum(r[key] == REVIEW for r in clean) / len(clean), 1) if clean else ""

    details, summary = [], []
    for model in models:
        print(f"\n=== {model} === {datetime.now():%H:%M:%S}", flush=True)
        unload_all_models()
        with RamSampler() as ram:
            load_s, warmup_s = warm_up(model, warmup_text)
            rows = []
            for r in range(args.repeat):
                def show(row):
                    print(f"  {row['episode']} {row['document']:<34} expected={row['expected']:<10} "
                          f"actual={row['actual']:<10} {'OK ' if row['correct'] else 'BAD'} {row['seconds']} s",
                          flush=True)
                for row in run_documents(model, cfg, synthetic, check=args.completeness_check, on_row=show):
                    row.update(model=model, run=r + 1)
                    rows.append(row)
        ps = {m["model"]: m for m in ollama.ps().get("models", [])}
        size_ollama = (ps.get(model) or ps.get(f"{model}:latest") or {}).get("size", 0)
        n = len(rows)
        tokens = sum(r["eval_tokens"] for r in rows)
        eval_s = sum(r["eval_ms"] for r in rows) / 1000
        lic = licenses.get(model, {})
        summary.append(dict(
            model=model, thinking="off" if model in no_think else "model default",
            license=lic.get("license", "NOT CHECKED"), license_url=lic.get("url", ""),
            documents=n,
            passed_validation_pct=round(100 * sum(r["actual"] == APPROVED for r in rows) / n, 1),
            quarantined=sum(r["actual"] == REVIEW for r in rows),
            correct_outcome_pct=pct(rows),
            wrongly_approved=sum(r["wrongly_approved"] for r in rows),
            completeness_check="on" if args.completeness_check else "off",
            schema=args.schema,
            correct_outcome_pct_without_check=pct(rows, "correct_without_check"),
            wrongly_approved_without_check=sum(r["wrongly_approved_without_check"] for r in rows),
            clean_quarantined_pct=clean_quarantined(rows, "actual"),
            clean_quarantined_pct_without_check=clean_quarantined(rows, "actual_without_check"),
            errors=sum(r["actual"] == ERROR for r in rows),
            documents_with_silent_error=len({r["document"] for r in rows if r["wrongly_approved"]}),
            documents_outcome_differs_between_runs=len(differing_documents(rows)),
            correct_original_pct=pct([r for r in rows if r["doc_set"] == "original"]),
            correct_synthetic_pct=pct([r for r in rows if r["doc_set"] == "synthetic"]),
            runs_per_document=args.repeat,
            s_per_document=round(sum(r["seconds"] for r in rows) / n, 2),
            tokens_per_s=round(tokens / eval_s, 1) if eval_s else 0.0,
            model_ram_peak_gb=round(ram.peak_bytes / 2**30, 2),
            ollama_reported_size_gb=round(size_ollama / 2**30, 2),
            load_s=round(load_s, 1), warmup_document_s=round(warmup_s, 1), **info))
        summary[-1]["verdict"] = verdict(summary[-1])
        details.extend(rows)
        print(f"  -> {summary[-1]['correct_outcome_pct']} % correct, {summary[-1]['wrongly_approved']} wrongly approved, "
              f"{summary[-1]['s_per_document']} s/doc, RAM peak {summary[-1]['model_ram_peak_gb']} GB, "
              f"{summary[-1]['verdict']}", flush=True)

        # Written after every model, so a crash later in the night keeps what is done.
        for path, out_rows in ((Path(f"{base}_summary.csv"), summary), (Path(f"{base}_detail.csv"), details)):
            with path.open("w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
                w.writeheader()
                w.writerows(out_rows)
        print(f"Written: {base}_summary.csv / _detail.csv", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
