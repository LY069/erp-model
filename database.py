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
            date               TEXT PRIMARY KEY,    -- YYYY-MM-DD
            sp500_level        REAL NOT NULL,
            dividend_yield     REAL NOT NULL,       -- decimal, e.g. 0.0168
            buyback_yield      REAL NOT NULL DEFAULT 0.0,
            total_yield        REAL NOT NULL,       -- dividend + buyback
            analyst_5yr_growth REAL,                -- blended 5-yr CAGR, decimal
            year1_growth       REAL,                -- FY1 analyst estimate, decimal
            year2_growth       REAL,                -- FY2 analyst estimate, decimal
            tbond_10yr_rate    REAL NOT NULL,       -- decimal, e.g. 0.0418
            trailing_eps       REAL,                -- S&P 500 trailing 12-month EPS
            payout_ratio       REAL DEFAULT 0.7785, -- total payout ratio (div + buyback)
            data_source        TEXT DEFAULT 'auto',
            growth_source      TEXT,                -- description of growth data source
            updated_at         INTEGER NOT NULL     -- unix timestamp
        );

        CREATE TABLE IF NOT EXISTS erp_computations (
            date                   TEXT NOT NULL,
            method                 TEXT NOT NULL DEFAULT 'ddm',  -- 'ddm' or 'fcfe'
            implied_cost_of_equity REAL NOT NULL,   -- the solved 'r'
            implied_erp            REAL NOT NULL,   -- r - Tbond rate
            pv_stage1              REAL,             -- PV of 5-year cash flows
            terminal_value         REAL,             -- undiscounted TV
            pv_terminal            REAL,             -- discounted TV
            annual_growth_rates    TEXT,             -- JSON array of 5 growth rates
            cash_flows             TEXT,             -- JSON array of 5 cash flows
            solver_iterations      INTEGER,
            solver_method          TEXT,             -- 'newton' or 'brentq'
            computed_at            INTEGER NOT NULL,
            PRIMARY KEY (date, method),
            FOREIGN KEY (date) REFERENCES erp_inputs(date)
        );

        CREATE TABLE IF NOT EXISTS erp_forecasts (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            generated_at   INTEGER NOT NULL,        -- unix timestamp of when forecast was run
            base_date      TEXT NOT NULL,           -- date the forecast was made from
            scenario       TEXT NOT NULL,           -- 'base', 'bull', 'bear', or custom
            forecast_year  INTEGER NOT NULL,        -- 1..N years ahead
            forecast_date  TEXT NOT NULL,           -- YYYY-MM-DD of the forecast point
            sp500_projected REAL,
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
            sp500_level           REAL NOT NULL,
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
            step        TEXT NOT NULL,   -- fetch / compute / forecast / error / info
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
                PRIMARY KEY (date, method)
            );

            INSERT INTO erp_computations
                (date, method, implied_cost_of_equity, implied_erp,
                 pv_stage1, terminal_value, pv_terminal,
                 solver_iterations, solver_method, computed_at)
            SELECT
                date, 'ddm', implied_cost_of_equity, implied_erp,
                pv_stage1, terminal_value, pv_terminal,
                solver_iterations, solver_method, computed_at
            FROM erp_computations_old;

            DROP TABLE erp_computations_old;
        """)

    conn.commit()
    conn.close()


def log_event(dt: str, step: str, message: str):
    """Write to the audit log."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO calculation_log (date, step, message, created_at) VALUES (?, ?, ?, ?)",
        (dt, step, message, int(time.time()))
    )
    conn.commit()
    conn.close()


def upsert_inputs(
    dt: str,
    sp500: float,
    div_yield: float,
    buyback_yield: float,
    growth: Optional[float],
    tbond: float,
    source: str = "auto",
    trailing_eps: Optional[float] = None,
    payout_ratio: float = 0.7785,
    year1_growth: Optional[float] = None,
    year2_growth: Optional[float] = None,
    growth_source: Optional[str] = None,
):
    """Insert or replace a row in erp_inputs."""
    conn = get_connection()
    total = div_yield + buyback_yield
    conn.execute("""
        INSERT OR REPLACE INTO erp_inputs
            (date, sp500_level, dividend_yield, buyback_yield, total_yield,
             analyst_5yr_growth, year1_growth, year2_growth,
             tbond_10yr_rate, trailing_eps, payout_ratio,
             data_source, growth_source, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (dt, sp500, div_yield, buyback_yield, total, growth,
          year1_growth, year2_growth,
          tbond, trailing_eps, payout_ratio,
          source, growth_source, int(time.time())))
    conn.commit()
    conn.close()
    log_event(dt, "fetch",
              f"Inputs stored: S&P={sp500:.2f}, div={div_yield:.4f}, "
              f"buyback={buyback_yield:.4f}, growth={growth}, Tbond={tbond:.4f}, "
              f"EPS={trailing_eps}")


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
):
    """Insert or replace a computation result. Keyed on (date, method_model)."""
    conn = get_connection()
    conn.execute("""
        INSERT OR REPLACE INTO erp_computations
            (date, method, implied_cost_of_equity, implied_erp, pv_stage1,
             terminal_value, pv_terminal, annual_growth_rates, cash_flows,
             solver_iterations, solver_method, computed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (dt, method_model, r, erp, pv1, tv, pv_tv,
          json.dumps(annual_growth_rates) if annual_growth_rates else None,
          json.dumps(cash_flows) if cash_flows else None,
          iterations, method_solver, int(time.time())))
    conn.commit()
    conn.close()
    log_event(dt, "compute",
              f"ERP={erp:.4f} (r={r:.4f}), model={method_model}, "
              f"solver={method_solver}, iter={iterations}")


def upsert_forecast(
    base_date: str,
    scenario: str,
    points: list[dict],
):
    """
    Store forecast results.
    Clears existing forecasts for (base_date, scenario) before inserting.
    """
    conn = get_connection()
    generated_at = int(time.time())
    conn.execute(
        "DELETE FROM erp_forecasts WHERE base_date=? AND scenario=?",
        (base_date, scenario)
    )
    for pt in points:
        conn.execute("""
            INSERT INTO erp_forecasts
                (generated_at, base_date, scenario, forecast_year, forecast_date,
                 sp500_projected, eps_projected, tbond_projected, growth_projected,
                 implied_erp, implied_r)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (generated_at, base_date, scenario,
              pt.get("year"), pt.get("date"),
              pt.get("sp500"), pt.get("eps"),
              pt.get("tbond_rate"), pt.get("analyst_growth"),
              pt.get("implied_erp"), pt.get("implied_r")))
    conn.commit()
    conn.close()
    log_event(base_date, "forecast",
              f"Stored {len(points)} forecast points for scenario '{scenario}'")


def upsert_breakeven(
    dt: str,
    sp500: float,
    eps: float,
    tbond: float,
    breakeven_growth: float,
    normal_erp: float,
    normal_erp_method: str,
    interpretation: str = "",
):
    """Store a breakeven growth computation."""
    conn = get_connection()
    conn.execute("""
        INSERT INTO erp_breakeven
            (computed_at, date, sp500_level, trailing_eps, tbond_rate,
             breakeven_growth, normal_erp, normal_erp_method, interpretation)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (int(time.time()), dt, sp500, eps, tbond,
          breakeven_growth, normal_erp, normal_erp_method, interpretation))
    conn.commit()
    conn.close()
    log_event(dt, "breakeven",
              f"Breakeven growth={breakeven_growth:.4f} for normal ERP={normal_erp:.4f} "
              f"(method={normal_erp_method})")


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


def get_latest(method: str = "fcfe") -> Optional[dict]:
    """Return the most recent computation joined with inputs for a given method."""
    conn = get_connection()
    row = conn.execute("""
        SELECT i.*, c.implied_cost_of_equity, c.implied_erp,
               c.pv_stage1, c.terminal_value, c.pv_terminal,
               c.solver_method, c.method as computation_method,
               c.annual_growth_rates, c.cash_flows
        FROM erp_inputs i
        JOIN erp_computations c ON i.date = c.date
        WHERE c.method = ?
        ORDER BY i.date DESC LIMIT 1
    """, (method,)).fetchone()
    if not row:
        # Fall back to any method
        row = conn.execute("""
            SELECT i.*, c.implied_cost_of_equity, c.implied_erp,
                   c.pv_stage1, c.terminal_value, c.pv_terminal,
                   c.solver_method, c.method as computation_method,
                   c.annual_growth_rates, c.cash_flows
            FROM erp_inputs i
            JOIN erp_computations c ON i.date = c.date
            ORDER BY i.date DESC LIMIT 1
        """).fetchone()
    conn.close()
    return _parse_json_fields(dict(row)) if row else None


def get_history(start: str = "1900-01-01", end: str = "2099-12-31",
                method: str = "fcfe") -> pd.DataFrame:
    """Return full time series of inputs + computations as a DataFrame."""
    conn = get_connection()
    df = pd.read_sql_query("""
        SELECT i.date, i.sp500_level, i.dividend_yield, i.buyback_yield,
               i.total_yield, i.analyst_5yr_growth, i.tbond_10yr_rate,
               i.trailing_eps, i.payout_ratio,
               c.implied_cost_of_equity, c.implied_erp, c.method
        FROM erp_inputs i
        JOIN erp_computations c ON i.date = c.date AND c.method = ?
        WHERE i.date BETWEEN ? AND ?
        ORDER BY i.date
    """, conn, params=(method, start, end), parse_dates=["date"])

    # If no rows for that method, try any method
    if df.empty:
        df = pd.read_sql_query("""
            SELECT i.date, i.sp500_level, i.dividend_yield, i.buyback_yield,
                   i.total_yield, i.analyst_5yr_growth, i.tbond_10yr_rate,
                   i.trailing_eps, i.payout_ratio,
                   c.implied_cost_of_equity, c.implied_erp, c.method
            FROM erp_inputs i
            JOIN erp_computations c ON i.date = c.date
            WHERE i.date BETWEEN ? AND ?
            ORDER BY i.date
        """, conn, params=(start, end), parse_dates=["date"])

    # Parse JSON string columns back to lists
    for col in ("annual_growth_rates", "cash_flows"):
        if col in df.columns:
            df[col] = df[col].apply(
                lambda v: json.loads(v) if isinstance(v, str) else v
            )

    conn.close()
    return df


def get_forecasts(base_date: Optional[str] = None, scenario: Optional[str] = None) -> pd.DataFrame:
    """Return stored forecasts, optionally filtered."""
    conn = get_connection()
    query = "SELECT * FROM erp_forecasts"
    params: list = []
    conditions = []
    if base_date:
        conditions.append("base_date = ?")
        params.append(base_date)
    if scenario:
        conditions.append("scenario = ?")
        params.append(scenario)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY base_date, scenario, forecast_year"
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df


def get_latest_breakeven() -> Optional[dict]:
    """Return the most recent breakeven growth computation."""
    conn = get_connection()
    row = conn.execute("""
        SELECT * FROM erp_breakeven ORDER BY computed_at DESC LIMIT 1
    """).fetchone()
    conn.close()
    return dict(row) if row else None


def get_log(limit: int = 50) -> pd.DataFrame:
    """Return recent log entries."""
    conn = get_connection()
    df = pd.read_sql_query(
        "SELECT * FROM calculation_log ORDER BY created_at DESC LIMIT ?",
        conn, params=(limit,)
    )
    conn.close()
    return df


def get_stats() -> dict:
    """Return summary statistics for display on the dashboard."""
    conn = get_connection()

    # ERP stats from all methods
    rows = conn.execute("""
        SELECT c.implied_erp, c.method
        FROM erp_computations c
        WHERE c.implied_erp IS NOT NULL AND c.implied_erp > 0
        ORDER BY c.date
    """).fetchall()
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
