"""
EP05 — watch-folder service: documents in, POS rows out.

Builds on the EP04 watcher idea (drop a file -> it is processed) and adds
what EP04 deliberately left out:

  * created AND moved events, plus a scan of the folder at start-up, so a
    file that arrived while the service was stopped is not forgotten;
  * a file is processed only when it is READY: its size and mtime did not
    change over several checks and it can be opened. No fixed 0.5 s sleep.
    (This is a heuristic for files copied in by a person or Explorer. A
    producer we control should write "name.part" and rename when done.)
  * the file is copied to a private work folder, hashed there, and the
    original is re-checked just before COMMIT; if it changed, nothing is
    committed and the file is retried;
  * a document hash that is already in ep05_dokumenti is never written again;
  * the file is archived only AFTER the commit; if moving it fails, only the
    archiving is retried later, never the database write.

Run:
    python ep05_fiscal_ingest_robot\\pos_watch_service.py                 (watch)
    python ep05_fiscal_ingest_robot\\pos_watch_service.py --once FILE     (one file)
    $env:EP05_FAIL_AFTER_OPS=3
    python ep05_fiscal_ingest_robot\\pos_watch_service.py --once demo_inputs\\fail_probe.txt --demo-failure-injection
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import queue
import shutil
import sys
import threading
import time
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ep05_fiscal_ingest_robot.adapter_config import AdapterConfig, load_config
from ep05_fiscal_ingest_robot.completeness_check import reconcile
from ep05_fiscal_ingest_robot.mysql_pos_adapter import (FailureInjection, InjectedFailure,
                                                        PosAdapter, SourceChanged)
from ep05_fiscal_ingest_robot.pos_validation import QUARANTINE
from ep05_fiscal_ingest_robot.source_extractors import LlmFn, extract_any, ollama_pos_llm

SUPPORTED = {".txt", ".md", ".pdf", ".jpg", ".jpeg", ".png"}
KIND_TAG = {"text": "TXT", "pdf": "PDF", "image": "IMG"}


def log(msg: str) -> None:
    print(f"{datetime.now().strftime('%H:%M:%S')} {msg}", flush=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def wait_until_ready(path: Path, cfg: AdapterConfig) -> bool:
    """True when size+mtime stayed the same for `stable_checks` checks and the
    file opens for reading. False if it vanished or never settled."""
    deadline = time.monotonic() + cfg.max_wait_s
    last, same = None, 0
    while time.monotonic() < deadline:
        try:
            st = path.stat()
            sig = (st.st_size, st.st_mtime_ns)
            with open(path, "rb"):
                pass
        except (FileNotFoundError, PermissionError, OSError):
            sig = None
        if sig is None and not path.exists():
            return False
        if sig is not None and sig == last and sig[0] > 0:
            same += 1
            if same >= cfg.stable_checks:
                return True
        else:
            same = 0
        last = sig
        time.sleep(cfg.stable_interval_s)
    return False


def is_candidate_file(path: Path, cfg: AdapterConfig) -> bool:
    name = path.name.lower()
    return (path.suffix.lower() in SUPPORTED and not name.startswith((".", "~$"))
            and not name.endswith(cfg.ignore_suffixes) and ".note." not in name)


def _archive(src: Path, cfg: AdapterConfig, folder: str, doc_id: int | None, file_hash: str,
             note: str | None = None) -> Path:
    dest_dir = cfg.archive_dir / folder
    dest_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"{doc_id:04d}_" if doc_id else ""
    dest = dest_dir / f"{prefix}{file_hash[:8]}_{src.name}"
    shutil.move(str(src), str(dest))
    if note:
        dest.with_name(dest.name + ".NOTE.txt").write_text(note, encoding="utf-8")
    return dest


def _write_report(cfg: AdapterConfig, file_hash: str, payload: dict) -> Path:
    out = cfg.archive_dir / "reports" / f"{file_hash[:12]}_{payload['file_name']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return out


def _try_archive(adapter: PosAdapter, cfg: AdapterConfig, src: Path, doc_id: int, file_hash: str,
                 quarantined: int, total: int) -> None:
    folder = "quarantine" if quarantined else "committed"
    note = None
    if quarantined:
        note = (f"Document #{doc_id}: {total - quarantined} of {total} items were already written "
                f"to the POS tables. {quarantined} item(s) wait in ep05_karantin.\n"
                f"Use quarantine_cli.py list / resolve. Do NOT re-send this file to 'fix' them.\n")
    try:
        dest = _archive(src, cfg, folder, doc_id, file_hash, note)
    except OSError as exc:
        adapter.mark_archived(doc_id, None, ok=False)
        log(f"[ARCHIVE] move failed ({exc}); DB commit is kept, only archiving will be retried")
        return
    adapter.mark_archived(doc_id, str(dest), ok=True)
    log(f"[ARCHIVE] -> {dest.relative_to(cfg.archive_dir)}")


def process_file(path: Path, cfg: AdapterConfig, adapter: PosAdapter, llm: LlmFn = ollama_pos_llm,
                 failure: FailureInjection | None = None, today: date | None = None,
                 wait: bool = True) -> dict[str, Any]:
    """The whole pipeline for one file. Returns a small summary dict."""
    t_start = time.perf_counter()
    if wait and not wait_until_ready(path, cfg):
        log(f"[SKIP] {path.name}: not ready or disappeared")
        return {"status": "not_ready"}

    # 1) private copy + hash (outside any transaction, no lock held)
    cfg.work_dir.mkdir(parents=True, exist_ok=True)
    work = cfg.work_dir / f"{uuid.uuid4().hex[:8]}_{path.name}"
    shutil.copy2(path, work)
    file_hash = sha256_file(work)
    if sha256_file(path) != file_hash:
        work.unlink(missing_ok=True)
        raise SourceChanged(f"{path.name} changed while being copied")
    log(f"[RECEIVED] {path.name} sha256={file_hash[:12]}")

    try:
        # 2) replay / archive-retry check before spending time on OCR or the model
        prev = adapter.find_document(file_hash)
        if prev:
            if prev["archived_at"] is None:
                log(f"[RETRY ARCHIVE] doc #{prev['id']} was committed earlier; only archiving now")
                _try_archive(adapter, cfg, path, prev["id"], file_hash,
                             prev["items_quarantined"], prev["items_total"])
                return {"status": "archive_retry", "doc_id": prev["id"]}
            dest = _archive(path, cfg, "duplicates", None, file_hash,
                            f"Same content as document #{prev['id']} ({prev['file_name']}). Nothing written.\n")
            log(f"[REPLAY] identical to doc #{prev['id']} -> nothing written, moved to duplicates/")
            return {"status": "duplicate", "doc_id": prev["id"], "archived": str(dest)}

        # 3) extraction (EP01/EP02/EP03) + independent completeness check
        t0 = time.perf_counter()
        doc = extract_any(work, cfg.model_name, llm, cfg.ocr_y_tolerance_px, cfg.ocr_min_confidence, today,
                          cfg.sku_min, cfg.sku_max, cfg.code_tables())
        candidates = reconcile(doc, cfg.sku_min, cfg.sku_max)
        extract_ms = round((time.perf_counter() - t0) * 1000, 1)
        tag = KIND_TAG[doc.kind]
        for line in doc.log:      # raw OCR rows and every raw model answer, visible in the console log
            if line.startswith(("model [", "raw ocr rows", "rows after spacing fix", "skew corrected")):
                log(f"  {line}")

        # 4) one transaction: lock, decide against current state, write, audit
        def still_unchanged() -> bool:
            return path.exists() and sha256_file(path) == file_hash

        t1 = time.perf_counter()
        result = adapter.apply_document(
            candidates, file_hash=file_hash, file_name=path.name, source_path=str(path),
            source_kind=doc.kind, model_name=doc.model_name,
            still_unchanged=still_unchanged, failure=failure)
        db_ms = round((time.perf_counter() - t1) * 1000, 1)
        if result.duplicate:   # another writer committed the same bytes meanwhile
            _archive(path, cfg, "duplicates", None, file_hash, "Committed by another writer.\n")
            log(f"[REPLAY] committed concurrently as doc #{result.doc_id}; nothing written")
            return {"status": "duplicate", "doc_id": result.doc_id}

        for it in result.items:
            c, d = it.candidate, it.decision
            price = f"${c.retail_price}" if c.retail_price is not None else "(no price)"
            extra = (f" {d.old_price} -> {c.retail_price}" if d.outcome == "UPDATE" else "")
            why = f"  [{d.reason}]" if d.outcome == QUARANTINE else ""
            log(f"  [{tag} {c.locator.split('/bbox')[0]}] {c.sku} {c.name or '?'} {price}"
                f" -> {d.outcome}{extra}{why}")
        q = result.count(QUARANTINE)
        total_ms = round((time.perf_counter() - t_start) * 1000, 1)
        metrics = doc.metrics or {}
        log(f"[COMMIT] doc #{result.doc_id}: INSERT {result.count('INSERT')}, UPDATE {result.count('UPDATE')},"
            f" NO_CHANGE {result.count('NO_CHANGE')}, QUARANTINE {q}"
            f" | extract {extract_ms} ms (model calls {metrics.get('model_calls', 0)},"
            f" first-call load {metrics.get('load_duration_ms', 0)} ms), db {db_ms} ms,"
            f" total {total_ms} ms")
        _write_report(cfg, file_hash, {
            "file_name": path.name, "sha256": file_hash, "doc_id": result.doc_id, "kind": doc.kind,
            "profile_version": cfg.profile_version, "model": doc.model_name, "metrics": metrics,
            "timing_ms": {"extract": extract_ms, "db": db_ms, "total": total_ms},
            "extraction_log": doc.log,
            "items": [{"candidate": i.candidate.to_dict(), "outcome": i.decision.outcome,
                       "reason": i.decision.reason, "detail": i.decision.detail} for i in result.items],
        })
        # 5) archive only after COMMIT
        _try_archive(adapter, cfg, path, result.doc_id, file_hash, q, len(result.items))
        return {"status": "committed", "doc_id": result.doc_id, "quarantined": q,
                "outcomes": {i.candidate.sku: i.decision.outcome for i in result.items}}
    except InjectedFailure as exc:
        reached = bool(exc.reached)
        status = "rolled_back" if reached else "failure_threshold_not_reached"
        log(f"[ROLLBACK{' VERIFIED STOP' if reached else ' INCOMPLETE PROBE'}] {exc}. "
            f"Actual mutations: {exc.actual_ops}; required: {exc.planned_ops}.")
        _archive(path, cfg, "failed", None, file_hash,
                 f"Rolled back by the demo failure injection: {exc}\n")
        result = {"status": status, "actual_ops": exc.actual_ops,
                  "planned_ops": exc.planned_ops, "injection_reached": reached,
                  "file_name": path.name, "sha256": file_hash}
        _write_report(cfg, file_hash, result)
        return result
    finally:
        work.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Watch mode
# ---------------------------------------------------------------------------

class Service:
    def __init__(self, cfg: AdapterConfig, adapter: PosAdapter, llm: LlmFn = ollama_pos_llm):
        self.cfg, self.adapter, self.llm = cfg, adapter, llm
        self.q: "queue.Queue[Path]" = queue.Queue()
        self.pending: set[Path] = set()
        self.attempts: dict[Path, int] = {}
        self.lock = threading.Lock()
        self.results: dict[Path, dict] = {}
        self.errors: dict[Path, str] = {}

    def enqueue(self, path: Path) -> None:
        path = Path(path)
        if path.parent.resolve() != self.cfg.incoming_dir.resolve() or not is_candidate_file(path, self.cfg):
            return
        with self.lock:
            if path in self.pending:
                return
            self.pending.add(path)
        self.q.put(path)

    def startup_scan(self) -> None:
        for p in sorted(self.cfg.incoming_dir.iterdir(), key=lambda p: p.stat().st_mtime):
            if p.is_file():
                self.enqueue(p)

    def worker(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                path = self.q.get(timeout=0.5)
            except queue.Empty:
                continue
            with self.lock:
                self.pending.discard(path)
            if not path.exists():
                continue
            try:
                result = process_file(path, self.cfg, self.adapter, self.llm)
                with self.lock:
                    self.results[path] = result
                    self.errors.pop(path, None)
                self.attempts.pop(path, None)
            except Exception as exc:  # DB down, source changed, OCR error ...
                n = self.attempts.get(path, 0) + 1
                self.attempts[path] = n
                if n < self.cfg.retry_limit and path.exists():
                    log(f"[RETRY {n}/{self.cfg.retry_limit}] {path.name}: {exc}")
                    time.sleep(1.0 * n)
                    self.enqueue(path)
                else:
                    with self.lock:
                        self.errors[path] = str(exc)
                    log(f"[FAILED] {path.name}: {exc} -> moved to failed/ (nothing committed)")
                    if path.exists():
                        try:
                            _archive(path, self.cfg, "failed", None, sha256_file(path), f"{exc}\n")
                        except OSError:
                            pass

    def start(self) -> None:
        """Start worker + watchdog observer, then scan files that arrived while stopped."""
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        svc = self

        class Handler(FileSystemEventHandler):
            def on_created(self, event):
                if not event.is_directory:
                    svc.enqueue(Path(event.src_path))

            def on_moved(self, event):     # Explorer "move" and *.part -> final rename
                if not event.is_directory:
                    svc.enqueue(Path(event.dest_path))

        self.cfg.incoming_dir.mkdir(parents=True, exist_ok=True)
        self._stop = threading.Event()
        self._worker = threading.Thread(target=self.worker, args=(self._stop,), daemon=True)
        self._worker.start()
        self._observer = Observer()
        self._observer.schedule(Handler(), str(self.cfg.incoming_dir), recursive=False)
        self._observer.start()
        self.startup_scan()
        log(f"[EP05] watching {self.cfg.incoming_dir}  db={self.cfg.db_name}  model={self.cfg.model_name}"
            f"  profile={self.cfg.profile_version}")

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join()
        self._stop.set()
        self._worker.join()

    def run(self) -> None:
        self.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()


def watcher_smoke(paths: list[Path], cfg: AdapterConfig, adapter: PosAdapter,
                  timeout_s: float = 600, llm: LlmFn = ollama_pos_llm) -> dict:
    """Exercise startup scan, .part rename and create events through real watch mode.

    A unique folder isolates the run from an already running normal service.
    The adapter still uses the selected demo DB. This does not reset that DB.
    """
    if len(paths) != 3 or len({p.name for p in paths}) != 3:
        raise ValueError("Watcher smoke requires three files with distinct names")
    for path in paths:
        if not path.is_file() or not is_candidate_file(path, cfg):
            raise ValueError(f"Missing or unsupported smoke input: {path}")
    run_dir = cfg.work_dir.parent / "ep05_watcher_smoke" / uuid.uuid4().hex
    run_cfg = dataclasses.replace(cfg, incoming_dir=run_dir / "incoming",
                                  work_dir=run_dir / "work", archive_dir=run_dir / "archive")
    run_cfg.incoming_dir.mkdir(parents=True)
    hashes = {path.name: sha256_file(path) for path in paths}
    # A prior processed hash would bypass extraction and invalidate this proof.
    if any(adapter.find_document(value) for value in hashes.values()):
        raise RuntimeError("Watcher smoke needs unprocessed input hashes (run after the demo seed reset)")
    first = run_cfg.incoming_dir / paths[0].name
    shutil.copy2(paths[0], first)
    svc = Service(run_cfg, adapter, llm)
    started = False
    deadline = time.monotonic() + timeout_s
    try:
        svc.start()
        started = True
        for index, source in enumerate(paths):
            target = run_cfg.incoming_dir / source.name
            if index == 1:
                part = target.with_name(target.name + ".part")
                shutil.copy2(source, part)
                # Observer must have time to see and reject the incomplete suffix.
                time.sleep(max(0.2, run_cfg.stable_interval_s))
                if adapter.find_document(hashes[source.name]) is not None:
                    raise RuntimeError("A .part input was processed before its final rename")
                part.rename(target)
            elif index == 2:
                shutil.copy2(source, target)
            while True:
                with svc.lock:
                    result = svc.results.get(target)
                    error = svc.errors.get(target)
                if error:
                    raise RuntimeError(f"Watcher failed {source.name}: {error}")
                if result is not None:
                    if result.get("status") != "committed":
                        raise RuntimeError(f"Watcher did not process a fresh document: {result}")
                    record = adapter.find_document(hashes[source.name])
                    if not record or record["archived_at"] is None or target.exists():
                        raise RuntimeError(f"Watcher did not complete archive of {source.name}")
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Watcher timed out waiting for {source.name}")
                time.sleep(0.1)
        result = {"status": "watcher_smoke_pass", "run_dir": str(run_dir),
                  "events_exercised": ["startup_scan", "moved_from_part", "created"],
                  "input_hashes": hashes, "documents_processed": 3}
        log("[WATCHER SMOKE PASS] startup scan, .part rename, created event; 3 fresh documents committed and archived")
        return result
    finally:
        if started:
            svc.stop()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path)
    ap.add_argument("--once", type=Path, help="process one file and exit")
    ap.add_argument("--watch-smoke", type=Path, nargs=3,
                    help="bounded real watcher rehearsal for three fresh documents")
    ap.add_argument("--watch-timeout", type=float, default=600)
    ap.add_argument("--result-json", type=Path, help="write a machine-checkable result")
    ap.add_argument("--demo-failure-injection", action="store_true",
                    help="rollback demo only; needs EP05_FAIL_AFTER_OPS")
    args = ap.parse_args()
    cfg = load_config(args.config)
    adapter = PosAdapter(cfg)
    failure = FailureInjection.from_env(args.demo_failure_injection)
    if args.watch_smoke:
        if args.once or failure:
            ap.error("--watch-smoke cannot be combined with --once or failure injection")
        res = watcher_smoke(args.watch_smoke, cfg, adapter, args.watch_timeout)
        if args.result_json:
            args.result_json.parent.mkdir(parents=True, exist_ok=True)
            args.result_json.write_text(json.dumps(res, indent=2), encoding="utf-8")
        return 0
    if args.once:
        # The original (e.g. demo_inputs/fail_probe.txt) is never moved: a copy is
        # processed from a separate manual folder, so a running watch service
        # does not pick it up as well.
        manual = cfg.work_dir.parent / "ep05_manual" / uuid.uuid4().hex
        manual.mkdir(parents=True, exist_ok=True)
        staged = manual / args.once.name
        shutil.copy2(args.once, staged)
        res = process_file(staged, cfg, adapter, failure=failure)
        if args.result_json:
            args.result_json.parent.mkdir(parents=True, exist_ok=True)
            args.result_json.write_text(json.dumps(res, indent=2), encoding="utf-8")
        if not any(manual.iterdir()):
            manual.rmdir()
        return 0 if res.get("status") in {"committed", "duplicate", "archive_retry", "rolled_back"} else 1
    if failure:
        print("--demo-failure-injection is only allowed together with --once")
        return 2
    Service(cfg, adapter).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
