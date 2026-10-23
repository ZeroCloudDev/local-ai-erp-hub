"""
EP05 — content snapshot for the rollback proof.

A row COUNT that stays the same proves little (one insert + one delete also
keeps the count). This script stores the sorted CONTENT of:
    artikli (managed SKU range), their artcjenik rows, ep05_dokumenti,
    ep05_stavke, ep05_karantin, ep05_writer_lock
and a SHA-256 over that content. Before and after the failure probe the two
hashes must be identical.

Read in ONE consistent snapshot (START TRANSACTION WITH CONSISTENT SNAPSHOT),
while no other processing, archive retry or resolver is running.
The time the snapshot was taken is stored next to the hash, never inside it.
Note: InnoDB does not roll back AUTO_INCREMENT counters; they are not row
content and are deliberately not part of the hash.

    python ep05_fiscal_ingest_robot\\snapshot_demo_state.py --label before_fail
    python ep05_fiscal_ingest_robot\\snapshot_demo_state.py --label after_fail --compare before_fail
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ep05_fiscal_ingest_robot.adapter_config import AdapterConfig, load_config
from ep05_fiscal_ingest_robot.mysql_pos_adapter import PosAdapter


def take_snapshot(cfg: AdapterConfig) -> dict:
    conn = PosAdapter(cfg).connect()
    try:
        with conn.cursor() as cur:
            cur.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT")
            tables: dict[str, list] = {}
            cur.execute("SELECT * FROM artikli WHERE art_broj BETWEEN %s AND %s ORDER BY id",
                        (cfg.sku_min, cfg.sku_max))
            tables["artikli"] = list(cur.fetchall())
            ids = [r["id"] for r in tables["artikli"]] or ["-"]
            cur.execute(f"SELECT * FROM artcjenik WHERE idart IN ({','.join(['%s'] * len(ids))}) ORDER BY id", ids)
            tables["artcjenik"] = list(cur.fetchall())
            for t in ("ep05_dokumenti", "ep05_stavke", "ep05_karantin", "ep05_writer_lock"):
                cur.execute(f"SELECT * FROM {t} ORDER BY id")
                tables[t] = list(cur.fetchall())
            conn.rollback()
    finally:
        conn.close()
    canonical = json.dumps(tables, sort_keys=True, default=str, ensure_ascii=False)
    return {"sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "row_counts": {t: len(r) for t, r in tables.items()},
            "taken_at": datetime.now().isoformat(timespec="seconds"),
            "tables": json.loads(canonical)}


def snapshot_path(cfg: AdapterConfig, label: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", label):
        raise ValueError("Snapshot label must be 1-80 letters, digits, underscores or hyphens")
    return cfg.archive_dir / "snapshots" / f"{label}.json"


def validate_snapshot(snapshot: dict) -> bool:
    if not isinstance(snapshot.get("tables"), dict):
        return False
    canonical = json.dumps(snapshot["tables"], sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest() == snapshot.get("sha256")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path)
    ap.add_argument("--label", required=True)
    ap.add_argument("--compare", help="label of an earlier snapshot that must be identical")
    args = ap.parse_args()
    cfg = load_config(args.config)
    out = snapshot_path(cfg, args.label)
    if out.exists():
        raise FileExistsError(f"Snapshot already exists; use a new label: {out}")
    if args.compare == args.label:
        raise ValueError("A snapshot cannot be compared with itself")
    snap = take_snapshot(cfg)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(snap, indent=1, ensure_ascii=False))
    print(f"[{args.label}] sha256={snap['sha256']}  rows={snap['row_counts']}")
    if args.compare:
        other = json.loads(snapshot_path(cfg, args.compare).read_text(encoding="utf-8"))
        same = validate_snapshot(other) and other["sha256"] == snap["sha256"]
        print(f"[{args.compare}] sha256={other['sha256']}")
        print("SNAPSHOT IDENTICAL - PASS" if same else "SNAPSHOT DIFFERENT - FAIL")
        return 0 if same else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
