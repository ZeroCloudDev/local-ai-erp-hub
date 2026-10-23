"""EP05 extraction + completeness: a misbehaving model must never produce a wrong write."""

import json
import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ep05_fakes import make_llm, scripted_llm  # noqa: E402

from ep05_fiscal_ingest_robot.adapter_config import load_config
from ep05_fiscal_ingest_robot.completeness_check import reconcile, scan_occurrences
from ep05_fiscal_ingest_robot.pos_validation import static_reasons
from ep05_fiscal_ingest_robot.source_extractors import (compact, extract_image, extract_pdf,
                                                        extract_text, fix_ocr_spacing, map_pdf_header,
                                                        Segment, _line_candidates, money_tokens, parse_price_text)

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / "ep05_fiscal_ingest_robot" / "demo_inputs"
PHOTO = ROOT / "tests" / "fixtures" / "ep05_simulated_shelf_photo.jpg"
CFG = load_config()
TODAY = date(2026, 10, 22)
MSG = INPUTS / "register_update_message.txt"


def by_sku(cands):
    return {c.sku: c for c in cands}


class MessageExtraction(unittest.TestCase):
    def test_well_behaved_model(self):
        doc = extract_text(MSG, "m", scripted_llm, TODAY)
        c = by_sku(reconcile(doc, CFG.sku_min, CFG.sku_max))
        self.assertEqual(sorted(c), [95001, 95010, 95011, 95012])
        self.assertEqual(c[95010].retail_price, Decimal("4.79"))
        self.assertEqual(c[95010].field_sources["currency"].origin, "source")
        self.assertEqual(c[95001].effective, "today")
        self.assertIsNone(c[95001].tax_class)            # not on the line -> comes from the POS
        self.assertIn("MISSING_PRICE", static_reasons(c[95012], CFG))
        self.assertEqual(static_reasons(c[95011], CFG), [])

    def test_invented_price_is_caught(self):
        def lie(line, item):
            if "95012" in line:
                item["retail_price"] = "$3.49"
            return item
        c = by_sku(reconcile(extract_text(MSG, "m", make_llm(lie), TODAY), CFG.sku_min, CFG.sku_max))
        self.assertIn("PRICE_NOT_IN_SOURCE", c[95012].issues)
        self.assertIsNone(c[95012].retail_price)

    def test_sku_comes_from_the_line_not_from_the_model(self):
        # The first real rehearsal: qwen2.5:3b returned no SKUs at all.
        c = by_sku(extract_text(MSG, "m", scripted_llm, TODAY).candidates)
        self.assertEqual(sorted(c), [95001, 95010, 95011, 95012])
        self.assertEqual(c[95010].field_sources["sku"].origin, "source")

    def test_every_sku_line_gets_exactly_one_model_call(self):
        calls = []

        def spy(line, model):
            calls.append(line)
            return scripted_llm(line, model)
        doc = extract_text(MSG, "m", spy, TODAY)
        self.assertEqual(len(calls), 4)
        self.assertEqual(doc.metrics["model_calls"], 4)

    def test_empty_or_broken_model_answer_quarantines(self):
        empty = make_llm(lambda line, item: {"name": None, "sales_unit": None, "tax_class": None, "retail_price": None})
        c = by_sku(extract_text(MSG, "m", empty, TODAY).candidates)
        self.assertIn("MISSING_NAME", static_reasons(c[95011], CFG))
        broken = make_llm(lambda line, item: "{not json")
        c = by_sku(extract_text(MSG, "m", broken, TODAY).candidates)
        self.assertIn("MODEL_OUTPUT_INVALID", c[95011].issues)

    def test_sku_inside_name_is_rejected(self):
        def glue(line, item):
            if "95011" in line:
                item["name"] = "95011 Blueberry Muffin"
            return item
        c = by_sku(extract_text(MSG, "m", make_llm(glue), TODAY).candidates)
        self.assertIn("NAME_NOT_IN_SOURCE", c[95011].issues)

    def test_unresolved_extraction_when_a_candidate_is_missing(self):
        doc = extract_text(MSG, "m", scripted_llm, TODAY)
        doc.candidates = [c for c in doc.candidates if c.sku != 95011]
        c = by_sku(reconcile(doc, CFG.sku_min, CFG.sku_max))
        self.assertEqual(c[95011].issues, ["UNRESOLVED_EXTRACTION"])

    def test_invented_tax_class_is_discarded_not_used(self):
        def add_tax(line, item):
            if "95001" in line:
                item["tax_class"], item["sales_unit"] = "E", "LB"
            return item
        c = by_sku(extract_text(MSG, "m", make_llm(add_tax), TODAY).candidates)
        self.assertIsNone(c[95001].tax_class)
        self.assertIsNone(c[95001].sales_unit)       # "lb" is part of the name, not a unit
        self.assertTrue(any("discarded" in n for n in c[95001].notes))

    def test_tax_answer_with_label_is_normalized(self):
        def labelled(line, item):
            if "95010" in line:
                item["tax_class"] = "tax T"
            return item
        c = by_sku(extract_text(MSG, "m", make_llm(labelled), TODAY).candidates)
        self.assertEqual(c[95010].tax_class, "T")

    def test_name_not_on_line(self):
        def rename(line, item):
            if "95011" in line:
                item["name"] = "Blueberry Muffin Large"
            return item
        c = by_sku(extract_text(MSG, "m", make_llm(rename), TODAY).candidates)
        self.assertIn("NAME_NOT_IN_SOURCE", c[95011].issues)

    def test_future_date_and_two_amounts(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "m.txt"
            p.write_text("All prices USD, before sales tax.\n"
                         "Set Espresso Beans 1 lb, SKU 95001, to $13.49 from Monday.\n"
                         "Change Cane Sugar 4 lb, SKU 95002, from $4.49 to $4.79 effective today.\n",
                         encoding="utf-8")
            c = by_sku(extract_text(p, "m", scripted_llm, TODAY).candidates)
        self.assertIn("EFFECTIVE_DATE_NOT_TODAY", static_reasons(c[95001], CFG))
        self.assertIn("AMBIGUOUS_PRICE", c[95002].issues)


class OcrSpacing(unittest.TestCase):
    def test_spaces_dropped_by_ocr_are_restored(self):
        # Seen in the first real rehearsal with a phone photo.
        self.assertEqual(fix_ocr_spacing("95010 | OatMilk64oz | EA | Taxable | $4.79"),
                         "95010 | Oat Milk 64 oz | EA | Taxable | $4.79")
        self.assertEqual(fix_ocr_spacing("95040 | Granola Bar 1.5oz | EA | Taxable | $1.49"),
                         "95040 | Granola Bar 1.5 oz | EA | Taxable | $1.49")
        self.assertEqual(fix_ocr_spacing("95010OatMilk64oz"), "95010 Oat Milk 64 oz")
        self.assertEqual(fix_ocr_spacing("$1.49"), "$1.49")

    def test_identity_comparison_ignores_spacing(self):
        self.assertEqual(compact("Oat Milk 64 oz"), compact("OatMilk64oz"))
        self.assertNotEqual(compact("Oat Milk 64 oz"), compact("Oat Milk 32 oz"))


class PdfExtraction(unittest.TestCase):
    def test_twenty_rows_with_provenance(self):
        doc = extract_pdf(INPUTS / "approved_retail_price_update.pdf", TODAY)
        self.assertEqual(len(doc.candidates), 20)
        self.assertEqual(len(scan_occurrences(doc, CFG.sku_min, CFG.sku_max)), 20)
        c = by_sku(doc.candidates)
        self.assertEqual(c[95029].sales_unit, "LB")
        self.assertEqual(c[95020].field_sources["currency"].origin, "column_header")
        self.assertEqual(c[95020].effective, "today")
        self.assertIn("UNKNOWN_TAX_CLASS", static_reasons(c[95033], CFG))
        self.assertNotIn(95039, c)

    def test_cost_column_is_never_a_retail_price(self):
        mapping, problems = map_pdf_header(["SKU", "Description", "Unit Cost (USD)", "Retail Price Cost"])
        self.assertNotIn("retail_price", mapping)
        self.assertTrue(any("no column for retail_price" in p for p in problems))


class PhotoExtraction(unittest.TestCase):
    def test_simulated_tilted_photo(self):
        doc = extract_image(PHOTO, "m", scripted_llm, CFG.ocr_y_tolerance_px, CFG.ocr_min_confidence, TODAY)
        c = by_sku(reconcile(doc, CFG.sku_min, CFG.sku_max))
        self.assertEqual(sorted(c), [95010, 95040, 95041])
        self.assertNotEqual(doc.metrics["skew_degrees"], 0)
        self.assertEqual(c[95040].retail_price, Decimal("1.49"))
        self.assertEqual(c[95040].tax_class, "TAXABLE")
        self.assertTrue(c[95040].locator.startswith("ocr_row:"))
        if "| Sparkling Water 12 oz EA |" in c[95041].source_segment:
            # The OCR engine merged two physical columns. Our intentionally
            # simplistic test model then misassigns Taxable as unit and $1.19
            # as tax. Holding this row is the correct safety outcome; do not
            # weaken runtime validation to make a simulated picture pass.
            self.assertIn("NAME_BOUNDARY_UNCERTAIN", static_reasons(c[95041], CFG))
            self.assertIn("UNKNOWN_SALES_UNIT", static_reasons(c[95041], CFG))
            self.assertIn("UNKNOWN_TAX_CLASS", static_reasons(c[95041], CFG))
        else:
            self.assertEqual(static_reasons(c[95041], CFG), [])

    def test_low_confidence_goes_to_review(self):
        doc = extract_image(PHOTO, "m", scripted_llm, CFG.ocr_y_tolerance_px, 0.99, TODAY)
        self.assertTrue(all("OCR_UNCERTAIN" in c.issues for c in doc.candidates))


class Inputs(unittest.TestCase):
    def test_expected_results_are_consistent(self):
        exp = json.loads((INPUTS / "expected_results.json").read_text(encoding="utf-8"))
        arts = exp["after_three_documents"]["articles"]
        self.assertEqual(len(arts), exp["after_three_documents"]["article_count"])
        self.assertEqual(len(exp["documents"]["approved_retail_price_update.pdf"]["items"]), 20)
        self.assertEqual(exp["after_resolution"]["article_count"], 28)

    def test_pdfs_are_reproducible(self):
        # Generate into a temporary directory; tests must never rewrite the
        # published inputs while a rehearsal is hashing or processing them.
        from reportlab import rl_config
        from ep05_fiscal_ingest_robot.make_demo_inputs import build_price_update_pdf, build_shelf_print_pdf
        before = {p.name: p.read_bytes() for p in INPUTS.glob("*.pdf")}
        previous = rl_config.invariant
        try:
            rl_config.invariant = 1
            with tempfile.TemporaryDirectory() as td:
                for filename, build in (("approved_retail_price_update.pdf", build_price_update_pdf),
                                        ("shelf_tags_to_print.pdf", build_shelf_print_pdf)):
                    path = Path(td) / filename
                    build(path)
                    self.assertEqual(path.read_bytes(), before[filename])
        finally:
            rl_config.invariant = previous
        self.assertEqual({p.name: p.read_bytes() for p in INPUTS.glob("*.pdf")}, before)


class SourceGroundingRegressions(unittest.TestCase):
    def candidate(self, text, name, price="$7.49", unit=None):
        raw = json.dumps(dict(name=name, sales_unit=unit, tax_class=None, retail_price=price))
        return _line_candidates(Segment("line:1", text), raw, TODAY,
                                ("USD", "before_tax", "today", "test note"),
                                CFG.sku_min, CFG.sku_max, CFG.code_tables())[0]

    def test_complete_name_anchor_is_generic_across_skus_and_layouts(self):
        for text in ("95077 Dark Roast Coffee 12 oz | EA | tax T | $7.49",
                     "95077 | Dark Roast Coffee 12 oz | EA | tax T | $7.49",
                     "Set Dark Roast Coffee 12 oz, SKU 95077, to $7.49 effective today."):
            with self.subTest(text=text):
                candidate = self.candidate(text, "Dark Roast Coffee", unit="12 oz")
                self.assertEqual(candidate.name, "Dark Roast Coffee 12 oz")
                self.assertIn("deterministic complete_name", candidate.field_sources["name"].detail)
                self.assertNotEqual(candidate.sales_unit, "12 OZ")
                self.assertNotIn("NAME_NOT_IN_SOURCE", candidate.issues)

    def test_partial_free_form_name_is_held(self):
        candidate = self.candidate("Please add 95077 Dark Roast Coffee 12 oz for $7.49 today.", "Coffee")
        self.assertIn("NAME_BOUNDARY_UNCERTAIN", static_reasons(candidate, CFG))

    def test_missing_model_name_is_not_silently_recovered(self):
        candidate = self.candidate("95077 Dark Roast Coffee 12 oz | EA | tax T | $7.49", None)
        self.assertIsNone(candidate.name)
        self.assertIn("MISSING_NAME", static_reasons(candidate, CFG))

    def test_pack_size_is_never_an_unlabelled_sales_unit(self):
        for proposed_unit in ("LB", "1 lb"):
            candidate = self.candidate("Set Dark Roast Coffee 1 lb, SKU 95077, to $7.49 effective today.",
                                       "Dark Roast Coffee", unit=proposed_unit)
            self.assertEqual(candidate.name, "Dark Roast Coffee 1 lb")
            self.assertIsNone(candidate.sales_unit)

    def test_source_negative_or_malformed_amount_cannot_ground_positive_model(self):
        for source_amount, proposed in (("-$4.79", "$4.79"), ("$-4.79", "$4.79"),
                                        ("−$4.79", "$4.79"), ("- 4.79", "$4.79"),
                                        ("($4.79)", "$4.79"), ("$4,79", "$4"),
                                        ("$4.79.2", "$4.79"), ("$4..79", "$4.79"),
                                        ("$4.790", "$4.79"), ("$1,23.45", "$23.45"),
                                        ("$5-00", "$5"), ("$4. 79", "$4"),
                                        ("-5.00", "$5.00")):
            with self.subTest(source_amount=source_amount):
                candidate = self.candidate(f"95077 Dark Roast Coffee | EA | tax T | {source_amount}",
                                           "Dark Roast Coffee", proposed)
                self.assertIsNone(candidate.retail_price)
                self.assertIn("PRICE_NOT_IN_SOURCE", candidate.issues)
                self.assertEqual(money_tokens(source_amount), [])

    def test_strict_full_amount_parser_preserves_valid_us_grouping(self):
        self.assertEqual(parse_price_text("$1,234.56"), Decimal("1234.56"))
        self.assertEqual(money_tokens("price USD 1,234.56"), [Decimal("1234.56")])
        for raw in ("$4,79", "-$4.79", "$-4.79", "$4.790", "$4.79.2"):
            self.assertIsNone(parse_price_text(raw))

    def test_duplicate_pdf_headers_do_not_choose_one_price(self):
        for field, headers in (("retail_price", ["SKU", "Description", "Retail Price A", "Retail Price B"]),
                               ("name", ["SKU", "Description", "Name", "Retail Price"]),
                               ("tax_class", ["SKU", "Description", "Tax", "Tax Class", "Retail Price"])):
            with self.subTest(field=field):
                mapping, problems = map_pdf_header(headers)
                self.assertNotIn(field, mapping)
                self.assertIn(f"two columns map to {field}", problems)

    def test_ambiguous_pdf_table_is_held_by_completeness_check(self):
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ambiguous.pdf"
            table = Table([["SKU", "Description", "Retail Price A", "Retail Price B"],
                           ["95077", "Dark Roast Coffee", "7.49", "9.49"]])
            table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 1, "black")]))
            SimpleDocTemplate(str(path)).build([table])
            doc = extract_pdf(path, TODAY)
        self.assertEqual(doc.candidates, [])
        held = reconcile(doc, CFG.sku_min, CFG.sku_max)
        self.assertEqual([candidate.sku for candidate in held], [95077])
        self.assertIn("UNRESOLVED_EXTRACTION", held[0].issues)


if __name__ == "__main__":
    unittest.main()
