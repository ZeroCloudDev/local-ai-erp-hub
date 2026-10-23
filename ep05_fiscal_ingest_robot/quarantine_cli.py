"""
EP05 — operator CLI for the quarantine.

    python ep05_fiscal_ingest_robot\\quarantine_cli.py list
    python ep05_fiscal_ingest_robot\\quarantine_cli.py resolve 1 --price 3.49 --operator Eldar --confirm "price confirmed by Mike"
    python ep05_fiscal_ingest_robot\\quarantine_cli.py resolve sku:95012 --price 3.49 --operator Eldar --confirm "price confirmed by Mike"
    python ep05_fiscal_ingest_robot\\quarantine_cli.py reject 2 --operator Eldar --confirm "wrong SKU on the PDF, supplier asked"

Why a CLI and not a dashboard: the episode shows the real database rows in
HeidiSQL; the operator action is one command, recorded with who, when and
why (value_source=operator). The CLI goes through the same writer lock as
the watch service, so both can run at the same time. Running the same
resolve twice has no second effect.
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ep05_fiscal_ingest_robot.adapter_config import load_config
from ep05_fiscal_ingest_robot.mysql_pos_adapter import PosAdapter, ResolutionRefused


def _price(text: str) -> Decimal:
    try:
        value = Decimal(text.replace("$", "").strip())
    except InvalidOperation:
        raise argparse.ArgumentTypeError(f"not a price: {text!r}")
    if value <= 0 or value.as_tuple().exponent < -2:
        raise argparse.ArgumentTypeError("price must be > 0 with at most 2 decimals")
    return value


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path)
    sub = ap.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list")
    ls.add_argument("--status", default="OPEN", choices=["OPEN", "RESOLVED", "REJECTED", "ALL"])
    for name in ("resolve", "reject"):
        p = sub.add_parser(name)
        p.add_argument("id", help="ep05_karantin.id, or sku:95012 for the single OPEN item of that SKU")
        p.add_argument("--operator", required=True)
        p.add_argument("--confirm", required=True, help="why / who confirmed it (stored in the audit)")
        if name == "resolve":
            p.add_argument("--price", required=True, type=_price, help="USD before sales tax")
    args = ap.parse_args(argv)
    adapter = PosAdapter(load_config(args.config), holder="quarantine_cli")

    if args.cmd == "list":
        rows = adapter.list_quarantine(args.status)
        if not rows:
            print("no items")
        for r in rows:
            print(f"#{r['id']:<3} {r['status']:<9} SKU {r['art_broj']}  {r['reason']:<26} "
                  f"{r['file_name']} [{r['locator'].split('/bbox')[0]}]")
            print(f"      source: {r['source_segment']}")
        return 0
    target = args.id
    if target.lower().startswith("sku:"):
        sku = int(target[4:])
        matches = [r for r in adapter.list_quarantine("ALL") if r["art_broj"] == sku]
        open_ = [r for r in matches if r["status"] == "OPEN"]
        if len(open_) > 1:
            print(f"REFUSED: {len(open_)} open items for SKU {sku}; use the numeric id")
            return 1
        if not matches:
            print(f"no quarantine item for SKU {sku}")
            return 1
        # No OPEN item but a closed one: let resolve() report "already done" (idempotent).
        target = (open_ or matches)[-1]["id"]
    args.id = int(target)
    try:
        res = adapter.resolve(args.id, operator=args.operator, confirmation=args.confirm,
                              price=getattr(args, "price", None), reject=args.cmd == "reject")
    except ResolutionRefused as exc:
        print(f"REFUSED: {exc}  (nothing was written)")
        return 1
    if res["effect"] == "none":
        print(res["message"])
    else:
        print(f"quarantine #{args.id}: {res['status']}  effect={res['effect']}"
              + (f"  art_id={res['art_id']}" if res.get("art_id") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
