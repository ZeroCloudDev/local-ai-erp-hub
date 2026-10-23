"""
Generates all 1920x1080 (16:9) production visuals, architecture diagrams, OCR bounding-box overlays,
and YouTube thumbnail templates directly into `E:\\ProjektiOtvoreni\\yt_edit\\studio\\local-ai-zero-cloud`.
"""

from pathlib import Path
import shutil
import sys
import cv2
import fitz  # PyMuPDF
from PIL import Image, ImageDraw, ImageFont
from rapidocr_onnxruntime import RapidOCR

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT_CODE = Path(__file__).resolve().parent.parent
STUDIO_ROOT = Path(r"E:\ProjektiOtvoreni\yt_edit\studio\local-ai-zero-cloud")

EP1_SNIMCI = STUDIO_ROOT / "ep01-pydantic-json-lock" / "snimci"
EP2_SNIMCI = STUDIO_ROOT / "ep02-pdf-tables-xray" / "snimci"
EP3_SNIMCI = STUDIO_ROOT / "ep03-fast-cpu-ocr-pipeline" / "snimci"
EP4_SNIMCI = STUDIO_ROOT / "ep04-zero-ui-watchdog" / "snimci"

BG_DARK = (15, 23, 42)        # Slate 900 (#0f172a)
PANEL_DARK = (30, 41, 59)     # Slate 800 (#1e293b)
ACCENT_TEAL = (100, 221, 189) # Studio Mint/Teal (#64ddbd)
ACCENT_RED = (248, 113, 113)  # Soft Red (#f87171)
ACCENT_AMBER = (251, 191, 36) # Amber (#fbbf24)
TEXT_WHITE = (248, 250, 252)
TEXT_MUTED = (148, 163, 184)


def load_font(size: int, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if mono:
        candidates = [r"C:\Windows\Fonts\consolab.ttf" if bold else r"C:\Windows\Fonts\consola.ttf"]
    else:
        candidates = [
            r"C:\Windows\Fonts\segoeuib.ttf" if bold else r"C:\Windows\Fonts\segoeui.ttf",
            r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
        ]
    for c in candidates:
        if Path(c).exists():
            return ImageFont.truetype(c, size=size)
    return ImageFont.load_default()


def draw_badge(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, bg_color: tuple[int, int, int], text_color: tuple[int, int, int] = BG_DARK) -> None:
    font = load_font(26, bold=True)
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0] + 36
    h = bbox[3] - bbox[1] + 20
    x, y = xy
    draw.rounded_rectangle([x, y, x + w, y + h], radius=10, fill=bg_color)
    draw.text((x + 18, y + 8), text, fill=text_color, font=font)


def generate_ep01_visuals() -> None:
    EP1_SNIMCI.mkdir(parents=True, exist_ok=True)

    # 1. Thumbnail / Split Comparison (1920x1080)
    img = Image.new("RGB", (1920, 1080), BG_DARK)
    draw = ImageDraw.Draw(img)

    # Top banner
    draw.text((80, 48), "ZERO-CLOUD ERP ENGINE ON A LAPTOP  •  PART 1", fill=ACCENT_TEAL, font=load_font(28, bold=True))
    draw.text((80, 92), "ZERO CLOUD ERP: BULLETPROOF LOCAL AI", fill=TEXT_WHITE, font=load_font(62, bold=True))

    # Left Card: Naive Prompting Failure
    draw.rounded_rectangle([80, 210, 920, 980], radius=20, fill=PANEL_DARK, outline=ACCENT_RED, width=4)
    draw_badge(draw, (120, 245), "❌ NAIVE PROMPT + REGEX", ACCENT_RED, BG_DARK)
    bad_code = (
        'Here is the extracted JSON:\n'
        '```json\n'
        '{\n'
        '  "item": "Romex Wire",\n'
        '  "qty": 3,\n'
        '  "unit_price": 95.00,  // HALLUCINATED!\n'
        '  "total": 285.00,\n'
        '}\n'
        '```\n\n'
        'JSONDecodeError: Expecting value:\n'
        'line 1 column 1 (char 0)'
    )
    draw.text((120, 340), bad_code, fill=(254, 202, 202), font=load_font(30, mono=True))
    draw.text((120, 880), "• Crashes json.loads() on markdown wrapper\n• Invents missing unit prices silently", fill=ACCENT_RED, font=load_font(26, bold=True))

    # Right Card: Two-Layer Defense
    draw.rounded_rectangle([1000, 210, 1840, 980], radius=20, fill=PANEL_DARK, outline=ACCENT_TEAL, width=4)
    draw_badge(draw, (1040, 245), "✅ OLLAMA GBNF + PYDANTIC LAYER 2", ACCENT_TEAL, BG_DARK)
    good_code = (
        '{\n'
        '  "vendor_name": "Lowe\'s",\n'
        '  "job_or_po_number": "409",\n'
        '  "items": [\n'
        '    {\n'
        '      "item_name": "12/2 Romex NM-B wire",\n'
        '      "quantity": 3.0,\n'
        '      "unit_price": null,\n'
        '      "line_total": null\n'
        '    }\n'
        '  ],\n'
        '  "stated_total": 285.0,\n'
        '  "needs_human_review": true\n'
        '}'
    )
    draw.text((1040, 330), good_code, fill=(209, 250, 229), font=load_font(28, mono=True))
    draw.text((1040, 880), "• Layer 1: C++ Grammar Lock (0 syntax errors)\n• Layer 2: Python Math & Null Audit Flag", fill=ACCENT_TEAL, font=load_font(26, bold=True))

    img.save(str(EP1_SNIMCI / "01-thumbnail-ep01.png"))

    # 2. Architecture Slide: Two-Layer Defense Flow
    arch = Image.new("RGB", (1920, 1080), BG_DARK)
    d2 = ImageDraw.Draw(arch)
    d2.text((80, 50), "ARCHITECTURE: TWO-LAYER DEFENSE FOR SMALL LOCAL LLMs (3B)", fill=ACCENT_TEAL, font=load_font(30, bold=True))
    d2.text((80, 100), "Why Valid JSON Syntax ≠ Valid Business Data", fill=TEXT_WHITE, font=load_font(52, bold=True))

    boxes = [
        (80, 260, 480, 820, "1. CHAOTIC INPUT", TEXT_MUTED, "Field SMS / WhatsApp\nVoice Transcripts\n\n• Smudged prices\n• Missing quantities\n• Typos & filler words\n• Wrong receipt totals"),
        (560, 260, 1000, 820, "2. LAYER 1: SYNTAX LOCK", ACCENT_TEAL, "Ollama C++ GBNF Mask\n(qwen2.5:3b on CPU)\n\n• format = model_json_schema()\n• Invalid JSON tokens masked\n  to probability 0.0\n• SkipJsonSchema hides audit\n  fields from LLM"),
        (1080, 260, 1520, 820, "3. LAYER 2: PYTHON MATH", ACCENT_AMBER, "Pydantic @model_validator\n(Deterministic Python)\n\n• Checks qty * unit == line\n• Checks sum(lines) == total\n• Keeps missing prices null\n• Sets needs_human_review"),
        (1580, 260, 1860, 820, "4. SQLITE ERP", ACCENT_TEAL, "erp_procurement.db\n\n• SHA-256 Idempotent\n• ✅ AUTO-APPROVED\n• ⚠️ QUARANTINE"),
    ]
    for x0, y0, x1, y1, title, col, body in boxes:
        d2.rounded_rectangle([x0, y0, x1, y1], radius=18, fill=PANEL_DARK, outline=col, width=3)
        d2.text((x0 + 25, y0 + 30), title, fill=col, font=load_font(28, bold=True))
        d2.text((x0 + 25, y0 + 100), body, fill=TEXT_WHITE, font=load_font(25))

    d2.text((80, 900), "Measured on AMD Ryzen 7 PRO 7840U (Pure CPU, Zero Cloud): ~8.7s per order at 16.9 tokens/sec", fill=ACCENT_TEAL, font=load_font(30, bold=True))
    arch.save(str(EP1_SNIMCI / "02-architecture-two-layer-defense.png"))


def generate_ep02_visuals() -> None:
    EP2_SNIMCI.mkdir(parents=True, exist_ok=True)
    pdf_dir = ROOT_CODE / "data" / "samples_ep2_pdf"
    xray_src = pdf_dir / "digikey_xray_debug.png"
    if xray_src.exists():
        shutil.copy2(xray_src, EP2_SNIMCI / "03-digikey-xray-raw.png")

    # Render bordered PDF page to PNG for comparison slide
    bordered_pdf = pdf_dir / "mouser_bordered_invoice.pdf"
    doc = fitz.open(str(bordered_pdf))
    pix = doc[0].get_pixmap(dpi=150)
    bordered_png = EP2_SNIMCI / "02-mouser-bordered-invoice.png"
    pix.save(str(bordered_png))
    doc.close()

    # 1. Create 1920x1080 Episode 2 Thumbnail / Comparison Slide
    canvas = Image.new("RGB", (1920, 1080), BG_DARK)
    draw = ImageDraw.Draw(canvas)
    draw.text((80, 45), "ZERO-CLOUD ERP ENGINE ON A LAPTOP  •  PART 2", fill=ACCENT_TEAL, font=load_font(28, bold=True))
    draw.text((80, 90), "PDF TABLE X-RAY: MULTI-COLUMN INVOICES", fill=TEXT_WHITE, font=load_font(56, bold=True))

    # Left: Broken pypdf stream
    draw.rounded_rectangle([80, 200, 900, 990], radius=20, fill=PANEL_DARK, outline=ACCENT_RED, width=4)
    draw_badge(draw, (115, 235), "❌ STANDARD pypdf.extract_text()", ACCENT_RED, BG_DARK)
    broken_txt = (
        "SKU Component Name Qty Unit Price Line Total\n"
        "ESP32-S3-WROOM-1 Wi-Fi + BLE MCU 20 3.80 76.00\n"
        "ADS1115IDGSR 16-Bit I2C ADC 15 5.60 84.00\n"
        "SALEAE-LOGIC-8 USB Logic Probe 1 135.00 135.00\n\n"
        "• No <table> tags exist inside a PDF!\n"
        "• Multi-line cells & borderless columns\n"
        "  smash together into corrupted strings."
    )
    draw.text((115, 330), broken_txt, fill=(254, 202, 202), font=load_font(27, mono=True))

    # Right: Visual X-Ray image embedded
    draw.rounded_rectangle([960, 200, 1840, 990], radius=20, fill=PANEL_DARK, outline=ACCENT_TEAL, width=4)
    draw_badge(draw, (995, 235), "✅ pdfplumber VISUAL X-RAY + pymupdf4llm", ACCENT_TEAL, BG_DARK)
    if xray_src.exists():
        xray_img = Image.open(xray_src).convert("RGB")
        w, h = xray_img.size
        cropped = xray_img.crop((0, 0, w, int(h * 0.42)))
        cropped.thumbnail((810, 560))
        canvas.paste(cropped, (995, 320))
    draw.text((995, 895), "• Reconstructs exact Markdown pipe tables (| SKU | Qty | Price |)\n• Plugs directly into Part 1 ERP Engine in 15 lines of Python", fill=ACCENT_TEAL, font=load_font(24, bold=True))
    canvas.save(str(EP2_SNIMCI / "01-thumbnail-ep02.png"))

    # 4. Roadmap Slide with Part 2 Highlighted
    road = Image.new("RGB", (1920, 1080), BG_DARK)
    d_road = ImageDraw.Draw(road)
    d_road.text((80, 45), "ZERO-CLOUD ERP ENGINE ON A LAPTOP  •  4-PART SERIES ROADMAP", fill=ACCENT_TEAL, font=load_font(28, bold=True))
    d_road.text((80, 90), "Series Architecture & Ingestion Roadmap", fill=TEXT_WHITE, font=load_font(54, bold=True))

    r_cards = [
        (80, 220, 480, 850, "EPISODE 1", "COMPLETED", ACCENT_TEAL,
         "Structured Text & Chat\n\n• WhatsApp / Field SMS\n• Two-Layer Defense\n• C++ GBNF Syntax Lock\n• Pydantic Math Audit\n• SQLite Idempotency\n\n✅ Auto-Approved: $207"),
        (520, 220, 960, 850, "EPISODE 2", "CURRENT EPISODE", ACCENT_TEAL,
         "Multi-Column PDF Tables\n\n• Bordered: pymupdf4llm\n• Borderless: pdfplumber\n• Cell Boundary X-Ray\n• Footer Total Recovery\n• 100% Core Reuse\n\n🔍 Live: Mouser & DigiKey"),
        (1000, 220, 1440, 850, "EPISODE 3", "UPCOMING", TEXT_MUTED,
         "Fast CPU Receipt OCR\n\n• Crooked Phone Photos\n• RapidOCR (435 ms)\n• 12-Line Y-Row Sorter\n• Zero Cloud Vision APIs\n• 10x Faster than VLM\n\n⚡ Sub-Second Ingestion"),
        (1480, 220, 1840, 850, "EPISODE 4", "UPCOMING", TEXT_MUTED,
         "Autonomous Daemon\n\n• Watchdog File Service\n• Zero-Click Drop-Folder\n• Auto-Router Pipeline\n• Approved vs Quarantine\n• Full System Demo\n\n🤖 Autonomous Back-Office"),
    ]
    for x0, y0, x1, y1, ep_title, ep_status, col, body in r_cards:
        is_cur = ep_status == "CURRENT EPISODE"
        border_w = 4 if is_cur else 2
        bg_col = (20, 35, 55) if is_cur else PANEL_DARK
        d_road.rounded_rectangle([x0, y0, x1, y1], radius=18, fill=bg_col, outline=col, width=border_w)
        d_road.text((x0 + 25, y0 + 30), ep_title, fill=col, font=load_font(26, bold=True))
        status_bg = ACCENT_TEAL if is_cur else PANEL_DARK
        status_fg = BG_DARK if is_cur else TEXT_MUTED
        draw_badge(d_road, (x0 + 25, y0 + 75), ep_status, status_bg, status_fg)
        d_road.text((x0 + 25, y0 + 150), body, fill=TEXT_WHITE, font=load_font(24))

    d_road.text((80, 930), "Open Source Repository: github.com/eldar6776/local-ai-erp-hub", fill=ACCENT_TEAL, font=load_font(28, bold=True))
    road.save(str(EP2_SNIMCI / "04-series-roadmap-ep02.png"))

    # 5. Intermediate Slide: Why PDF Has No Tables (The Floating Coordinate Trap)
    trap = Image.new("RGB", (1920, 1080), BG_DARK)
    dtrap = ImageDraw.Draw(trap)
    dtrap.text((80, 45), "THE ANATOMY OF PDF DOCUMENTS  •  WHY STANDARD PARSERS FAIL", fill=ACCENT_TEAL, font=load_font(28, bold=True))
    dtrap.text((80, 90), "PDF Has No Tables: The Floating Coordinate Trap", fill=TEXT_WHITE, font=load_font(52, bold=True))

    dtrap.rounded_rectangle([80, 200, 900, 860], radius=18, fill=PANEL_DARK, outline=ACCENT_RED, width=3)
    draw_badge(dtrap, (115, 230), "WHAT DEVELOPERS EXPECT", ACCENT_RED, BG_DARK)
    dtrap.text((115, 310), "Relational Table Structure:\n\n<table>\n  <tr>\n    <th>Part No</th>\n    <th>Description</th>\n    <th>Qty</th>\n    <th>Unit Price</th>\n  </tr>\n  <tr>\n    <td>STM32F407</td>\n    <td>MCU 168MHz</td>\n    <td>10</td>\n    <td>$11.20</td>\n  </tr>\n</table>", fill=(254, 202, 202), font=load_font(26, mono=True))

    dtrap.rounded_rectangle([960, 200, 1840, 860], radius=18, fill=PANEL_DARK, outline=ACCENT_AMBER, width=3)
    draw_badge(dtrap, (995, 230), "WHAT PDF ACTUALLY STORES", ACCENT_AMBER, BG_DARK)
    raw_pdf_stream = (
        "Raw PDF Operator Stream (PostScript Drawing Canvas):\n\n"
        "BT\n"
        "  /F1 10.0 Tf\n"
        "  72.0 712.5 Td (STM32F407) Tj   % X=72.0, Y=712.5\n"
        "  154.2 0.0 Td (MCU 168MHz) Tj   % Offset X=154.2\n"
        "  182.0 0.0 Td (10) Tj           % Offset X=182.0\n"
        "  45.0 0.0 Td ($11.20) Tj        % Offset X=45.0\n"
        "ET\n\n"
        "• Letters are painted at absolute canvas positions.\n"
        "• Naive pypdf reads strings in reading-order, merging\n"
        "  adjacent words without respecting column gaps!"
    )
    dtrap.text((995, 310), raw_pdf_stream, fill=TEXT_WHITE, font=load_font(24, mono=True))
    dtrap.text((80, 920), "Result of naive text extraction: 'STM32F407 MCU 168MHz 10 $11.20' -> LLM confuses 168MHz with quantity!", fill=ACCENT_RED, font=load_font(26, bold=True))
    trap.save(str(EP2_SNIMCI / "05-pdf-coordinate-chaos.png"))

    # 6. Intermediate Slide: Bordered vs Borderless Invoices
    bvb = Image.new("RGB", (1920, 1080), BG_DARK)
    dbvb = ImageDraw.Draw(bvb)
    dbvb.text((80, 45), "DUAL PROCUREMENT STRATEGY  •  BORDERED VS BORDERLESS INVOICES", fill=ACCENT_TEAL, font=load_font(28, bold=True))
    dbvb.text((80, 90), "Two Distinct Document Classes Require Two Adapters", fill=TEXT_WHITE, font=load_font(52, bold=True))

    dbvb.rounded_rectangle([80, 200, 900, 860], radius=18, fill=PANEL_DARK, outline=ACCENT_TEAL, width=3)
    draw_badge(dbvb, (115, 230), "CLASS A: BORDERED VENDOR INVOICES", ACCENT_TEAL, BG_DARK)
    dbvb.text((115, 310), "Example: Mouser Electronics, Grainger\n\n• Physical grid lines drawn in PDF vector paths\n• Clear cell delimiters (top, bottom, left, right)\n\nSolution: pymupdf4llm\n• Uses MuPDF C-library vector intersection\n• Detects table bounding boxes in < 200 ms\n• Emits clean Markdown pipes: | SKU | Qty | Price |\n• Zero GPU or heavy ML dependencies", fill=TEXT_WHITE, font=load_font(26))

    dbvb.rounded_rectangle([960, 200, 1840, 860], radius=18, fill=PANEL_DARK, outline=ACCENT_AMBER, width=3)
    draw_badge(dbvb, (995, 230), "CLASS B: BORDERLESS WHITESPACE INVOICES", ACCENT_AMBER, BG_DARK)
    dbvb.text((995, 310), "Example: DigiKey Electronics, Stripe, AWS\n\n• Zero vertical grid lines between columns\n• Columns separated purely by whitespace gaps\n• pymupdf4llm sees no table lines and fails!\n\nSolution: pdfplumber Visual X-Ray\n• Character-level X-coordinate projection\n• Clusters words by horizontal proximity\n• Extracts whitespace-aligned Markdown table\n• Preserves summary lines outside the grid", fill=TEXT_WHITE, font=load_font(26))

    dbvb.text((80, 920), "Our Pipeline: Automatic Fallback -> If pymupdf4llm finds no table grid, trigger pdfplumber X-Ray!", fill=ACCENT_TEAL, font=load_font(28, bold=True))
    bvb.save(str(EP2_SNIMCI / "06-bordered-vs-borderless.png"))

    # 7. Intermediate Slide: Visual X-Ray & Footer Preservation
    xray_slide = Image.new("RGB", (1920, 1080), BG_DARK)
    dxray = ImageDraw.Draw(xray_slide)
    dxray.text((80, 45), "DEEP DIVE: VISUAL CELL PROJECTION & FOOTER PRESERVATION", fill=ACCENT_TEAL, font=load_font(28, bold=True))
    dxray.text((80, 90), "How Visual X-Ray Reconstructs Invisible Columns", fill=TEXT_WHITE, font=load_font(52, bold=True))

    dxray.rounded_rectangle([80, 200, 920, 860], radius=18, fill=PANEL_DARK, outline=ACCENT_TEAL, width=3)
    draw_badge(dxray, (115, 230), "1. CELL GEOMETRY PROJECTION", ACCENT_TEAL, BG_DARK)
    dxray.text((115, 310), "pdfplumber table_settings:\n  • vertical_strategy = 'text'\n  • horizontal_strategy = 'text'\n  • snap_tolerance = 4\n\nAlgorithm Mechanism:\n1. Computes character bounding boxes [x0, top, x1, bottom]\n2. Detects column gutters where no characters exist\n3. Casts virtual vertical grid lines through whitespace\n4. Groups words into strict row and column cells", fill=TEXT_WHITE, font=load_font(25, mono=True))

    dxray.rounded_rectangle([980, 200, 1840, 860], radius=18, fill=PANEL_DARK, outline=ACCENT_AMBER, width=3)
    draw_badge(dxray, (1015, 230), "2. FOOTER TOTAL SAFEGUARD", ACCENT_AMBER, BG_DARK)
    dxray.text((1015, 310), "The Hidden Danger of Standard Table Extractors:\n• Summary lines sit 20px below the table grid:\n  'Overall Invoice Total: $310.00'\n• Standard table finders discard lines outside the grid!\n• Without the stated total, Layer 2 math audit cannot verify sums.\n\nOur 4-Line Python Safeguard (pdf_parser.py:65-70):\n  for line in raw_page_text.splitlines():\n      if 'total' in line.lower() or 'vendor:' in line.lower():\n          markdown_blocks.append(line.strip())", fill=TEXT_WHITE, font=load_font(24, mono=True))

    dxray.text((80, 920), "Result: Both the multi-column line items AND the stated total are safely fed into Qwen 2.5 3B!", fill=ACCENT_TEAL, font=load_font(28, bold=True))
    xray_slide.save(str(EP2_SNIMCI / "07-xray-cell-projection.png"))

    # 8. Architecture Flow Slide: 15 Lines of Adapter + 100% Core Reuse
    aflow = Image.new("RGB", (1920, 1080), BG_DARK)
    da = ImageDraw.Draw(aflow)
    da.text((80, 45), "SYSTEM ARCHITECTURE  •  ZERO REDUNDANCY ACROSS EPISODES", fill=ACCENT_TEAL, font=load_font(28, bold=True))
    da.text((80, 90), "Episode 2 Adapter Plugs Directly into Episode 1 Core", fill=TEXT_WHITE, font=load_font(52, bold=True))

    a_boxes = [
        (80, 240, 480, 840, "EPISODE 2 ADAPTER", ACCENT_AMBER,
         "ep02_pdf_tables/\npdf_parser.py\n\n• extract_broken_pypdf()\n• extract_clean_pymupdf()\n• extract_whitespace_xray()\n• process_pdf_to_erp()\n\nOnly 15 new lines of code!"),
        (540, 240, 940, 840, "STANDARDIZED INTERFACE", ACCENT_TEAL,
         "Clean Markdown Table\n\n| Part No | Qty | Price |\n| STM32F4 | 10  | 11.20 |\n\nOverall Invoice Total:\n$242.50\n\nIdentical to Episode 1!"),
        (1000, 240, 1400, 840, "EPISODE 1 CORE ENGINE", ACCENT_TEAL,
         "core/llm_client.py\ncore/schemas.py\n\n• Qwen 2.5 3B (Ollama)\n• C++ GBNF Grammar Lock\n• Pydantic @model_validator\n• Auto-Audit Math Checks\n• needs_human_review flag"),
        (1460, 240, 1840, 840, "SQLITE ERP LEDGER", ACCENT_TEAL,
         "core/database.py\n\n• data/erp_procurement.db\n• SHA-256 byte fingerprint\n• Idempotent (No duplicates)\n• ✅ AUTO-APPROVED\n• ⚠️ QUARANTINED"),
    ]
    for x0, y0, x1, y1, title, col, body in a_boxes:
        da.rounded_rectangle([x0, y0, x1, y1], radius=18, fill=PANEL_DARK, outline=col, width=3)
        da.text((x0 + 25, y0 + 30), title, fill=col, font=load_font(26, bold=True))
        da.text((x0 + 25, y0 + 95), body, fill=TEXT_WHITE, font=load_font(24))

    da.text((80, 920), "Pure CPU Telemetry on ThinkPad (Ryzen 7 PRO 7840U): 18.5 tokens/sec | ~16s full end-to-end audit", fill=ACCENT_TEAL, font=load_font(28, bold=True))
    aflow.save(str(EP2_SNIMCI / "08-ep02-architecture-flow.png"))

    # 9. Final Binge Handoff Slide: Click Here for Episode 3
    handoff = Image.new("RGB", (1920, 1080), BG_DARK)
    dh = ImageDraw.Draw(handoff)
    dh.text((80, 45), "ZERO-CLOUD ERP ENGINE ON A LAPTOP  •  SERIES HANDOFF", fill=ACCENT_TEAL, font=load_font(28, bold=True))
    dh.text((80, 90), "Digital PDFs Are Solved. What About Paper Receipts?", fill=TEXT_WHITE, font=load_font(52, bold=True))

    dh.rounded_rectangle([80, 200, 920, 830], radius=20, fill=PANEL_DARK, outline=ACCENT_RED, width=4)
    draw_badge(dh, (115, 235), "❌ 11B VISION LLM ON LAPTOP CPU", ACCENT_RED, BG_DARK)
    dh.text((115, 320), "The Trap of Local Vision Models:\n\n• Feeding receipt photos to llama3.2-vision:11b\n• Over 1,000 image patch tokens on CPU\n• 84.2 seconds wait time per receipt!\n• Tilted rows (-2.1°) cause line items to cross\n• Totally unusable for real back-office automation", fill=(254, 202, 202), font=load_font(26))

    dh.rounded_rectangle([980, 200, 1840, 830], radius=20, fill=PANEL_DARK, outline=ACCENT_TEAL, width=4)
    draw_badge(dh, (1015, 235), "✅ COMING UP IN PART 3: SUB-SECOND CPU OCR", ACCENT_TEAL, BG_DARK)
    dh.text((1015, 320), "Our Two-Stage Lightweight CPU Pipeline:\n\n1. RapidOCR (ONNX C++): 0.44 seconds on CPU!\n2. 12-Line Geometric Y-Row Sorter (< 0.01s)\n3. Reuses Episode 1 Qwen 2.5 3B Core Engine\n\n• Total execution time: < 12 seconds on pure CPU\n• 10x faster than Vision LLMs with zero GPU required!", fill=TEXT_WHITE, font=load_font(26))

    # Big CTA Button at bottom
    dh.rounded_rectangle([80, 870, 1840, 980], radius=16, fill=ACCENT_TEAL)
    dh.text((120, 900), "👉 CLICK RIGHT HERE FOR PART 3: FAST RECEIPT OCR ON PURE CPU", fill=BG_DARK, font=load_font(34, bold=True))
    handoff.save(str(EP2_SNIMCI / "09-handoff-to-ep03.png"))


def generate_ep03_visuals() -> None:
    EP3_SNIMCI.mkdir(parents=True, exist_ok=True)
    receipt_path = ROOT_CODE / "data" / "samples_ep3_images" / "tilted_fastenal_receipt.png"

    # Generate annotated bounding-box visual showing RapidOCR boxes + Y-row centers!
    engine = RapidOCR()
    img_bgr = cv2.imread(str(receipt_path))
    ocr_res, _ = engine(img_bgr)

    annotated = img_bgr.copy()
    if ocr_res:
        for box, text, _score in ocr_res:
            pts = [(int(pt[0]), int(pt[1])) for pt in box]
            for i in range(4):
                cv2.line(annotated, pts[i], pts[(i + 1) % 4], (0, 200, 110), 2)
            y_center = int(sum(pt[1] for pt in box) / 4.0)
            x_left = int(min(pt[0] for pt in box))
            cv2.circle(annotated, (x_left, y_center), 5, (0, 0, 255), -1)

    annotated_path = EP3_SNIMCI / "02-rapidocr-bounding-boxes-overlay.png"
    cv2.imwrite(str(annotated_path), annotated)

    # Create 1920x1080 Episode 3 Slide / Thumbnail
    canvas = Image.new("RGB", (1920, 1080), BG_DARK)
    draw = ImageDraw.Draw(canvas)
    draw.text((80, 45), "ZERO-CLOUD ERP ENGINE ON A LAPTOP  •  PART 3", fill=ACCENT_TEAL, font=load_font(28, bold=True))
    draw.text((80, 90), "10X FASTER ON CPU: 0.4s RECEIPT OCR + Y-SORTER", fill=TEXT_WHITE, font=load_font(54, bold=True))

    # Left: Annotated Receipt Image
    draw.rounded_rectangle([80, 200, 980, 990], radius=20, fill=PANEL_DARK, outline=ACCENT_TEAL, width=4)
    draw_badge(draw, (115, 235), "STAGE 1: RAPIDOCR (435 ms ON CPU)", ACCENT_TEAL, BG_DARK)
    ann_pil = Image.open(annotated_path).convert("RGB")
    ann_pil.thumbnail((830, 620))
    canvas.paste(ann_pil, (115, 320))
    draw.text((115, 920), "Green: RapidOCR ONNX Boxes  |  Red Dots: Y-Centers (±24px Row Grouping)", fill=ACCENT_TEAL, font=load_font(23, bold=True))

    # Right: Benchmark Comparison + Aligned Output
    draw.rounded_rectangle([1030, 200, 1840, 990], radius=20, fill=PANEL_DARK, outline=ACCENT_AMBER, width=4)
    draw_badge(draw, (1065, 235), "CPU BENCHMARK: VLM vs 2-STAGE PIPELINE", ACCENT_AMBER, BG_DARK)
    bench_txt = (
        "❌ 11B Vision LLM on Laptop CPU:\n"
        "   • 1,000+ image patch tokens\n"
        "   • 84.2 seconds wait time\n\n"
        "✅ Our Two-Stage CPU Pipeline:\n"
        "   • Stage 1 (RapidOCR ONNX): 0.44 sec\n"
        "   • Stage 2 (12-Line Y-Row Sorter): < 0.01 sec\n"
        "   • Stage 3 (Qwen 2.5 3B + Pydantic): 11.0 sec\n"
        "   --------------------------------------------\n"
        "   • Aligned Row Output:\n"
        "     Qty: 4 | StainlessHexBoltsM8 | $12.50 | $50.00\n"
        "     Qty: 2 | Loctite243          | $18.00 | $36.00\n"
        "     Qty: 1 | Fluke117Multimeter  | $210.0 | $210.0"
    )
    draw.text((1065, 330), bench_txt, fill=TEXT_WHITE, font=load_font(26, mono=True))

    canvas.save(str(EP3_SNIMCI / "01-thumbnail-ep03.png"))


def generate_ep04_visuals() -> None:
    EP4_SNIMCI.mkdir(parents=True, exist_ok=True)
    canvas = Image.new("RGB", (1920, 1080), BG_DARK)
    draw = ImageDraw.Draw(canvas)

    draw.text((80, 45), "ZERO-CLOUD ERP ENGINE ON A LAPTOP  •  PART 4 (FINALE)", fill=ACCENT_TEAL, font=load_font(28, bold=True))
    draw.text((80, 90), "ZERO-CLICK AI ROBOT: WATCH-FOLDER TO SQLITE", fill=TEXT_WHITE, font=load_font(54, bold=True))

    # 3 Columns: Incoming -> Router + Core -> Processed & SQLite
    # Col 1
    draw.rounded_rectangle([80, 220, 600, 960], radius=20, fill=PANEL_DARK, outline=TEXT_MUTED, width=3)
    draw_badge(draw, (115, 255), "1. INCOMING_WATCH/", TEXT_MUTED, BG_DARK)
    draw.text((115, 350), "Drop Any File Format:\n\n📄 smudged_wire_note.txt\n   (Ep 1 Text Adapter)\n\n📑 mouser_invoice.pdf\n   (Ep 2 PDF X-Ray Adapter)\n\n📷 tilted_receipt.png\n   (Ep 3 RapidOCR Adapter)", fill=TEXT_WHITE, font=load_font(27))

    # Col 2
    draw.rounded_rectangle([660, 220, 1240, 960], radius=20, fill=PANEL_DARK, outline=ACCENT_TEAL, width=4)
    draw_badge(draw, (695, 255), "2. PYTHON WATCHDOG + CORE", ACCENT_TEAL, BG_DARK)
    draw.text((695, 350), "watcher_service.py (90 LoC):\n\n• Auto-detects file extension\n• Routes to Ep 1 / Ep 2 / Ep 3\n• Enforces Ollama GBNF Schema\n• Runs Pydantic Math Validator\n• Computes SHA-256 file hash\n  (Zero duplicate DB rows!)", fill=TEXT_WHITE, font=load_font(27))

    # Col 3
    draw.rounded_rectangle([1300, 220, 1840, 960], radius=20, fill=PANEL_DARK, outline=ACCENT_AMBER, width=4)
    draw_badge(draw, (1335, 255), "3. AUTO-SORT & SQLITE", ACCENT_AMBER, BG_DARK)
    draw.text((1335, 350), "processed_watch/\n\n✅ approved/\n   ├── mouser_invoice.pdf\n   └── tilted_receipt.png\n\n⚠️ quarantine_review/\n   └── smudged_wire_note.txt\n\n🗄️ erp_procurement.db\n   Validated SQLite Tables", fill=TEXT_WHITE, font=load_font(27, mono=True))

    canvas.save(str(EP4_SNIMCI / "01-thumbnail-ep04.png"))


if __name__ == "__main__":
    generate_ep01_visuals()
    generate_ep02_visuals()
    generate_ep03_visuals()
    generate_ep04_visuals()
    print("All studio visuals successfully generated across all 4 episodes!")
