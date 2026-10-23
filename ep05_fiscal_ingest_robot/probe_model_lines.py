"""
EP05 - quick check of the REAL local model on the demo lines (no database).

For every SKU line of the message (and, if present, of the photo) it calls the
same model function the service uses, prints the raw JSON answer and what the
deterministic source checks make of it. Run it before a rehearsal: it shows in
~20 seconds whether the model reads the lines the way the expected results need.

    python ep05_fiscal_ingest_robot\\probe_model_lines.py
    python ep05_fiscal_ingest_robot\\probe_model_lines.py --photo ep05_fiscal_ingest_robot\\demo_inputs\\shelf_tags_photo.jpg
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ep05_fiscal_ingest_robot.adapter_config import load_config
from ep05_fiscal_ingest_robot.pos_validation import static_reasons
from ep05_fiscal_ingest_robot.source_extractors import extract_image, extract_text

HERE = Path(__file__).resolve().parent
# What a correct reading must give: (name, price, unit, tax). None price = must stay
# missing; None unit/tax = must come from the existing POS article (95001).
EXPECTED = {
    95010: ("Oat Milk 64 oz", "4.79", "EA", ("T", "TAXABLE")), 95011: ("Blueberry Muffin", "2.99", "EA", ("T",)),
    95012: ("Mint Tea 20 ct", None, "EA", ("T",)), 95001: ("Espresso Beans 1 lb", "13.49", None, (None,)),
    95040: ("Granola Bar 1.5 oz", "1.49", "EA", ("TAXABLE",)), 95041: ("Sparkling Water 12 oz", "1.19", "EA", ("TAXABLE",)),
    # fail_probe.txt: these must read cleanly, otherwise the rollback probe stops too early
    95002: ("Cane Sugar 4 lb", "4.79", None, (None,)), 95050: ("Rollback Probe Item A", "1.00", "EA", ("T",)),
    95051: ("Rollback Probe Item B", "1.00", "EA", ("T",)), 95052: ("Rollback Probe Item C", "1.00", "EA", ("T",)),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--photo", type=Path)
    args = ap.parse_args()
    cfg = load_config()
    docs = [extract_text(HERE / "demo_inputs" / "register_update_message.txt", cfg.model_name,
                         sku_min=cfg.sku_min, sku_max=cfg.sku_max, codes=cfg.code_tables())]
    docs.append(extract_text(HERE / "demo_inputs" / "fail_probe.txt", cfg.model_name,
                             sku_min=cfg.sku_min, sku_max=cfg.sku_max, codes=cfg.code_tables()))
    if args.photo:
        docs.append(extract_image(args.photo, cfg.model_name, y_tol=cfg.ocr_y_tolerance_px,
                                  min_conf=cfg.ocr_min_confidence, sku_min=cfg.sku_min, sku_max=cfg.sku_max,
                                  codes=cfg.code_tables()))
    bad = 0
    for doc in docs:
        print(f"== {doc.path.name}  model={cfg.model_name}  calls={doc.metrics.get('model_calls')}"
              f"  model time={doc.metrics.get('wall_time_ms')} ms  first-call load={doc.metrics.get('load_duration_ms')} ms")
        for line in doc.log:
            print("  " + line)
        for c in doc.candidates:
            reasons = static_reasons(c, cfg)
            exp = EXPECTED.get(c.sku)
            ok = exp is not None and (c.name or "").casefold() == exp[0].casefold() and (
                (exp[1] is None and c.retail_price is None) or (exp[1] is not None and str(c.retail_price) == exp[1])
            ) and c.sales_unit == exp[2] and c.tax_class in exp[3]
            if exp and exp[1] is not None:
                ok = ok and not reasons
            bad += 0 if ok else 1
            print(f"  {'OK ' if ok else 'BAD'} {c.sku} name={c.name!r} price={c.retail_price} unit={c.sales_unit}"
                  f" tax={c.tax_class} reasons={reasons}")
    print("MODEL PROBE PASS" if bad == 0 else f"MODEL PROBE: {bad} line(s) not read as expected")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    t0 = time.perf_counter()
    rc = main()
    print(f"total {round(time.perf_counter() - t0, 1)} s")
    sys.exit(rc)
