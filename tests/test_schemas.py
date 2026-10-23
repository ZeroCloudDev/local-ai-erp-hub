import math
from decimal import Decimal
from pathlib import Path
import unittest

from pydantic import ValidationError

from core.schemas import FiscalItem, LineItem, PurchaseOrderExtraction, parse_tax_rate
from core.schema_rules import calculate_fiscal_price, fiscal_money


class SchemaTests(unittest.TestCase):
    def test_reject_invalid_numeric_source_values(self):
        for field in ("quantity", "unit_price", "line_total"):
            values = (math.inf, -math.inf, math.nan, -1)
            if field == "quantity":
                values += (0,)
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                    LineItem(item_name="Cable", **{field: value})
        for value in (math.inf, -math.inf, math.nan, -1):
            with self.subTest(stated_total=value), self.assertRaises(ValidationError):
                PurchaseOrderExtraction(stated_total=value)
        with self.assertRaises(ValidationError):
            PurchaseOrderExtraction.model_validate_json('{"items":[{"item_name":"Cable","quantity":1,"unit_price":1e309}]}')

    def test_finite_quantity_has_no_arbitrary_million_limit(self):
        po = PurchaseOrderExtraction(items=[LineItem(item_name="Cable", quantity=1_000_001, unit_price=0.01)])
        self.assertFalse(po.needs_human_review)
        self.assertEqual(po.items[0].line_total, 10_000.01)

    def test_recovered_quantities_are_validated(self):
        po = PurchaseOrderExtraction(items=[LineItem(item_name="4x Cable", unit_price=2)])
        self.assertEqual(po.items[0].quantity, 4)
        self.assertEqual(po.items[0].line_total, 8)
        for prefix in ("0", "9" * 400):
            with self.subTest(prefix=prefix), self.assertRaises(ValidationError):
                PurchaseOrderExtraction(items=[LineItem(item_name=prefix + "x Cable", unit_price=2)])

    def test_reject_derived_product_overflow(self):
        with self.assertRaisesRegex(ValidationError, "multiplied"):
            PurchaseOrderExtraction(items=[LineItem(item_name="Cable", quantity=1e308, unit_price=2)])

    def test_reject_aggregate_overflow_even_without_invoice_total(self):
        items = [LineItem(item_name="Cable", quantity=1, line_total=1e308) for _ in range(2)]
        with self.assertRaisesRegex(ValidationError, "Sum of line totals"):
            PurchaseOrderExtraction(items=items)

    def test_baseline_math_and_missing_data_rules(self):
        clean = PurchaseOrderExtraction(items=[LineItem(item_name="Cable", quantity=2, unit_price=5)], stated_total=10)
        mismatch = PurchaseOrderExtraction(items=[LineItem(item_name="Cable", quantity=2, unit_price=5)], stated_total=15)
        missing = PurchaseOrderExtraction(items=[LineItem(item_name="Cable", unit_price=5)])
        self.assertFalse(clean.needs_human_review)
        self.assertTrue(mismatch.needs_human_review)
        self.assertIn("Invoice total mismatch", mismatch.review_reasons[0])
        self.assertTrue(missing.needs_human_review)
        self.assertTrue(PurchaseOrderExtraction().needs_human_review)

    def test_tax_rates_and_derived_prices(self):
        for rate, gross in (("0%", 100), ("17%", 117), ("17% PDV", 117), ("17,0%", 117)):
            with self.subTest(rate=rate):
                item = FiscalItem(naziv="Cable", porezna_stopa=rate, cijena_bez_pdv=100)
                self.assertEqual(item.cijena_sa_pdv, gross)
                self.assertEqual(item.status_validacije, "APPROVED")
        self.assertEqual(FiscalItem(naziv="Cable", cijena_sa_pdv=117).cijena_bez_pdv, 100)

    def test_unsupported_tax_codes_quarantined_without_guessing(self):
        for rate in ("E", "K", "unknown", "-17%", "101%", "NaN%"):
            with self.subTest(rate=rate):
                self.assertIsNone(parse_tax_rate(rate))
                item = FiscalItem(naziv="Cable", porezna_stopa=rate, cijena_bez_pdv=100)
                self.assertEqual(item.status_validacije, "QUARANTINE_UNSUPPORTED_TAX")
                self.assertIsNone(item.cijena_sa_pdv)

    def test_fiscal_half_up_rounding_and_exact_tolerance(self):
        item = FiscalItem(naziv="Cable", porezna_stopa="17%", cijena_bez_pdv=12.50)
        self.assertEqual(item.cijena_sa_pdv, 14.63)
        self.assertEqual(fiscal_money(Decimal("1.005")), 1.01)
        self.assertEqual(calculate_fiscal_price(Decimal("1.17585"), 0.17, gross=False), 1.01)
        within = FiscalItem(naziv="Cable", porezna_stopa="0%", cijena_bez_pdv=1, cijena_sa_pdv=1.05)
        outside = FiscalItem(naziv="Cable", porezna_stopa="0%", cijena_bez_pdv=1, cijena_sa_pdv=1.06)
        self.assertEqual(within.status_validacije, "APPROVED")
        self.assertEqual(outside.status_validacije, "QUARANTINE_PRICE_MISMATCH")

    def test_fiscal_decimal_huge_values_remain_finite_or_reject(self):
        self.assertTrue(math.isfinite(calculate_fiscal_price(1.7e308, 0)))
        self.assertTrue(math.isfinite(calculate_fiscal_price(1.7e308, 0.17, gross=False)))
        with self.assertRaisesRegex(ValueError, "finite numeric range"):
            calculate_fiscal_price(1.7e308, 0.17)
        with self.assertRaisesRegex(ValueError, "finite numeric range"):
            fiscal_money(Decimal("1e309"))

    def test_fiscal_invalid_prices_and_overflow(self):
        for field in ("cijena_sa_pdv", "cijena_bez_pdv"):
            for value in (math.inf, -math.inf, math.nan, -1):
                with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                    FiscalItem(naziv="Cable", **{field: value})
        item = FiscalItem(naziv="Cable", cijena_bez_pdv=1.7e308)
        self.assertEqual(item.status_validacije, "QUARANTINE_INVALID_PRICE")
        self.assertIsNone(item.cijena_sa_pdv)
        missing = FiscalItem(naziv="Cable", cijena_sa_pdv=0)
        self.assertEqual(missing.status_validacije, "QUARANTINE_MISSING_PRICE")

    def test_fiscal_mismatch_and_existing_quarantine_preserved(self):
        mismatch = FiscalItem(naziv="Cable", cijena_sa_pdv=110, cijena_bez_pdv=100)
        self.assertEqual(mismatch.status_validacije, "QUARANTINE_PRICE_MISMATCH")
        item = FiscalItem(naziv="Cable", cijena_sa_pdv=117, status_validacije="QUARANTINE_CURRENCY", razlog_karantina="Foreign currency")
        self.assertEqual(item.status_validacije, "QUARANTINE_CURRENCY")
        self.assertEqual(item.razlog_karantina, "Foreign currency")
        self.assertEqual(item.cijena_bez_pdv, 100)

    def test_video_schema_line_anchors(self):
        schema_path = Path(__file__).resolve().parents[1] / "core" / "schemas.py"
        lines = schema_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 152)
        anchors = {13: "class LineItem", 35: "class PurchaseOrderExtraction", 66: "    def verify_math_and_completeness", 128: "class FiscalItem", 144: "    def validate_fiscal_integrity"}
        for number, text in anchors.items():
            self.assertTrue(lines[number - 1].startswith(text), (number, lines[number - 1]))


if __name__ == "__main__":
    unittest.main()
