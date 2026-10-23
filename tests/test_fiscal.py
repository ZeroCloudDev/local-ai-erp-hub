import concurrent.futures
from contextlib import ExitStack, closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from core.schemas import FiscalItem
from ep05_fiscal_ingest_robot import fiscal_ingest_service as service


class FiscalParserTests(unittest.TestCase):
    def test_local_text_and_bom(self):
        items = service.parse_viber_text("\ufeffEvo ubaci mi:\nKafa 1kg - 28.50 KM\nSecer - 11 BAM\nCaj - vidi cijenu sa sefom", "input.txt")
        self.assertEqual([item.naziv for item in items], ["Kafa 1kg", "Secer", "Caj - vidi cijenu sa sefom"])
        self.assertEqual([item.cijena_sa_pdv for item in items], [28.5, 11, None])
        self.assertEqual(items[0].status_validacije, "APPROVED")
        self.assertTrue(items[2].status_validacije.startswith("QUARANTINE"))

    def test_negative_zero_and_malformed_prices_quarantined(self):
        for text in ("Kafa - -5 KM", "Kafa -5 KM", "Kafa - 0 KM", "Kafa 1.234 KM", "Kafa 1,234.56 KM", "Kafa -NaN KM", "Kafa - inf KM", "Kafa 1 234 KM", "Kafa - - 5 KM"):
            with self.subTest(text=text):
                item = service.parse_viber_text(text, "x.txt")[0]
                self.assertTrue(item.status_validacije.startswith("QUARANTINE"))
                self.assertIsNone(item.cijena_sa_pdv)

    def test_model_number_is_not_price(self):
        item = service.parse_viber_text("Artikal model 123", "x.txt")[0]
        self.assertTrue(item.status_validacije.startswith("QUARANTINE"))
        self.assertIsNone(item.cijena_sa_pdv)

    def test_foreign_currency_is_never_approved_as_km(self):
        for text in ("Kafa - $12.50", "Kafa - 12.50 EUR", "Kafa - 12.50 USD", "Kafa - USD 12.50 KM"):
            with self.subTest(text=text):
                item = service.parse_viber_text(text, "x.txt")[0]
                self.assertEqual(item.status_validacije, "QUARANTINE_CURRENCY")
                self.assertEqual(item.cijena_sa_pdv, 12.5)

    def test_pdf_uses_unit_price_header_not_specs_or_line_total(self):
        mapping = service._table_columns(["SKU", "Description", "Qty", "Line Total KM", "Unit Price KM"])
        item = service.extract_fiscal_from_table_row(["A-001", "Connector 2.54mm", "4", "50.00", "12.50"], mapping)
        self.assertEqual(item.naziv, "Connector 2.54mm")
        self.assertEqual(item.sifra, "A-001")
        self.assertEqual(item.cijena_bez_pdv, 12.5)
        self.assertEqual(item.cijena_sa_pdv, 14.63)
        self.assertEqual(item.status_validacije, "APPROVED")

    def test_pdf_missing_header_currency_or_negative_price_quarantines(self):
        mapping = service._table_columns(["SKU", "Description", "Unit Price KM"])
        for price in ("-12.50", "12.345", "", "12,345.00"):
            with self.subTest(price=price):
                item = service.extract_fiscal_from_table_row(["A", "Part 2.54mm", price], mapping)
                self.assertTrue(item.status_validacije.startswith("QUARANTINE"))
        self.assertTrue(service.extract_fiscal_from_table_row(["A", "Part 2.54mm", "12.50"]).status_validacije.startswith("QUARANTINE"))

    def test_image_rows_preserve_names_unit_prices_and_unpriced_items(self):
        from ep03_fast_cpu_ocr import ocr_pipeline
        aligned = "Vendor: Shop\nCurrency: KM\nQty: 4 | Bolts M8 | Unit: 12.50 | Total: 50.00\nQty: 1 | New tea | Unit: ask boss\nOverallReceiptTotal: 50.00"
        with patch.object(ocr_pipeline, "get_ocr_engine", return_value=lambda image: ([], None)), patch.object(ocr_pipeline, "preprocess_receipt_image", return_value=None), patch.object(ocr_pipeline, "sort_ocr_boxes_into_rows", return_value=aligned):
            items = service.parse_image_receipt(Path("mock.png"))
        self.assertEqual([item.naziv for item in items], ["Bolts M8", "New tea"])
        self.assertEqual(items[0].cijena_sa_pdv, 12.5)
        self.assertEqual(items[0].status_validacije, "APPROVED")
        self.assertTrue(items[1].status_validacije.startswith("QUARANTINE"))

    def test_missing_description_is_not_approved(self):
        mapping = service._table_columns(["SKU", "Description", "Unit Price KM"])
        item = service.extract_fiscal_from_table_row(["A", "", "12.50"], mapping)
        self.assertEqual(item.status_validacije, "QUARANTINE_MISSING_NAME")
        from ep03_fast_cpu_ocr import ocr_pipeline
        with patch.object(ocr_pipeline, "get_ocr_engine", return_value=lambda image: ([], None)), patch.object(ocr_pipeline, "preprocess_receipt_image", return_value=None), patch.object(ocr_pipeline, "sort_ocr_boxes_into_rows", return_value="Qty: 2 | Unit: 12.50 KM | Total: 25.00 KM"):
            items = service.parse_image_receipt(Path("missing_name.png"))
        self.assertEqual(items[0].status_validacije, "QUARANTINE_MISSING_NAME")

    def test_blank_image_quarantines(self):
        from ep03_fast_cpu_ocr import ocr_pipeline
        with patch.object(ocr_pipeline, "get_ocr_engine", return_value=lambda image: ([], None)), patch.object(ocr_pipeline, "preprocess_receipt_image", return_value=None), patch.object(ocr_pipeline, "sort_ocr_boxes_into_rows", return_value=""):
            items = service.parse_image_receipt(Path("blank.png"))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].status_validacije, "QUARANTINE_EMPTY_EXTRACTION")

    def test_shipped_pdf_is_extracted_but_usd_requires_review(self):
        items = service.parse_pdf_catalog(service.BASE_DIR / "data/incoming_fiskal/veleprodaja_cjenik.pdf")
        self.assertEqual(len(items), 3)
        self.assertEqual([item.cijena_bez_pdv for item in items], [11.2, 14.5, 29.0])
        self.assertTrue(all(item.status_validacije == "QUARANTINE_CURRENCY" for item in items))

    def test_shipped_image_real_ocr(self):
        items = service.parse_image_receipt(service.BASE_DIR / "data/incoming_fiskal/papir_dopis.png")
        self.assertEqual(len(items), 3)
        self.assertEqual([item.cijena_sa_pdv for item in items], [12.5, 18.0, 210.0])
        self.assertIn("Bolts", items[0].naziv)
        self.assertIn("Threadlocker", items[1].naziv)
        self.assertIn("Multimeter", items[2].naziv)
        self.assertTrue(all(item.status_validacije == "QUARANTINE_CURRENCY" for item in items))


class FiscalStorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.assertTrue(Path(self.directory.name).resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()))
        base = Path(self.directory.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key, value in {"DB_PATH":base/"data/ledger.db", "INCOMING_DIR":base/"incoming", "APPROVED_DIR":base/"processed/approved", "QUARANTINE_DIR":base/"processed/quarantine"}.items():
            self.stack.enter_context(patch.object(service,key,value))

    def counts(self):
        with closing(sqlite3.connect(str(service.DB_PATH))) as conn:
            return tuple(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ("fiscal_items", "fiscal_quarantine", "processed_fiscal_files"))

    def test_commit_hash_idempotence_under_concurrency(self):
        items = [FiscalItem(naziv="Coffee", cijena_sa_pdv=11.7)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda _:service.commit_items_to_db(items,"same.txt","a"*64), range(8)))
        self.assertEqual(results, [(1,0)]*8)
        self.assertEqual(self.counts(), (1,0,1))

    def test_existing_gemini_receipts_migrate_without_reimport(self):
        service.init_fiscal_db()
        with closing(sqlite3.connect(str(service.DB_PATH))) as conn:
            conn.execute("DROP TABLE processed_fiscal_files")
            conn.execute("CREATE TABLE processed_fiscal_files (file_hash TEXT PRIMARY KEY, file_name TEXT NOT NULL, status TEXT NOT NULL, items_count INTEGER DEFAULT 0, processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            conn.executemany("INSERT INTO processed_fiscal_files (file_hash,file_name,status,items_count) VALUES (?,?,?,?)", [("old-approved", "original.txt", "APPROVED", 2), ("old-review", "review.txt", "QUARANTINE", 1)])
            conn.execute("INSERT INTO fiscal_items (naziv,cijena_sa_pdv,source_doc) VALUES ('Original coffee',11.70,'original.txt')")
            conn.execute("INSERT INTO fiscal_items (naziv,cijena_sa_pdv,source_doc) VALUES ('Original sugar',2.34,'original.txt')")
            conn.execute("INSERT INTO fiscal_quarantine (naziv,razlog_karantina,source_doc) VALUES ('Original tea','Missing price','review.txt')")
            conn.commit()
        service.init_fiscal_db()
        with closing(sqlite3.connect(str(service.DB_PATH))) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(processed_fiscal_files)")}
            self.assertTrue({"approved_count", "quarantine_count"}.issubset(columns))
            original_receipts = conn.execute("SELECT file_hash,file_name,status,items_count,processed_at FROM processed_fiscal_files ORDER BY file_hash").fetchall()
        replacement_items = [FiscalItem(naziv="Must not insert", cijena_sa_pdv=99.45)]
        self.assertEqual(service.commit_items_to_db(replacement_items, "repeat.txt", "old-approved"), (2,0))
        self.assertEqual(service.commit_items_to_db(replacement_items, "repeat.txt", "old-review"), (0,1))
        self.assertEqual(self.counts(), (2,1,2))
        with closing(sqlite3.connect(str(service.DB_PATH))) as conn:
            self.assertEqual(conn.execute("SELECT naziv FROM fiscal_items ORDER BY id").fetchall(), [("Original coffee",), ("Original sugar",)])
            self.assertEqual(conn.execute("SELECT naziv FROM fiscal_quarantine").fetchall(), [("Original tea",)])
            self.assertEqual(conn.execute("SELECT file_hash,file_name,status,items_count,processed_at FROM processed_fiscal_files ORDER BY file_hash").fetchall(), original_receipts)

    def test_transaction_rolls_back_rows_and_hash_on_failure(self):
        service.init_fiscal_db()
        with closing(sqlite3.connect(str(service.DB_PATH))) as conn:
            conn.execute("CREATE TRIGGER fail_insert BEFORE INSERT ON fiscal_items WHEN NEW.naziv = 'Fail' BEGIN SELECT RAISE(ABORT, 'test'); END")
        items = [FiscalItem(naziv="Good", cijena_sa_pdv=2.34), FiscalItem(naziv="Fail", cijena_sa_pdv=2.34)]
        with self.assertRaises(sqlite3.IntegrityError):
            service.commit_items_to_db(items,"test.txt","b"*64)
        self.assertEqual(self.counts(), (0,0,0))

    def test_direct_processing_initializes_db_and_dirs_and_keeps_bom_clean(self):
        source = Path(self.directory.name)/"invoice.txt"
        source.write_text("\ufeffEvo ubaci mi:\nCoffee - 11.70 KM", encoding="utf-8")
        service.process_incoming_file(source)
        self.assertFalse(source.exists())
        self.assertTrue((service.APPROVED_DIR/"invoice.txt").exists())
        self.assertEqual(self.counts(), (1,0,1))

    def test_archive_failure_retry_does_not_duplicate(self):
        source = Path(self.directory.name)/"invoice.txt"
        source.write_text("Coffee - 11.70 KM", encoding="utf-8")
        with patch.object(service.shutil, "move", side_effect=OSError("test move failure")):
            with self.assertRaises(OSError):
                service.process_incoming_file(source)
        self.assertEqual(self.counts(), (1,0,1))
        self.assertTrue(source.exists())
        service.process_incoming_file(source)
        self.assertEqual(self.counts(), (1,0,1))
        self.assertFalse(source.exists())

    def test_same_filename_distinct_contents_preserve_archives(self):
        source = Path(self.directory.name)/"invoice.txt"
        for text in ("Coffee - 11.70 KM", "Sugar - 2.34 KM"):
            source.write_text(text, encoding="utf-8")
            service.process_incoming_file(source)
        archived = sorted(path.read_text(encoding="utf-8") for path in service.APPROVED_DIR.iterdir())
        self.assertEqual(archived, ["Coffee - 11.70 KM", "Sugar - 2.34 KM"])
        self.assertEqual(self.counts(), (2,0,2))

    def test_empty_file_and_mixed_file_go_to_quarantine(self):
        for filename, text in (("empty.txt",""), ("mixed.txt","Coffee - 11.70 KM\nTea - ask boss")):
            source = Path(self.directory.name)/filename
            source.write_text(text, encoding="utf-8")
            service.process_incoming_file(source)
            self.assertTrue((service.QUARANTINE_DIR/filename).exists())
        self.assertEqual(self.counts(), (1,2,2))


if __name__ == "__main__":
    unittest.main()
