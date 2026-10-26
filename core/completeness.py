"""Dropped-line check for free-text messages, kept outside the video-aligned schema module.

The EP01 validator compares line totals with the stated total. When a message has
no total, a model that silently leaves out a whole line still passes. This check
compares the extraction with the source text instead: every money amount in the
text that is not a total is taken as one item price, and the extraction must have
at least that many items. It can only send a document to quarantine, never approve
one, and it does not see items that have no price in the text at all.

See benchmarks/README.md, addendum 2026-10-25, for the measurement and its limits.
"""

import re

MONEY = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?")

# Words just before an amount that make it a total, not an item price; up to four
# words may sit in between ("Total on receipt is $207.00", "total written at bottom is $290.00").
# `tot\w*` also covers misspellings such as "totl".
TOTAL_BEFORE = re.compile(
    r"(?:\btot\w*|\bttl\b|\bthat'?s|\bthat is|\bcomes? to|\bcame to|=)(?:\W+\w+){0,4}\W*$", re.IGNORECASE)
TOTAL_AFTER = re.compile(r"^\W*(?:all in\b|in total\b|total\b)", re.IGNORECASE)
WINDOW = 40  # characters looked at on each side of an amount


def item_price_count(text: str) -> int:
    """Number of money amounts in `text` that are not totals."""
    count = 0
    for m in MONEY.finditer(text or ""):
        before = text[max(0, m.start() - WINDOW):m.start()]
        after = text[m.end():m.end() + WINDOW]
        if TOTAL_BEFORE.search(before) or TOTAL_AFTER.search(after):
            continue
        count += 1
    return count


def dropped_line_reasons(source_text: str, po) -> list[str]:
    """Review reasons if the extraction has fewer items than item prices in the source. ADAPT HERE."""
    expected = item_price_count(source_text)
    if len(po.items) < expected:
        return [f"Possible dropped line: the source has {expected} item prices, the extraction has {len(po.items)} items."]
    return []
