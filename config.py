"""
Configuration for the Forward-Looking Equity Risk Premium Model
Based on Damodaran (NYU Stern) methodology
"""
import os
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent

# ── .env loader (gitignored) ───────────────────────────────────────
# Minimal KEY=VALUE parser; only sets keys not already in os.environ
_env_file = BASE_DIR / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _v = _line.split("=", 1)
        _k, _v = _k.strip(), _v.strip().strip('"').strip("'")
        os.environ.setdefault(_k, _v)
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# SQLite DB location.
# Default: ~/erp_model.db  (user's home directory — survives across sessions
#           and works on any OS without permission issues)
# Override: set ERP_DB_PATH environment variable to any absolute path.
_db_env = os.environ.get("ERP_DB_PATH", "")
if _db_env:
    DB_PATH = Path(_db_env)
else:
    DB_PATH = Path.home() / "erp_model.db"

# ── API Keys ───────────────────────────────────────────────────────
# FRED API key: get a free one at https://fred.stlouisfed.org/docs/api/api_key.html
# Set via environment variable or paste here (not recommended for shared repos)
FRED_API_KEY = os.environ.get("FRED_API_KEY", "")

# ── Model Parameters ──────────────────────────────────────────────
# Damodaran uses a 2-stage DDM:
#   Stage 1: 5 years of high growth at analyst consensus rate
#   Stage 2: perpetuity at the risk-free rate (stable growth = Tbond rate)
PROJECTION_YEARS = 5                # Stage 1 horizon
SOLVER_TOLERANCE = 1e-8             # Newton-Raphson convergence threshold
SOLVER_MAX_ITER = 200               # Max iterations for root finder
SOLVER_INITIAL_GUESS = 0.08         # Starting guess for implied cost of equity (8%)
SOLVER_BRACKET_LOW = 0.001          # Lower bound for brentq fallback (0.1%)
SOLVER_BRACKET_HIGH = 0.50          # Upper bound for brentq fallback (50%)

# ── Default Assumptions ───────────────────────────────────────────
# When analyst growth estimates are unavailable, fall back to this
DEFAULT_ANALYST_GROWTH = 0.08       # 8% — long-run nominal earnings growth

# Buyback yield: historically ~2-3% for S&P 500 post-2000
# This is the hardest input to get from free sources.
# Override with actual data when available via --buyback-yield flag
DEFAULT_BUYBACK_YIELD = 0.02        # 2% — conservative default

# Payout ratio: from Damodaran's ERPJan26.xlsx 'Buyback & Dividend computation' sheet
# = (Dividends + Buybacks) / Net Income, trailing average
# Damodaran's Jan 2026 value: 78.85%
# This represents the fraction of earnings returned to shareholders (dividends + buybacks)
DEFAULT_PAYOUT_RATIO = 0.7785       # 78.85% — Damodaran Jan 2026 actual

# ── Data Source Configuration ─────────────────────────────────────
YAHOO_SP500_TICKER = "^GSPC"
FRED_TBOND_SERIES = "DGS10"         # 10-Year Treasury Constant Maturity Rate
FRED_TBILL_SERIES = "DTB3"          # 3-Month Treasury Bill (for reference)
FRED_SP500_DIV_YIELD = None         # Not available on FRED; use Yahoo

# ── Display ───────────────────────────────────────────────────────
DECIMAL_PLACES = 4                  # Precision for displayed percentages
