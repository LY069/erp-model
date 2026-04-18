"""
One-time historical seeder: loads Damodaran's published histimpl.xls into the DB.
Downloads the file automatically from NYU Stern if not found locally.

Usage:
  python seed_historical.py                         # downloads and seeds
  python seed_historical.py --file path/to/file.xls # use a local copy
"""
import argparse
import sys
import urllib.request
from pathlib import Path

import pandas as pd

# Make sure local modules resolve
sys.path.insert(0, str(Path(__file__).parent))

from database import init_db, upsert_inputs, upsert_computation
from erp_calculator import compute_erp

DAMODARAN_URL = "https://pages.stern.nyu.edu/~adamodar/pc/datasets/histimpl.xls"
LOCAL_CACHE   = Path(__file__).parent / "histimpl_cache.xls"


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


def seed(xls_path: Path, start_year: int = 1961, verbose: bool = True):
    """Load historical data into the ERP database."""
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

        # Store inputs
        upsert_inputs(
            dt=dt,
            sp500=sp500,
            div_yield=div_y,
            buyback_yield=max(0.0, buyback_yield),
            growth=growth,
            tbond=tbond,
            source="damodaran_histimpl",
        )

        # Compute & store ERP (DDM method for historical data — no EPS available)
        try:
            result = compute_erp(
                dt=dt,
                sp500_level=sp500,
                total_yield=total_yield,
                growth_high=growth,
                tbond_rate=tbond,
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


def main():
    parser = argparse.ArgumentParser(description="Seed DB with Damodaran historical ERP data")
    parser.add_argument("--file", help="Path to local histimpl.xls (downloads if not given)")
    parser.add_argument("--start", type=int, default=1961,
                        help="First year to seed (default: 1961)")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-row output")
    args = parser.parse_args()

    if args.file:
        xls_path = Path(args.file)
    else:
        xls_path = LOCAL_CACHE
        if not xls_path.exists():
            download_xls(xls_path)

    seed(xls_path, start_year=args.start, verbose=not args.quiet)


if __name__ == "__main__":
    main()
