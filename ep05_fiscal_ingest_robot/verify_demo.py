"""
EP05 — PASS/FAIL against demo_inputs/expected_results.json.

    python ep05_fiscal_ingest_robot\\verify_demo.py --phase seed
    python ep05_fiscal_ingest_robot\\verify_demo.py --phase after_three_documents
    python ep05_fiscal_ingest_robot\\verify_demo.py --phase after_resolution
    python ep05_fiscal_ingest_robot\\verify_demo.py --phase after_replay
    python ep05_fiscal_ingest_robot\\verify_demo.py --phase after_fail_probe --snapshot-before before_fail

The expected file is the truth that was written before the first run. If the
database disagrees, the verdict is FAIL; the expected file is never edited
to make a run pass.

Integrity checks run on every phase and are independent of the JOIN shown in
HeidiSQL: duplicate art_broj, exactly one selected price row per article,
valid tarifa reference, canonical jedmjer text with an existing jmjera row,
and artikli.cij equal to the selected price row at 2 decimals.
"""

from __future__ import annotations

import argparse
import hashlib
from collections import Counter
import json
import sys
from decimal import Decimal
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ep05_fiscal_ingest_robot.adapter_config import AdapterConfig, load_config
from ep05_fiscal_ingest_robot.mysql_pos_adapter import PosAdapter
from ep05_fiscal_ingest_robot.pos_validation import canonical_unit_id, to_cents

EXPECTED = Path(__file__).resolve().parent / "demo_inputs" / "expected_results.json"
PHASES = ["seed", "after_three_documents", "after_resolution", "after_replay", "after_fail_probe"]


class Checker:
    def __init__(self) -> None:
        self.failures = 0

    def check(self, ok: bool, label: str, detail: str = "") -> None:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail and not ok else ""))
        if not ok:
            self.failures += 1


def load_state(cfg: AdapterConfig) -> dict:
    conn = PosAdapter(cfg).connect()
    where, params = cfg.price_list_where("c")
    try:
        with conn.cursor() as cur:
            cur.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT")
            cur.execute("SELECT a.id, a.art_broj, a.naziv, a.cij, a.tarifa, a.jedmjer, t.porez, j.nazivskr"
                        " FROM artikli a LEFT JOIN tarifa t ON t.id = a.tarifa"
                        " LEFT JOIN jmjera j ON a.jedmjer REGEXP '^[1-9][0-9]*$'"
                        "   AND j.id = CAST(a.jedmjer AS UNSIGNED)"
                        " WHERE a.art_broj BETWEEN %s AND %s AND a.deleted = 0 ORDER BY a.art_broj",
                        (cfg.sku_min, cfg.sku_max))
            arts = list(cur.fetchall())
            cur.execute(f"SELECT c.idart, c.cijena FROM artcjenik c WHERE {where}", params)
            prices: dict[str, list] = {}
            for r in cur.fetchall():
                prices.setdefault(r["idart"], []).append(r["cijena"])
            cur.execute("SELECT k.art_broj FROM ep05_karantin k WHERE k.status = 'OPEN' ORDER BY k.art_broj")
            open_q = [r["art_broj"] for r in cur.fetchall()]
            cur.execute("SELECT d.file_name, s.art_broj, s.outcome, s.reason, s.old_price, s.new_price,"
                        " s.value_source, s.locator FROM ep05_stavke s"
                        " JOIN ep05_dokumenti d ON d.id = s.doc_id ORDER BY s.id")
            stavke = list(cur.fetchall())
            conn.rollback()
    finally:
        conn.close()
    return {"arts": arts, "prices": prices, "open_q": open_q, "stavke": stavke}


def integrity(st: dict, c: Checker) -> None:
    skus = [a["art_broj"] for a in st["arts"]]
    dups = sorted({s for s in skus if skus.count(s) > 1})
    c.check(not dups, "no duplicate art_broj", f"duplicates {dups}")
    bad_rows = [a["art_broj"] for a in st["arts"] if len(st["prices"].get(a["id"], [])) != 1]
    c.check(not bad_rows, "exactly one selected price-list row per article", f"{bad_rows}")
    bad_tax = [a["art_broj"] for a in st["arts"] if a["porez"] is None]
    c.check(not bad_tax, "every article has a valid tarifa", f"{bad_tax}")
    bad_unit = [a["art_broj"] for a in st["arts"]
                if canonical_unit_id(a["jedmjer"]) is None or a["nazivskr"] is None]
    c.check(not bad_unit, "every jedmjer is canonical text of an existing jmjera.id", f"{bad_unit}")
    mismatch = [a["art_broj"] for a in st["arts"] if len(st["prices"].get(a["id"], [])) == 1
                and to_cents(a["cij"]) != to_cents(st["prices"][a["id"]][0])]
    c.check(not mismatch, "artikli.cij equals the selected artcjenik price (2 decimals)", f"{mismatch}")


def compare_articles(st: dict, expected: dict, c: Checker) -> None:
    by_sku = {a["art_broj"]: a for a in st["arts"]}
    wrong = []
    for sku, exp in expected.items():
        a = by_sku.get(int(sku))
        got = None if a is None else {"name": a["naziv"], "price": str(to_cents(a["cij"])),
                                      "tax_class": a["porez"], "sales_unit": a["nazivskr"]}
        if got != exp:
            wrong.append(f"{sku}: expected {exp}, got {got}")
    extra = sorted(set(by_sku) - {int(s) for s in expected})
    c.check(not wrong, f"{len(expected)} articles have the expected name/price/tax/unit", "; ".join(wrong[:5]))
    c.check(not extra, "no unexpected articles in the range", f"{extra}")


def compare_document_outcomes(st: dict, expected: dict, c: Checker) -> None:
    """Check every audit occurrence, never collapse duplicate SKU records."""
    for fname, dexp in expected.items():
        rows = [s for s in st["stavke"] if s["file_name"] == fname and s["value_source"] != "operator"]
        expected_count = dexp.get("row_count", len(dexp["items"]))
        c.check(len(rows) == expected_count, f"{fname}: exactly {expected_count} audit rows", f"got {len(rows)}")
        counts = Counter(row["art_broj"] for row in rows)
        problems = []
        for sku, iexp in dexp["items"].items():
            matching = [row for row in rows if row["art_broj"] == int(sku)]
            if len(matching) != 1:
                problems.append(f"{sku}: expected one outcome, got {len(matching)}")
                continue
            row = matching[0]
            if row["outcome"] not in iexp["outcome"]:
                problems.append(f"{sku}: {row['outcome']} not in {iexp['outcome']}")
            if "reason" in iexp and row["reason"] not in iexp["reason"]:
                problems.append(f"{sku}: reason {row['reason']} not in {iexp['reason']}")
            for field in ("old_price", "new_price"):
                if field in iexp and (row[field] is None or to_cents(row[field]) != Decimal(iexp[field])):
                    problems.append(f"{sku}: {field} {row[field]}")
        extra = set(counts) - {int(key) for key in dexp["items"]}
        if extra:
            problems.append(f"unexpected SKUs {sorted(extra, key=repr)}")
        c.check(not problems, f"{fname}: all expected per-item outcomes", "; ".join(problems))


def check_failure_result(result: dict, c: Checker, required_ops: int = 3) -> None:
    c.check(result.get("status") == "rolled_back" and result.get("injection_reached") is True
            and type(result.get("actual_ops")) is int and result["actual_ops"] == required_ops
            and type(result.get("planned_ops")) is int and result["planned_ops"] == required_ops,
            f"rollback injected after exactly {required_ops} real POS mutations", repr(result))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path)
    ap.add_argument("--phase", required=True, choices=PHASES)
    ap.add_argument("--snapshot-before", help="label of the snapshot taken before the fail probe")
    ap.add_argument("--failure-result", type=Path, help="JSON evidence from the injected service run")
    ap.add_argument("--expected-sha256", help="freeze the expected-results file for the entire rehearsal")
    args = ap.parse_args()
    cfg = load_config(args.config)
    expected_bytes = EXPECTED.read_bytes()
    expected_hash = hashlib.sha256(expected_bytes).hexdigest()
    print(f"expected_results sha256={expected_hash}")
    if args.expected_sha256 and expected_hash != args.expected_sha256.lower():
        print("FAIL: expected_results.json changed after rehearsal preflight")
        return 1
    exp = json.loads(expected_bytes.decode("utf-8"))
    st = load_state(cfg)
    c = Checker()
    print(f"EP05 verify - phase {args.phase}")
    integrity(st, c)

    if args.phase == "seed":
        c.check(len(st["arts"]) == 5, "5 seed articles", f"got {len(st['arts'])}")
        c.check(st["open_q"] == [], "0 open quarantine items", f"got {st['open_q']}")  # None = item without SKU
        compare_articles(st, exp["seed"], c)
    else:
        phase_exp = exp[args.phase] if args.phase != "after_three_documents" else exp["after_three_documents"]
        n = phase_exp["article_count"]
        c.check(len(st["arts"]) == n, f"{n} articles in {cfg.sku_min}-{cfg.sku_max}", f"got {len(st['arts'])}")
        c.check(sorted(st["open_q"], key=lambda x: (x is None, x or 0)) == phase_exp["open_quarantine_skus"],
                f"open quarantine = {phase_exp['open_quarantine_skus']}", f"got {st['open_q']}")
        articles = dict(exp["after_three_documents"]["articles"])
        if args.phase != "after_three_documents":
            res = exp["operator_resolution"]
            articles[str(res["sku"])] = res["expected_article"]
            op = [s for s in st["stavke"] if s["art_broj"] == res["sku"] and s["outcome"] in ("INSERT", "UPDATE")]
            c.check(len(op) == 1 and op[0]["value_source"] == res["expected_value_source"],
                    f"{res['sku']} written once, price value_source = operator", f"{op}")
        compare_articles(st, articles, c)

        compare_document_outcomes(st, exp["documents"], c)
        ins_10 = [s for s in st["stavke"] if s["art_broj"] == 95010 and s["outcome"] == "INSERT"]
        c.check(len(ins_10) == 1, "95010 inserted exactly once (message and photo)", f"{len(ins_10)} inserts")

    if args.phase == "after_fail_probe":
        from ep05_fiscal_ingest_robot.snapshot_demo_state import snapshot_path, take_snapshot, validate_snapshot
        if not args.failure_result:
            c.check(False, "failure operation-count proof", "pass --failure-result JSON")
        else:
            check_failure_result(json.loads(args.failure_result.read_text(encoding="utf-8")), c)
        if not args.snapshot_before:
            c.check(False, "snapshot comparison", "pass --snapshot-before LABEL")
        else:
            before = json.loads(snapshot_path(cfg, args.snapshot_before).read_text(encoding="utf-8"))
            c.check(validate_snapshot(before), "stored snapshot content matches its hash")
            now = take_snapshot(cfg)
            c.check(before["sha256"] == now["sha256"], "content snapshot identical before/after fail probe",
                    f"{before['sha256'][:12]} != {now['sha256'][:12]}")
        probe = [s for s in st["stavke"] if s["file_name"] == "fail_probe.txt"]
        c.check(not probe, "no audit rows from fail_probe.txt", f"{len(probe)} rows")

    print(("ALL PASS" if c.failures == 0 else f"{c.failures} FAIL") + f" - phase {args.phase}")
    return 0 if c.failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
