"""EP05 validation rules without a database."""

import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from ep05_fiscal_ingest_robot.adapter_config import load_config
from ep05_fiscal_ingest_robot.catalog_candidate import CatalogCandidate
from ep05_fiscal_ingest_robot.completeness_check import reconcile
from ep05_fiscal_ingest_robot.mysql_pos_adapter import FailureInjection, InjectedFailure, PosAdapter
from ep05_fiscal_ingest_robot.pos_validation import (INSERT, NO_CHANGE, QUARANTINE, UPDATE,
                                                     canonical_unit_id, decide,
                                                     mark_in_document_conflicts, static_reasons)
from ep05_fiscal_ingest_robot.source_extractors import (ExtractedDocument, Segment, detect_currency, detect_effective,
                                                        detect_price_basis, money_tokens)

CFG = load_config()
TODAY = date(2026, 10, 22)


def cand(**kw):
    base = dict(sku=95010, name="Oat Milk 64 oz", sales_unit="EA", tax_class="T",
                retail_price=Decimal("4.79"), retail_price_raw="$4.79", currency="USD",
                price_basis="before_tax", effective="today", locator="line:2",
                source_segment="95010 Oat Milk 64 oz | EA | tax T | $4.79")
    base.update(kw)
    return CatalogCandidate(**base)


ART = {"id": "a1", "art_broj": 95010, "naziv": "Oat Milk 64 oz", "cij": Decimal("4.7900"),
       "tarifa": 1, "jedmjer": "1"}
ROW = {"id": "c1", "cijena": 4.79}


class StaticRules(unittest.TestCase):
    def test_valid_candidate_has_no_reasons(self):
        self.assertEqual(static_reasons(cand(), CFG), [])

    def test_each_rule(self):
        cases = {
            "SKU_OUT_OF_RANGE": dict(sku=94000),
            "INVALID_SKU": dict(sku=None),
            "MISSING_NAME": dict(name=" "),
            "NAME_TOO_LONG": dict(name="x" * 51),
            "MISSING_PRICE": dict(retail_price=None),
            "INVALID_PRICE": dict(retail_price=Decimal("4.799")),
            "PRICE_ABOVE_LIMIT": dict(retail_price=Decimal("1000.00")),
            "CURRENCY_UNKNOWN": dict(currency=None),
            "CURRENCY_CONFLICT": dict(currency="FOREIGN:EUR"),
            "PRICE_BASIS_UNKNOWN": dict(price_basis=None),
            "PRICE_BASIS_CONFLICT": dict(price_basis="tax_included"),
            "EFFECTIVE_DATE_MISSING": dict(effective=None),
            "EFFECTIVE_DATE_NOT_TODAY": dict(effective="Monday"),
            "UNKNOWN_TAX_CLASS": dict(tax_class="X"),
            "UNKNOWN_SALES_UNIT": dict(sales_unit="BOX"),
        }
        for reason, kw in cases.items():
            with self.subTest(reason=reason):
                self.assertIn(reason, static_reasons(cand(**kw), CFG))

    def test_zero_and_negative_price(self):
        for v in ("0", "-1.00"):
            self.assertIn("INVALID_PRICE", static_reasons(cand(retail_price=Decimal(v)), CFG))


    def test_nonfinite_and_untyped_price_or_sku_are_reviewed(self):
        for value in (Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity"), 4.79, "4.79"):
            with self.subTest(price=value):
                self.assertIn("INVALID_PRICE", static_reasons(cand(retail_price=value), CFG))
        for sku in (True, 95010.0, "95010"):
            with self.subTest(sku=sku):
                self.assertIn("INVALID_SKU", static_reasons(cand(sku=sku), CFG))

    def test_name_is_never_truncated(self):
        c = cand(name="N" * 60)
        self.assertEqual(decide(c, [], [], CFG).outcome, QUARANTINE)
        self.assertEqual(len(c.name), 60)


class StateRules(unittest.TestCase):
    def test_new_article_insert_and_missing_tax_or_unit(self):
        self.assertEqual(decide(cand(), [], [], CFG).outcome, INSERT)
        self.assertEqual(decide(cand(tax_class=None), [], [], CFG).reason, "MISSING_TAX_CLASS")
        self.assertEqual(decide(cand(sales_unit=None), [], [], CFG).reason, "MISSING_SALES_UNIT")

    def test_same_name_same_price_is_no_change(self):
        self.assertEqual(decide(cand(), [ART], [ROW], CFG).outcome, NO_CHANGE)

    def test_price_change_keeps_tax_and_unit_from_pos(self):
        d = decide(cand(retail_price=Decimal("4.99"), tax_class=None, sales_unit=None), [ART], [ROW], CFG)
        self.assertEqual((d.outcome, d.old_price, d.tarifa_id, d.jmjera_id), (UPDATE, Decimal("4.79"), 1, 1))

    def test_identity_conflict(self):
        self.assertEqual(decide(cand(name="Almond Milk"), [ART], [ROW], CFG).reason, "IDENTITY_CONFLICT")

    def test_attribute_change_goes_to_review(self):
        self.assertEqual(decide(cand(tax_class="E"), [ART], [ROW], CFG).reason, "ATTRIBUTE_CHANGE")
        self.assertEqual(decide(cand(sales_unit="LB"), [ART], [ROW], CFG).reason, "ATTRIBUTE_CHANGE")

    def test_duplicate_art_broj_and_ambiguous_price_list(self):
        self.assertEqual(decide(cand(), [ART, dict(ART, id="a2")], [], CFG).reason, "DUPLICATE_ART_BROJ_IN_POS")
        self.assertEqual(decide(cand(), [ART], [ROW, dict(ROW, id="c2")], CFG).reason, "PRICE_LIST_AMBIGUOUS")

    def test_missing_price_row_on_existing_article_is_update(self):
        self.assertEqual(decide(cand(), [ART], [], CFG).outcome, UPDATE)

    def test_double_column_compared_at_two_decimals(self):
        self.assertEqual(decide(cand(), [ART], [{"id": "c1", "cijena": 4.789999999}], CFG).outcome, NO_CHANGE)

    def test_non_canonical_unit_text_is_not_cast(self):
        for bad in ("0", "-1", " 1", "01", "kom", None, "1.0"):
            self.assertIsNone(canonical_unit_id(bad))
            self.assertEqual(decide(cand(), [dict(ART, jedmjer=bad)], [ROW], CFG).reason, "POS_DATA_INVALID")
        self.assertEqual(canonical_unit_id("3"), 3)


    def test_existing_invalid_tax_reference_is_reviewed(self):
        for value in (0, None, -1):
            with self.subTest(tarifa=value):
                d = decide(cand(tax_class=None), [dict(ART, tarifa=value)], [ROW], CFG)
                self.assertEqual((d.outcome, d.reason), (QUARANTINE, "POS_DATA_INVALID"))

    def test_existing_decimal_price_is_not_silently_rounded_into_no_change(self):
        d = decide(cand(), [dict(ART, cij=Decimal("4.7949"))], [ROW], CFG)
        self.assertEqual(d.outcome, UPDATE)
        self.assertEqual(d.old_price, Decimal("4.7949"))

    def test_invalid_existing_amounts_do_not_crash_or_approve(self):
        for value in (None, Decimal("NaN"), Decimal("Infinity"), Decimal("0")):
            with self.subTest(price=value):
                d = decide(cand(), [dict(ART, cij=value)], [ROW], CFG)
                self.assertEqual((d.outcome, d.reason), (QUARANTINE, "POS_DATA_INVALID"))

    def test_same_sku_twice_in_one_document(self):
        a, b = cand(), cand(locator="line:7")
        mark_in_document_conflicts([a, b])
        self.assertEqual(a.issues, [])
        a, b = cand(), cand(locator="line:7", retail_price=Decimal("4.99"))
        mark_in_document_conflicts([a, b])
        self.assertIn("CONFLICT_IN_DOCUMENT", a.issues)
        self.assertIn("CONFLICT_IN_DOCUMENT", b.issues)


class TextRules(unittest.TestCase):
    def test_sizes_are_not_prices(self):
        self.assertEqual(money_tokens("95004 Bottled Water 16.9 oz | $1.29"), [Decimal("1.29")])
        self.assertEqual(money_tokens("Granola Bar 1.5 oz 1.49"), [Decimal("1.49")])
        self.assertEqual(money_tokens("Oat Milk 64 oz"), [])
        self.assertEqual(money_tokens("from $12.99 to $13.49"), [Decimal("12.99"), Decimal("13.49")])

    def test_effective_date(self):
        self.assertEqual(detect_effective("to $13.49 effective today.", TODAY), "today")
        self.assertEqual(detect_effective("effective 2026-10-22", TODAY), "today")
        self.assertNotEqual(detect_effective("go up to 13.49 from Monday", TODAY), "today")
        self.assertNotEqual(detect_effective("effective next week", TODAY), "today")
        self.assertNotEqual(detect_effective("effective 2026-11-01", TODAY), "today")
        self.assertIsNone(detect_effective("95010 Oat Milk 64 oz | EA | tax T | $4.79", TODAY))

    def test_currency_and_basis(self):
        self.assertEqual(detect_currency("$4.79"), "USD")
        self.assertTrue(detect_currency("4.79 EUR").startswith("FOREIGN"))
        self.assertEqual(detect_price_basis("All prices USD, before sales tax."), "before_tax")
        self.assertEqual(detect_price_basis("Prices include sales tax"), "tax_included")



class ReviewCompleteness(unittest.TestCase):
    def test_unrecognized_document_gets_visible_review(self):
        doc = ExtractedDocument("text", Path("unrecognized.txt"), [Segment("line:1", "No recognized products")], [], [])
        result = reconcile(doc, CFG.sku_min, CFG.sku_max)
        self.assertEqual(len(result), 1)
        self.assertIn("DOCUMENT_UNRECOGNIZED", result[0].issues)
        self.assertEqual(decide(result[0], [], [], CFG).outcome, QUARANTINE)

    def test_out_of_range_sku_is_not_silently_lost(self):
        doc = ExtractedDocument("text", Path("outside.txt"), [Segment("line:1", "94000 Test Item $4.79")], [], [])
        result = reconcile(doc, CFG.sku_min, CFG.sku_max)
        self.assertEqual([c.sku for c in result], [94000])
        self.assertIn("SKU_OUT_OF_RANGE", static_reasons(result[0], CFG))

    def test_review_token_detects_absent_to_present_and_price_changes(self):
        empty = PosAdapter._state_snapshot([], [])
        present = PosAdapter._state_snapshot([ART], [ROW])
        changed = PosAdapter._state_snapshot([dict(ART, cij=Decimal("4.99"))], [dict(ROW, cijena=4.99)])
        self.assertNotEqual(empty, present)
        self.assertNotEqual(present, changed)
        self.assertEqual(present, PosAdapter._state_snapshot([dict(ART)], [dict(ROW)]))

    def test_probe_evidence_distinguishes_reached_threshold_from_safety_rollback(self):
        error = InjectedFailure("not reached", actual_ops=0, planned_ops=3, reached=False)
        self.assertEqual((error.actual_ops, error.planned_ops, error.reached), (0, 3, False))
        for value in (0, -1, True, 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                FailureInjection(value)


if __name__ == "__main__":
    unittest.main()
