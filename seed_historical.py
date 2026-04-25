"""
Historical seeder for the ERP database.

Per-market dispatch:

  python seed_historical.py                          # US (default), Damodaran XLS
  python seed_historical.py --market US              # explicit US
  python seed_historical.py --market UK              # UK from Yahoo + FRED, 1990+

US path: Damodaran's histimpl.xls (auto-downloaded if missing).
UK path: FTSE 100 year-end levels (yfinance ^FTSE) + UK 10Y Gilt
         year-end yields (FRED IRLTLT01GBM156N). Dividend yield, payout
         ratio and growth use the v1 bootstrap defaults from
         markets_config.MARKETS["UK"] — flagged in data_source so they
         are distinguishable from live-fetched rows.
"""
import argparse
import sys
import urllib.request
from datetime import date
from pathlib import Path

import pandas as pd

# Make sure local modules resolve
sys.path.insert(0, str(Path(__file__).parent))

import config  # noqa: F401  (loads .env into os.environ)
from database import init_db, upsert_inputs, upsert_computation
from erp_calculator import compute_erp
from markets_config import get_market

DAMODARAN_URL = "https://pages.stern.nyu.edu/~adamodar/pc/datasets/histimpl.xls"
LOCAL_CACHE   = Path(__file__).parent / "histimpl_cache.xls"


# ─────────────────────────────────────────────────────────────────────
# US (existing path)
# ─────────────────────────────────────────────────────────────────────

def download_xls(dest: Path):
    print(f"  Downloading from {DAMODARAN_URL} ...")
    urllib.request.urlretrieve(DAMODARAN_URL, dest)
    print(f"  Saved to {dest.name}")


def load_damodaran_df(xls_path: Path) -> pd.DataFrame:
    """Parse the XLS into a clean DataFrame with standardised column names."""
    xl = pd.ExcelFile(str(xls_path), engine="xlrd")
    raw = xl.parse(xl.sheet_names[0], header=None)

    # Row 6 = headers, row 7+ = data
    headers = raw.iloc[6].tolist()
    data = raw.iloc[7:].copy()
    data.columns = headers

    # Drop NaN / non-year rows
    data = data[pd.to_numeric(data["Year"], errors="coerce").notna()].copy()
    data["Year"] = data["Year"].astype(int)

    return data


def seed_us(xls_path: Path, start_year: int = 1961, verbose: bool = True) -> int:
    """Load Damodaran historical US data into the ERP database."""
    init_db()
    df = load_damodaran_df(xls_path)
    df = df[df["Year"] >= start_year].copy()

    seeded = 0
    skipped = 0

    print(f"  Seeding {len(df)} years ({df['Year'].min()}–{df['Year'].max()})...")

    for _, row in df.iterrows():
        yr = int(row["Year"])
        dt = f"{yr}-12-31"

        sp500    = float(row["S&P 500"])
        div_y    = float(row["Dividend Yield"])
        tbond    = float(row["T.Bond Rate"])

        # Total cash yield = (Dividends + Buybacks) / S&P level
        div_buy_raw = row.get("Dividends + Buybacks")
        if pd.notna(div_buy_raw) and float(div_buy_raw) > 0:
            total_cash = float(div_buy_raw)
            total_yield = total_cash / sp500
            buyback_yield = total_yield - div_y
        else:
            total_yield = div_y
            buyback_yield = 0.0

        # Growth: prefer analyst estimate, fall back to smoothed
        analyst_g = row.get("Analyst Growth Estimate")
        smoothed_g = row.get("Smoothed Growth")
        if pd.notna(analyst_g) and float(analyst_g) > 0:
            growth = float(analyst_g)
        elif pd.notna(smoothed_g) and float(smoothed_g) > 0:
            growth = float(smoothed_g)
        else:
            skipped += 1
            if verbose:
                print(f"    {yr}: skipped — no usable growth estimate")
            continue

        upsert_inputs(
            dt=dt,
            index_level=sp500,
            div_yield=div_y,
            buyback_yield=max(0.0, buyback_yield),
            growth=growth,
            rfr_rate=tbond,
            source="damodaran_histimpl",
            market="US",
        )

        try:
            result = compute_erp(
                dt=dt,
                index_level=sp500,
                total_yield=total_yield,
                growth_high=growth,
                rfr_rate=tbond,
                method="ddm",
            )
            upsert_computation(
                dt=dt,
                r=result.implied_r,
                erp=result.implied_erp,
                pv1=result.pv_stage1,
                tv=result.terminal_value,
                pv_tv=result.pv_terminal,
                iterations=result.solver_iterations,
                method_solver=result.solver_method,
                method_model="ddm",
                annual_growth_rates=result.annual_growth_rates,
                cash_flows=result.cash_flows,
                market="US",
            )
            seeded += 1
            if verbose:
                pub_ddm = row.get("Implied Premium (DDM)")
                pub_fcfe = row.get("Implied ERP (FCFE)")
                pub_str = ""
                if pd.notna(pub_fcfe):
                    pub_str = f"  Damodaran FCFE={float(pub_fcfe):.2%}"
                elif pd.notna(pub_ddm):
                    pub_str = f"  Damodaran DDM={float(pub_ddm):.2%}"
                print(f"    {yr}: ERP={result.implied_erp:.2%}  "
                      f"(r={result.implied_r:.2%}, yield={total_yield:.2%}, "
                      f"growth={growth:.2%}){pub_str}")
        except Exception as e:
            skipped += 1
            if verbose:
                print(f"    {yr}: solver failed — {e}")

    print(f"\n  Done. Seeded: {seeded}  Skipped: {skipped}")
    return seeded


# ─────────────────────────────────────────────────────────────────────
# UK (new path — FTSE 100 + FRED 10Y Gilt, v1 bootstrap)
# ─────────────────────────────────────────────────────────────────────

def _fetch_ftse_yearend_closes(start_year: int, end_year: int) -> dict[int, float]:
    """Return {year: Dec close} for ^FTSE on Yahoo, year ∈ [start_year, end_year]."""
    import yfinance as yf
    ticker = yf.Ticker("^FTSE")
    hist = ticker.history(
        start=f"{start_year}-01-01",
        end=f"{end_year + 1}-01-15",
        interval="1mo",
        auto_adjust=False,
    )
    if hist.empty:
        raise RuntimeError("yfinance returned no ^FTSE history")
    closes = hist["Close"].copy()
    closes.index = pd.to_datetime(closes.index).tz_localize(None)
    out: dict[int, float] = {}
    for yr in range(start_year, end_year + 1):
        slice_ = closes[(closes.index.year == yr) & (closes.index.month == 12)]
        if not slice_.empty:
            out[yr] = float(slice_.iloc[-1])
    return out


def _fetch_fred_yearend_rates(series_id: str, start_year: int, end_year: int,
                              api_key: str) -> dict[int, float]:
    """Return {year: rate as decimal} from FRED for the December monthly observation."""
    import requests
    url = (
        "https://api.stlouisfed.org/fred/series/observations"
        f"?series_id={series_id}&api_key={api_key}&file_type=json"
        f"&observation_start={start_year}-01-01"
        f"&observation_end={end_year}-12-31"
    )
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    obs = resp.json().get("observations", [])
    out: dict[int, float] = {}
    for o in obs:
        if o.get("value") in (".", "", None):
            continue
        d = pd.Timestamp(o["date"])
        if d.month == 12:
            out[d.year] = float(o["value"]) / 100.0
    return out


def seed_uk(start_year: int = 1990, end_year: int | None = None,
            verbose: bool = True) -> int:
    """
    v1 UK bootstrap: FTSE 100 year-end + UK 10Y Gilt year-end.
    Dividend yield, payout, growth use MarketSpec defaults.
    """
    init_db()
    spec = get_market("UK")
    api_key = config.FRED_API_KEY
    if not api_key:
        raise RuntimeError(
            "FRED_API_KEY not set. Add it to .env or export it before running."
        )

    end_year = end_year or (date.today().year - 1)

    print(f"  Fetching ^FTSE year-end closes {start_year}–{end_year} ...")
    ftse = _fetch_ftse_yearend_closes(start_year, end_year)

    print(f"  Fetching FRED {spec.fred_rfr_series} year-end (Dec) rates ...")
    gilt = _fetch_fred_yearend_rates(spec.fred_rfr_series, start_year, end_year, api_key)

    div_y    = 0.035                             # FTSE 100 long-run mean (bootstrap)
    buyback  = spec.default_buyback_yield        # 0.012
    growth   = spec.default_analyst_growth       # 0.06
    payout   = spec.default_payout_ratio         # 0.60
    src_tag  = "seed:UK:bootstrap"

    seeded = 0
    skipped: list[tuple[int, str]] = []

    print(f"\n  Seeding UK {start_year}–{end_year} (DDM, "
          f"div_y={div_y:.2%}, buyback={buyback:.2%}, growth={growth:.2%}) ...")

    for yr in range(start_year, end_year + 1):
        dt = f"{yr}-12-31"
        if yr not in ftse:
            skipped.append((yr, "no ^FTSE Dec close"))
            continue
        if yr not in gilt:
            skipped.append((yr, "no Gilt Dec value"))
            continue

        index_level = ftse[yr]
        rfr_rate = gilt[yr]
        total_yield = div_y + buyback

        upsert_inputs(
            dt=dt,
            index_level=index_level,
            div_yield=div_y,
            buyback_yield=buyback,
            growth=growth,
            rfr_rate=rfr_rate,
            source=src_tag,
            payout_ratio=payout,
            market="UK",
        )

        try:
            result = compute_erp(
                dt=dt,
                index_level=index_level,
                total_yield=total_yield,
                growth_high=growth,
                rfr_rate=rfr_rate,
                method="ddm",
            )
            upsert_computation(
                dt=dt,
                r=result.implied_r,
                erp=result.implied_erp,
                pv1=result.pv_stage1,
                tv=result.terminal_value,
                pv_tv=result.pv_terminal,
                iterations=result.solver_iterations,
                method_solver=result.solver_method,
                method_model="ddm",
                annual_growth_rates=result.annual_growth_rates,
                cash_flows=result.cash_flows,
                market="UK",
            )
            seeded += 1
            if verbose:
                print(f"    {yr}: FTSE={index_level:>8.2f}  "
                      f"Gilt={rfr_rate:>6.2%}  ERP={result.implied_erp:>6.2%}  "
                      f"r={result.implied_r:>6.2%}")
        except Exception as e:
            skipped.append((yr, f"solver: {e}"))

    print(f"\n  Done. Seeded: {seeded}  Skipped: {len(skipped)}")
    if skipped and verbose:
        for yr, why in skipped:
            print(f"    skipped {yr}: {why}")
    return seeded


# ─────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Seed DB with historical ERP data")
    parser.add_argument("--market", default="US", choices=["US", "UK"],
                        help="Market to seed (default: US)")
    parser.add_argument("--file", help="(US only) Path to local histimpl.xls")
    parser.add_argument("--start", type=int, default=None,
                        help="First year to seed (default: 1961 US, 1990 UK)")
    parser.add_argument("--end", type=int, default=None,
                        help="(UK only) Last year to seed (default: last calendar year)")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-row output")
    args = parser.parse_args()

    if args.market == "US":
        if args.file:
            xls_path = Path(args.file)
        else:
            xls_path = LOCAL_CACHE
            if not xls_path.exists():
                download_xls(xls_path)
        seed_us(xls_path, start_year=args.start or 1961, verbose=not args.quiet)
    elif args.market == "UK":
        seed_uk(start_year=args.start or 1990, end_year=args.end,
                verbose=not args.quiet)


if __name__ == "__main__":
    main()
