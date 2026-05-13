#!/usr/bin/env python3
"""
scripts/reconcile_damodaran.py — Phase 6 Track A cross-time reconciliation.

Validates our solver against Damodaran's published annual implied-ERP
series in histimpl.xls (https://pages.stern.nyu.edu/~adamodar/pc/datasets/).

For each of the most recent N annual rows, plugs his published inputs
into our DDM solver and compares to his published Implied ERP. Reports
a per-year side-by-side, the cross-time median delta, and a verdict
classifying any systematic gap. Also cross-checks the hardcoded Jan
2026 case in erp_calculator.validate_against_damodaran against the
histimpl.xls latest row.

Run from repo root:
    python scripts/reconcile_damodaran.py              # last 10 years
    python scripts/reconcile_damodaran.py --years 25   # last 25 years
    python scripts/reconcile_damodaran.py --refresh    # force re-download
"""
from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path
from statistics import median

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from erp_calculator import (                          # noqa: E402
    compute_erp_ddm,
    compute_erp_fcfe,
)
from seed_historical import DAMODARAN_URL, LOCAL_CACHE  # noqa: E402

# Hardcoded Jan 2026 inputs as they appear in erp_calculator.validate_against_damodaran.
# Track A asks: are these consistent with histimpl.xls's latest row?
JAN26_HARDCODE = {
    "S&P":         5881.63,
    "EPS":         271.52,
    "payout":      0.7785,
    "yr1_growth":  0.1559,
    "yr2_growth":  0.1448,
    "tbond":       0.0418,
    "expected_erp_in_code": 0.0423,
}


def ensure_xls(refresh: bool = False) -> Path:
    """Return path to histimpl_cache.xls. Download from DAMODARAN_URL if missing."""
    if LOCAL_CACHE.exists() and not refresh:
        return LOCAL_CACHE
    print(f"  Downloading {DAMODARAN_URL} → {LOCAL_CACHE.name} ...")
    urllib.request.urlretrieve(DAMODARAN_URL, LOCAL_CACHE)
    return LOCAL_CACHE


def load_published_series(xls_path: Path) -> pd.DataFrame:
    """Parse histimpl.xls into a DataFrame with both inputs and Damodaran's
    published Implied ERP. Extends seed_historical.load_damodaran_df with
    the implied-ERP output column.

    If the Implied ERP column is missing or differently named, prints
    the full header row and exits — the parser needs human attention,
    not a silent NaN.
    """
    xl = pd.ExcelFile(str(xls_path), engine="xlrd")
    raw = xl.parse(xl.sheet_names[0], header=None)

    headers = [str(h).strip() if h is not None else "" for h in raw.iloc[6].tolist()]
    data = raw.iloc[7:].copy()
    data.columns = headers
    data = data[pd.to_numeric(data["Year"], errors="coerce").notna()].copy()
    data["Year"] = data["Year"].astype(int)

    erp_col_candidates = [
        "Implied ERP (FCFE)",
        "Implied Premium (FCFE)",
        "Implied ERP",
        "Implied Premium",
        "Implied Equity Risk Premium",
    ]
    erp_col = next((c for c in erp_col_candidates if c in data.columns), None)
    if erp_col is None:
        print("Could not find a published Implied-ERP column. Available headers:")
        for h in headers:
            if h:
                print(f"  - {h!r}")
        raise SystemExit(
            "Extend load_published_series with the correct column name "
            "(open histimpl_cache.xls in Excel to find the right header)."
        )
    data = data.rename(columns={erp_col: "Implied ERP"})
    return data


def reproduce_row(row: pd.Series) -> dict:
    """Run our solver against one annual row's inputs using DDM.

    histimpl rows are historically dividend-and-buyback oriented;
    seed_historical.py uses compute_erp method='ddm' on the same data.
    """
    yr        = int(row["Year"])
    sp        = float(row["S&P 500"])
    div_y     = float(row["Dividend Yield"])
    tbond     = float(row["T.Bond Rate"])
    div_buy   = row.get("Dividends + Buybacks")
    growth_a  = row.get("Analyst Growth Estimate")
    growth_s  = row.get("Smoothed Growth")

    growth = None
    if pd.notna(growth_a) and float(growth_a) > 0:
        growth = float(growth_a)
    elif pd.notna(growth_s) and float(growth_s) > 0:
        growth = float(growth_s)

    if growth is None:
        return {"year": yr, "ours_ddm_erp": None, "skip_reason": "no growth"}

    if pd.notna(div_buy) and float(div_buy) > 0:
        total_yield = float(div_buy) / sp
    else:
        total_yield = div_y

    ddm = compute_erp_ddm(
        dt=f"{yr}-12-31",
        index_level=sp,
        total_yield=total_yield,
        growth_high=growth,
        rfr_rate=tbond,
        ramped=True,
    )
    return {
        "year": yr,
        "ours_ddm_erp": ddm.implied_erp,
        "his_erp": float(row["Implied ERP"]) if pd.notna(row["Implied ERP"]) else None,
    }


def print_cross_time_table(rows: list[dict]) -> dict:
    """Print a year-by-year ours-vs-his table. Returns summary stats."""
    print()
    print("─" * 72)
    print(f"  {'Year':<8}{'Damodaran':>14}{'Ours (DDM)':>14}{'Δ (bp)':>14}{'note':>14}")
    print("─" * 72)
    deltas_bp: list[float] = []
    for r in rows:
        if r.get("skip_reason"):
            print(f"  {r['year']:<8}{'—':>14}{'—':>14}{'—':>14}{r['skip_reason']:>14}")
            continue
        h = r["his_erp"]
        o = r["ours_ddm_erp"]
        if h is None or o is None:
            print(f"  {r['year']:<8}{(h or 0):>14.4%}{(o or 0):>14.4%}{'—':>14}{'(NaN)':>14}")
            continue
        delta_bp = (o - h) * 1e4
        deltas_bp.append(delta_bp)
        print(f"  {r['year']:<8}{h:>14.4%}{o:>14.4%}{delta_bp:>14,.1f}{'':>14}")
    print("─" * 72)

    if not deltas_bp:
        return {"n": 0}

    med = median(deltas_bp)
    avg_abs = sum(abs(d) for d in deltas_bp) / len(deltas_bp)
    max_abs = max(abs(d) for d in deltas_bp)
    same_sign = all(d > 0 for d in deltas_bp) or all(d < 0 for d in deltas_bp)
    return {
        "n": len(deltas_bp),
        "median_bp": med,
        "mean_abs_bp": avg_abs,
        "max_abs_bp": max_abs,
        "same_sign": same_sign,
    }


def classify(stats: dict, jan26_check: dict) -> str:
    """Classify the gap based on cross-time stats + Jan 2026 input check."""
    if stats.get("n", 0) == 0:
        return "no_data — parser found no usable rows; investigate"

    med = abs(stats["median_bp"])
    max_ = stats["max_abs_bp"]
    same = stats["same_sign"]

    if max_ > 100 and not same:
        return "parser_misalignment — large random deltas; re-check column mapping"
    if med < 10 and max_ < 50:
        verdict = (
            "methodology_consistent — our solver matches Damodaran within "
            "~10bp median; any gap is input precision / rounding"
        )
    elif same and med > 20:
        sign = "+" if stats["median_bp"] > 0 else "-"
        verdict = (
            f"methodology_systematic — consistent {sign}{med:.0f}bp bias "
            "across years; lever likely DDM-with-buybacks vs "
            "FCFE-with-payout-ramp"
        )
    else:
        verdict = "mixed — moderate per-year deltas without a clean systematic pattern"

    if jan26_check.get("input_mismatch"):
        verdict += "; ALSO: validate_against_damodaran hardcoded inputs differ from histimpl latest row"
    return verdict


def check_jan26_consistency(df: pd.DataFrame) -> dict:
    """Compare the hardcoded Jan 2026 inputs in validate_against_damodaran
    to histimpl.xls's most recent row."""
    latest = df.iloc[-1]
    yr = int(latest["Year"])
    h_sp     = float(latest["S&P 500"])
    h_tbond  = float(latest["T.Bond Rate"])
    h_erp    = float(latest["Implied ERP"]) if pd.notna(latest["Implied ERP"]) else None

    out = {
        "latest_year": yr,
        "histimpl_sp": h_sp,
        "histimpl_tbond": h_tbond,
        "histimpl_erp": h_erp,
        "hardcoded_sp": JAN26_HARDCODE["S&P"],
        "hardcoded_tbond": JAN26_HARDCODE["tbond"],
        "hardcoded_expected_erp": JAN26_HARDCODE["expected_erp_in_code"],
    }

    sp_match    = abs(h_sp - JAN26_HARDCODE["S&P"])     < 5.0
    tbond_match = abs(h_tbond - JAN26_HARDCODE["tbond"]) < 0.001
    erp_match   = h_erp is not None and abs(h_erp - JAN26_HARDCODE["expected_erp_in_code"]) < 0.001
    out["input_mismatch"] = not (sp_match and tbond_match)
    out["expected_erp_mismatch"] = not erp_match

    fcfe = compute_erp_fcfe(
        dt="2026-01-01",
        index_level=JAN26_HARDCODE["S&P"],
        trailing_eps=JAN26_HARDCODE["EPS"],
        analyst_growth=0.1050,
        rfr_rate=JAN26_HARDCODE["tbond"],
        payout_ratio=JAN26_HARDCODE["payout"],
        year1_growth=JAN26_HARDCODE["yr1_growth"],
        year2_growth=JAN26_HARDCODE["yr2_growth"],
    )
    out["ours_fcfe_jan26"] = fcfe.implied_erp
    return out


def print_jan26_check(c: dict) -> None:
    print()
    print("─" * 72)
    print(f"  Jan 2026 hardcode (validate_against_damodaran) vs histimpl {c['latest_year']} row")
    print("─" * 72)
    sp_tag    = "match" if not c["input_mismatch"] else "DIFFER"
    erp_tag   = "match" if not c["expected_erp_mismatch"] else "DIFFER"
    print(f"  S&P 500       hardcoded {c['hardcoded_sp']:.2f}    histimpl {c['histimpl_sp']:.2f}    {sp_tag}")
    print(f"  T-bond        hardcoded {c['hardcoded_tbond']:.4%}    histimpl {c['histimpl_tbond']:.4%}")
    h_erp_str = f"{c['histimpl_erp']:.4%}" if c['histimpl_erp'] is not None else "(NaN)"
    print(f"  Expected ERP  hardcoded {c['hardcoded_expected_erp']:.4%}    histimpl {h_erp_str}    {erp_tag}")
    print(f"  Our FCFE solver against hardcoded inputs: {c['ours_fcfe_jan26']:.4%}")
    print("─" * 72)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--years", type=int, default=10,
                    help="How many of the most recent annual rows to print (default 10)")
    ap.add_argument("--refresh", action="store_true",
                    help="Force re-download of histimpl.xls")
    args = ap.parse_args()

    print("=" * 72)
    print("  Phase 6 Track A — Solver vs Damodaran reconciliation (cross-time)")
    print("=" * 72)

    print("\n→ Ensuring histimpl_cache.xls ...")
    xls = ensure_xls(refresh=args.refresh)
    print(f"  using: {xls}")

    print("\n→ Parsing published series ...")
    df = load_published_series(xls)
    print(f"  rows: {len(df)} years {df['Year'].min()}–{df['Year'].max()}")

    print(f"\n→ Reproducing the last {args.years} years with our DDM solver ...")
    recent = df.tail(args.years).to_dict("records")
    results = [reproduce_row(pd.Series(r)) for r in recent]
    stats = print_cross_time_table(results)

    print("\n→ Jan 2026 hardcode cross-check ...")
    jan26 = check_jan26_consistency(df)
    print_jan26_check(jan26)

    verdict = classify(stats, jan26)
    print()
    print("═" * 72)
    print(f"  VERDICT: {verdict}")
    print("═" * 72)
    print()
    print("Summary stats (cross-time DDM):")
    if stats.get("n"):
        print(f"  n={stats['n']}  median_Δ={stats['median_bp']:+.1f}bp  "
              f"mean|Δ|={stats['mean_abs_bp']:.1f}bp  max|Δ|={stats['max_abs_bp']:.1f}bp  "
              f"same_sign={stats['same_sign']}")
    print()
    print("Use this verdict to fill in:")
    print("  - erp_calculator.validate_against_damodaran() print block")
    print("  - .github/workflows/smoke.yml golden-guard comment")
    print("  - SHARED_NOTES.md Phase 6 Track A Status Log entry")


if __name__ == "__main__":
    main()
