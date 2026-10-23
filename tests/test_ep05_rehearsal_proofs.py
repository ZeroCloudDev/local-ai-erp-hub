"""Proof gates without MariaDB or a model; watcher test uses real filesystem events."""

from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ep05_fiscal_ingest_robot.adapter_config import load_config
from ep05_fiscal_ingest_robot.mysql_pos_adapter import InjectedFailure
from ep05_fiscal_ingest_robot import pos_watch_service as service
from ep05_fiscal_ingest_robot.snapshot_demo_state import snapshot_path, validate_snapshot
from ep05_fiscal_ingest_robot.verify_demo import Checker, check_failure_result, compare_document_outcomes


class ProofGates(unittest.TestCase):
    def checker(self, function, *args):
        checker = Checker()
        with redirect_stdout(io.StringIO()):
            function(*args, checker)
        return checker.failures

    def test_rollback_requires_exactly_three_completed_mutations(self):
        good = dict(status="rolled_back", injection_reached=True, actual_ops=3, planned_ops=3)
        self.assertEqual(self.checker(check_failure_result, good), 0)
        for bad in (dict(good, actual_ops=0), dict(good, actual_ops=2), dict(good, injection_reached=False),
                    dict(good, planned_ops=99), dict(good, actual_ops=True),
                    dict(good, status="failure_threshold_not_reached"), {}):
            with self.subTest(result=bad):
                self.assertGreater(self.checker(check_failure_result, bad), 0)

    def test_audit_duplicates_and_wrong_new_price_fail(self):
        expected = {"input.txt": {"row_count": 1, "items": {
            "95001": {"outcome": ["UPDATE"], "old_price": "12.99", "new_price": "13.49"}}}}
        row = dict(file_name="input.txt", art_broj=95001, value_source="source", outcome="UPDATE",
                   reason="", old_price="12.99", new_price="13.49")
        self.assertEqual(self.checker(compare_document_outcomes, {"stavke": [row]}, expected), 0)
        for rows in ([row, dict(row)], [dict(row, new_price="99.00")], [], [dict(row, art_broj=None)]):
            with self.subTest(rows=rows):
                self.assertGreater(self.checker(compare_document_outcomes, {"stavke": rows}, expected), 0)

    def test_row_count_cannot_be_ignored(self):
        expected = {"empty.txt": {"row_count": 20, "items": {}}}
        self.assertGreater(self.checker(compare_document_outcomes, {"stavke": []}, expected), 0)

    def test_snapshot_hash_is_recomputed_and_path_escape_rejected(self):
        tables = {"artikli": [{"id": "a", "price": "1.00"}]}
        digest = hashlib.sha256(json.dumps(tables, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        snapshot = {"tables": tables, "sha256": digest}
        self.assertTrue(validate_snapshot(snapshot))
        snapshot["tables"]["artikli"][0]["price"] = "2.00"
        self.assertFalse(validate_snapshot(snapshot))
        cfg = load_config()
        for label in ("../before", "a/b", "..", "", "C:\\other"):
            with self.subTest(label=label), self.assertRaises(ValueError):
                snapshot_path(cfg, label)


class IsolatedServiceProof(unittest.TestCase):
    def setUp(self):
        self.root_parent = Path.cwd().resolve()
        self.temp = tempfile.TemporaryDirectory(prefix="ep05-proof-tests-", dir=self.root_parent)
        self.addCleanup(self.cleanup)
        self.root = Path(self.temp.name)
        import dataclasses
        self.cfg = dataclasses.replace(load_config(), incoming_dir=self.root / "in",
                                       work_dir=self.root / "work", archive_dir=self.root / "archive",
                                       stable_interval_s=0.01, stable_checks=1, max_wait_s=2)

    def cleanup(self):
        target = Path(self.temp.name).resolve()
        if target.parent != self.root_parent or not target.name.startswith("ep05-proof-tests-"):
            raise RuntimeError("Unsafe test cleanup target")
        self.temp.cleanup()

    def test_service_distinguishes_safety_rollback_from_reached_injection(self):
        for actual, planned, reached, expected_status in (
            (0, 3, False, "failure_threshold_not_reached"), (3, 3, True, "rolled_back")):
            with self.subTest(actual=actual, reached=reached):
                source = self.root / f"probe-{actual}.txt"
                source.write_text("isolated test source", encoding="utf-8")
                exception = InjectedFailure("test", actual_ops=actual, planned_ops=planned, reached=reached)
                adapter = SimpleNamespace(find_document=lambda value: None)
                def fail(*args, **kwargs):
                    raise exception
                adapter.apply_document = fail
                document = SimpleNamespace(kind="text", model_name="test-double", log=[], metrics={})
                with patch.object(service, "extract_any", return_value=document), \
                        patch.object(service, "reconcile", return_value=[]), redirect_stdout(io.StringIO()):
                    result = service.process_file(source, self.cfg, adapter, wait=False)
                self.assertEqual(result["status"], expected_status)
                self.assertEqual((result["actual_ops"], result["planned_ops"], result["injection_reached"]),
                                 (actual, planned, reached))

    @unittest.skipUnless(importlib.util.find_spec("watchdog"), "watchdog is not installed")
    def test_real_watcher_events_use_isolated_folders(self):
        paths = []
        for index in range(3):
            path = self.root / f"source-{index}.txt"
            path.write_text(f"isolated source {index}", encoding="utf-8")
            paths.append(path)
        records, seen = {}, []
        lock = threading.Lock()
        class Adapter:
            def find_document(self, digest):
                with lock:
                    return records.get(digest)
        def process(path, cfg, adapter, llm):
            digest = service.sha256_file(path)
            cfg.archive_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(cfg.archive_dir / path.name))
            with lock:
                seen.append(path.name)
                records[digest] = {"archived_at": "isolated test"}
            return {"status": "committed"}
        with patch.object(service, "process_file", side_effect=process), redirect_stdout(io.StringIO()):
            result = service.watcher_smoke(paths, self.cfg, Adapter(), timeout_s=5)
        self.assertEqual(result["status"], "watcher_smoke_pass")
        self.assertEqual(seen, [path.name for path in paths])
        self.assertEqual(result["events_exercised"], ["startup_scan", "moved_from_part", "created"])
        self.assertTrue(all(path.exists() for path in paths), "Original inputs must be preserved")


if __name__ == "__main__":
    unittest.main()
