"""
Test doubles for EP05. NOT used by the service.

scripted_llm imitates a well-behaved model for ONE source line (the shape of
the real call): it returns name / unit / tax class / price as written.
Tests then make it misbehave on purpose (invent a price, add a tax class,
rename, put the SKU into the name, return broken JSON) to prove that the
deterministic checks catch it.

The real model is only exercised on the presenter's laptop (Ollama), see
run_ep05_rehearsal.ps1. Container tests never claim to test the model.
"""

from __future__ import annotations

import json
import re

SKU_RE = re.compile(r"(?<!\d)(\d{5})(?!\d)")
PRICE_RE = re.compile(r"\$\s?\d+(?:\.\d{1,2})?")
SET_RE = re.compile(r"Set (.+?), SKU (\d{5}), to (\$\d+\.\d{2})")


def parse_line(text: str) -> dict:
    m = SET_RE.search(text)
    if m:
        return dict(name=m.group(1), sales_unit=None, tax_class=None, retail_price=m.group(3))
    sku = SKU_RE.search(text)
    cells = [c.strip() for c in text.split("|")]
    first = cells[0]
    if sku and first.startswith(sku.group(1)) and len(first) > 5:      # "95010 Oat Milk | EA | ..."
        name, rest = first[sku.end():].strip(), cells[1:]
    else:                                                              # "95040 | Granola Bar | EA | ..."
        name, rest = (cells[1] if len(cells) > 1 else None), cells[2:]
    unit = rest[0] if len(rest) > 0 else None
    tax = rest[1] if len(rest) > 1 else None
    if tax and tax.lower().startswith("tax "):
        tax = tax[4:]
    price = PRICE_RE.search(text)
    return dict(name=name, sales_unit=unit, tax_class=tax, retail_price=price.group(0) if price else None)


def scripted_llm(line: str, model: str) -> tuple[str, dict]:
    return json.dumps(parse_line(line)), {"wall_time_ms": 0.0, "load_duration_ms": 0.0}


def make_llm(mutate):
    """mutate(line, item_dict) -> item_dict (or a raw string to return as-is)."""
    def llm(line: str, model: str):
        item = mutate(line, parse_line(line))
        raw = item if isinstance(item, str) else json.dumps(item)
        return raw, {"wall_time_ms": 0.0}
    return llm
