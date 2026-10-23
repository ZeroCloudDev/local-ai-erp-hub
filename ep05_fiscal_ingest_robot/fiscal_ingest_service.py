"""Local fiscal ingestion with explicit price parsing and transactional deduplication."""

from contextlib import closing
import hashlib
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import time
import threading
import unicodedata
from typing import List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.schemas import FiscalItem

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "erp_procurement.db"
INCOMING_DIR = BASE_DIR / "data" / "incoming_fiskal"
APPROVED_DIR = BASE_DIR / "data" / "processed_fiskal" / "approved"
QUARANTINE_DIR = BASE_DIR / "data" / "processed_fiskal" / "quarantine"
_INIT_LOCK = threading.RLock()

CURRENCY = r"(?:KM|BAM|EUR|USD|GBP|\$|€|£)"
PRICE = re.compile(rf"^\s*(?P<prefix>{CURRENCY})?\s*(?P<num>[+-]?\d+(?:[.,]\d{{1,2}})?)\s*(?P<suffix>{CURRENCY})?\s*$", re.I)
TEXT_PRICE = re.compile(rf"^(?P<name>.+?)\s+(?:[-:]\s+)?(?P<price>(?:{CURRENCY}\s*)?[+-]?\d+(?:[.,]\d{{1,2}})?\s*(?:{CURRENCY})?)\s*$", re.I)


def calculate_file_hash(file_path: Path) -> str:
    hasher = hashlib.sha256()
    with file_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def init_fiscal_dirs():
    for directory in (DB_PATH.parent, INCOMING_DIR, APPROVED_DIR, QUARANTINE_DIR):
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            if not directory.is_dir():
                raise


def init_fiscal_db():
    with _INIT_LOCK:
        _init_fiscal_db()


def _init_fiscal_db():
    init_fiscal_dirs()
    with closing(sqlite3.connect(str(DB_PATH), timeout=30)) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS fiscal_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT, sifra TEXT, barkod TEXT,
                naziv TEXT NOT NULL, jedinica_mjere TEXT DEFAULT 'kom',
                porezna_stopa TEXT DEFAULT '17%', cijena_sa_pdv REAL NOT NULL,
                cijena_bez_pdv REAL, source_doc TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS fiscal_quarantine (
                id INTEGER PRIMARY KEY AUTOINCREMENT, sifra TEXT, barkod TEXT,
                naziv TEXT NOT NULL, jedinica_mjere TEXT DEFAULT 'kom',
                porezna_stopa TEXT DEFAULT '17%', raw_price_text TEXT,
                razlog_karantina TEXT NOT NULL, source_doc TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS processed_fiscal_files (
                file_hash TEXT PRIMARY KEY, file_name TEXT NOT NULL,
                status TEXT NOT NULL, items_count INTEGER DEFAULT 0,
                approved_count INTEGER, quarantine_count INTEGER,
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(processed_fiscal_files)")}
        for column in ("approved_count", "quarantine_count"):
            if column not in columns:
                try:
                    conn.execute(f"ALTER TABLE processed_fiscal_files ADD COLUMN {column} INTEGER")
                except sqlite3.OperationalError as exc:
                    if "duplicate column" not in str(exc).lower():
                        raise


def is_file_already_processed(file_hash: str) -> bool:
    init_fiscal_db()
    with closing(sqlite3.connect(str(DB_PATH), timeout=30)) as conn:
        return conn.execute("SELECT 1 FROM processed_fiscal_files WHERE file_hash = ?", (file_hash,)).fetchone() is not None


def discover_schema() -> List[Tuple[str, str, bool]]:
    init_fiscal_db()
    with closing(sqlite3.connect(str(DB_PATH), timeout=30)) as conn:
        return [(row[1], row[2], bool(row[3])) for row in conn.execute("PRAGMA table_info(fiscal_items)")]


def _review(name: str, reason: str, status="QUARANTINE_UNCLEAR_PRICE", **values) -> FiscalItem:
    return FiscalItem(naziv=name.strip() or "Unidentified item", status_validacije=status, razlog_karantina=reason, **values)


def empty_extraction_item(source_name: str) -> FiscalItem:
    return _review(f"Empty extraction: {source_name}", "Zero fiscal items extracted; inspect original document.", "QUARANTINE_EMPTY_EXTRACTION")


def _priced_item(name: str, raw: str, *, net=False, currency=None, sifra=None) -> FiscalItem:
    if not name.strip() or name.strip() in {"-", ":"}:
        return _review(name, "Missing item description; inspect source document.", "QUARANTINE_MISSING_NAME", sifra=sifra)
    match = PRICE.fullmatch(raw)
    if not match:
        return _review(name, f"Missing or malformed price: {raw!r}", sifra=sifra)
    amount = float(match['num'].replace(",", "."))
    if not math.isfinite(amount) or amount <= 0:
        return _review(name, f"Non-positive or invalid price: {raw!r}", "QUARANTINE_INVALID_PRICE", sifra=sifra)
    currencies = {x.upper() for x in (match['prefix'], match['suffix'], currency) if x}
    normalized = {"BAM" if c == "KM" else "USD" if c == "$" else "EUR" if c == "€" else "GBP" if c == "£" else c for c in currencies}
    values = {"cijena_bez_pdv" if net else "cijena_sa_pdv": amount, "sifra": sifra}
    if not normalized:
        return _review(name, "Missing currency; confirm BAM/KM before POS import.", "QUARANTINE_CURRENCY", sifra=sifra)
    if normalized != {"BAM"}:
        reason = f"Currency {', '.join(sorted(normalized))} requires operator confirmation/conversion to BAM; no conversion was performed."
        return _review(name, reason, "QUARANTINE_CURRENCY", **values)
    return FiscalItem(naziv=name.strip() or "Unidentified item", **values)


def parse_viber_text(text_content: str, filename: str) -> List[FiscalItem]:
    items = []
    for line in text_content.lstrip("\ufeff").splitlines():
        line = line.strip()
        if not line or re.fullmatch(r"(?:evo ubaci(?: mi)?|pozdrav|hvala|saljem)[:.! ]*", line, re.I):
            continue
        match = TEXT_PRICE.fullmatch(line)
        if match:
            name, raw = match['name'].rstrip(" :"), match['price']
            # A delimiter immediately followed by a minus denotes a negative price.
            if name.endswith("-") and raw.lstrip().startswith("-"):
                name = name[:-1].rstrip()
            if name.endswith("-"):
                items.append(_review(line, "Malformed signed price; inspect source text.", "QUARANTINE_INVALID_PRICE"))
            elif re.search(r"\d$", name) and not re.search(r"[-:]\s+" + re.escape(raw) + r"\s*$", line):
                items.append(_review(line, "Ambiguous numeric groups; confirm the complete price."))
            else:
                items.append(_priced_item(name, raw))
        else:
            items.append(_review(line, "Missing or malformed price; inspect source text."))
    return items or [empty_extraction_item(filename)]


def _normalize(text):
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c)).split())


def _table_columns(row):
    columns = {}
    for index, cell in enumerate(row):
        text = _normalize(cell or "")
        if any(word in text for word in ("description", "naziv")) or text in {"item", "name", "artikal"}:
            columns['name'] = index
        if any(word in text for word in ("sku", "part no", "sifra")):
            columns['sku'] = index
        if any(word in text for word in ("total", "ukupno", "subtotal")) or text == "total":
            continue
        if any(word in text for word in ("unit price", "cijena", "price", "mpc")):
            columns['price'] = index
            columns['net'] = not any(word in text for word in ("sa pdv", "with tax", "gross", "retail", "mpc"))
            found = re.search(CURRENCY, text, re.I)
            columns['currency'] = found.group().upper() if found else None
    return columns if 'name' in columns and 'price' in columns else None


def extract_fiscal_from_table_row(row: List[str], columns=None) -> Optional[FiscalItem]:
    cleaned = [(cell or "").strip() for cell in row]
    if not any(cleaned):
        return None
    if columns is None:
        return _review(" | ".join(cleaned), "No unambiguous description/unit-price column mapping; inspect table.")
    name_index, price_index = columns['name'], columns['price']
    name = cleaned[name_index] if name_index < len(cleaned) else " | ".join(cleaned)
    if _normalize(name) in {"total", "subtotal", "grand total", "ukupno"}:
        return None
    raw = cleaned[price_index] if price_index < len(cleaned) else ""
    sku_index = columns.get('sku')
    sku = cleaned[sku_index] if sku_index is not None and sku_index < len(cleaned) else None
    return _priced_item(name, raw, net=columns.get('net', True), currency=columns.get('currency'), sifra=sku)


def parse_pdf_catalog(pdf_path: Path) -> List[FiscalItem]:
    import pdfplumber
    items = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                columns = None
                for row in table:
                    if not row or not any(row):
                        continue
                    header = _table_columns(row)
                    if header:
                        columns = header
                        continue
                    item = extract_fiscal_from_table_row(row, columns)
                    if item:
                        items.append(item)
    return items or [empty_extraction_item(pdf_path.name)]


def parse_image_receipt(img_path: Path) -> List[FiscalItem]:
    from ep03_fast_cpu_ocr.ocr_pipeline import get_ocr_engine, preprocess_receipt_image, sort_ocr_boxes_into_rows
    boxes, _ = get_ocr_engine()(preprocess_receipt_image(img_path))
    aligned = sort_ocr_boxes_into_rows(boxes, y_tolerance_px=24.0)
    lines = [line.strip() for line in aligned.splitlines() if line.strip()]
    currency_match = re.search(rf"Currency\s*:\s*({CURRENCY})", aligned, re.I)
    currency = currency_match.group(1) if currency_match else None
    items = []
    for row in lines:
        compact = re.sub(r"\s+", "", row).lower()
        if compact.startswith(("vendor:", "jobnumber:", "currency:", "overallreceipttotal:", "receipttotal:", "total:", "subtotal:")):
            continue
        parts = [part.strip() for part in row.split("|")]
        name_parts = [part for part in parts if part and not re.match(r"^(?:qty|unit|total|price|cijena)\s*:", part, re.I) and not PRICE.fullmatch(part)]
        if not name_parts:
            items.append(_review(row, "Missing OCR item description; inspect source image.", "QUARANTINE_MISSING_NAME"))
            continue
        name = " | ".join(name_parts)
        unit = next((part.split(":", 1)[1].strip() for part in parts if re.match(r"^(?:unit|price|cijena)\s*:", part, re.I)), None)
        if unit is None:
            # A separated single price cell is a retail price; never substitute a line total.
            candidates = [part for part in parts if PRICE.fullmatch(part)]
            unit = candidates[0] if len(candidates) == 1 else ""
        items.append(_priced_item(name, unit, currency=currency))
    return items or [empty_extraction_item(img_path.name)]


def commit_items_to_db(items: List[FiscalItem], source_name: str, file_hash: Optional[str] = None) -> Tuple[int, int]:
    """Commit ledger rows and content receipt atomically; duplicate content returns original counts."""
    init_fiscal_db()
    items = items or [empty_extraction_item(source_name)]
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    try:
        conn.execute("BEGIN IMMEDIATE")
        if file_hash:
            row = conn.execute("SELECT status, items_count, approved_count, quarantine_count FROM processed_fiscal_files WHERE file_hash = ?", (file_hash,)).fetchone()
            if row:
                conn.rollback()
                if row[2] is not None and row[3] is not None:
                    return row[2], row[3]
                return (row[1], 0) if row[0] == "APPROVED" else (0, row[1] or 1)
        approved = quarantined = 0
        for item in items:
            if item.status_validacije == "APPROVED" and item.cijena_sa_pdv is not None and math.isfinite(item.cijena_sa_pdv) and item.cijena_sa_pdv > 0:
                conn.execute("INSERT INTO fiscal_items (sifra,barkod,naziv,jedinica_mjere,porezna_stopa,cijena_sa_pdv,cijena_bez_pdv,source_doc) VALUES (?,?,?,?,?,?,?,?)", (item.sifra,item.barkod,item.naziv,item.jedinica_mjere,item.porezna_stopa,item.cijena_sa_pdv,item.cijena_bez_pdv,source_name))
                approved += 1
            else:
                raw_price = f"gross={item.cijena_sa_pdv!r}; net={item.cijena_bez_pdv!r}"
                conn.execute("INSERT INTO fiscal_quarantine (sifra,barkod,naziv,jedinica_mjere,porezna_stopa,raw_price_text,razlog_karantina,source_doc) VALUES (?,?,?,?,?,?,?,?)", (item.sifra,item.barkod,item.naziv,item.jedinica_mjere,item.porezna_stopa,raw_price,item.razlog_karantina or "Needs human review",source_name))
                quarantined += 1
        if file_hash:
            conn.execute("INSERT INTO processed_fiscal_files (file_hash,file_name,status,items_count,approved_count,quarantine_count) VALUES (?,?,?,?,?,?)", (file_hash,source_name,"APPROVED" if approved and not quarantined else "QUARANTINE",approved+quarantined,approved,quarantined))
        conn.commit()
        return approved, quarantined
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _archive_file(file_path: Path, directory: Path, file_hash: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / file_path.name
    if file_path.resolve() == candidate.resolve():
        return candidate
    attempt = 0
    while True:
        try:
            descriptor = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(descriptor)
            break
        except FileExistsError:
            attempt += 1
            candidate = directory / f"{file_path.stem}_{file_hash[:12]}_{attempt}{file_path.suffix}"
    try:
        shutil.move(str(file_path), str(candidate))
    except Exception:
        if candidate.exists() and candidate.stat().st_size == 0:
            candidate.unlink()
        raise
    return candidate


def process_incoming_file(file_path: Path):
    print(f"\n[DETECTED] Processing: {file_path.name}")
    start = time.time()
    init_fiscal_db()
    extension = file_path.suffix.lower()
    if extension not in {".txt", ".pdf", ".png", ".jpg", ".jpeg"}:
        print(f"Skipping unsupported file: {file_path.name}")
        return
    file_hash = calculate_file_hash(file_path)
    if is_file_already_processed(file_hash):
        print(f"  -> [IDEMPOTENCY] File {file_path.name} already processed in DB. Moving without duplicate INSERT.")
        with closing(sqlite3.connect(str(DB_PATH), timeout=30)) as conn:
            status = conn.execute("SELECT status FROM processed_fiscal_files WHERE file_hash = ?", (file_hash,)).fetchone()[0]
        directory = APPROVED_DIR if status == "APPROVED" else QUARANTINE_DIR
    else:
        if extension == ".txt":
            items = parse_viber_text(file_path.read_text(encoding="utf-8-sig", errors="strict"), file_path.name)
        elif extension == ".pdf":
            items = parse_pdf_catalog(file_path)
        else:
            items = parse_image_receipt(file_path)
        if calculate_file_hash(file_path) != file_hash:
            raise RuntimeError("Source changed during parsing; retry after writing finishes.")
        approved, quarantined = commit_items_to_db(items, file_path.name, file_hash)
        print(f"  -> Extracted {len(items)} items in {(time.time()-start)*1000:.1f}ms")
        print(f"  -> Approved: {approved} | Quarantined: {quarantined}")
        directory = APPROVED_DIR if approved > 0 and quarantined == 0 else QUARANTINE_DIR
    destination = _archive_file(file_path, directory, file_hash)
    print(f"  -> Moved to: {destination}")


def run_watcher_loop():
    init_fiscal_db()
    cols = discover_schema()
    print("=" * 65)
    print("FISCAL INGEST ROBOT (ZERO-CLOUD POS AUTOMATION)")
    print("=" * 65)
    print(f"Monitoring folder: {INCOMING_DIR}")
    print(f"Discovered SQLite Schema: {[column[0] for column in cols]}")
    print("Waiting for customer notes (Viber, PDF catalogs, receipt photos)...")
    print("(Press Ctrl+C to stop)\n")
    while True:
        try:
            for file_path in INCOMING_DIR.iterdir():
                if file_path.is_file() and not file_path.name.startswith("."):
                    try:
                        process_incoming_file(file_path)
                    except Exception as exc:
                        print(f"Error processing {file_path.name}: {exc}")
            time.sleep(1)
        except KeyboardInterrupt:
            print("\nFiscal Ingest Robot stopped by operator.")
            break
        except Exception as exc:
            print(f"Error in watcher loop: {exc}")
            time.sleep(2)


if __name__ == "__main__":
    run_watcher_loop()
