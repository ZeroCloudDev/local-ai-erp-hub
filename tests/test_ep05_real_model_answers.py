"""
Regression test with the EXACT answers qwen2.5:3b gave in the first real probe
on the presenter's laptop (22.10.2026, Ollama 0.40.5, CPU). They exposed:
  * unit and tax class keys left out of the JSON,
  * "Blueberry Muffin | EA" - the name ran into the next column,
  * an invented price "$9.50" for the line without a price,
  * OCR rows without spaces ("OatMilk64oz", "Granola Bar 1.5oz").
"""

import json
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from ep05_fiscal_ingest_robot.adapter_config import load_config
from ep05_fiscal_ingest_robot.catalog_candidate import CatalogCandidate  # noqa: F401
from ep05_fiscal_ingest_robot.pos_validation import static_reasons
from ep05_fiscal_ingest_robot.source_extractors import (Segment, _document_level, _line_candidates,
                                                        extract_text, fix_ocr_spacing)

ROOT = Path(__file__).resolve().parents[1]
MSG = ROOT / "ep05_fiscal_ingest_robot" / "demo_inputs" / "register_update_message.txt"
CFG = load_config()
TODAY = date(2026, 10, 22)

REAL_TXT_ANSWERS = {
    "95010": {"name": "Oat Milk 64 oz", "retail_price": "$4.79"},
    "95011": {"name": "Blueberry Muffin | EA", "retail_price": "$2.99"},
    "95012": {"name": "Mint Tea 20 ct", "retail_price": "$9.50"},
    "95001": {"name": "Espresso Beans 1 lb", "retail_price": "$13.49"},
}
REAL_OCR_ROWS = [
    "MAPLE STREET MARKET-SHELF TAG UPDATE",
    "All retail prices in UsD,before sales tax. Effective today",
    "SKU | Item | Unit Tax | Price",
    "95040 | Granola Bar 1.5oz | EA | Taxable | $1.49",
    "95041 | Sparkling Water 12 oz | EA | Taxable | $1.19",
    "95010 | OatMilk64oz | EA | Taxable | $4.79",
]
REAL_OCR_ANSWERS = {
    "95040": {"name": "Granola Bar 1.5 oz", "retail_price": "$1.49"},
    "95041": {"name": "Sparkling Water 12 oz", "retail_price": "$1.19"},
    "95010": {"name": "Oat Milk 64 oz", "retail_price": "$4.79"},
}


# Exact raw answers from the Normal and Reverse rehearsals (22.10.2026, same laptop).
# New shapes: tax_class "tax T" with the column label, sales_unit null although
# the line says EA, and retail_price null (instead of an invented price) for 95012.
REHEARSAL_TXT_RAW = {
    "95010": '{\n  "name": "Oat Milk 64 oz",\n  "sales_unit": null,\n  "tax_class": "T",\n  "retail_price": "$4.79"\n}',
    "95011": '{\n  "name": "Blueberry Muffin",\n  "sales_unit": null,\n  "tax_class": "tax T",\n  "retail_price": "$2.99"\n}',
    "95012": '{\n  "name": "Mint Tea 20 ct",\n  "sales_unit": null,\n  "tax_class": "tax T",\n  "retail_price": null\n}',
    "95001": '{ "name": "Espresso Beans", "sales_unit": "1 lb", "tax_class": null, "retail_price": "$13.49" }',
}
REHEARSAL_FAIL_PROBE_RAW = {
    "95002": '{\n  "name": "Cane Sugar 4 lb",\n  "sales_unit": null,\n  "tax_class": null,\n  "retail_price": "$4.79"\n}',
    **{sku: '{\n  "name": "Rollback Probe Item %s",\n  "sales_unit": null,\n  "tax_class": "tax T",\n'
            '  "retail_price": "$1.00"\n}' % letter
       for sku, letter in (("95050", "A"), ("95051", "B"), ("95052", "C"))},
}
# 95040 came back with sales_unit "EA" in some calls and null in others for the same row.
REHEARSAL_OCR_RAW = {
    "95040": ['{\n  "name": "Granola Bar 1.5 oz",\n  "sales_unit": "EA",\n  "tax_class": "Taxable",\n  "retail_price": "$1.49"\n}',
              '{\n  "name": "Granola Bar 1.5 oz",\n  "sales_unit": null,\n  "tax_class": "Taxable",\n  "retail_price": "$1.49"\n}'],
    "95041": ['{\n  "name": "Sparkling Water 12 oz",\n  "sales_unit": "EA",\n  "tax_class": "Taxable",\n  "retail_price": "$1.19"\n}'],
    "95010": ['{\n  "name": "Oat Milk 64 oz",\n  "sales_unit": null,\n  "tax_class": "Taxable",\n  "retail_price": "$4.79"\n}'],
}
FAIL_PROBE = ROOT / "ep05_fiscal_ingest_robot" / "demo_inputs" / "fail_probe.txt"


def replay(answers):
    def llm(line, model):
        key = next(k for k in answers if k in line)
        return json.dumps(answers[key]), {"wall_time_ms": 0.0}
    return llm


def replay_raw(answers):
    def llm(line, model):
        key = next(k for k in answers if k in line)
        return answers[key], {"wall_time_ms": 0.0}
    return llm


class RealModelAnswers(unittest.TestCase):
    def test_command_word_in_name_is_removed(self):
        # Second real run: qwen2.5:3b answered "Set Cane Sugar 4 lb" for the fail-probe line.
        seg = Segment("line:3", "Set Cane Sugar 4 lb, SKU 95002, to $4.79 effective today.")
        raw = json.dumps({"name": "Set Cane Sugar 4 lb", "sales_unit": None, "tax_class": None, "retail_price": "$4.79"})
        ctx = ("USD", "before_tax", "today", "note")
        c = _line_candidates(seg, raw, TODAY, ctx, CFG.sku_min, CFG.sku_max, CFG.code_tables())[0]
        self.assertEqual(c.name, "Cane Sugar 4 lb")
        self.assertEqual(static_reasons(c, CFG), [])

    def test_latest_espresso_answer_anchors_full_command_name(self):
        # Exact latest real answer: the model split a package size into sales_unit.
        raw = '{"name":"Espresso Beans","sales_unit":"1 lb","tax_class":null,"retail_price":"$13.49"}'
        source = "Set Espresso Beans 1 lb, SKU 95001, to $13.49 effective today."
        candidate = _line_candidates(Segment("line:5", source), raw, TODAY,
                                     ("USD", "before_tax", "today", "note"),
                                     CFG.sku_min, CFG.sku_max, CFG.code_tables())[0]
        self.assertEqual(candidate.name, "Espresso Beans 1 lb")
        self.assertIsNone(candidate.sales_unit)
        self.assertIsNone(candidate.tax_class)
        self.assertEqual(candidate.retail_price, Decimal("13.49"))
        self.assertEqual(static_reasons(candidate, CFG), [])
        self.assertEqual(candidate.field_sources["name"].origin, "source")
        self.assertIn("deterministic complete_name", candidate.field_sources["name"].detail)
        self.assertTrue(any("raw model name 'Espresso Beans'" in note for note in candidate.notes))
        # Replay uses the real raw JSON verbatim; source normalization never rewrites it.
        def recorded(line, model):
            if line == source:
                return raw, {"wall_time_ms": 0.0}
            return replay(REAL_TXT_ANSWERS)(line, model)
        doc = extract_text(MSG, "qwen2.5:3b", recorded, TODAY, codes=CFG.code_tables())
        self.assertTrue(any(log.endswith("-> " + raw) for log in doc.log))

    def test_message(self):
        doc = extract_text(MSG, "qwen2.5:3b", replay(REAL_TXT_ANSWERS), TODAY, codes=CFG.code_tables())
        c = {x.sku: x for x in doc.candidates}
        self.assertEqual((c[95010].name, c[95010].sales_unit, c[95010].tax_class), ("Oat Milk 64 oz", "EA", "T"))
        self.assertEqual(static_reasons(c[95010], CFG), [])
        self.assertEqual((c[95011].name, c[95011].sales_unit, c[95011].tax_class), ("Blueberry Muffin", "EA", "T"))
        self.assertEqual(static_reasons(c[95011], CFG), [])
        self.assertIn("PRICE_NOT_IN_SOURCE", static_reasons(c[95012], CFG))
        self.assertIsNone(c[95012].retail_price)
        self.assertEqual((c[95012].sales_unit, c[95012].tax_class), ("EA", "T"))   # resolvable by price alone
        self.assertEqual(c[95001].retail_price, Decimal("13.49"))
        self.assertIsNone(c[95001].tax_class)        # comes from the existing article
        self.assertEqual(static_reasons(c[95001], CFG), [])

    def test_photo_rows(self):
        rows = [fix_ocr_spacing(r) for r in REAL_OCR_ROWS]
        self.assertIn("UsD", rows[1])                 # not split into "Us D"
        segs = [Segment(f"ocr_row:{i + 1}", t, is_note=i < 3, min_ocr_score=0.9) for i, t in enumerate(rows)]
        ctx = _document_level([s.text for s in segs if s.is_note], TODAY)
        llm = replay(REAL_OCR_ANSWERS)
        out = {}
        for s in segs[3:]:
            raw, _ = llm(s.text, "m")
            for c in _line_candidates(s, raw, TODAY, ctx, CFG.sku_min, CFG.sku_max, CFG.code_tables()):
                out[c.sku] = c
        for sku, name in ((95040, "Granola Bar 1.5 oz"), (95041, "Sparkling Water 12 oz"), (95010, "Oat Milk 64 oz")):
            with self.subTest(sku=sku):
                c = out[sku]
                self.assertEqual((c.name, c.sales_unit, c.tax_class), (name, "EA", "TAXABLE"))
                self.assertEqual(c.currency, "USD")
                self.assertEqual(static_reasons(c, CFG), [])

    def test_rehearsal_message_answers(self):
        doc = extract_text(MSG, "qwen2.5:3b", replay_raw(REHEARSAL_TXT_RAW), TODAY, codes=CFG.code_tables())
        c = {x.sku: x for x in doc.candidates}
        for sku, name in ((95010, "Oat Milk 64 oz"), (95011, "Blueberry Muffin")):
            with self.subTest(sku=sku):
                self.assertEqual((c[sku].name, c[sku].sales_unit, c[sku].tax_class), (name, "EA", "T"))
                self.assertEqual(static_reasons(c[sku], CFG), [])
        self.assertIsNone(c[95012].retail_price)
        self.assertEqual((c[95012].sales_unit, c[95012].tax_class), ("EA", "T"))
        self.assertEqual(static_reasons(c[95012], CFG), ["MISSING_PRICE"])
        self.assertEqual((c[95001].name, c[95001].retail_price), ("Espresso Beans 1 lb", Decimal("13.49")))
        self.assertEqual(static_reasons(c[95001], CFG), [])

    def test_rehearsal_fail_probe_answers(self):
        doc = extract_text(FAIL_PROBE, "qwen2.5:3b", replay_raw(REHEARSAL_FAIL_PROBE_RAW), TODAY,
                           codes=CFG.code_tables())
        c = {x.sku: x for x in doc.candidates}
        self.assertEqual(sorted(c), [95002, 95050, 95051, 95052])
        self.assertEqual((c[95002].name, c[95002].retail_price), ("Cane Sugar 4 lb", Decimal("4.79")))
        for sku in (95050, 95051, 95052):
            with self.subTest(sku=sku):
                self.assertEqual((c[sku].sales_unit, c[sku].tax_class, c[sku].retail_price),
                                 ("EA", "T", Decimal("1.00")))
        for x in c.values():
            self.assertEqual(static_reasons(x, CFG), [])

    def test_rehearsal_photo_answers_including_unstable_unit(self):
        rows = [fix_ocr_spacing(r) for r in REAL_OCR_ROWS]
        segs = [Segment(f"ocr_row:{i + 1}", t, is_note=i < 3, min_ocr_score=0.9) for i, t in enumerate(rows)]
        ctx = _document_level([s.text for s in segs if s.is_note], TODAY)
        for seg in segs[3:]:
            sku = seg.text.split()[0]
            for raw in REHEARSAL_OCR_RAW[sku]:
                with self.subTest(sku=sku, raw=raw):
                    c = _line_candidates(seg, raw, TODAY, ctx, CFG.sku_min, CFG.sku_max, CFG.code_tables())[0]
                    self.assertEqual((c.sku, c.sales_unit, c.tax_class), (int(sku), "EA", "TAXABLE"))
                    self.assertEqual(static_reasons(c, CFG), [])


if __name__ == "__main__":
    unittest.main()
