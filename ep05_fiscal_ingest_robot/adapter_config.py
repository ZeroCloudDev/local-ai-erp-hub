"""
EP05 — load pos_adapter_config.toml into one typed object.

Everything that is specific to the target POS lives in the TOML file, so the
rest of the code can say "the approved tax map" instead of hard-coding "T=1".
The config is loaded once and passed explicitly; nothing reads globals.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
DEFAULT_CONFIG = HERE / "pos_adapter_config.toml"
EXAMPLE_CONFIG = HERE / "pos_adapter_config.example.toml"


@dataclass(frozen=True)
class AdapterConfig:
    profile_version: str
    db_host: str
    db_port: int
    db_user: str
    db_name: str
    db_password_env: str
    model_name: str
    incoming_dir: Path
    work_dir: Path
    archive_dir: Path
    sku_min: int
    sku_max: int
    name_max_len: int
    max_price: Decimal
    currency: str
    tax_class_map: dict[str, int]
    sales_unit_map: dict[str, int]
    price_list: dict[str, object]
    pos_test_values: dict[str, object]
    stable_checks: int = 3
    stable_interval_s: float = 0.4
    max_wait_s: float = 60.0
    retry_limit: int = 3
    ignore_suffixes: tuple[str, ...] = (".part", ".tmp")
    ocr_min_confidence: float = 0.6
    ocr_y_tolerance_px: float = 24.0
    source_file: Path | None = field(default=None, compare=False)

    def db_password(self) -> str:
        # The password is never stored in a file that could be published:
        # 1) environment variable, or 2) the local git-ignored file
        #    ep05_fiscal_ingest_robot/.ep05_db_password (one line, nothing else).
        value = os.environ.get(self.db_password_env)
        if value is None:
            local = HERE / ".ep05_db_password"
            if local.exists():
                value = local.read_text(encoding="utf-8").strip()
        if not value:
            raise RuntimeError(
                f"Set {self.db_password_env} or write the password into {HERE / '.ep05_db_password'}."
            )
        return value

    def code_tables(self) -> tuple[frozenset, frozenset]:
        """Approved tax-class and sales-unit codes (for looking up | columns)."""
        return frozenset(self.tax_class_map), frozenset(self.sales_unit_map)

    # --- the ONE definition of "the selected price-list row" ---------------
    def price_list_where(self, alias: str = "c") -> tuple[str, list[object]]:
        """SQL fragment + params that select the shelf-price row of an article.

        Used by the adapter, the report and verify_demo, so all three always
        look at the same artcjenik row. deleted=0 is not optional.
        """
        p = self.price_list
        sql = (f"{alias}.cjnaziv = %s AND {alias}.loc = %s AND {alias}.pjs = %s "
               f"AND {alias}.deleted = 0")
        return sql, [p["cjnaziv"], p["loc"], p["pjs"]]


def _resolve(path_value: str) -> Path:
    p = Path(path_value)
    return p if p.is_absolute() else REPO_ROOT / p


def load_config(path: Path | None = None) -> AdapterConfig:
    """Load the real config, or the shipped example if no real one exists."""
    if path is None:
        path = DEFAULT_CONFIG if DEFAULT_CONFIG.exists() else EXAMPLE_CONFIG
    raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    db, folders, rng, watch, ocr = (raw["database"], raw["folders"], raw["range"],
                                    raw.get("watch", {}), raw.get("ocr", {}))
    return AdapterConfig(
        profile_version=raw["profile_version"],
        db_host=db["host"], db_port=int(db["port"]), db_user=db["user"],
        db_name=db["database"], db_password_env=db["password_env"],
        model_name=raw["model"]["name"],
        incoming_dir=_resolve(folders["incoming"]),
        work_dir=_resolve(folders["work"]),
        archive_dir=_resolve(folders["archive"]),
        sku_min=int(rng["sku_min"]), sku_max=int(rng["sku_max"]),
        name_max_len=int(rng["name_max_len"]), max_price=Decimal(str(rng["max_price"])),
        currency=raw["currency"]["required"].upper(),
        tax_class_map={k.upper(): int(v) for k, v in raw["tax_class_map"].items()},
        sales_unit_map={k.upper(): int(v) for k, v in raw["sales_unit_map"].items()},
        price_list=dict(raw["price_list_selector"]),
        pos_test_values=dict(raw["pos_test_values"]),
        stable_checks=int(watch.get("stable_checks", 3)),
        stable_interval_s=float(watch.get("stable_interval_s", 0.4)),
        max_wait_s=float(watch.get("max_wait_s", 60)),
        retry_limit=int(watch.get("retry_limit", 3)),
        ignore_suffixes=tuple(s.lower() for s in watch.get("ignore_suffixes", [".part", ".tmp"])),
        ocr_min_confidence=float(ocr.get("min_confidence", 0.6)),
        ocr_y_tolerance_px=float(ocr.get("y_tolerance_px", 24.0)),
        source_file=Path(path),
    )
