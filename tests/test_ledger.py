import csv
import io
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from core.database import export_to_csv, fetch_all_line_items_flat, get_connection, init_db, save_extraction
from core.ledger_tools import format_approved_spend, format_money
from core.schemas import PurchaseOrderExtraction


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'ledger.db'
        init_db(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def order(self, currency='USD'):
        return PurchaseOrderExtraction(currency=currency, items=[dict(item_name='Bolt', quantity=1, unit_price=10)], stated_total=10)

    def test_connection_raw_api_and_closing_context(self):
        conn = get_connection(self.path)
        self.assertIsInstance(conn, sqlite3.Connection)
        self.assertEqual(conn.execute('SELECT 1').fetchone()[0], 1)
        conn.close()
        with get_connection(self.path) as conn:
            conn.execute('CREATE TABLE closing_test (value INTEGER)')
        with self.assertRaises(sqlite3.ProgrammingError):
            conn.execute('SELECT 1')

    def test_transaction_rollback(self):
        with self.assertRaisesRegex(RuntimeError, 'rollback'):
            with get_connection(self.path) as conn:
                conn.execute('INSERT INTO purchase_orders (source_hash,source_type,source_name,needs_human_review,created_at_utc) VALUES (?,?,?,?,?)', ('bad','test','test',0,'today'))
                raise RuntimeError('rollback')
        with get_connection(self.path) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM purchase_orders').fetchone()[0], 0)

    def test_empty_quarantine_visible_in_ledger_and_export(self):
        po = PurchaseOrderExtraction()
        save_extraction(po, 'test', 'empty.txt', 'empty', db_path=self.path)
        rows = fetch_all_line_items_flat(self.path)
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]['item_name'])
        self.assertIn('QUARANTINED', rows[0]['audit_status'])
        exported = list(csv.DictReader(io.StringIO(export_to_csv(self.path))))
        self.assertIn('No line items', exported[0]['review_reasons_json'])

    def test_currency_export_and_approved_spend(self):
        for code in ('EUR', 'USD'):
            save_extraction(self.order(code), 'test', code, code, db_path=self.path)
        rows = fetch_all_line_items_flat(self.path)
        self.assertEqual(format_approved_spend(rows), 'EUR 10.00 | USD 10.00')
        exported = list(csv.DictReader(io.StringIO(export_to_csv(self.path))))
        self.assertEqual({r['currency'] for r in exported}, {'EUR','USD'})
        self.assertEqual(format_money(None), 'N/A')
        self.assertEqual(format_money(0), '$0.00')
        self.assertEqual(format_money(10, 'EUR'), 'EUR 10.00')

    def test_repeat_ingest_has_one_order_and_no_stale_lines(self):
        save_extraction(self.order(), 'test', 'a.txt', 'same', db_path=self.path)
        save_extraction(PurchaseOrderExtraction(), 'test', 'b.txt', 'same', db_path=self.path)
        with get_connection(self.path) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM purchase_orders').fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT count(*) FROM line_items').fetchone()[0], 0)

    def test_concurrent_same_content_is_serialized(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            ids = list(pool.map(lambda i: save_extraction(self.order(), 'test', str(i), 'same', db_path=self.path), range(8)))
        self.assertTrue(all(isinstance(i, int) for i in ids))
        with get_connection(self.path) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM purchase_orders').fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT count(*) FROM line_items').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
