"""
SQLite persistence layer for the ERP model.
Stores raw market inputs, computed ERPs, forecasts, and an audit log.
"""
from __future__ import annotations   # enables float | None on Python 3.9

import json
import sqlite3
import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from config import DB_PATH


def get_connection() -> sqlite3.Connection:
    """Return a connection with row_factory for dict-like access."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    # Use DELETE journal mode for maximum filesystem compatibility
    # (WAL mode is unsupported on some network/FUSE mounts)
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create all tables if they don't exist. Safe to call multiple times."""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS erp_inputs (
            date               TEXT NOT NULL,       -- YYYY-MM-DD
            market             TEXT NOT NULL DEFAULT 'US',
            index_level        REAL NOT NULL,       -- local-CCY index close
            dividend_yield     REAL NOT NULL,       -- decimal, e.g. 0.0168
            buyback_yield      REAL NOT NULL DEFAULT 0.0,
            total_yield        REAL NOT NULL,       -- dividend + buyback
            analyst_5yr_growth REAL,                -- blended 5-yr CAGR, decimal
            year1_growth       REAL,                -- FY1 analyst estimate, decimal
            year2_growth       REAL,                -- FY2 analyst estimate, decimal
            rfr_rate           REAL NOT NULL,       -- local 10yr sovereign yield, decimal
            trailing_eps       REAL,                -- index trailing 12-month EPS
            payout_ratio       REAL DEFAULT 0.7785, -- total payout ratio (div + buyback)
            data_source        TEXT DEFAULT 'auto',
            growth_source      TEXT,                -- description of growth data source
            updated_at         INTEGER NOT NULL,    -- unix timestamp
            PRIMARY KEY (date, market)
        );

        CREATE TABLE IF NOT EXISTS erp_computations (
            date                   TEXT NOT NULL,
            market                 TEXT NOT NULL DEFAULT 'US',
            method                 TEXT NOT NULL DEFAULT 'ddm',  -- 'ddm' or 'fcfe'
            implied_cost_of_equity REAL NOT NULL,
            implied_erp            REAL NOT NULL,
            pv_stage1              REAL,
            terminal_value         REAL,
            pv_terminal            REAL,
            annual_growth_rates    TEXT,
            cash_flows             TEXT,
            solver_iterations      INTEGER,
            solver_method          TEXT,
            computed_at            INTEGER NOT NULL,
            PRIMARY KEY (date, market, method)
        );

        CREATE TABLE IF NOT EXISTS erp_forecasts (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            generated_at   INTEGER NOT NULL,        -- unix timestamp of when forecast was run
            market         TEXT NOT NULL DEFAULT 'US',
            base_date      TEXT NOT NULL,           -- date the forecast was made from
            scenario       TEXT NOT NULL,           -- 'base', 'bull', 'bear', or custom
            forecast_year  INTEGER NOT NULL,        -- 1..N years ahead
            forecast_date  TEXT NOT NULL,           -- YYYY-MM-DD of the forecast point
            index_projected REAL,
            eps_projected   REAL,
            tbond_projected REAL,
            growth_projected REAL,
            implied_erp     REAL NOT NULL,
            implied_r       REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS erp_breakeven (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            computed_at           INTEGER NOT NULL,
            date                  TEXT NOT NULL,
            market                TEXT NOT NULL DEFAULT 'US',
            index_level           REAL NOT NULL,
            trailing_eps          REAL NOT NULL,
            tbond_rate            REAL NOT NULL,
            breakeven_growth      REAL NOT NULL,    -- growth needed for normal ERP
            normal_erp            REAL NOT NULL,    -- definition of normal used
            normal_erp_method     TEXT NOT NULL,    -- 'longrun', 'decade', 'custom'
            interpretation        TEXT
        );

        CREATE TABLE IF NOT EXISTS calculation_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            date        TEXT,
            market      TEXT,                                -- NULL = global event
            step        TEXT NOT NULL,   -- fetch / compute / forecast / error / info
            level       TEXT NOT NULL DEFAULT 'INFO',
            message     TEXT NOT NULL,
            created_at  INTEGER NOT NULL
        );
    """)

    # ── Migration: erp_inputs new columns ──────────────────────────
    existing_inputs_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(erp_inputs)").fetchall()
    }
    inputs_migrations = [
        ("year1_growth",  "REAL"),
        ("year2_growth",  "REAL"),
        ("trailing_eps",  "REAL"),
        ("payout_ratio",  "REAL DEFAULT 0.7785"),
        ("growth_source", "TEXT"),
    ]
    for col, coldef in inputs_migrations:
        if col not in existing_inputs_cols:
            conn.execute(f"ALTER TABLE erp_inputs ADD COLUMN {col} {coldef}")

    # ── Phase 1 column renames (idempotent) ───────────────────────
    # Upgrades any DB still on the pre-Phase-1 column names to the
    # market-agnostic names. For DBs already migrated by
    # migrations/001_multi_market.py + the Phase 1 sqlite rename, this
    # is a no-op.
    existing_inputs_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(erp_inputs)").fetchall()
    }
    if "sp500_level" in existing_inputs_cols and "index_level" not in existing_inputs_cols:
        conn.execute("ALTER TABLE erp_inputs RENAME COLUMN sp500_level TO index_level")
    if "tbond_10yr_rate" in existing_inputs_cols and "rfr_rate" not in existing_inputs_cols:
        conn.execute("ALTER TABLE erp_inputs RENAME COLUMN tbond_10yr_rate TO rfr_rate")

    fc_cols = {row[1] for row in conn.execute("PRAGMA table_info(erp_forecasts)").fetchall()}
    if "sp500_projected" in fc_cols and "index_projected" not in fc_cols:
        conn.execute("ALTER TABLE erp_forecasts RENAME COLUMN sp500_projected TO index_projected")

    be_cols = {row[1] for row in conn.execute("PRAGMA table_info(erp_breakeven)").fetchall()}
    if "sp500_level" in be_cols and "index_level" not in be_cols:
        conn.execute("ALTER TABLE erp_breakeven RENAME COLUMN sp500_level TO index_level")

    # ── Migration: erp_computations — add method column & fix PK ───
    # Old schema had PRIMARY KEY (date) with no method column.
    # New schema needs PRIMARY KEY (date, method).
    # SQLite can't ALTER a PRIMARY KEY, so we rebuild the table if needed.
    comp_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(erp_computations)").fetchall()
    }
    if "method" not in comp_cols:
        # Rebuild: rename old table, create new one, copy data, drop old.
        conn.executescript("""
            ALTER TABLE erp_computations RENAME TO erp_computations_old;

            CREATE TABLE erp_computations (
                date                   TEXT NOT NULL,
                market                 TEXT NOT NULL DEFAULT 'US',
                method                 TEXT NOT NULL DEFAULT 'ddm',
                implied_cost_of_equity REAL NOT NULL,
                implied_erp            REAL NOT NULL,
                pv_stage1              REAL,
                terminal_value         REAL,
                pv_terminal            REAL,
                annual_growth_rates    TEXT,
                cash_flows             TEXT,
                solver_iterations      INTEGER,
                solver_method          TEXT,
                computed_at            INTEGER NOT NULL,
                PRIMARY KEY (date, market, method)
            );

            INSERT INTO erp_computations
                (date, market, method, implied_cost_of_equity, implied_erp,
                 pv_stage1, terminal_value, pv_terminal,
                 solver_iterations, solver_method, computed_at)
            SELECT
                date, 'US', 'ddm', implied_cost_of_equity, implied_erp,
                pv_stage1, terminal_value, pv_terminal,
                solver_iterations, solver_method, computed_at
            FROM erp_computations_old;

            DROP TABLE erp_computations_old;
        """)

    conn.commit()
    conn.close()


def log_event(dt: str, step: str, message: str, market: Optional[str] = None):
    """Write to the audit log."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO calculation_log (date, market, step, message, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (dt, market, step, message, int(time.time()))
    )
    conn.commit()
    conn.close()


def upsert_inputs(
    dt: str,
    index_level: float,
    div_yield: float,
    buyback_yield: float,
    growth: Optional[float],
    rfr_rate: float,
    source: str = "auto",
    trailing_eps: Optional[float] = None,
    payout_ratio: float = 0.7785,
    year1_growth: Optional[float] = None,
    year2_growth: Optional[float] = None,
    growth_source: Optional[str] = None,
    market: str = "US",
):
    """Insert or replace a row in erp_inputs (keyed by (date, market))."""
    conn = get_connection()
    total = div_yield + buyback_yield
    conn.execute("""
        INSERT OR REPLACE INTO erp_inputs
            (date, market, index_level, dividend_yield, buyback_yield, total_yield,
             analyst_5yr_growth, year1_growth, year2_growth,
             rfr_rate, trailing_eps, payout_ratio,
             data_source, growth_source, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (dt, market, index_level, div_yield, buyback_yield, total, growth,
          year1_growth, year2_growth,
          rfr_rate, trailing_eps, payout_ratio,
          source, growth_source, int(time.time())))
    conn.commit()
    conn.close()
    log_event(dt, "fetch",
              f"[{market}] Inputs stored: index={index_level:.2f}, div={div_yield:.4f}, "
              f"buyback={buyback_yield:.4f}, growth={growth}, rfr={rfr_rate:.4f}, "
              f"EPS={trailing_eps}",
              market=market)


def upsert_computation(
    dt: str,
    r: float,
    erp: float,
    pv1: float,
    tv: float,
    pv_tv: float,
    iterations: int,
    method_solver: str,
    method_model: str = "ddm",
    annual_growth_rates: Optional[list] = None,
    cash_flows: Optional[list] = None,
    market: str = "US",
):
    """Insert or replace a computation result. Keyed on (date, market, method_model)."""
    conn = get_connection()
    conn.execute("""
        INSERT OR REPLACE INTO erp_computations
            (date, market, method, implied_cost_of_equity, implied_erp, pv_stage1,
             terminal_value, pv_terminal, annual_growth_rates, cash_flows,
             solver_iterations, solver_method, computed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (dt, market, method_model, r, erp, pv1, tv, pv_tv,
          json.dumps(annual_growth_rates) if annual_growth_rates else None,
          json.dumps(cash_flows) if cash_flows else None,
          iterations, method_solver, int(time.time())))
    conn.commit()
    conn.close()
    log_event(dt, "compute",
              f"[{market}] ERP={erp:.4f} (r={r:.4f}), model={method_model}, "
              f"solver={method_solver}, iter={iterations}",
              market=market)


def upsert_forecast(
    base_date: str,
    scenario: str,
    points: list[dict],
    market: str = "US",
):
    """
    Store forecast results.
    Clears existing forecasts for (market, base_date, scenario) before inserting.
    """
    conn = get_connection()
    generated_at = int(time.time())
    conn.execute(
        "DELETE FROM erp_forecasts WHERE market=? AND base_date=? AND scenario=?",
        (market, base_date, scenario)
    )
    for pt in points:
        conn.execute("""
            INSERT INTO erp_forecasts
                (generated_at, market, base_date, scenario, forecast_year, forecast_date,
                 index_projected, eps_projected, tbond_projected, growth_projected,
                 implied_erp, implied_r)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (generated_at, market, base_date, scenario,
              pt.get("year"), pt.get("date"),
              pt.get("index"), pt.get("eps"),
              pt.get("rfr_rate"), pt.get("analyst_growth"),
              pt.get("implied_erp"), pt.get("implied_r")))
    conn.commit()
    conn.close()
    log_event(base_date, "forecast",
              f"[{market}] Stored {len(points)} forecast points for scenario '{scenario}'",
              market=market)


def upsert_breakeven(
    dt: str,
    index_level: float,
    eps: float,
    rfr_rate: float,
    breakeven_growth: float,
    normal_erp: float,
    normal_erp_method: str,
    interpretation: str = "",
    market: str = "US",
):
    """Store a breakeven growth computation."""
    conn = get_connection()
    conn.execute("""
        INSERT INTO erp_breakeven
            (computed_at, date, market, index_level, trailing_eps, tbond_rate,
             breakeven_growth, normal_erp, normal_erp_method, interpretation)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (int(time.time()), dt, market, index_level, eps, rfr_rate,
          breakeven_growth, normal_erp, normal_erp_method, interpretation))
    conn.commit()
    conn.close()
    log_event(dt, "breakeven",
              f"[{market}] Breakeven growth={breakeven_growth:.4f} "
              f"for normal ERP={normal_erp:.4f} (method={normal_erp_method})",
              market=market)


def _parse_json_fields(d: dict) -> dict:
    """Parse JSON string fields back to Python lists."""
    for field in ("annual_growth_rates", "cash_flows"):
        val = d.get(field)
        if isinstance(val, str):
            try:
                d[field] = json.loads(val)
            except (json.JSONDecodeError, ValueError):
                d[field] = []
    return d


def get_latest(method: str = "fcfe", market: str = "US") -> Optional[dict]:
    """Return the most recent computation joined with inputs for a given method/market."""
    conn = get_connection()
    row = conn.execute("""
        SELECT i.*, c.implied_cost_of_equity, c.implied_erp,
               c.pv_stage1, c.terminal_value, c.pv_terminal,
               c.solver_method, c.method as computation_method,
               c.annual_growth_rates, c.cash_flows
        FROM erp_inputs i
        JOIN erp_computations c ON i.date = c.date AND i.market = c.market
        WHERE c.method = ? AND i.market = ?
        ORDER BY i.date DESC LIMIT 1
    """, (method, market)).fetchone()
    if not row:
        # Fall back to any method for this market
        row = conn.execute("""
            SELECT i.*, c.implied_cost_of_equity, c.implied_erp,
                   c.pv_stage1, c.terminal_value, c.pv_terminal,
                   c.solver_method, c.method as computation_method,
                   c.annual_growth_rates, c.cash_flows
            FROM erp_inputs i
            JOIN erp_computations c ON i.date = c.date AND i.market = c.market
            WHERE i.market = ?
            ORDER BY i.date DESC LIMIT 1
        """, (market,)).fetchone()
    conn.close()
    return _parse_json_fields(dict(row)) if row else None


def get_history(start: str = "1900-01-01", end: str = "2099-12-31",
                method: str = "fcfe", market: str = "US") -> pd.DataFrame:
    """Return full time series of inputs + computations as a DataFrame."""
    conn = get_connection()
    df = pd.read_sql_query("""
        SELECT i.date, i.market, i.index_level, i.dividend_yield, i.buyback_yield,
               i.total_yield, i.analyst_5yr_growth, i.rfr_rate,
               i.trailing_eps, i.payout_ratio,
               c.implied_cost_of_equity, c.implied_erp, c.method
        FROM erp_inputs i
        JOIN erp_computations c ON i.date = c.date AND i.market = c.market
        WHERE c.method = ? AND i.market = ? AND i.date BETWEEN ? AND ?
        ORDER BY i.date
    """, conn, params=(method, market, start, end), parse_dates=["date"])

    # If no rows for that method, try any method
    if df.empty:
        df = pd.read_sql_query("""
            SELECT i.date, i.market, i.index_level, i.dividend_yield, i.buyback_yield,
                   i.total_yield, i.analyst_5yr_growth, i.rfr_rate,
                   i.trailing_eps, i.payout_ratio,
                   c.implied_cost_of_equity, c.implied_erp, c.method
            FROM erp_inputs i
            JOIN erp_computations c ON i.date = c.date AND i.market = c.market
            WHERE i.market = ? AND i.date BETWEEN ? AND ?
            ORDER BY i.date
        """, conn, params=(market, start, end), parse_dates=["date"])

    # Parse JSON string columns back to lists
    for col in ("annual_growth_rates", "cash_flows"):
        if col in df.columns:
            df[col] = df[col].apply(
                lambda v: json.loads(v) if isinstance(v, str) else v
            )

    conn.close()
    return df


def get_forecasts(base_date: Optional[str] = None, scenario: Optional[str] = None,
                  market: str = "US") -> pd.DataFrame:
    """Return stored forecasts, optionally filtered."""
    conn = get_connection()
    query = "SELECT * FROM erp_forecasts WHERE market = ?"
    params: list = [market]
    if base_date:
        query += " AND base_date = ?"
        params.append(base_date)
    if scenario:
        query += " AND scenario = ?"
        params.append(scenario)
    query += " ORDER BY base_date, scenario, forecast_year"
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df


def get_latest_breakeven(market: str = "US") -> Optional[dict]:
    """Return the most recent breakeven growth computation for a market."""
    conn = get_connection()
    row = conn.execute("""
        SELECT * FROM erp_breakeven WHERE market = ?
        ORDER BY computed_at DESC LIMIT 1
    """, (market,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_log(limit: int = 50, market: Optional[str] = None) -> pd.DataFrame:
    """Return recent log entries. If market is given, include that market plus global rows."""
    conn = get_connection()
    if market is None:
        df = pd.read_sql_query(
            "SELECT * FROM calculation_log ORDER BY created_at DESC LIMIT ?",
            conn, params=(limit,)
        )
    else:
        df = pd.read_sql_query(
            "SELECT * FROM calculation_log WHERE market = ? OR market IS NULL "
            "ORDER BY created_at DESC LIMIT ?",
            conn, params=(market, limit)
        )
    conn.close()
    return df


def get_stats(market: str = "US") -> dict:
    """Return summary statistics for display on the dashboard."""
    conn = get_connection()

    # ERP stats from all methods for this market
    rows = conn.execute("""
        SELECT c.implied_erp, c.method
        FROM erp_computations c
        WHERE c.market = ?
          AND c.implied_erp IS NOT NULL AND c.implied_erp > 0
        ORDER BY c.date
    """, (market,)).fetchall()
    conn.close()

    if not rows:
        return {}

    all_erp = [r["implied_erp"] for r in rows]
    fcfe_erp = [r["implied_erp"] for r in rows if r["method"] == "fcfe"]
    ddm_erp = [r["implied_erp"] for r in rows if r["method"] == "ddm"]

    import statistics
    def safe_stats(vals):
        if not vals:
            return {}
        return {
            "mean": statistics.mean(vals),
            "median": statistics.median(vals),
            "stdev": statistics.stdev(vals) if len(vals) > 1 else 0,
            "min": min(vals),
            "max": max(vals),
            "count": len(vals),
        }

    return {
        "all": safe_stats(all_erp),
        "fcfe": safe_stats(fcfe_erp),
        "ddm": safe_stats(ddm_erp),
    }
