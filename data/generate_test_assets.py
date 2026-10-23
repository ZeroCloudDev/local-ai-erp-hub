"""
Generates realistic B2B PDF invoices (Episode 2) and tilted thermal receipt photos (Episode 3)
so the entire 4-episode repository can be tested and recorded deterministically with zero external files.
"""

from pathlib import Path
import sys
import fitz  # PyMuPDF
from PIL import Image, ImageDraw, ImageFont

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DATA_DIR = Path(__file__).resolve().parent
EP2_DIR = DATA_DIR / "samples_ep2_pdf"
EP3_DIR = DATA_DIR / "samples_ep3_images"


def create_bordered_pdf(out_path: Path) -> None:
    """Creates a bordered B2B hardware/electronics PDF invoice (Mouser Electronics style)."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4

    page.insert_text((40, 45), "MOUSER ELECTRONICS B2B COMMERCIAL INVOICE", fontsize=14, fontname="helv")
    page.insert_text((40, 68), "Vendor: Mouser Electronics Inc.   |   Job / PO Number: PO-9042   |   Currency: USD", fontsize=10, fontname="helv")

    # Draw bordered table
    top_y = 100
    row_h = 26
    cols_x = [40, 145, 345, 405, 475, 555]
    headers = ["Part No (SKU)", "Item Description", "Qty", "Unit Price", "Line Total"]

    rows = [
        headers,
        ["STM32F407VGT6", "ARM Cortex-M4 32-bit MCU 168MHz", "10", "$11.20", "$112.00"],
        ["BME280-BREAKOUT", "Bosch I2C Environmental Sensor Board", "5", "$14.50", "$72.50"],
        ["MEANWELL-LRS-350", "24V 14.6A Switching Power Supply", "2", "$29.00", "$58.00"],
    ]

    for r_idx, row in enumerate(rows):
        y0 = top_y + r_idx * row_h
        y1 = y0 + row_h
        for c_idx in range(len(cols_x) - 1):
            x0, x1 = cols_x[c_idx], cols_x[c_idx + 1]
            rect = fitz.Rect(x0, y0, x1, y1)
            fill = (0.92, 0.94, 0.97) if r_idx == 0 else None
            page.draw_rect(rect, color=(0.2, 0.2, 0.2), fill=fill, width=1.0)
            page.insert_text((x0 + 6, y0 + 17), row[c_idx], fontsize=9.5, fontname="helv")

    page.insert_text((390, top_y + len(rows) * row_h + 25), "Overall Invoice Total: $242.50", fontsize=11, fontname="helv")
    doc.save(str(out_path))
    doc.close()


def create_borderless_pdf(out_path: Path) -> None:
    """
    Creates a modern borderless (whitespace-aligned) B2B PDF invoice (DigiKey style)
    with a subtle arithmetic discrepancy ($310.00 stated vs $295.00 sum) to showcase
    both `pdfplumber` X-Ray table detection and Layer 2 Pydantic math validation.
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)

    page.insert_text((40, 45), "DIGIKEY ELECTRONICS — WHITESPACE INVOICE", fontsize=14, fontname="helv")
    page.insert_text((40, 68), "Vendor: DigiKey Electronics   |   Job / PO Number: JOB-773   |   Currency: USD", fontsize=10, fontname="helv")

    top_y = 105
    row_h = 24
    cols_x = [40, 165, 375, 435, 505]

    rows = [
        ["SKU", "Component Name", "Qty", "Unit Price", "Line Total"],
        ["ESP32-S3-WROOM-1", "Wi-Fi + BLE MCU Module 16MB Flash", "20", "3.80", "76.00"],
        ["ADS1115IDGSR", "16-Bit I2C ADC 4-Channel Module", "15", "5.60", "84.00"],
        ["SALEAE-LOGIC-8", "8-Channel USB Logic Analyzer Probe", "1", "135.00", "135.00"],
    ]

    # Only horizontal header underline, zero vertical grid lines!
    page.draw_line((40, top_y + 20), (555, top_y + 20), color=(0.4, 0.4, 0.4), width=0.8)

    for r_idx, row in enumerate(rows):
        y = top_y + r_idx * row_h + 15
        for c_idx, text in enumerate(row):
            page.insert_text((cols_x[c_idx], y), text, fontsize=9.5, fontname="cour")

    page.insert_text((365, top_y + len(rows) * row_h + 30), "Overall Invoice Total: $310.00", fontsize=11, fontname="helv")
    doc.save(str(out_path))
    doc.close()


def _load_receipt_font(size: int = 22) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in ["C:\\Windows\\Fonts\\arial.ttf", "C:\\Windows\\Fonts\\segoeui.ttf", "C:\\Windows\\Fonts\\consola.ttf"]:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def create_tilted_receipt_image(out_path: Path, angle_deg: float = -2.1) -> None:
    """
    Creates a realistic thermal store receipt rotated by `angle_deg` degrees.
    Demonstrates why naive top-to-bottom OCR splits left item names from right prices,
    and how our 12-line Y-coordinate row sorter fixes it.
    """
    img = Image.new("RGB", (820, 620), color=(246, 245, 240))
    draw = ImageDraw.Draw(img)
    font_title = _load_receipt_font(25)
    font_body = _load_receipt_font(21)

    draw.text((175, 40), "Vendor: Fastenal Industrial Supply", fill=(20, 20, 20), font=font_title)
    draw.text((210, 78), "Job Number: JOB-884   |   Currency: USD", fill=(35, 35, 35), font=font_body)
    draw.line([(70, 115), (750, 115)], fill=(80, 80, 80), width=2)

    items = [
        ("Qty: 4", "Stainless Hex Bolts M8", "Unit: $12.50", "Total: $50.00"),
        ("Qty: 2", "Loctite 243 Threadlocker", "Unit: $18.00", "Total: $36.00"),
        ("Qty: 1", "Fluke 117 Multimeter", "Unit: $210.00", "Total: $210.00"),
    ]

    y = 148
    for qty_s, name, unit_p, total_p in items:
        draw.text((70, y), qty_s, fill=(15, 15, 15), font=font_body)
        draw.text((175, y), name, fill=(15, 15, 15), font=font_body)
        draw.text((465, y), unit_p, fill=(15, 15, 15), font=font_body)
        draw.text((625, y), total_p, fill=(15, 15, 15), font=font_body)
        y += 62

    draw.line([(80, y + 10), (720, y + 10)], fill=(80, 80, 80), width=2)
    draw.text((340, y + 35), "Overall Receipt Total: $296.00", fill=(10, 10, 10), font=font_title)

    # Rotate to simulate a technician taking a slightly tilted phone photo on a workbench
    rotated = img.rotate(angle_deg, expand=False, fillcolor=(230, 228, 220), resample=Image.BICUBIC)
    rotated.save(str(out_path))


if __name__ == "__main__":
    EP2_DIR.mkdir(parents=True, exist_ok=True)
    EP3_DIR.mkdir(parents=True, exist_ok=True)

    p1 = EP2_DIR / "mouser_bordered_invoice.pdf"
    p2 = EP2_DIR / "digikey_borderless_invoice.pdf"
    p3 = EP3_DIR / "tilted_fastenal_receipt.png"

    create_bordered_pdf(p1)
    create_borderless_pdf(p2)
    create_tilted_receipt_image(p3)

    print(f"Generated: {p1.name}, {p2.name}, {p3.name}")
