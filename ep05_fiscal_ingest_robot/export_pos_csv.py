"""
EP05 — documented example export of the managed articles to CSV.

This is an EXAMPLE format for this test database, not a universal import
format for any cash register. It reads the database (the single source of
truth) through the same selected-price-row rule as the adapter.

    python ep05_fiscal_ingest_robot\\export_pos_csv.py --out data\\ep05_archive\\export\\articles.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ep05_fiscal_ingest_robot.adapter_config import load_config
from ep05_fiscal_ingest_robot.mysql_pos_adapter import PosAdapter, main_view_sql
from ep05_fiscal_ingest_robot.pos_validation import to_cents

COLUMNS = ["sku", "name", "retail_price_usd_before_tax", "tax_class", "demo_tax_rate_pct", "sales_unit"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--show", action="store_true", help="also print the rows (same SELECT as HeidiSQL)")
    args = ap.parse_args()
    cfg = load_config(args.config)
    out = args.out or cfg.archive_dir / "export" / "ep05_articles.csv"
    sql, params = main_view_sql(cfg)
    conn = PosAdapter(cfg).connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = list(cur.fetchall())
    finally:
        conn.close()
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for r in rows:
            w.writerow([r["art_broj"], r["naziv"], to_cents(r["retail_price_usd"]), r["tax_class"],
                        r["demo_sales_tax_rate"], r["sales_unit"]])
    if args.show:
        print(f"{'SKU':<6} {'NAME':<28} {'PRICE':>7} TAX RATE  UNIT  OSNOVNI")
        for r in rows:
            print(f"{r['art_broj']:<6} {r['naziv']:<28} {to_cents(r['retail_price_usd']):>7} {r['tax_class'] or '?':<3}"
                  f" {'' if r['demo_sales_tax_rate'] is None else r['demo_sales_tax_rate']!s:<5} {r['sales_unit'] or '?':<5} {r['osnovni_price']}")
    print(f"{len(rows)} articles -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
