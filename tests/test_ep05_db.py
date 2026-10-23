"""
EP05 database tests against a real MariaDB/MySQL server.

DESTRUCTIVE for kasa_ep05 (it is reset many times). Opt-in only:
    $env:EP05_DB_TESTS = "1"
    $env:EP05_DB_PASSWORD = "..."          # ep05_demo password
    $env:EP05_ADMIN_PASSWORD = ""          # XAMPP root has an empty password
    python -m pytest tests\\test_ep05_db.py -v

The model is replaced by tests/ep05_fakes.scripted_llm; the real model is
exercised by run_ep05_rehearsal.ps1.
"""

import dataclasses
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ep05_fakes import scripted_llm  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / "ep05_fiscal_ingest_robot" / "demo_inputs"
PHOTO = INPUTS / "shelf_tags_photo.jpg"  # Real demo photo; ambiguous synthetic OCR is tested separately.
DOCS = ["register_update_message.txt", "approved_retail_price_update.pdf", "shelf_tags_photo.jpg"]

ENABLED = os.environ.get("EP05_DB_TESTS") == "1"


def reset_db(cfg):
    import pymysql
    from ep05_fiscal_ingest_robot import setup_demo_db as setup
    admin = pymysql.connect(host=cfg.db_host, port=cfg.db_port,
                            user=os.environ.get("EP05_ADMIN_USER", "root"),
                            password=os.environ.get("EP05_ADMIN_PASSWORD", ""), charset="utf8")
    try:
        setup.run_file(admin, setup.SQL_DIR / "01_schema.sql")
        setup.run_file(admin, setup.SQL_DIR / "02_seed.sql")
        with admin.cursor() as cur:
            for host in ("localhost", "127.0.0.1"):
                cur.execute("CREATE USER IF NOT EXISTS %s@%s IDENTIFIED BY %s", (cfg.db_user, host, cfg.db_password()))
        admin.commit()
        setup.run_file(admin, setup.SQL_DIR / "03_user.sql")
    finally:
        admin.close()


@unittest.skipUnless(ENABLED, "set EP05_DB_TESTS=1 (destructive for kasa_ep05)")
class Ep05Database(unittest.TestCase):
    def setUp(self):
        from ep05_fiscal_ingest_robot.adapter_config import load_config
        from ep05_fiscal_ingest_robot.mysql_pos_adapter import PosAdapter
        self.tmp = Path(tempfile.mkdtemp(prefix="ep05_"))
        base = load_config()
        self.cfg = dataclasses.replace(base, incoming_dir=self.tmp / "in", work_dir=self.tmp / "work",
                                       archive_dir=self.tmp / "archive", stable_interval_s=0.05)
        self.cfg.incoming_dir.mkdir(parents=True)
        reset_db(self.cfg)
        self.adapter = PosAdapter(self.cfg)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # helpers ---------------------------------------------------------------
    def drop(self, name, dest_name=None):
        src = PHOTO if name == "shelf_tags_photo.jpg" else INPUTS / name
        dest = self.cfg.incoming_dir / (dest_name or name)
        shutil.copy(src, dest)
        return dest

    def process(self, path, **kw):
        from ep05_fiscal_ingest_robot.pos_watch_service import process_file
        return process_file(path, self.cfg, self.adapter, kw.pop("llm", scripted_llm), **kw)

    def q(self, sql, args=()):
        conn = self.adapter.connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, args)
                return list(cur.fetchall())
        finally:
            conn.close()

    def counts(self):
        a = self.q("SELECT COUNT(*) n FROM artikli WHERE art_broj BETWEEN 95001 AND 95099")[0]["n"]
        o = self.q("SELECT COUNT(*) n FROM ep05_karantin WHERE status='OPEN'")[0]["n"]
        return a, o

    def karantin_id(self, sku):
        return self.q("SELECT id FROM ep05_karantin WHERE art_broj=%s AND status='OPEN'", (sku,))[0]["id"]


    def write_sql(self, sql, args=()):
        """Mutate only this class's opt-in, freshly reset demo database."""
        conn = self.adapter.connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, args)
            conn.commit()
        finally:
            conn.close()

    def write_document(self, filename, rows):
        path = self.cfg.incoming_dir / filename
        path.write_text("All retail prices USD, before sales tax. Effective today.\n" + rows + "\n", encoding="utf-8")
        return path

    # tests -----------------------------------------------------------------
    def test_full_sequence_in_both_orders(self):
        from ep05_fiscal_ingest_robot.snapshot_demo_state import take_snapshot
        from ep05_fiscal_ingest_robot.mysql_pos_adapter import FailureInjection
        for order in (DOCS, list(reversed(DOCS))):
            with self.subTest(order=order):
                reset_db(self.cfg)
                self.assertEqual(self.counts(), (5, 0))
                for name in order:
                    self.process(self.drop(name))
                self.assertEqual(self.counts(), (27, 3))
                self.assertEqual(self.q("SELECT cij FROM artikli WHERE art_broj=95001")[0]["cij"], Decimal("13.49"))
                res = self.adapter.resolve(self.karantin_id(95012), operator="t", confirmation="c",
                                           price=Decimal("3.49"))
                self.assertEqual(res["effect"], "INSERT")
                self.assertEqual(self.counts(), (28, 2))
                self.assertEqual(self.process(self.drop(DOCS[0]))["status"], "duplicate")
                self.assertEqual(self.counts(), (28, 2))
                before = take_snapshot(self.cfg)
                probe = self.tmp / "fail_probe.txt"
                shutil.copy(INPUTS / "fail_probe.txt", probe)
                proof = self.process(probe, failure=FailureInjection(3))
                self.assertEqual(proof["status"], "rolled_back")
                self.assertEqual((proof["actual_ops"], proof["planned_ops"], proof["injection_reached"]), (3, 3, True))
                self.assertEqual(take_snapshot(self.cfg)["sha256"], before["sha256"])

    def test_failure_probe_never_commits_even_if_injection_point_is_missed(self):
        from ep05_fiscal_ingest_robot.snapshot_demo_state import take_snapshot
        from ep05_fiscal_ingest_robot.mysql_pos_adapter import FailureInjection
        before = take_snapshot(self.cfg)
        probe = self.tmp / "fail_probe.txt"
        shutil.copy(INPUTS / "fail_probe.txt", probe)
        # 99 > number of mutations in the probe: the stop point is never reached
        proof = self.process(probe, failure=FailureInjection(99))
        self.assertEqual(proof["status"], "failure_threshold_not_reached")
        self.assertFalse(proof["injection_reached"])
        self.assertEqual(proof["planned_ops"], 99)
        self.assertLess(proof["actual_ops"], 99)
        self.assertEqual(take_snapshot(self.cfg)["sha256"], before["sha256"])

    def test_same_bytes_under_another_name_are_not_written_twice(self):
        self.process(self.drop(DOCS[0]))
        res = self.process(self.drop(DOCS[0], "copy_of_message.txt"))
        self.assertEqual(res["status"], "duplicate")
        self.assertEqual(self.counts(), (7, 1))

    def test_concurrent_writers_same_document(self):
        a, b = self.drop(DOCS[1]), self.drop(DOCS[1], "same_pdf_second_name.pdf")
        results = []
        threads = [threading.Thread(target=lambda p=p: results.append(self.process(p))) for p in (a, b)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(sorted(r["status"] for r in results), ["committed", "duplicate"])
        self.assertEqual(self.counts(), (23, 2))

    def test_resolver_double_submit_is_idempotent(self):
        self.process(self.drop(DOCS[0]))
        kid = self.karantin_id(95012)
        out = []

        def go():
            out.append(self.adapter.resolve(kid, operator="t", confirmation="c", price=Decimal("3.49")))
        threads = [threading.Thread(target=go) for _ in range(3)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(sorted(r["effect"] for r in out), ["INSERT", "none", "none"])
        self.assertEqual(len(self.q("SELECT id FROM artikli WHERE art_broj=95012")), 1)
        row = self.q("SELECT value_source FROM ep05_stavke WHERE art_broj=95012 AND outcome='INSERT'")
        self.assertEqual([r["value_source"] for r in row], ["operator"])

    def test_resolver_refuses_non_price_problems_and_reject_works(self):
        from ep05_fiscal_ingest_robot.mysql_pos_adapter import ResolutionRefused
        self.process(self.drop(DOCS[1]))
        kid = self.karantin_id(95033)
        with self.assertRaises(ResolutionRefused):
            self.adapter.resolve(kid, operator="t", confirmation="c", price=Decimal("2.79"))
        self.assertEqual(self.counts(), (23, 2))
        self.assertEqual(self.adapter.resolve(kid, operator="t", confirmation="c", reject=True)["status"], "REJECTED")
        self.assertEqual(self.counts(), (23, 1))

    def test_archive_failure_retries_only_the_archive(self):
        import ep05_fiscal_ingest_robot.pos_watch_service as svc
        path = self.drop(DOCS[0])
        real_move = shutil.move
        calls = {"n": 0}

        def flaky(src, dst):
            calls["n"] += 1
            if calls["n"] == 1:
                raise PermissionError("file locked by antivirus")
            return real_move(src, dst)
        with patch.object(svc.shutil, "move", side_effect=flaky):
            self.assertEqual(self.process(path)["status"], "committed")
        self.assertTrue(path.exists())
        doc = self.q("SELECT archived_at, archive_attempts FROM ep05_dokumenti")[0]
        self.assertIsNone(doc["archived_at"])
        stavke_before = self.q("SELECT COUNT(*) n FROM ep05_stavke")[0]["n"]
        self.assertEqual(self.process(path)["status"], "archive_retry")
        self.assertEqual(self.q("SELECT COUNT(*) n FROM ep05_stavke")[0]["n"], stavke_before)
        self.assertIsNotNone(self.q("SELECT archived_at FROM ep05_dokumenti")[0]["archived_at"])
        self.assertFalse(path.exists())
        notes = list((self.cfg.archive_dir / "quarantine").glob("*.NOTE.txt"))
        self.assertEqual(len(notes), 1)
        self.assertIn("already written", notes[0].read_text(encoding="utf-8"))

    def test_source_changed_before_commit_writes_nothing(self):
        from ep05_fiscal_ingest_robot.mysql_pos_adapter import SourceChanged
        path = self.drop(DOCS[0])

        def llm_that_sees_file_change(numbered, model):
            path.write_text(path.read_text(encoding="utf-8") + "\n95013 Late Line | EA | tax T | $1.00\n",
                            encoding="utf-8")
            return scripted_llm(numbered, model)
        with self.assertRaises(SourceChanged):
            self.process(path, llm=llm_that_sees_file_change)
        self.assertEqual(self.counts(), (5, 0))
        self.assertEqual(self.q("SELECT COUNT(*) n FROM ep05_dokumenti")[0]["n"], 0)

    def test_service_restart_scan_and_watch_events(self):
        from ep05_fiscal_ingest_robot.pos_watch_service import Service
        self.drop(DOCS[0])                                     # arrived while "stopped"
        s = Service(self.cfg, self.adapter, scripted_llm)
        s.start()
        try:
            part = self.cfg.incoming_dir / "approved_retail_price_update.pdf.part"
            shutil.copy(INPUTS / DOCS[1], part)               # ignored while .part
            time.sleep(0.5)
            part.rename(self.cfg.incoming_dir / DOCS[1])      # moved event
            self.drop(DOCS[2])                                 # created event
            deadline = time.time() + 60
            while time.time() < deadline and self.q("SELECT COUNT(*) n FROM ep05_dokumenti")[0]["n"] < 3:
                time.sleep(0.3)
        finally:
            s.stop()
        self.assertEqual(self.counts(), (27, 3))
        self.assertEqual(list(self.cfg.incoming_dir.iterdir()), [])


    def test_direct_empty_candidate_list_is_a_review_document(self):
        result = self.adapter.apply_document([], file_hash="e" * 64, file_name="unrecognized.txt",
                                             source_path="unrecognized.txt", source_kind="text", model_name=None)
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].decision.reason, "DOCUMENT_UNRECOGNIZED")
        self.assertEqual(self.counts(), (5, 1))
        doc = self.q("SELECT status,items_total,items_quarantined FROM ep05_dokumenti")[0]
        self.assertEqual((doc["status"], doc["items_total"], doc["items_quarantined"]), ("COMMITTED_WITH_QUARANTINE", 1, 1))

    def test_out_of_range_document_is_a_visible_review(self):
        path = self.write_document("out_of_range.txt", "94000 Test Outside Item | EA | tax T | $1.99")
        self.process(path)
        self.assertEqual(self.counts(), (5, 1))
        self.assertEqual(self.q("SELECT art_broj FROM ep05_karantin")[0]["art_broj"], 94000)

    def test_stale_new_sku_review_cannot_overwrite_another_document(self):
        from ep05_fiscal_ingest_robot.mysql_pos_adapter import ResolutionRefused
        self.process(self.drop(DOCS[0]))
        kid = self.karantin_id(95012)
        self.process(self.write_document("new_tea_price.txt", "95012 Mint Tea 20 ct | EA | tax T | $4.49"))
        with self.assertRaisesRegex(ResolutionRefused, "POS state changed"):
            self.adapter.resolve(kid, operator="operator", confirmation="stale form", price=Decimal("3.49"))
        self.assertEqual(self.q("SELECT cij FROM artikli WHERE art_broj=95012")[0]["cij"], Decimal("4.49"))
        self.assertEqual(self.q("SELECT status FROM ep05_karantin WHERE id=%s", (kid,))[0]["status"], "OPEN")

    def test_stale_existing_price_review_cannot_overwrite_a_newer_price(self):
        from ep05_fiscal_ingest_robot.mysql_pos_adapter import ResolutionRefused
        self.process(self.write_document("ask_existing_price.txt", "95001 Espresso Beans 1 lb | EA | tax T | ask for price"))
        kid = self.karantin_id(95001)
        self.process(self.write_document("new_espresso_price.txt", "95001 Espresso Beans 1 lb | EA | tax T | $13.99"))
        with self.assertRaisesRegex(ResolutionRefused, "POS state changed"):
            self.adapter.resolve(kid, operator="operator", confirmation="stale form", price=Decimal("13.49"))
        self.assertEqual(self.q("SELECT cij FROM artikli WHERE art_broj=95001")[0]["cij"], Decimal("13.99"))

    def test_missing_live_lookup_reference_cannot_insert(self):
        for attribute, mapping in (("tax_class_map", {"T": 999}), ("sales_unit_map", {"EA": 999})):
            with self.subTest(attribute=attribute):
                reset_db(self.cfg)
                cfg = dataclasses.replace(self.cfg, **{attribute: mapping})
                path = self.write_document(attribute + ".txt", "95060 Lookup Test Item | EA | tax T | $1.99")
                with patch.object(self.adapter, "cfg", cfg):
                    self.process(path)
                self.assertEqual(self.counts(), (5, 1))
                self.assertEqual(self.q("SELECT reason FROM ep05_karantin")[0]["reason"], "POS_REFERENCE_INVALID")

    def test_existing_orphan_lookup_cannot_approve_a_price_change(self):
        self.write_sql("UPDATE artikli SET jedmjer='999' WHERE art_broj=95001")
        self.process(self.write_document("orphan_unit.txt", "Set Espresso Beans 1 lb, SKU 95001, to $13.49 effective today."))
        self.assertEqual(self.q("SELECT cij FROM artikli WHERE art_broj=95001")[0]["cij"], Decimal("12.99"))
        self.assertEqual(self.q("SELECT reason FROM ep05_karantin")[0]["reason"], "POS_REFERENCE_INVALID")

    def test_inactive_unit_is_checked_at_runtime(self):
        self.write_sql("UPDATE jmjera SET deleted=1 WHERE id=1")
        self.process(self.write_document("inactive_unit.txt", "95060 Lookup Test Item | EA | tax T | $1.99"))
        self.assertEqual(self.counts(), (5, 1))
        self.assertEqual(self.q("SELECT reason FROM ep05_karantin")[0]["reason"], "POS_REFERENCE_INVALID")

    def test_demo_account_cannot_delete_or_drop(self):
        import pymysql
        for sql in ("DELETE FROM artikli WHERE art_broj = 95001", "DROP TABLE ep05_karantin"):
            with self.subTest(sql=sql), self.assertRaises(pymysql.err.OperationalError):
                self.q(sql)


if __name__ == "__main__":
    unittest.main()
