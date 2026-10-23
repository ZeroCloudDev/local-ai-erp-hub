"""
Local SQLite persistence layer shared across all 4 episodes.
Stores purchase orders, individual line items, source hashes (for idempotency), and audit flags.
"""

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from core.schemas import PurchaseOrderExtraction
from core.ledger_tools import ClosingConnection
DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "erp_procurement.db"


def get_connection(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), factory=ClosingConnection)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS purchase_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_hash TEXT UNIQUE NOT NULL,
                source_type TEXT NOT NULL,
                source_name TEXT NOT NULL,
                vendor_name TEXT,
                job_or_po_number TEXT,
                currency TEXT,
                stated_total REAL,
                needs_human_review INTEGER NOT NULL,
                review_reasons_json TEXT,
                wall_time_ms REAL,
                created_at_utc TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS line_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                po_id INTEGER NOT NULL,
                item_name TEXT NOT NULL,
                sku_or_part_no TEXT,
                quantity REAL,
                unit_price REAL,
                line_total REAL,
                FOREIGN KEY (po_id) REFERENCES purchase_orders (id) ON DELETE CASCADE
            )
            """
        )
        conn.commit()


def compute_content_hash(content: bytes | str) -> str:
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()[:16]


def save_extraction(
    po: PurchaseOrderExtraction,
    source_type: str,
    source_name: str,
    raw_content: bytes | str,
    wall_time_ms: float = 0.0,
    db_path: Path = DEFAULT_DB_PATH,
) -> int:
    """
    Idempotent upsert by SHA-256 content hash: re-running the same file updates the existing record
    rather than duplicating rows in the ERP database.
    """
    init_db(db_path)
    source_hash = compute_content_hash(raw_content)
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    with get_connection(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE"); existing = conn.execute(
            "SELECT id FROM purchase_orders WHERE source_hash = ?", (source_hash,)
        ).fetchone()
        if existing:
            conn.execute("DELETE FROM line_items WHERE po_id = ?", (existing["id"],))
            conn.execute("DELETE FROM purchase_orders WHERE id = ?", (existing["id"],))

        cursor = conn.execute(
            """
            INSERT INTO purchase_orders (
                source_hash, source_type, source_name, vendor_name, job_or_po_number,
                currency, stated_total, needs_human_review, review_reasons_json,
                wall_time_ms, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_hash,
                source_type,
                source_name,
                po.vendor_name,
                po.job_or_po_number,
                po.currency,
                po.stated_total,
                1 if po.needs_human_review else 0,
                json.dumps(po.review_reasons),
                wall_time_ms,
                now_utc,
            ),
        )
        po_id = int(cursor.lastrowid)

        for item in po.items:
            conn.execute(
                """
                INSERT INTO line_items (
                    po_id, item_name, sku_or_part_no, quantity, unit_price, line_total
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    po_id,
                    item.item_name,
                    item.sku_or_part_no,
                    item.quantity,
                    item.unit_price,
                    item.line_total,
                ),
            )
        conn.commit()
        return po_id


def fetch_all_line_items_flat(db_path: Path = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                po.id AS po_id,
                po.source_type,
                po.source_name,
                po.vendor_name,
                po.job_or_po_number, po.currency,
                li.item_name,
                li.sku_or_part_no,
                li.quantity,
                li.unit_price,
                li.line_total,
                po.stated_total,
                CASE WHEN po.needs_human_review = 1 THEN '⚠️ QUARANTINED' ELSE '✅ APPROVED' END AS audit_status,
                CASE WHEN po.needs_human_review = 1 THEN '⚠️ REVIEW' ELSE '✅ OK' END AS status,
                po.review_reasons_json,
                po.wall_time_ms
            FROM purchase_orders po
            LEFT JOIN line_items li ON po.id = li.po_id
            ORDER BY po.id DESC, li.id ASC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def export_to_csv(db_path: Path = DEFAULT_DB_PATH) -> str:
    """Export currency and quarantined documents, including those without items."""
    import csv
    import io
    rows = fetch_all_line_items_flat(db_path)
    if not rows:
        return ""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()
