"""
Check an anonymized message set before it is used: no phone numbers, e-mail
addresses, street addresses, company/store names or personal ID numbers may
remain. Placeholders such as [IME], [TELEFON], [ADRESA], [RADNJA] are allowed.

    python benchmarks\\check_anonymized.py path\\to\\messages.jsonl
    python benchmarks\\check_anonymized.py messages.jsonl --blocklist my_private_names.txt

Exit code 0 = nothing found, 1 = findings (each one printed masked), 2 = file error.

The rules are deliberately strict: a false alarm costs a minute, a missed phone
number cannot be taken back once the data is used. Prices, quantities and
5-digit SKUs are not flagged. A pattern cannot know every real store name, so
pass a private --blocklist (one name per line, never committed) with the names
of the actual stores, suppliers and people that appear in the original data.

Format of one record: see benchmarks/real_messages_FORMAT.md.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PLACEHOLDER_RE = re.compile(r"\[(IME|TELEFON|ADRESA|RADNJA|FIRMA|EMAIL|BROJ)\d*\]")

RULES: list[tuple[str, re.Pattern]] = [
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("url", re.compile(r"\b(?:https?://|www\.)\S+", re.I)),
    # +387 61 234 567, 061/234-567, 061 234 567, 0038761234567, +1 (555) 123-4567
    ("phone", re.compile(r"(?<![\d.,$€])(?:\+|00)\d{1,3}[\s/.-]?\(?\d{1,3}\)?(?:[\s/.-]?\d{2,4}){2,4}(?![\d.,])")),
    ("phone", re.compile(r"(?<![\d.,$€])0\d{1,2}[\s/.-]?\d{3}[\s/.-]?\d{3,4}(?![\d.,])")),
    # 13-digit JMBG / JIB, IBAN
    ("id_number", re.compile(r"(?<!\d)\d{12,13}(?!\d)")),
    ("iban", re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}\b")),
    # street addresses: BHS and English forms with a house number or "bb"
    ("address", re.compile(r"\b(?:ul\.|ulica|ulici|trg|trgu|naselje|bulevar|put|cesta|šetalište)\s+[\wČĆŽŠĐčćžšđ.\s]{2,40}?\s(?:\d{1,4}[a-zA-Z]?|bb)\b", re.I)),
    ("address", re.compile(r"\b[\wČĆŽŠĐčćžšđ]+\s+(?:bb|b\.b\.)\b", re.I)),
    ("address", re.compile(r"\b\d{1,5}\s+[A-Z][\w]+(?:\s[A-Z][\w]+)?\s(?:Street|St\.|Avenue|Ave\.?|Road|Rd\.|Blvd\.?|Lane|Drive|Dr\.)", re.I)),
    ("postal_code", re.compile(r"(?<!\d)7[1-9]\d{3}\s+[A-ZČĆŽŠĐ][a-zčćžšđ]+")),   # 71000 Sarajevo
    # legal forms and shop words that usually come with a name
    ("company", re.compile(r"\b(?:d\.?\s?o\.?\s?o\.?|d\.?\s?d\.?|s\.?\s?z\.?\s?r\.?|szr|obrt|zanatska radnja|trgovinska radnja|inc\.|llc|ltd\.?|gmbh)\b", re.I)),
    ("store_word", re.compile(r"\b(?:market|prodavnica|prodavnici|radnja|radnji|trgovina|trgovini|apoteka|pekara|mesnica|butik|kafić|kafana|restoran|salon)\s+[\"„“']?[A-ZČĆŽŠĐ][\wčćžšđ-]+", re.I)),
]


_DIAKRITIKA = str.maketrans({"č": "c", "ć": "c", "š": "s", "ž": "z", "đ": "d"})


def normalize(s: str) -> str:
    """Lowercase, no diacritics, dj -> d: messages are often typed without č/ć/š/ž/đ."""
    return s.lower().translate(_DIAKRITIKA).replace("dj", "d")


def name_pattern(name: str) -> re.Pattern:
    """Match a blocklisted name in any BHS case form and with or without diacritics.
    A final vowel is dropped from the stem (Ivana -> Ivani, Đorđe -> Đorđu)."""
    stem = normalize(name)
    if len(stem) >= 4 and stem[-1] in "aeiou":
        stem = stem[:-1]
    return re.compile(r"(?<!\w)" + re.escape(stem) + r"\w{0,4}(?!\w)")


def mask(s: str) -> str:
    """Show enough to find the spot, not enough to reveal the value."""
    s = s.strip()
    return s if len(s) <= 4 else s[:2] + "*" * (len(s) - 4) + s[-2:]


def texts_of(record: dict) -> list[tuple[str, str]]:
    """Every free-text field of a record that may hold personal data."""
    out = [("text", record.get("text", ""))]
    exp = record.get("expected") or {}
    out.append(("expected.note", exp.get("note", "") or ""))
    for i, line in enumerate(exp.get("lines") or []):
        out.append((f"expected.lines[{i}].name", line.get("name", "") or ""))
    return out


def check(path: Path, blocklist: list[str]) -> int:
    findings = 0
    # BHS case endings and missing diacritics are handled in name_pattern()/normalize()
    blocked = [(b, name_pattern(b)) for b in blocklist]
    for n, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"line {n}: not valid JSON ({e})")
            findings += 1
            continue
        rid = rec.get("id", f"line {n}")
        if rec.get("anonymization_checked_by") in (None, ""):
            print(f"{rid}: field anonymization_checked_by is empty")
            findings += 1
        for field, text in texts_of(rec):
            clean = PLACEHOLDER_RE.sub(" ", text)
            for kind, rx in RULES:
                for m in rx.finditer(clean):
                    print(f"{rid} [{field}] {kind}: {mask(m.group(0))!r}")
                    findings += 1
            for name, rx in blocked:
                if rx.search(normalize(clean)):
                    print(f"{rid} [{field}] blocklist: {mask(name)!r}")
                    findings += 1
    print("OK: nothing found" if findings == 0 else f"{findings} finding(s): fix them before the data is used")
    return 0 if findings == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", type=Path)
    ap.add_argument("--blocklist", type=Path, help="private list of real names, one per line")
    args = ap.parse_args()
    if not args.file.exists():
        print(f"not found: {args.file}")
        return 2
    names = []
    if args.blocklist:
        names = [l.strip() for l in args.blocklist.read_text(encoding="utf-8-sig").splitlines()
                 if l.strip() and not l.startswith("#")]
    return check(args.file, names)


if __name__ == "__main__":
    sys.exit(main())
