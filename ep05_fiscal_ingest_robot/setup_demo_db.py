"""
EP05 — create / reset the kasa_ep05 demo database.

Runs demo_db/01_schema.sql, 02_seed.sql, creates the ep05_demo user with the
password from EP05_DB_PASSWORD, runs 03_user.sql and checks the seed (5 / 0).

This is a SETUP step, deliberately separate from processing: DROP/CREATE
cause implicit commits and must never run inside a business transaction.

It needs an administrator account only for this step (XAMPP default:
root with an empty password). The admin password, if any, comes from
EP05_ADMIN_PASSWORD. The processing code itself never uses the admin account.

    $env:EP05_DB_PASSWORD = "choose-a-local-password"
    python ep05_fiscal_ingest_robot\\setup_demo_db.py --reset
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymysql

from ep05_fiscal_ingest_robot.adapter_config import load_config

HERE = Path(__file__).resolve().parent
SQL_DIR = HERE / "demo_db"


def sql_statements(path: Path) -> list[str]:
    """Split a simple SQL file (no procedures, no ';' inside literals) into statements."""
    text = path.read_text(encoding="utf-8")
    text = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("--"))
    return [s.strip() for s in re.split(r";[ \t]*(?:--[^\n]*)?(?:\n|$)", text) if s.strip()]


def run_file(conn, path: Path) -> None:
    with conn.cursor() as cur:
        for stmt in sql_statements(path):
            cur.execute(stmt)
    conn.commit()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reset", action="store_true", help="required: drops and recreates kasa_ep05")
    ap.add_argument("--admin-user", default="root")
    ap.add_argument("--config", type=Path)
    args = ap.parse_args()
    if not args.reset:
        print("Refusing to run without --reset (this drops kasa_ep05).")
        return 2
    cfg = load_config(args.config)
    if cfg.db_name != "kasa_ep05":
        print(f"Refusing: this setup only manages kasa_ep05, config says {cfg.db_name!r}.")
        return 2
    demo_pw = cfg.db_password()
    admin = pymysql.connect(host=cfg.db_host, port=cfg.db_port, user=args.admin_user,
                            password=os.environ.get("EP05_ADMIN_PASSWORD", ""), charset="utf8",
                            autocommit=False)
    try:
        run_file(admin, SQL_DIR / "01_schema.sql")
        run_file(admin, SQL_DIR / "02_seed.sql")
        with admin.cursor() as cur:
            for host in ("localhost", "127.0.0.1"):
                cur.execute("CREATE USER IF NOT EXISTS %s@%s IDENTIFIED BY %s", (cfg.db_user, host, demo_pw))
                cur.execute("ALTER USER %s@%s IDENTIFIED BY %s", (cfg.db_user, host, demo_pw))
        admin.commit()
        run_file(admin, SQL_DIR / "03_user.sql")
        with admin.cursor() as cur:
            cur.execute("SELECT VERSION()")
            version = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM kasa_ep05.artikli WHERE art_broj BETWEEN %s AND %s",
                        (cfg.sku_min, cfg.sku_max))
            articles = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM kasa_ep05.ep05_karantin WHERE status = 'OPEN'")
            open_q = cur.fetchone()[0]
            cur.execute("SELECT table_name, engine FROM information_schema.tables "
                        "WHERE table_schema = 'kasa_ep05' ORDER BY table_name")
            engines = cur.fetchall()
    finally:
        admin.close()
    print(f"server: {version}")
    print("tables:", ", ".join(f"{t}={e}" for t, e in engines))
    print(f"seed check: articles={articles} open_quarantine={open_q}  (expected 5 / 0)")
    ok = articles == 5 and open_q == 0 and all(e == "InnoDB" for _t, e in engines)
    print("SEED PASS" if ok else "SEED FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
