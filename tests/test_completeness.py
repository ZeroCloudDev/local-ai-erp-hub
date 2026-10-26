import json
from pathlib import Path
import unittest

from core.completeness import dropped_line_reasons, item_price_count
from core.schemas import LineItem, PurchaseOrderExtraction

ROOT = Path(__file__).resolve().parents[1]


class CompletenessTests(unittest.TestCase):
    def test_totals_are_not_item_prices(self):
        cases = {
            "5x Fluid at $3.49 each (line total $17.45). Total on receipt is $17.45.": 1,
            "at $3.49 eahc (line totl $6.98). totl on reciept $13.10.": 1,
            "two AGM batteries at $199.99 a piece, that's $399.98": 1,
            "at $4.00 and $2.00 each, respectively, $10.00 all in.": 2,
            "Overall invoice total written at bottom is $290.00.": 0,
            "Receipt smudged, just says total was $285.00.": 0,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(item_price_count(text), expected)

    def test_dropped_line_goes_to_review(self):
        # syn_hard_noqty_06: qwen3:4b returned only the first item (benchmarks/results, 2026-10-25).
        text = ("team, Carlos here, Grainger for Job #504: 6x ESP32-S3 Module (SKU: ESP32-S3-WROOM-1) at $3.90 each "
                "(line total $23.40), plus however many they had of AGM Battery H6 (AGM-H6) at $199.99 each, "
                "didn't count them.")
        po = PurchaseOrderExtraction(items=[LineItem(item_name="ESP32-S3 Module", quantity=6, unit_price=3.9, line_total=23.4)])
        self.assertFalse(po.needs_human_review)
        self.assertEqual(len(dropped_line_reasons(text, po)), 1)

    def test_full_extraction_of_clean_messages_is_not_flagged(self):
        synthetic = json.loads((ROOT / "benchmarks" / "synthetic_set.json").read_text(encoding="utf-8"))
        for msg in synthetic["messages"]:
            if msg["lines"] is None:
                continue
            with self.subTest(msg=msg["id"]):
                self.assertLessEqual(item_price_count(msg["text"]), len(msg["lines"]))


if __name__ == "__main__":
    unittest.main()
