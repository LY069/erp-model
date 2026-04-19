"""
Forward-Looking Equity Risk Premium Model
Based on Damodaran (NYU Stern) 2-Stage Augmented DDM Methodology

Usage:
  python main.py --update                        # Fetch latest data & compute ERP (FCFE)
  python main.py --update --method ddm           # Use DDM method instead
  python main.py --update --buyback 0.025        # Override buyback yield
  python main.py --update --growth 0.08          # Override analyst growth
  python main.py --update --eps 271.52           # Override trailing EPS (FCFE)
  python main.py --update --payout 0.7785        # Override payout ratio
  python main.py --report                        # Print current ERP & history
  python main.py --plot                          # Generate charts to output/
  python main.py --export                        # Export history to CSV
  python main.py --validate                      # Validate solver vs Damodaran Jan 2026
  python main.py --history                       # Show last 20 database entries
  python main.py --forecast                      # Print forward ERP forecast
  python main.py --breakeven                     # Print breakeven EPS growth analysis
  python main.py --update --report --plot        # Chain: update then report and plot
"""

import argparse
import sys
import traceback
from datetime import date

from config import DB_PATH, OUTPUT_DIR, DEFAULT_PAYOUT_RATIO
from database import (
    init_db, upsert_inputs, upsert_computation, upsert_forecast, upsert_breakeven,
    get_latest, get_history, get_log
)
from data_fetcher import fetch_all_inputs
from erp_calculator import (
    compute_erp, compute_erp_fcfe, compute_erp_ddm,
    forecast_erp, compute_breakeven_growth, validate_against_damodaran
)
from visualization import plot_erp_history, plot_inputs_dashboard, print_report, export_csv


def cmd_update(args):
    """Fetch latest market data, compute ERP, store in database."""
    method = getattr(args, 'method', 'fcfe') or 'fcfe'
    market = getattr(args, 'market', 'US') or 'US'
    print("─" * 60)
    print(f"  Fetching market data ({method.upper()} method, market={market})...")
    print("─" * 60)

    buyback_override = float(args.buyback) if args.buyback else None
    growth_override  = float(args.growth)  if args.growth  else None
    eps_override     = float(args.eps)     if args.eps     else None
    payout_override  = float(args.payout)  if args.payout  else DEFAULT_PAYOUT_RATIO

    try:
        inputs = fetch_all_inputs(
            as_of=args.as_of,
            buyback_override=buyback_override,
            growth_override=growth_override,
            method=method,
            market=market,
        )
    except Exception as e:
        print(f"\n[ERROR] Data fetch failed: {e}")
        print("  Check your internet connection and FRED_API_KEY (if set).")
        sys.exit(1)

    if eps_override is not None:
        inputs["trailing_eps"] = eps_override

    print(f"  Date:             {inputs['date']}")
    print(f"  Index Level:      {inputs['index_level']:>10,.2f}")
    print(f"  Dividend Yield:   {inputs['dividend_yield']:>10.2%}")
    print(f"  Buyback Yield:    {inputs['buyback_yield']:>10.2%}  "
          f"{'(override)' if buyback_override else '(default)'}")
    print(f"  Total Yield:      {inputs['total_yield']:>10.2%}")
    if method == "fcfe" and inputs.get("trailing_eps"):
        print(f"  Trailing EPS:     {inputs['trailing_eps']:>10.2f}  "
              f"{'(override)' if eps_override else '(fetched/estimate)'}")
        print(f"  Payout Ratio:     {payout_override:>10.2%}")
    print(f"  Analyst Growth:   {inputs['analyst_5yr_growth']:>10.2%}  "
          f"{'(override)' if growth_override else '(fetched/default)'}")
    if inputs.get("year1_growth"):
        print(f"    → Year 1:       {inputs['year1_growth']:>10.2%}")
    if inputs.get("year2_growth"):
        print(f"    → Year 2:       {inputs['year2_growth']:>10.2%}")
    print(f"  Risk-Free Rate:   {inputs['rfr_rate']:>10.2%}")

    upsert_inputs(
        dt=inputs["date"],
        index_level=inputs["index_level"],
        div_yield=inputs["dividend_yield"],
        buyback_yield=inputs["buyback_yield"],
        growth=inputs["analyst_5yr_growth"],
        rfr_rate=inputs["rfr_rate"],
        source=method,
        trailing_eps=inputs.get("trailing_eps"),
        payout_ratio=payout_override,
        year1_growth=inputs.get("year1_growth"),
        year2_growth=inputs.get("year2_growth"),
        growth_source=inputs.get("growth_source"),
        market=market,
    )

    print("\n  Computing implied ERP...")
    try:
        if method == "fcfe":
            trailing_eps = inputs.get("trailing_eps")
            if not trailing_eps:
                print("  [WARN] No trailing EPS; falling back to DDM method")
                result = compute_erp_ddm(
                    dt=inputs["date"],
                    index_level=inputs["index_level"],
                    total_yield=inputs["total_yield"],
                    growth_high=inputs["analyst_5yr_growth"],
                    rfr_rate=inputs["rfr_rate"],
                    ramped=True,
                )
            else:
                result = compute_erp_fcfe(
                    dt=inputs["date"],
                    index_level=inputs["index_level"],
                    trailing_eps=trailing_eps,
                    analyst_growth=inputs["analyst_5yr_growth"],
                    rfr_rate=inputs["rfr_rate"],
                    payout_ratio=payout_override,
                    year1_growth=inputs.get("year1_growth"),
                    year2_growth=inputs.get("year2_growth"),
                )
        else:
            result = compute_erp_ddm(
                dt=inputs["date"],
                index_level=inputs["index_level"],
                total_yield=inputs["total_yield"],
                growth_high=inputs["analyst_5yr_growth"],
                rfr_rate=inputs["rfr_rate"],
                ramped=True,
            )
    except Exception as e:
        print(f"\n[ERROR] Solver failed: {e}")
        traceback.print_exc()
        sys.exit(1)

    upsert_computation(
        dt=result.date,
        r=result.implied_r,
        erp=result.implied_erp,
        pv1=result.pv_stage1,
        tv=result.terminal_value,
        pv_tv=result.pv_terminal,
        iterations=result.solver_iterations,
        method_solver=result.solver_method,
        method_model=result.method,
        annual_growth_rates=result.annual_growth_rates,
        cash_flows=result.cash_flows,
        market=market,
    )

    print()
    print(result.summary())
    print(f"\n  ✓ Results saved to: {DB_PATH.name}")


def cmd_report(args):
    """Print formatted report from the database."""
    market = getattr(args, 'market', 'US') or 'US'
    print_report(market=market)


def cmd_plot(_args):
    """Generate PNG charts to the output/ directory."""
    df = get_history()
    if df.empty:
        print("No data in database. Run: python main.py --update")
        return
    print(f"Generating charts → {OUTPUT_DIR}/")
    p1 = plot_erp_history(df)
    p2 = plot_inputs_dashboard(df)
    print("\nCharts saved:")
    if p1:
        print(f"  {p1.name}")
    if p2:
        print(f"  {p2.name}")


def cmd_export(_args):
    """Export history to CSV."""
    df = get_history()
    if df.empty:
        print("No data to export.")
        return
    path = export_csv(df)
    print(f"Exported {len(df)} rows → {path}")


def cmd_history(args):
    """Print the last 20 database entries."""
    market = getattr(args, 'market', 'US') or 'US'
    df = get_history(market=market)
    if df.empty:
        print("No data in database. Run: python main.py --update")
        return
    recent = df.tail(20).copy()
    print(f"\n{'Date':<12} {'Index':>8} {'Method':>6} {'Growth':>7} "
          f"{'Rfr':>6} {'Impl.r':>7} {'ERP':>7}")
    print("─" * 65)
    for _, row in recent.iterrows():
        dt = str(row["date"])[:10]
        m = str(row.get("method", "—"))[:4]
        print(f"{dt:<12} {row['index_level']:>8,.0f} "
              f"{m:>6} "
              f"{row['analyst_5yr_growth']*100:>6.2f}% "
              f"{row['rfr_rate']*100:>5.2f}% "
              f"{row['implied_cost_of_equity']*100:>6.2f}% "
              f"{row['implied_erp']*100:>6.2f}%")
    print()


def cmd_validate(_args):
    """Run solver validation against Damodaran's published examples."""
    validate_against_damodaran()


def cmd_forecast(args):
    """Print forward ERP projections under base/bull/bear scenarios."""
    method = getattr(args, 'method', 'fcfe') or 'fcfe'
    market = getattr(args, 'market', 'US') or 'US'
    row = get_latest(method=method, market=market) or get_latest(market=market)
    if row is None:
        print("No data in database. Run: python main.py --update")
        return

    index_level = row["index_level"]
    eps    = row.get("trailing_eps") or index_level / 21.0
    rfr    = row["rfr_rate"]
    growth = row["analyst_5yr_growth"]
    payout = row.get("payout_ratio", DEFAULT_PAYOUT_RATIO) or DEFAULT_PAYOUT_RATIO

    print(f"\n{'─'*60}")
    print(f"  Forward ERP Forecast (base: {row['date']}, market: {market})")
    print(f"  Index={index_level:,.0f}, EPS={eps:.1f}, Rfr={rfr:.2%}, Growth={growth:.2%}")
    print(f"{'─'*60}")

    scenarios = forecast_erp(
        base_index_level=index_level, base_eps=eps, base_rfr=rfr,
        base_growth=growth, payout_ratio=payout
    )

    base_date = date.today().isoformat()
    for sname, pts in scenarios.items():
        upsert_forecast(base_date, sname, pts, market=market)

    for sname, pts in scenarios.items():
        print(f"\n  {sname.upper()} Scenario:")
        print(f"  {'Year':>4}  {'Date':<8}  {'Index':>7}  {'EPS':>6}  {'Rfr':>7}  {'Growth':>7}  {'ERP':>7}")
        print(f"  {'─'*60}")
        for pt in pts:
            print(f"  +{pt['year']:>3}  {pt['date'][:7]}  "
                  f"{pt['index']:>7,.0f}  {pt['eps']:>6.1f}  "
                  f"{pt['rfr_rate']:>6.2%}  {pt['analyst_growth']:>6.2%}  "
                  f"{pt['implied_erp']:>6.2%}")


def cmd_breakeven(args):
    """Compute breakeven earnings growth for normal ERP."""
    method = getattr(args, 'method', 'fcfe') or 'fcfe'
    market = getattr(args, 'market', 'US') or 'US'
    row = get_latest(method=method, market=market) or get_latest(market=market)
    if row is None:
        print("No data in database. Run: python main.py --update")
        return

    index_level = row["index_level"]
    eps    = row.get("trailing_eps") or index_level / 21.0
    rfr    = row["rfr_rate"]
    payout = row.get("payout_ratio", DEFAULT_PAYOUT_RATIO) or DEFAULT_PAYOUT_RATIO

    print(f"\n{'─'*60}")
    print(f"  Breakeven EPS Growth Analysis ({row['date']}, market: {market})")
    print(f"  Index={index_level:,.0f}, EPS={eps:.1f}, Rfr={rfr:.2%}")
    print(f"{'─'*60}\n")

    for erp_method in ["longrun", "decade"]:
        result = compute_breakeven_growth(
            index_level=index_level, trailing_eps=eps,
            rfr_rate=rfr, payout_ratio=payout,
            normal_erp_method=erp_method,
        )
        label = "Long-run (1960–present)" if erp_method == "longrun" else "Last decade (2015–2025)"
        print(f"  Normal ERP [{label}]: {result['normal_erp']:.2%}")
        print(f"  Breakeven growth rate:         {result['breakeven_growth']:.2%} / year")
        print(f"  {result['interpretation']}")
        print()

        upsert_breakeven(
            dt=date.today().isoformat(),
            index_level=index_level, eps=eps, rfr_rate=rfr,
            breakeven_growth=result["breakeven_growth"],
            normal_erp=result["normal_erp"],
            normal_erp_method=erp_method,
            interpretation=result.get("interpretation", ""),
            market=market,
        )


def cmd_log(_args):
    """Print recent audit log entries."""
    df = get_log(50)
    if df.empty:
        print("Audit log is empty.")
        return
    print(f"\n{'Timestamp':<20} {'Date':<12} {'Step':<10} {'Message'}")
    print("─" * 80)
    import datetime
    for _, row in df.iterrows():
        ts = datetime.datetime.fromtimestamp(row["created_at"]).strftime("%Y-%m-%d %H:%M:%S")
        print(f"{ts:<20} {str(row['date']):<12} {row['step']:<10} {row['message']}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Forward-Looking ERP Model (Damodaran Methodology)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Commands
    parser.add_argument("--update",    action="store_true", help="Fetch latest data and compute ERP")
    parser.add_argument("--report",    action="store_true", help="Print current ERP and historical summary")
    parser.add_argument("--plot",      action="store_true", help="Generate PNG charts to output/")
    parser.add_argument("--export",    action="store_true", help="Export history to CSV")
    parser.add_argument("--history",   action="store_true", help="Print last 20 database records")
    parser.add_argument("--validate",  action="store_true", help="Validate solver vs Damodaran examples")
    parser.add_argument("--log",       action="store_true", help="Show recent audit log")
    parser.add_argument("--forecast",  action="store_true", help="Print forward ERP forecast (5yr)")
    parser.add_argument("--breakeven", action="store_true", help="Compute breakeven EPS growth for normal ERP")

    # Update options
    parser.add_argument("--market",  metavar="CODE",       default="US",
                        help="Market code (e.g. US, UK). Default: US")
    parser.add_argument("--method",  metavar="STR",       default="fcfe",
                        help="Computation method: 'fcfe' (default) or 'ddm'")
    parser.add_argument("--as-of",  metavar="YYYY-MM-DD",
                        help="Use market data for a specific date (backfill)")
    parser.add_argument("--buyback", metavar="FLOAT",
                        help="Override buyback yield (e.g. 0.025 for 2.5%%)")
    parser.add_argument("--growth",  metavar="FLOAT",
                        help="Override analyst 5yr growth (e.g. 0.08 for 8%%)")
    parser.add_argument("--eps",     metavar="FLOAT",
                        help="Override trailing EPS (e.g. 271.52) — FCFE method only")
    parser.add_argument("--payout",  metavar="FLOAT",
                        help="Override payout ratio (e.g. 0.7785) — FCFE method only")

    args = parser.parse_args()

    # Always ensure DB is initialized
    init_db()

    # If no command given, show help
    if not any([args.update, args.report, args.plot, args.export,
                args.history, args.validate, args.log, args.forecast, args.breakeven]):
        parser.print_help()
        return

    # Execute commands (can chain: --update --report --plot)
    if args.update:
        cmd_update(args)
    if args.validate:
        cmd_validate(args)
    if args.report:
        cmd_report(args)
    if args.history:
        cmd_history(args)
    if args.plot:
        cmd_plot(args)
    if args.export:
        cmd_export(args)
    if args.forecast:
        cmd_forecast(args)
    if args.breakeven:
        cmd_breakeven(args)
    if args.log:
        cmd_log(args)


if __name__ == "__main__":
    main()
