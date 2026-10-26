"""
Synthetic EP01-style field messages for the model shootout, with a fixed seed.

    python benchmarks\\make_synthetic_set.py            # writes benchmarks/synthetic_set.json
    python benchmarks\\make_synthetic_set.py --check    # regenerates and compares, writes nothing

60 invented messages (no real people, firms or orders):
  20 easy   clean message, every field written, stated total matches
  40 hard   7 typos            (expected APPROVED: words misspelled, numbers and SKUs intact)
            7 two items in one sentence    (expected APPROVED)
            7 missing quantity             (expected QUARANTINE)
            7 unclear unit                 (expected QUARANTINE: box/case/reel price vs catalog price per piece)
            6 price differs from catalog   (expected QUARANTINE)
            6 unknown SKU                  (expected QUARANTINE: code is not in the catalog)

The expected outcome and every expected value are written here, from the same
numbers used to build the text. No model is involved in making the truth.

Every line carries a SKU from the catalog below (or an unknown one on purpose),
because the shootout adds a catalog check after the EP01 validation. That check
is part of the benchmark only; the episode code is not changed.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SEED = 20261023
HERE = Path(__file__).resolve().parent
OUT = HERE / "synthetic_set.json"

APPROVED, REVIEW = "APPROVED", "QUARANTINE"

# Price list (šifarnik): every item is sold per piece ("each").
CATALOG = {
    "BR120": ("Eaton 20A Circuit Breaker", "14.50"),
    "QO115": ("Square D 15A Circuit Breaker", "11.75"),
    "JB-4SQ": ("Square D Junction Box", "8.25"),
    "SDR-120-24": ("DIN Rail Power Supply 24V", "45.00"),
    "G2R-1-E": ("Omron Relay 12V", "15.00"),
    "NM12-2-250": ("Romex 12/2 NM-B Wire 250 ft Spool", "95.00"),
    "KL-11055": ("Klein Wire Stripper", "19.99"),
    "STM32F401RET6": ("STM32F401 Microcontroller", "4.80"),
    "ESP32-S3-WROOM-1": ("ESP32-S3 Module", "3.90"),
    "AGM-H6": ("AGM Battery H6", "199.99"),
    "WW-1G": ("Windshield Washer Fluid 1 gal", "3.49"),
    "WAGO-221-413": ("Wago Lever Connector 3-port", "0.89"),
    "LED-A19-9W": ("LED Bulb A19 9W", "2.75"),
    "GFCI-20": ("Leviton 20A GFCI Outlet", "22.50"),
    "EMT-12-10": ("1/2 in EMT Conduit 10 ft", "7.48"),
    "PVC-S40-1": ("1 in PVC Pipe Schedule 40 10 ft", "6.12"),
    "TAPE-33": ("3M Super 33+ Electrical Tape", "6.97"),
    "CB-6-50": ("Cat6 Patch Cable 50 ft", "12.40"),
}

# Codes that look like catalog codes but are not in it.
UNKNOWN_SKUS = ["BR125", "QO1150", "SDR-120-12", "G2R-2-E", "GFCI-15", "TAPE-88", "LED-A21-9W", "CB-5E-50"]
assert not set(UNKNOWN_SKUS) & set(CATALOG)

VENDORS = ["Home Depot", "Lowe's", "Grainger", "DigiKey Electronics", "Mouser", "Fastenal", "AutoZone"]
SENDERS = ["Mike", "Dave", "Carlos", "Ana", "Jen", "Tom", "Priya", "Luis"]
OFFICE = ["Sarah", "office", "team", "Kim"]

# Typos keep every number and every SKU intact.
TYPOS = {
    "picked": "pikced", "receipt": "reciept", "total": "totl", "each": "eahc", "bought": "bougth",
    "breaker": "breakr", "Breaker": "Breakr", "Circuit": "Circut", "Junction": "Junktion",
    "Supply": "Suply", "Relay": "Realy", "Connector": "Conector", "Outlet": "Outlte",
    "Conduit": "Condiut", "Electrical": "Electical", "Battery": "Batery", "Module": "Modle",
}

# Package words for "unclear unit": the catalog sells per piece, the message
# gives a price per package without saying how many pieces are inside.
PACKAGES = {"box": "boxes", "case": "cases", "pack": "packs", "bag": "bags"}


def money(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def fmt(x: Decimal) -> str:
    return f"${x:,.2f}"


class Builder:
    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        self.items = sorted(CATALOG)
        self.messages: list[dict] = []

    # --- small helpers -------------------------------------------------------
    def pick_items(self, n: int) -> list[str]:
        return self.rng.sample(self.items, n)

    def qty(self) -> int:
        return self.rng.choice([1, 2, 2, 3, 4, 5, 6, 8, 10, 12, 20])

    def job(self) -> str:
        return str(self.rng.randint(300, 999))

    def header(self) -> tuple[str, str, str]:
        return self.rng.choice(SENDERS), self.rng.choice(OFFICE), self.rng.choice(VENDORS)

    def line(self, sku: str, q: int, price: Decimal | None = None) -> dict:
        p = money(CATALOG[sku][1]) if price is None else price
        return dict(sku=sku, name=CATALOG[sku][0], quantity=q, unit_price=p, line_total=money(p * q))

    def add(self, mid: str, level: str, category: str, text: str, expected: str,
            lines: list[dict] | None, stated_total: Decimal | None, why: str) -> None:
        self.messages.append(dict(
            id=mid, level=level, category=category, text=text, expected=expected,
            stated_total=None if stated_total is None else float(stated_total),
            lines=None if lines is None else [
                dict(sku=l["sku"], quantity=l["quantity"], unit_price=float(l["unit_price"]),
                     line_total=float(l["line_total"])) for l in lines],
            why=why))

    @staticmethod
    def total(lines: list[dict]) -> Decimal:
        return money(sum(l["line_total"] for l in lines))

    def phrase(self, l: dict, with_line_total: bool = True) -> str:
        s = f"{l['quantity']}x {l['name']} (SKU: {l['sku']}) at {fmt(l['unit_price'])} each"
        if with_line_total:
            s += f" (line total {fmt(l['line_total'])})"
        return s

    # --- easy ----------------------------------------------------------------
    def easy(self, i: int) -> None:
        who, to, vendor = self.header()
        lines = [self.line(s, self.qty()) for s in self.pick_items(self.rng.choice([1, 2, 2]))]
        body = " and ".join(self.phrase(l) for l in lines)
        tot = self.total(lines)
        text = self.rng.choice([
            f"Hi {to}, {who} here. Picked up from {vendor} for Job #{self.job()}: {body}. Total on receipt is {fmt(tot)}.",
            f"Vendor: {vendor} | Job #{self.job()}. {body}. Receipt total {fmt(tot)}.",
            f"{to}, bought at {vendor} for Job #{self.job()}: {body}. Total {fmt(tot)}. - {who}",
        ])
        self.add(f"syn_easy_{i:02d}", "easy", "clean", text, APPROVED, lines, tot, "all fields written, totals match")

    # --- hard ----------------------------------------------------------------
    def typos(self, i: int) -> None:
        who, to, vendor = self.header()
        lines = [self.line(s, self.qty()) for s in self.pick_items(2)]
        tot = self.total(lines)
        text = (f"hey {to} picked up at {vendor} for job #{self.job()}: "
                f"{' and '.join(self.phrase(l) for l in lines)}. total on receipt {fmt(tot)}. {who}")
        for right, wrong in self.rng.sample(sorted(TYPOS.items()), len(TYPOS)):
            text = text.replace(right, wrong)
        self.add(f"syn_hard_typo_{i:02d}", "hard", "typos", text, APPROVED, lines, tot,
                 "misspelled words only; numbers and SKUs intact")

    def two_in_sentence(self, i: int) -> None:
        who, to, vendor = self.header()
        a, b = (self.line(s, self.qty()) for s in self.pick_items(2))
        tot = self.total([a, b])
        text = self.rng.choice([
            f"{to}, {who} at {vendor} for Job #{self.job()}, got {a['quantity']} {a['name']} ({a['sku']}) and "
            f"{b['quantity']} {b['name']} ({b['sku']}) at {fmt(a['unit_price'])} and {fmt(b['unit_price'])} each, "
            f"respectively, {fmt(tot)} all in.",
            f"Job #{self.job()} - {vendor}: {a['quantity']} of {a['sku']} {a['name']} at {fmt(a['unit_price'])} "
            f"plus {b['quantity']} of {b['sku']} {b['name']} at {fmt(b['unit_price'])} a piece, total {fmt(tot)}. {who}",
        ])
        self.add(f"syn_hard_two_{i:02d}", "hard", "two_items_one_sentence", text, APPROVED, [a, b], tot,
                 "two items share one sentence; all values written")

    def missing_qty(self, i: int) -> None:
        who, to, vendor = self.header()
        a, b = (self.line(s, self.qty()) for s in self.pick_items(2))
        vague = self.rng.choice(["some", "a bunch of", "a handful of", "a few", "however many they had of"])
        text = (f"{to}, {who} here, {vendor} for Job #{self.job()}: {self.phrase(a)}, plus {vague} "
                f"{b['name']} ({b['sku']}) at {fmt(b['unit_price'])} each, didn't count them.")
        self.add(f"syn_hard_noqty_{i:02d}", "hard", "missing_quantity", text, REVIEW, None, None,
                 f"no number for {b['sku']}")

    def unclear_unit(self, i: int) -> None:
        who, to, vendor = self.header()
        a = self.line(self.pick_items(1)[0], self.qty())
        cheap = [s for s in self.items if money(CATALOG[s][1]) < 25 and s != a["sku"]]
        sku = self.rng.choice(cheap)
        pkg = self.rng.choice(sorted(PACKAGES))
        n_pkg = self.rng.choice([2, 3, 4])
        pkg_price = money(money(CATALOG[sku][1]) * self.rng.choice([6, 10, 12, 25]) * Decimal("0.9"))
        text = (f"{who} for {to}: at {vendor}, Job #{self.job()}. {self.phrase(a)}. Also {n_pkg} {PACKAGES[pkg]} of "
                f"{CATALOG[sku][0]} ({sku}) at {fmt(pkg_price)} a {pkg}, not sure how many are in a {pkg}.")
        self.add(f"syn_hard_unit_{i:02d}", "hard", "unclear_unit", text, REVIEW, None, None,
                 f"{sku} priced per {pkg}; catalog sells per piece at {CATALOG[sku][1]}")

    def price_mismatch(self, i: int) -> None:
        who, to, vendor = self.header()
        a = self.line(self.pick_items(1)[0], self.qty())
        sku = self.rng.choice([s for s in self.items if s != a["sku"]])
        base = money(CATALOG[sku][1])
        new = money(base * Decimal(self.rng.choice(["1.15", "1.25", "0.80", "1.40"])))
        if new == base:
            new = base + Decimal("1.00")
        b = self.line(sku, self.qty(), price=new)
        tot = self.total([a, b])
        text = (f"Hi {to}, {vendor} for Job #{self.job()}: {self.phrase(a)} and {self.phrase(b)}. "
                f"Total {fmt(tot)}. {who}")
        self.add(f"syn_hard_price_{i:02d}", "hard", "price_not_in_catalog", text, REVIEW, None, tot,
                 f"{sku} at {new}, catalog says {base}")

    def unknown_sku(self, i: int, sku: str) -> None:
        who, to, vendor = self.header()
        a = self.line(self.pick_items(1)[0], self.qty())
        q = self.qty()
        p = money(self.rng.choice(["4.25", "9.99", "13.50", "27.00", "48.00"]))
        b = dict(sku=sku, name="part", quantity=q, unit_price=p, line_total=money(p * q))
        tot = self.total([a, b])
        text = (f"{to}, {who}: {vendor}, Job #{self.job()}. {self.phrase(a)}, and {q}x {sku} at {fmt(p)} each "
                f"(line total {fmt(b['line_total'])}). Total {fmt(tot)}.")
        self.add(f"syn_hard_sku_{i:02d}", "hard", "unknown_sku", text, REVIEW, None, tot,
                 f"{sku} is not in the catalog")

    def build(self) -> list[dict]:
        for i in range(1, 21):
            self.easy(i)
        for i in range(1, 8):
            self.typos(i)
        for i in range(1, 8):
            self.two_in_sentence(i)
        for i in range(1, 8):
            self.missing_qty(i)
        for i in range(1, 8):
            self.unclear_unit(i)
        for i in range(1, 7):
            self.price_mismatch(i)
        for i, sku in enumerate(self.rng.sample(UNKNOWN_SKUS, 6), start=1):
            self.unknown_sku(i, sku)
        return self.messages


def warmup_message() -> dict:
    """Fixed extra message, used only to warm up each model; never scored."""
    return dict(id="warmup", text="Hi office, Job #100 at Home Depot: 2x Eaton 20A Circuit Breaker (SKU: BR120) "
                                  "at $14.50 each (line total $29.00). Total $29.00.")


def build_set() -> dict:
    msgs = Builder(SEED).build()
    assert len(msgs) == 60 and sum(m["level"] == "easy" for m in msgs) == 20
    return dict(seed=SEED, catalog={k: dict(name=v[0], unit="each", unit_price=float(v[1])) for k, v in CATALOG.items()},
                warmup=warmup_message(), messages=msgs)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="regenerate and compare with the saved file")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    data = json.dumps(build_set(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        same = args.out.exists() and args.out.read_text(encoding="utf-8") == data
        print("same as saved file" if same else "DIFFERENT from saved file")
        return 0 if same else 1
    args.out.write_text(data, encoding="utf-8")
    counts: dict[str, int] = {}
    for m in json.loads(data)["messages"]:
        counts[m["category"]] = counts.get(m["category"], 0) + 1
    print(f"Written: {args.out}  ({counts})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
