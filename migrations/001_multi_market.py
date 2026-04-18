#!/usr/bin/env python3
"""
Migration 001: Multi-market schema foundation.

Idempotent. Adds `market` (default 'US') to every data table, adds provenance
columns, rebuilds `erp_inputs` and `erp_computations` with composite primary
keys, creates the `update_runs` audit table, and installs market-aware
indexes. Safe to re-run — a second invocation logs "already migrated" and
exits cleanly.

Column renames (sp500_level → index_level, tbond_10yr_rate → rfr_rate,
sp500_projected → index_projected) are *deferred* to Phase 1 where Python
call-sites are updated in the same commit. Phase 0 is intentionally
backward-compatible: the existing server.py continues to read/write via the
old column names.

Usage:
    python migrations/001_multi_market.py                  # uses ~/erp_model.db
    python migrations/001_multi_market.py --db /path.db    # override
    python migrations/001_multi_market.py --dry-run        # report only
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import time
from pathlib import Path

MIGRATION_NAME = "001_multi_market"
DEFAULT_DB = Path.home() / "erp_model.db"
BACKUP_SUFFIX = ".bak-pre0"


# --------------------------------------------------------------------- helpers

def _table_info(conn: sqlite3.Connection, table: str) -> dict:
    return {row[1]: row for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _pk_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    pk = [(r[5], r[1]) for r in rows if r[5] > 0]
    return [name for _, name in sorted(pk)]


def _add_column_if_missing(
    conn: sqlite3.Connection, table: str, column: str, coldef: str
) -> bool:
    if column in _table_info(conn, table):
        return False
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coldef}")
    return True


def _col_defs_from_info(info: dict) -> list[str]:
    """Reconstruct column DDL from PRAGMA table_info rows."""
    defs = []
    for _name, row in info.items():
        _cid, cname, ctype, notnull, dflt, _pk = row
        parts = [cname, ctype or ""]
        if notnull:
            parts.append("NOT NULL")
        if dflt is not None:
            parts.append(f"DEFAULT {dflt}")
        defs.append(" ".join(p for p in parts if p).strip())
    return defs


def _probe_exclusive(db_path: Path) -> None:
    """Flush any stale journal and verify no other process holds the DB."""
    conn = sqlite3.connect(str(db_path), timeout=2.0)
    try:
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("ROLLBACK")
    finally:
        conn.close()


def _ensure_backup(db_path: Path) -> Path:
    backup = db_path.with_name(db_path.name + BACKUP_SUFFIX)
    if not backup.exists():
        shutil.copy2(db_path, backup)
    return backup


# ------------------------------------------------------------------ migrations

def _migrate_erp_inputs(conn: sqlite3.Connection) -> list[str]:
    changes: list[str] = []
    if _add_column_if_missing(conn, "erp_inputs", "market",
                              "TEXT NOT NULL DEFAULT 'US'"):
        changes.append("add erp_inputs.market")
    for col, coldef in (
        ("currency",      "TEXT NOT NULL DEFAULT 'USD'"),
        ("index_source",  "TEXT"),
        ("rfr_source",    "TEXT"),
        ("divy_source",   "TEXT"),
        ("fetched_at",    "INTEGER"),
        ("stale_flag",    "INTEGER NOT NULL DEFAULT 0"),
        ("quality_notes", "TEXT"),
    ):
        if _add_column_if_missing(conn, "erp_inputs", col, coldef):
            changes.append(f"add erp_inputs.{col}")

    # Backfill fetched_at from updated_at where null. Sub-second on 65yr.
    conn.execute(
        "UPDATE erp_inputs SET fetched_at = updated_at WHERE fetched_at IS NULL"
    )

    if _pk_columns(conn, "erp_inputs") == ["date"]:
        _rebuild_table_with_pk(
            conn, "erp_inputs", new_pk="(date, market)"
        )
        changes.append("rebuild erp_inputs PK → (date, market)")

    if _add_index_if_missing(
        conn, "idx_inputs_market_date", "erp_inputs(market, date DESC)"
    ):
        changes.append("index idx_inputs_market_date")
    if _add_index_if_missing(conn, "idx_inputs_date", "erp_inputs(date)"):
        changes.append("index idx_inputs_date")
    return changes


def _migrate_erp_computations(conn: sqlite3.Connection) -> list[str]:
    changes: list[str] = []
    if _add_column_if_missing(conn, "erp_computations", "market",
                              "TEXT NOT NULL DEFAULT 'US'"):
        changes.append("add erp_computations.market")
    if _add_column_if_missing(conn, "erp_computations", "model_version",
                              "TEXT NOT NULL DEFAULT 'v1'"):
        changes.append("add erp_computations.model_version")

    if _pk_columns(conn, "erp_computations") != ["date", "market", "method"]:
        _rebuild_table_with_pk(
            conn, "erp_computations", new_pk="(date, market, method)"
        )
        changes.append("rebuild erp_computations PK → (date, market, method)")

    if _add_index_if_missing(
        conn, "idx_comp_market_date", "erp_computations(market, date DESC)"
    ):
        changes.append("index idx_comp_market_date")
    if _add_index_if_missing(conn, "idx_comp_date", "erp_computations(date)"):
        changes.append("index idx_comp_date")
    return changes


def _migrate_erp_forecasts(conn: sqlite3.Connection) -> list[str]:
    changes: list[str] = []
    if _add_column_if_missing(conn, "erp_forecasts", "market",
                              "TEXT NOT NULL DEFAULT 'US'"):
        changes.append("add erp_forecasts.market")
    if _add_index_if_missing(
        conn, "idx_fc_market_base", "erp_forecasts(market, base_date, scenario)"
    ):
        changes.append("index idx_fc_market_base")
    return changes


def _migrate_erp_breakeven(conn: sqlite3.Connection) -> list[str]:
    changes: list[str] = []
    if _add_column_if_missing(conn, "erp_breakeven", "market",
                              "TEXT NOT NULL DEFAULT 'US'"):
        changes.append("add erp_breakeven.market")
    if _add_index_if_missing(
        conn, "idx_be_market_date", "erp_breakeven(market, date DESC)"
    ):
        changes.append("index idx_be_market_date")
    return changes


def _migrate_calculation_log(conn: sqlite3.Connection) -> list[str]:
    changes: list[str] = []
    if _add_column_if_missing(conn, "calculation_log", "market", "TEXT"):
        changes.append("add calculation_log.market")
    if _add_column_if_missing(conn, "calculation_log", "level",
                              "TEXT NOT NULL DEFAULT 'INFO'"):
        changes.append("add calculation_log.level")
    if _add_index_if_missing(
        conn, "idx_log_market_date", "calculation_log(market, created_at DESC)"
    ):
        changes.append("index idx_log_market_date")
    return changes


def _create_update_runs(conn: sqlite3.Connection) -> list[str]:
    if _table_exists(conn, "update_runs"):
        return []
    conn.execute("""
        CREATE TABLE update_runs (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at    INTEGER NOT NULL,
            finished_at   INTEGER,
            markets       TEXT NOT NULL,
            status_json   TEXT NOT NULL,
            git_sha       TEXT,
            model_version TEXT
        )
    """)
    return ["create update_runs"]


# ------------------------------------------------------- PK-rebuild primitive

def _rebuild_table_with_pk(
    conn: sqlite3.Connection, table: str, new_pk: str
) -> None:
    """
    Rebuild a table to install a new composite PK.

    SQLite cannot ALTER a PRIMARY KEY, so we follow the documented recipe:
    rename → create new → INSERT…SELECT → drop old. We re-emit the existing
    column definitions verbatim from PRAGMA table_info so we never drift
    from whatever shape the table happens to have at migration time.
    """
    info = _table_info(conn, table)
    cols = list(info.keys())
    col_list = ", ".join(cols)
    col_defs = _col_defs_from_info(info)
    col_defs.append(f"PRIMARY KEY {new_pk}")
    ddl_body = ",\n    ".join(col_defs)

    # NB: execute statements individually rather than via executescript(),
    # because executescript() forces an implicit COMMIT of the outer txn.
    conn.execute(f"ALTER TABLE {table} RENAME TO {table}_old_001")
    conn.execute(f"CREATE TABLE {table} (\n    {ddl_body}\n)")
    conn.execute(
        f"INSERT INTO {table} ({col_list}) SELECT {col_list} FROM {table}_old_001"
    )
    conn.execute(f"DROP TABLE {table}_old_001")


def _add_index_if_missing(
    conn: sqlite3.Connection, name: str, target: str
) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (name,)
    ).fetchone()
    if row is not None:
        return False
    conn.execute(f"CREATE INDEX {name} ON {target}")
    return True


# ------------------------------------------------------------------- run loop

def _all_changes(conn: sqlite3.Connection) -> list[str]:
    changes: list[str] = []
    changes += _migrate_erp_inputs(conn)
    changes += _migrate_erp_computations(conn)
    changes += _migrate_erp_forecasts(conn)
    changes += _migrate_erp_breakeven(conn)
    changes += _migrate_calculation_log(conn)
    changes += _create_update_runs(conn)
    return changes


def _stamp_update_runs(conn: sqlite3.Connection, changes: list[str]) -> None:
    now = int(time.time())
    conn.execute(
        """
        INSERT INTO update_runs
            (started_at, finished_at, markets, status_json, git_sha, model_version)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            now,
            now,
            json.dumps(["US"]),
            json.dumps({
                "migration": MIGRATION_NAME,
                "changes": changes,
                "US": "migrated",
            }),
            None,
            "v1",
        ),
    )


def run(db_path: Path, dry_run: bool = False) -> int:
    if not db_path.exists():
        print(f"[ERR] DB not found: {db_path}", file=sys.stderr)
        return 2

    _probe_exclusive(db_path)
    backup = _ensure_backup(db_path)
    print(f"[OK] Backup: {backup}")

    conn = sqlite3.connect(str(db_path))
    # Disable Python's implicit transaction management — we drive BEGIN/COMMIT
    # explicitly so VACUUM (which cannot run inside a txn) works cleanly.
    conn.isolation_level = None
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("BEGIN")
        changes = _all_changes(conn)
        if dry_run:
            conn.execute("ROLLBACK")
            if changes:
                print("[DRY-RUN] Would apply:")
                for c in changes:
                    print(f"  - {c}")
            else:
                print("[DRY-RUN] Already migrated — no changes.")
            return 0

        if changes:
            _stamp_update_runs(conn, changes)
            conn.execute("COMMIT")
            print("[OK] Applied:")
            for c in changes:
                print(f"  - {c}")
        else:
            conn.execute("ROLLBACK")
            print("[OK] Already migrated — no changes.")

        conn.execute("PRAGMA foreign_keys = ON")
        integ = conn.execute("PRAGMA integrity_check").fetchone()[0]
        print(f"[OK] integrity_check: {integ}")
        if integ != "ok":
            return 3
        conn.execute("VACUUM")
        return 0
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    sys.exit(run(args.db, dry_run=args.dry_run))
