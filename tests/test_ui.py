import tempfile
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from core.schemas import PurchaseOrderExtraction

ROOT = Path(__file__).resolve().parents[1]


class DashboardTests(unittest.TestCase):
    def test_ep01_mixed_currency_and_empty_document_metrics(self):
        rows = [dict(po_id=1, item_name='Bolt', currency='USD', line_total=10, audit_status='APPROVED'),
                dict(po_id=2, item_name='Nut', currency='EUR', line_total=10, audit_status='APPROVED'),
                dict(po_id=3, item_name=None, currency='USD', line_total=None, audit_status='QUARANTINED')]
        with patch('core.database.fetch_all_line_items_flat', return_value=rows):
            app = AppTest.from_file(str(ROOT / 'ep01_structured_text/app_streamlit.py'), default_timeout=30).run()
        self.assertFalse(app.exception)
        self.assertEqual([m.value for m in app.metric], ['2','2','1','EUR 10.00 | USD 10.00'])

    def test_ep03_actual_dashboard_handles_absent_total(self):
        po = PurchaseOrderExtraction(items=[dict(item_name='Bolt', quantity=1, unit_price=10)])
        metrics = dict(ocr_duration_ms=1, wall_time_ms=1, tokens_per_sec=1, total_pipeline_ms=2)
        with patch('core.database.fetch_all_line_items_flat', return_value=[]), patch('core.database.save_extraction', return_value=1), patch('ep03_fast_cpu_ocr.ocr_pipeline.process_receipt_image_to_erp', return_value=('Bolt | 10', po, metrics)):
            app = AppTest.from_file(str(ROOT / 'ep03_fast_cpu_ocr/app_streamlit.py'), default_timeout=30).run()
            app.button[2].click().run()
            self.assertFalse(app.exception)
            self.assertTrue(any('Total:** N/A' in c.value for c in app.caption))

    def test_ep05_dashboard_empty_ingest_is_quarantined_and_repeat_is_deduplicated(self):
        import ep05_fiscal_ingest_robot.fiscal_ingest_service as service
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            incoming = base / 'incoming'
            incoming.mkdir()
            (incoming / 'viber_poruka.txt').write_text('', encoding='utf-8')
            app_source = (ROOT / 'ep05_fiscal_ingest_robot/app_streamlit.py').read_text(encoding='utf-8')
            # Redirect the actual application constants and service to a separate database.
            app_source = app_source.replace('BASE_DIR = Path(__file__).resolve().parent.parent', f'BASE_DIR = Path({str(base)!r})')
            app_source = app_source.replace('INCOMING_DIR = BASE_DIR / "data" / "incoming_fiskal"', 'INCOMING_DIR = BASE_DIR / "incoming"')
            (base / 'data').mkdir()
            with patch.multiple(service, BASE_DIR=base, DB_PATH=base/'data/erp_procurement.db', INCOMING_DIR=incoming,
                                APPROVED_DIR=base/'data/processed_fiskal/approved', QUARANTINE_DIR=base/'data/processed_fiskal/quarantine'):
                app = AppTest.from_string(app_source, default_timeout=30).run()
                self.assertFalse(app.exception)
                app.button[0].click().run()
                self.assertFalse(app.exception)
                self.assertTrue(app.error)
                self.assertTrue(app.button(key='inline_btn_1').disabled)
                app.number_input(key='inline_mpc_1').set_value(12.5).run()
                app.text_input(key='inline_name_1').set_value('Invented article').run()
                self.assertTrue(app.button(key='inline_btn_1').disabled)
                app.button[0].click().run()
                self.assertFalse(app.exception)
                self.assertTrue(any('već evidentiran' in i.value for i in app.info))

    def test_ep05_manual_resolution_requires_price_and_preserves_corrected_name_and_tax(self):
        import ep05_fiscal_ingest_robot.fiscal_ingest_service as service
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            incoming = base / 'incoming'
            incoming.mkdir()
            (incoming / 'viber_poruka.txt').write_text('Kafa - vidi cijenu', encoding='utf-8')
            source = (ROOT/'ep05_fiscal_ingest_robot/app_streamlit.py').read_text(encoding='utf-8')
            source = source.replace('BASE_DIR = Path(__file__).resolve().parent.parent', f'BASE_DIR = Path({str(base)!r})')
            source = source.replace('INCOMING_DIR = BASE_DIR / "data" / "incoming_fiskal"', 'INCOMING_DIR = BASE_DIR / "incoming"')
            (base/'data').mkdir()
            with patch.multiple(service, BASE_DIR=base, DB_PATH=base/'data/erp_procurement.db', INCOMING_DIR=incoming,
                                APPROVED_DIR=base/'data/processed_fiskal/approved', QUARANTINE_DIR=base/'data/processed_fiskal/quarantine'):
                app = AppTest.from_string(source, default_timeout=30).run()
                app.button[0].click().run()
                self.assertTrue(app.button(key='inline_btn_1').disabled)
                app.number_input(key='inline_mpc_1').set_value(12.5).run()
                app.text_input(key='inline_name_1').set_value('Kafa').run()
                app.selectbox(key='inline_tax_1').set_value('0%').run()
                app.button(key='inline_btn_1').click().run()
                self.assertFalse(app.exception)
                conn = sqlite3.connect(base/'data/erp_procurement.db')
                try:
                    self.assertEqual(conn.execute('SELECT naziv,porezna_stopa,cijena_sa_pdv,cijena_bez_pdv FROM fiscal_items').fetchall(), [('Kafa','0%',12.5,12.5)])
                    self.assertEqual(conn.execute('SELECT count(*) FROM fiscal_quarantine').fetchone()[0], 0)
                finally:
                    conn.close()


if __name__ == '__main__':
    unittest.main()
