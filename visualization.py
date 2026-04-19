"""
Visualization and reporting module for the ERP model.
Generates matplotlib charts and text reports from the database.
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

from config import OUTPUT_DIR
from database import get_history, get_latest


def plot_erp_history(df: pd.DataFrame | None = None,
                     output_path: Path | None = None) -> Path:
    """
    Plot implied ERP over time with mean ± 1σ bands.
    Returns the path to the saved PNG.
    """
    if df is None:
        df = get_history()
    if df.empty:
        print("No data to plot.")
        return None

    out = output_path or OUTPUT_DIR / "erp_history.png"

    fig, ax = plt.subplots(figsize=(14, 6))

    # Main line
    ax.plot(df["date"], df["implied_erp"] * 100, color="#1a5276",
            linewidth=2, label="Implied ERP")

    # Mean and bands
    mean_erp = df["implied_erp"].mean() * 100
    std_erp = df["implied_erp"].std() * 100
    ax.axhline(mean_erp, color="#e74c3c", linestyle="--", linewidth=1,
               label=f"Mean: {mean_erp:.2f}%")
    ax.fill_between(df["date"], mean_erp - std_erp, mean_erp + std_erp,
                    alpha=0.15, color="#e74c3c", label=f"±1σ ({std_erp:.2f}%)")

    # Current value annotation
    if len(df) > 0:
        latest = df.iloc[-1]
        ax.annotate(
            f'{latest["implied_erp"]*100:.2f}%',
            xy=(latest["date"], latest["implied_erp"] * 100),
            xytext=(15, 15), textcoords="offset points",
            fontsize=12, fontweight="bold", color="#1a5276",
            arrowprops=dict(arrowstyle="->", color="#1a5276"),
        )

    ax.set_title("Forward-Looking Implied Equity Risk Premium (Damodaran Method)",
                 fontsize=14, fontweight="bold", pad=15)
    ax.set_ylabel("Implied ERP (%)", fontsize=12)
    ax.set_xlabel("")
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.1f%%"))
    ax.legend(loc="upper left", fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    fig.tight_layout()
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")
    return out


def plot_inputs_dashboard(df: pd.DataFrame | None = None,
                           output_path: Path | None = None) -> Path:
    """
    4-panel dashboard: S&P level, total yield, growth, T-bond rate.
    """
    if df is None:
        df = get_history()
    if df.empty:
        print("No data to plot.")
        return None

    out = output_path or OUTPUT_DIR / "inputs_dashboard.png"

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    panels = [
        ("index_level",       "Index Level",             "#2c3e50", False),
        ("total_yield",       "Total Cash Yield (Div + Buyback)", "#27ae60", True),
        ("analyst_5yr_growth","Analyst 5-Year Growth",   "#8e44ad", True),
        ("rfr_rate",          "10-Year Risk-Free Rate",  "#e67e22", True),
    ]

    for ax, (col, title, color, as_pct) in zip(axes.flat, panels):
        if col not in df.columns:
            ax.text(0.5, 0.5, f"No data: {col}", ha="center", transform=ax.transAxes)
            continue
        vals = df[col] * 100 if as_pct else df[col]
        ax.plot(df["date"], vals, color=color, linewidth=1.5)
        ax.set_title(title, fontsize=11, fontweight="bold")
        if as_pct:
            ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.1f%%"))
        else:
            ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
        ax.grid(True, alpha=0.3)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    fig.suptitle("ERP Model — Input Data History", fontsize=14, fontweight="bold", y=1.01)
    fig.tight_layout()
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")
    return out


def print_report(market: str = "US"):
    """Print a formatted text report of the current ERP and history."""
    latest = get_latest(market=market)
    df = get_history(market=market)

    if latest is None:
        print("No computations in database. Run: python main.py --update")
        return

    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║     FORWARD-LOOKING EQUITY RISK PREMIUM — CURRENT REPORT   ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()
    print(f"  Date:                  {latest['date']}")
    print(f"  Market:                {latest.get('market', 'US')}")
    print(f"  Index Level:           {latest['index_level']:>10,.2f}")
    print(f"  Dividend Yield:        {latest['dividend_yield']:>10.2%}")
    print(f"  Buyback Yield:         {latest['buyback_yield']:>10.2%}")
    print(f"  Total Cash Yield:      {latest['total_yield']:>10.2%}")
    print(f"  Analyst Growth (5yr):  {latest['analyst_5yr_growth']:>10.2%}")
    print(f"  Risk-Free Rate (10yr): {latest['rfr_rate']:>10.2%}")
    print()
    print(f"  ┌─────────────────────────────────────────────┐")
    print(f"  │  Implied Cost of Equity: {latest['implied_cost_of_equity']:>8.2%}           │")
    print(f"  │  Implied ERP:            {latest['implied_erp']:>8.2%}           │")
    print(f"  │  Solver:                 {latest['solver_method']:<20s}   │")
    print(f"  └─────────────────────────────────────────────┘")

    if len(df) > 1:
        print()
        print("  Historical Context:")
        print(f"    Records in DB:   {len(df)}")
        print(f"    Mean ERP:        {df['implied_erp'].mean():.2%}")
        print(f"    Std Dev:         {df['implied_erp'].std():.2%}")
        print(f"    Min ERP:         {df['implied_erp'].min():.2%}"
              f"  ({df.loc[df['implied_erp'].idxmin(), 'date'].strftime('%Y-%m-%d') if hasattr(df.loc[df['implied_erp'].idxmin(), 'date'], 'strftime') else df.loc[df['implied_erp'].idxmin(), 'date']})")
        print(f"    Max ERP:         {df['implied_erp'].max():.2%}"
              f"  ({df.loc[df['implied_erp'].idxmax(), 'date'].strftime('%Y-%m-%d') if hasattr(df.loc[df['implied_erp'].idxmax(), 'date'], 'strftime') else df.loc[df['implied_erp'].idxmax(), 'date']})")
        pctile = (df["implied_erp"] < latest["implied_erp"]).mean()
        print(f"    Current Pctile:  {pctile:.0%}")
    print()


def export_csv(df: pd.DataFrame | None = None,
               output_path: Path | None = None) -> Path:
    """Export history to CSV for Excel analysis."""
    if df is None:
        df = get_history()
    out = output_path or OUTPUT_DIR / "erp_history.csv"
    df.to_csv(out, index=False)
    print(f"Exported: {out}")
    return out
