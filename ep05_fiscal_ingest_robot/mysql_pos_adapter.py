"""
EP05 — the MySQL/MariaDB POS adapter (this is the "ADAPT HERE" layer).

Everything above this file (extraction, completeness, validation) is generic.
This file knows the concrete POS tables of this example:

    artikli    one row per article; art_broj = SKU, naziv, cij (DECIMAL 18,4),
               tarifa -> tarifa.id, jedmjer = jmjera.id stored as text
    artcjenik  price-list rows; we touch exactly ONE selected row per article:
               idart + cjnaziv='OSNOVNI' + loc='0' + pjs=1 + deleted=0
    tarifa / jmjera  are only read (through the approved maps in the config)

TRANSACTION SHAPE (one connection, one transaction per document):

    SELECT ... FOR UPDATE on ep05_writer_lock   <- all writers queue here
    file_hash already processed?  -> stop, nothing is written (replay guard)
    for every candidate:
        read current article + selected price row (FOR UPDATE)
        decide()  -> INSERT / UPDATE / NO_CHANGE / QUARANTINE
        write POS rows, audit row, quarantine row
    source file unchanged since hashing?  (else roll back and retry later)
    COMMIT    -- or ROLLBACK of everything on any technical error

Slow work (OCR, model) is done BEFORE this, so the lock is held only for
milliseconds of SQL. Archiving the file happens AFTER the commit.

WHAT A DIFFERENT POS MAY NEED (ADAPT HERE)
    Other table/column names, a different business key, other price lists,
    sync flags such as `upd` that the POS app expects to be set on change,
    or no direct SQL at all (some systems only accept their API or import).
"""

from __future__ import annotations

import json
import os
import socket
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Callable

import pymysql
from pymysql.cursors import DictCursor

from ep05_fiscal_ingest_robot.adapter_config import AdapterConfig
from ep05_fiscal_ingest_robot.catalog_candidate import (EXISTING_ARTICLE, OPERATOR,
                                                        CatalogCandidate, FieldSource)
from ep05_fiscal_ingest_robot.completeness_check import unrecognized_document_candidate
from ep05_fiscal_ingest_robot.pos_validation import (INSERT, NO_CHANGE, PRICE_REASONS, QUARANTINE,
                                                     UPDATE, Decision, decide,
                                                     mark_in_document_conflicts, static_reasons)


class InjectedFailure(RuntimeError):
    """Explicit rollback probe with evidence of the actual mutation count."""

    def __init__(self, message: str, *, actual_ops: int, planned_ops: int, reached: bool):
        super().__init__(message)
        self.actual_ops = actual_ops
        self.planned_ops = planned_ops
        self.reached = reached


class SourceChanged(RuntimeError):
    """The source file changed between hashing and commit: roll back, retry later."""


class ResolutionRefused(RuntimeError):
    """The operator's value does not make the item valid; nothing was written."""


@dataclass
class FailureInjection:
    """Stop with an error after N business mutations, inside the transaction.

    Enabled only when the caller passes --demo-failure-injection AND sets
    EP05_FAIL_AFTER_OPS. In normal operation this object is never created.
    """
    fail_after_ops: int

    def __post_init__(self):
        if isinstance(self.fail_after_ops, bool) or not isinstance(self.fail_after_ops, int) or self.fail_after_ops < 1:
            raise ValueError("failure injection requires a positive integer mutation count")

    @classmethod
    def from_env(cls, enabled: bool) -> "FailureInjection | None":
        if not enabled:
            return None
        value = os.environ.get("EP05_FAIL_AFTER_OPS")
        if not value:
            raise RuntimeError("--demo-failure-injection needs EP05_FAIL_AFTER_OPS (e.g. 3)")
        return cls(int(value))


@dataclass
class ItemResult:
    candidate: CatalogCandidate
    decision: Decision
    stavka_id: int | None = None


@dataclass
class DocumentResult:
    doc_id: int | None
    duplicate: bool
    items: list[ItemResult] = field(default_factory=list)
    archived_at: datetime | None = None

    def count(self, outcome: str) -> int:
        return sum(1 for i in self.items if i.decision.outcome == outcome)


def main_view_sql(cfg: AdapterConfig) -> tuple[str, list]:
    """The SELECT shown in HeidiSQL. LEFT JOINs: a broken tax/unit reference
    must not hide an article; verify_demo reports such rows separately."""
    where, params = cfg.price_list_where("c")
    db = cfg.db_name
    sql = f"""
SELECT a.art_broj, a.naziv, a.cij AS retail_price_usd,
       t.porez AS tax_class, t.iznos AS demo_sales_tax_rate,
       j.nazivskr AS sales_unit, ROUND(c.cijena, 2) AS osnovni_price
FROM {db}.artikli a
LEFT JOIN {db}.tarifa t ON t.id = a.tarifa
LEFT JOIN {db}.jmjera j ON a.jedmjer REGEXP '^[1-9][0-9]*$' AND j.id = CAST(a.jedmjer AS UNSIGNED)
LEFT JOIN {db}.artcjenik c ON c.idart = a.id AND {where}
WHERE a.art_broj BETWEEN %s AND %s AND a.deleted = 0
ORDER BY a.art_broj"""
    return sql, params + [cfg.sku_min, cfg.sku_max]


class PosAdapter:
    def __init__(self, cfg: AdapterConfig, holder: str | None = None):
        self.cfg = cfg
        self.holder = holder or f"{socket.gethostname()}:{os.getpid()}"

    # ------------------------------------------------------------------ basics
    def connect(self) -> pymysql.connections.Connection:
        return pymysql.connect(host=self.cfg.db_host, port=self.cfg.db_port,
                               user=self.cfg.db_user, password=self.cfg.db_password(),
                               database=self.cfg.db_name, charset="utf8",
                               autocommit=False, cursorclass=DictCursor)

    def _lock(self, cur) -> None:
        # Blocks until every other writer has committed or rolled back.
        cur.execute("SELECT id FROM ep05_writer_lock WHERE id = 1 FOR UPDATE")
        if cur.fetchone() is None:
            raise RuntimeError("ep05_writer_lock row is missing - run setup_demo_db.py")
        cur.execute("UPDATE ep05_writer_lock SET holder = %s, acquired_at = NOW() WHERE id = 1",
                    (self.holder,))

    def _read_state(self, cur, sku: int) -> tuple[list[dict], list[dict]]:
        cur.execute("SELECT id, art_broj, naziv, cij, tarifa, jedmjer FROM artikli "
                    "WHERE art_broj = %s AND deleted = 0 FOR UPDATE", (sku,))
        existing = list(cur.fetchall())
        rows: list[dict] = []
        if len(existing) == 1:
            where, params = self.cfg.price_list_where("c")
            cur.execute(f"SELECT c.id, c.cijena FROM artcjenik c WHERE c.idart = %s AND {where} "
                        f"FOR UPDATE", [existing[0]["id"]] + params)
            rows = list(cur.fetchall())
        return existing, rows

    def find_document(self, file_hash: str) -> dict | None:
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM ep05_dokumenti WHERE file_hash = %s", (file_hash,))
                return cur.fetchone()
        finally:
            conn.close()

    @staticmethod
    def _state_snapshot(existing: list[dict], price_rows: list[dict]) -> str:
        """Stable, exact current-state token for an operator review precondition."""
        return json.dumps({
            "articles": sorted(existing, key=lambda row: str(row["id"])),
            "price_rows": sorted(price_rows, key=lambda row: str(row["id"])),
        }, sort_keys=True, default=str, separators=(",", ":"))

    def _valid_read_sku(self, c: CatalogCandidate) -> bool:
        return (isinstance(c.sku, int) and not isinstance(c.sku, bool)
                and self.cfg.sku_min <= c.sku <= self.cfg.sku_max)

    def _references_checked(self, cur, d: Decision) -> Decision:
        """The POS schema has no FKs: validate live lookup rows under read locks.

        A valid config key only identifies an ID; it does not prove the referenced
        row still exists. The shared locks prevent deletion before our commit.
        """
        if d.outcome == QUARANTINE:
            return d
        refs = [("tarifa", d.tarifa_id, ""), ("jmjera", d.jmjera_id, " AND deleted = 0")]
        if d.outcome == INSERT:
            refs.append(("artikli_grupe", self.cfg.pos_test_values["grupa"], " AND deleted = 0"))
        for table, row_id, active in refs:
            if isinstance(row_id, bool) or not isinstance(row_id, int) or row_id <= 0:
                return Decision(QUARANTINE, "POS_REFERENCE_INVALID", f"{table} needs a positive referenced ID")
            cur.execute(f"SELECT id FROM {table} WHERE id = %s{active} LOCK IN SHARE MODE", (row_id,))
            if cur.fetchone() is None:
                return Decision(QUARANTINE, "POS_REFERENCE_INVALID", f"{table}.id={row_id} is missing or inactive")
        return d

    # ------------------------------------------------------------------ writes
    def _write(self, cur, c: CatalogCandidate, d: Decision) -> None:
        """POS rows for one decided candidate. Called only for INSERT/UPDATE."""
        tv, pl = self.cfg.pos_test_values, self.cfg.price_list
        price = str(c.retail_price)  # exact decimal text; DECIMAL keeps it, DOUBLE stores nearest
        if d.outcome == INSERT:
            d.art_id = str(uuid.uuid4())                       # D7: UUID ids
            cur.execute(
                "INSERT INTO artikli (art_broj, naziv, cij, tarifa, jedmjer, id, sank, kasa, grupa,"
                " upd, idd, deleted) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0)",
                (c.sku, c.name, price, d.tarifa_id, str(d.jmjera_id), d.art_id,
                 tv["sank"], tv["kasa"], tv["grupa"], tv["upd"], tv["idd"]))
            d.price_row_id = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO artcjenik (id, cijena, loc, cjnaziv, br, upd, idart, deleted, sank, pjs)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,0,%s,%s)",
                (d.price_row_id, price, pl["loc"], pl["cjnaziv"], tv["artcjenik_br"], tv["upd"],
                 d.art_id, tv["sank"], pl["pjs"]))
        elif d.outcome == UPDATE:
            # Only the price changes. Tax class and unit stay as they are in the POS (D2/D3).
            cur.execute("UPDATE artikli SET cij = %s WHERE id = %s", (price, d.art_id))
            if d.price_row_id:
                cur.execute("UPDATE artcjenik SET cijena = %s WHERE id = %s", (price, d.price_row_id))
            else:   # the article had no selected price row: create exactly one
                d.price_row_id = str(uuid.uuid4())
                cur.execute(
                    "INSERT INTO artcjenik (id, cijena, loc, cjnaziv, br, upd, idart, deleted, sank, pjs)"
                    " VALUES (%s,%s,%s,%s,%s,%s,%s,0,%s,%s)",
                    (d.price_row_id, price, pl["loc"], pl["cjnaziv"], tv["artcjenik_br"], tv["upd"],
                     d.art_id, tv["sank"], pl["pjs"]))

    def _audit(self, cur, doc_id: int, c: CatalogCandidate, d: Decision,
               review_state: tuple[list[dict], list[dict]] | None = None) -> int:
        if d.outcome == QUARANTINE and review_state is not None:
            # Reserved audit-context key in the existing provenance JSON avoids a
            # schema migration. It is not an extracted product field. Snapshot
            # absent/present articles and the selected list before operator review.
            c.field_sources["_pos_state_at_review"] = FieldSource(
                EXISTING_ARTICLE, self._state_snapshot(*review_state))
        if d.outcome in (UPDATE, NO_CHANGE):
            for f in ("tax_class", "sales_unit"):
                c.field_sources.setdefault(f, FieldSource(EXISTING_ARTICLE, d.art_id or ""))
        new_price = c.retail_price if d.outcome in (INSERT, UPDATE, NO_CHANGE) else None
        cur.execute(
            "INSERT INTO ep05_stavke (doc_id, locator, source_segment, candidate_json, field_sources_json,"
            " outcome, reason, art_broj, art_id, old_price, new_price, value_source, created_at)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())",
            (doc_id, c.locator, c.source_segment, c.to_json(), c.field_sources_json(),
             d.outcome, d.reason, c.sku, d.art_id, d.old_price, new_price, c.price_origin()))
        stavka_id = cur.lastrowid
        if d.outcome == QUARANTINE:
            cur.execute("INSERT INTO ep05_karantin (stavka_id, art_broj, reason, detail, status)"
                        " VALUES (%s,%s,%s,%s,'OPEN')", (stavka_id, c.sku, d.reason, d.detail))
        return stavka_id

    # ------------------------------------------------------------------ document
    def apply_document(self, candidates: list[CatalogCandidate], *, file_hash: str, file_name: str,
                       source_path: str, source_kind: str, model_name: str | None,
                       still_unchanged: Callable[[], bool] = lambda: True,
                       failure: FailureInjection | None = None) -> DocumentResult:
        candidates = list(candidates) or [unrecognized_document_candidate()]
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                conn.begin()
                self._lock(cur)
                cur.execute("SELECT id, archived_at FROM ep05_dokumenti WHERE file_hash = %s", (file_hash,))
                prev = cur.fetchone()
                if prev:                                    # replay: nothing is written
                    conn.rollback()
                    return DocumentResult(prev["id"], True, archived_at=prev["archived_at"])
                cur.execute(
                    "INSERT INTO ep05_dokumenti (file_hash, file_name, source_path, source_kind,"
                    " profile_version, model_name, status, committed_at)"
                    " VALUES (%s,%s,%s,%s,%s,%s,'PROCESSING',NOW())",
                    (file_hash, file_name, source_path, source_kind, self.cfg.profile_version, model_name))
                doc_id = cur.lastrowid
                mark_in_document_conflicts(candidates)
                result = DocumentResult(doc_id, False)
                ops = 0
                for c in candidates:
                    static = static_reasons(c, self.cfg)
                    # Missing-price reviews still need a baseline of the current
                    # product. Otherwise a later approval could overwrite a price
                    # another document changed while the review was open.
                    existing, rows = self._read_state(cur, c.sku) if self._valid_read_sku(c) else ([], [])
                    d = self._references_checked(cur, decide(c, existing, rows, self.cfg, static))
                    if d.outcome in (INSERT, UPDATE):
                        self._write(cur, c, d)
                        ops += 1
                        if failure and ops >= failure.fail_after_ops:
                            raise InjectedFailure(
                                f"demo failure injected after {ops} actual business mutations",
                                actual_ops=ops, planned_ops=failure.fail_after_ops, reached=True)
                    stavka_id = self._audit(cur, doc_id, c, d, review_state=(existing, rows))
                    result.items.append(ItemResult(c, d, stavka_id))
                if failure:
                    # A failure probe must NEVER commit, even if the model read a line
                    # differently and the injection point was not reached.
                    raise InjectedFailure(
                        f"failure threshold NOT reached: {ops} actual mutations, planned {failure.fail_after_ops}; safety rollback only",
                        actual_ops=ops, planned_ops=failure.fail_after_ops, reached=False)
                q = result.count(QUARANTINE)
                cur.execute("UPDATE ep05_dokumenti SET status = %s, items_total = %s,"
                            " items_quarantined = %s, committed_at = NOW() WHERE id = %s",
                            ("COMMITTED_WITH_QUARANTINE" if q else "COMMITTED", len(candidates), q, doc_id))
                if not still_unchanged():
                    raise SourceChanged(f"{file_name} changed after it was hashed")
                conn.commit()
                return result
        except Exception:
            conn.rollback()                                  # all or nothing
            raise
        finally:
            conn.close()

    def mark_archived(self, doc_id: int, archived_path: str | None, ok: bool) -> None:
        """Separate small transaction AFTER the business commit. If moving the
        file failed, archived_at stays NULL and only archiving is retried."""
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                if ok:
                    cur.execute("UPDATE ep05_dokumenti SET archived_path = %s, archived_at = NOW(),"
                                " archive_attempts = archive_attempts + 1 WHERE id = %s",
                                (archived_path, doc_id))
                else:
                    cur.execute("UPDATE ep05_dokumenti SET archive_attempts = archive_attempts + 1"
                                " WHERE id = %s", (doc_id,))
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------ quarantine
    def list_quarantine(self, status: str = "OPEN") -> list[dict]:
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT k.id, k.art_broj, k.reason, k.status, k.detail, s.locator,"
                            " s.source_segment, d.file_name FROM ep05_karantin k"
                            " JOIN ep05_stavke s ON s.id = k.stavka_id"
                            " JOIN ep05_dokumenti d ON d.id = s.doc_id"
                            " WHERE (%s = 'ALL' OR k.status = %s) ORDER BY k.id", (status, status))
                return list(cur.fetchall())
        finally:
            conn.close()

    def resolve(self, karantin_id: int, *, operator: str, confirmation: str,
                price: Decimal | None = None, reject: bool = False) -> dict:
        """Operator decision. Idempotent: a second call for the same item has no effect.

        Re-checks the CURRENT state under the writer lock, so an approval that
        was valid a minute ago cannot overwrite something that changed since.
        """
        if not reject and price is None:
            raise ValueError("give --price or --reject")
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                conn.begin()
                self._lock(cur)
                cur.execute("SELECT * FROM ep05_karantin WHERE id = %s FOR UPDATE", (karantin_id,))
                k = cur.fetchone()
                if k is None:
                    raise ResolutionRefused(f"quarantine item {karantin_id} does not exist")
                if k["status"] != "OPEN":
                    conn.rollback()
                    return {"effect": "none", "status": k["status"],
                            "message": f"item {karantin_id} is already {k['status']}; nothing changed"}
                if reject:
                    cur.execute("UPDATE ep05_karantin SET status='REJECTED', operator_name=%s,"
                                " operator_confirmation=%s, resolved_at=NOW() WHERE id=%s",
                                (operator, confirmation, karantin_id))
                    conn.commit()
                    return {"effect": "rejected", "status": "REJECTED"}

                cur.execute("SELECT * FROM ep05_stavke WHERE id = %s", (k["stavka_id"],))
                s = cur.fetchone()
                c = CatalogCandidate.from_json(s["candidate_json"], s["field_sources_json"])
                baseline = c.field_sources.get("_pos_state_at_review")
                if baseline is None:
                    raise ResolutionRefused("this legacy review has no original POS-state snapshot; reject it and submit a corrected document with new content for a fresh review")
                existing, rows = self._read_state(cur, c.sku) if self._valid_read_sku(c) else ([], [])
                if self._state_snapshot(existing, rows) != baseline.detail:
                    raise ResolutionRefused("POS state changed since this item entered review; reject this stale item and submit a corrected document with new content before approval")
                # Rule 11: the operator may supply the PRICE only. Price-related
                # extraction issues are cleared; every other rule still applies.
                c.issues = [i for i in c.issues if i not in PRICE_REASONS]
                c.retail_price, c.retail_price_raw = price, str(price)
                c.field_sources["retail_price"] = FieldSource(
                    OPERATOR, f"{operator} @ {datetime.now().isoformat(timespec='seconds')}: {confirmation}")
                static = static_reasons(c, self.cfg)
                d = self._references_checked(cur, decide(c, existing, rows, self.cfg, static))
                if d.outcome == QUARANTINE:
                    conn.rollback()
                    raise ResolutionRefused(f"still not valid: {d.reason} ({d.detail})")
                if d.outcome in (INSERT, UPDATE):
                    self._write(cur, c, d)
                c.locator = s["locator"]
                new_id = self._audit(cur, s["doc_id"], c, d)
                cur.execute("UPDATE ep05_karantin SET status='RESOLVED', operator_price=%s, operator_name=%s,"
                            " operator_confirmation=%s, resolved_at=NOW(), resolution_stavka_id=%s"
                            " WHERE id=%s", (str(price), operator, confirmation, new_id, karantin_id))
                conn.commit()
                return {"effect": d.outcome, "status": "RESOLVED", "art_id": d.art_id, "stavka_id": new_id}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
