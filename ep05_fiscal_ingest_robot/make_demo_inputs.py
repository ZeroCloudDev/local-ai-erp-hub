"""
EP05 — generate the synthetic demo documents.

WHY THIS SCRIPT EXISTS
    The PDF and the printable shelf-tag sheet must be reproducible, so they
    are generated from the row lists below instead of being hand-edited.
    expected_results.json was written from the same business story BEFORE
    any processing run, and tests/test_ep05_inputs.py checks that the
    generated files and the expected results still agree.

WHAT IT DOES NOT DO
    It does not create the phone photo used in the video. That photo must be
    a real picture of the printed sheet (shelf_tags_to_print.pdf), saved as
    demo_inputs/shelf_tags_photo.jpg. The --simulated-photo option renders a
    clearly labelled SIMULATED image for automated tests only; it must never
    be shown in the video as if it were a real photo.

Usage:
    python ep05_fiscal_ingest_robot/make_demo_inputs.py
    python ep05_fiscal_ingest_robot/make_demo_inputs.py --simulated-photo tests/fixtures/ep05_simulated_shelf_photo.jpg
"""

from __future__ import annotations

import argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent
INPUTS = HERE / "demo_inputs"

STORE = "Maple Street Market (fictional store)"
PRICE_NOTE = "All retail prices in USD, before sales tax. Effective today."

# --- approved_retail_price_update.pdf --------------------------------------
# Exactly 20 rows: 95020-95038 (19 rows) + 95003.
#   * 95033 has tax class "X"  -> not in the approved tax map -> QUARANTINE
#   * 95003 "Paper Plates 9 in" collides with seed 95003 "Paper Cups 12 oz 50 ct"
#     -> identity conflict -> QUARANTINE
# There are no cost/wholesale prices and no margins in this document.
PDF_HEADER = ["SKU", "Description", "Sales Unit", "Tax Class",
              "Retail Price (USD, before sales tax)"]
PDF_ROWS = [
    ("95020", "Ground Coffee Medium 12 oz", "EA", "T", "8.99"),
    ("95021", "Green Tea 20 ct", "EA", "E", "3.49"),
    ("95022", "Peanut Butter 16 oz", "EA", "E", "3.79"),
    ("95023", "Strawberry Jam 18 oz", "EA", "E", "3.29"),
    ("95024", "Honey 12 oz", "EA", "E", "5.99"),
    ("95025", "Paper Towels 6 Roll", "EA", "T", "9.49"),
    ("95026", "Dish Soap 19 oz", "EA", "T", "2.99"),
    ("95027", "Trash Bags 13 gal 40 ct", "EA", "T", "8.79"),
    ("95028", "AA Batteries 8 pk", "EA", "T", "7.99"),
    ("95029", "Bananas", "LB", "E", "0.69"),
    ("95030", "Gala Apples", "LB", "E", "1.89"),
    ("95031", "Orange Juice 52 oz", "EA", "E", "3.99"),
    ("95032", "Spring Water 1 gal", "GAL", "E", "1.39"),
    ("95033", "Energy Drink 16 oz", "EA", "X", "2.79"),
    ("95034", "Potato Chips 8 oz", "EA", "T", "4.29"),
    ("95035", "Chocolate Bar 3.5 oz", "EA", "T", "2.49"),
    ("95036", "Paper Napkins 250 ct", "EA", "T", "3.99"),
    ("95037", "Plastic Forks 48 ct", "EA", "T", "2.29"),
    ("95038", "Hand Sanitizer 8 oz", "EA", "T", "3.49"),
    ("95003", "Paper Plates 9 in", "EA", "T", "5.49"),
]

# --- shelf_tags_to_print.pdf (to be printed and photographed) ---------------
# 95010 also appears in the message: whichever document arrives first inserts
# it, the second one finds the same name and price -> NO_CHANGE.
SHELF_HEADER = ["SKU", "Item", "Unit", "Tax", "Price"]
# The tax column says "Taxable" instead of a lone "T": OCR engines often drop
# isolated single letters, and a dropped tax class would (correctly) send a new
# article to quarantine. "Taxable" -> T is an approved synonym in the config.
SHELF_ROWS = [
    ("95040", "Granola Bar 1.5 oz", "EA", "Taxable", "$1.49"),
    ("95041", "Sparkling Water 12 oz", "EA", "Taxable", "$1.19"),
    ("95010", "Oat Milk 64 oz", "EA", "Taxable", "$4.79"),
]


def build_price_update_pdf(out: Path) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(out), pagesize=letter, title="Approved Retail Price Update",
                            author="EP05 synthetic demo", leftMargin=40, rightMargin=40)
    header_cells = [Paragraph(f"<b>{h}</b>", styles["BodyText"]) for h in PDF_HEADER]
    data = [header_cells] + [list(r) for r in PDF_ROWS]
    table = Table(data, colWidths=[50, 190, 65, 60, 150], repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8")),
        ("ALIGN", (4, 1), (4, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTSIZE", (0, 1), (-1, -1), 9.5),
    ]))
    story = [
        Paragraph("<b>Approved Retail Price Update</b>", styles["Title"]),
        Paragraph(STORE + " &mdash; synthetic demo document", styles["BodyText"]),
        Paragraph(PRICE_NOTE, styles["BodyText"]),
        Paragraph("Approved by: Store Manager (synthetic)", styles["BodyText"]),
        Spacer(1, 10),
        table,
    ]
    doc.build(story)


def build_shelf_print_pdf(out: Path) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    big = styles["BodyText"].clone("big", fontSize=15, leading=20)
    doc = SimpleDocTemplate(str(out), pagesize=letter, title="Shelf Tag Update (print me)",
                            author="EP05 synthetic demo")
    data = [SHELF_HEADER] + [list(r) for r in SHELF_ROWS]
    table = Table(data, colWidths=[75, 220, 50, 85, 70], rowHeights=34)
    table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 16),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("LINEBELOW", (0, 0), (-1, 0), 1.2, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story = [
        Paragraph("<b>MAPLE STREET MARKET - SHELF TAG UPDATE</b>", styles["Title"]),
        Paragraph(PRICE_NOTE, big),
        Spacer(1, 18),
        table,
        Spacer(1, 30),
        Paragraph("Synthetic demo sheet. Print on plain paper and photograph it with a phone.",
                  styles["Italic"]),
    ]
    doc.build(story)


def build_simulated_photo(out: Path) -> None:
    """Render the shelf sheet as an image with mild rotation and noise.

    SIMULATED — for automated OCR tests only. Not a real photo.
    """
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    def font(size: int):
        for name in ("DejaVuSans.ttf", "arial.ttf", "Arial.ttf"):
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                continue
        return ImageFont.load_default()

    img = Image.new("RGB", (1350, 900), (246, 244, 238))
    d = ImageDraw.Draw(img)
    d.text((80, 50), "MAPLE STREET MARKET - SHELF TAG UPDATE", fill=(20, 20, 20), font=font(42))
    d.text((80, 125), PRICE_NOTE, fill=(20, 20, 20), font=font(30))
    cols = [80, 260, 740, 860, 1110]
    y = 230
    for row in [SHELF_HEADER] + [list(r) for r in SHELF_ROWS]:
        for x, cell in zip(cols, row):
            d.text((x, y), cell, fill=(15, 15, 15), font=font(40))
        y += 110
    d.text((80, 800), "SIMULATED RENDER - NOT A REAL PHOTO", fill=(150, 30, 30), font=font(26))
    img = img.rotate(2.0, resample=Image.BICUBIC, expand=True, fillcolor=(90, 90, 90))
    img = img.filter(ImageFilter.GaussianBlur(0.4))
    arr = np.asarray(img).astype(np.int16)
    rng = np.random.default_rng(5)
    arr = np.clip(arr + rng.normal(0, 4, arr.shape), 0, 255).astype(np.uint8)
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(arr).save(out, quality=88)


def main() -> None:
    # invariant=1 removes timestamps/random IDs so the PDFs are byte-reproducible
    from reportlab import rl_config
    rl_config.invariant = 1
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--simulated-photo", type=Path, help="also render a SIMULATED photo (tests only)")
    args = ap.parse_args()
    INPUTS.mkdir(exist_ok=True)
    build_price_update_pdf(INPUTS / "approved_retail_price_update.pdf")
    build_shelf_print_pdf(INPUTS / "shelf_tags_to_print.pdf")
    print("written:", INPUTS / "approved_retail_price_update.pdf")
    print("written:", INPUTS / "shelf_tags_to_print.pdf  (print it, photograph it -> shelf_tags_photo.jpg)")
    if args.simulated_photo:
        build_simulated_photo(args.simulated_photo)
        print("written (SIMULATED, tests only):", args.simulated_photo)


if __name__ == "__main__":
    main()
