from __future__ import annotations
"""
Core ERP computation engine.

Implements Damodaran's 2-stage Augmented DDM / FCFE model
as used in his January 2026 S&P 500 ERP calculator.

KEY INSIGHTS from ERPJan26.xlsx:
─────────────────────────────────────────────────────────────
1. RAMPED GROWTH (not flat):
   Year 1-2: analyst consensus estimate (e.g. 15.59%, 14.48%)
   Year 3-5: linear ramp from analyst rate → T-bond rate (terminal)
   This is fundamentally different from a flat 5-year CAGR.

2. EARNINGS × PAYOUT RATIO (not yield × index):
   Base cash flow = Trailing EPS × Payout Ratio (default 78.85%)
   CF_t = Earnings_t × Payout Ratio
   Damodaran uses the payout ratio (dividends / earnings) as the
   sustainable cash return proxy, not raw div+buyback yield.

3. TERMINAL VALUE:
   TV = CF_5 × (1 + g_terminal) / (r - g_terminal)
   where g_terminal = T-bond rate (Damodaran's long-run nominal assumption)

4. SOLVE FOR r:
   S&P_level = Σ CF_t/(1+r)^t + TV/(1+r)^5
   ERP = r - T-bond rate

FORMULA SUMMARY (FCFE/Earnings-based method):
─────────────────────────────────────────────
  base_earnings = trailing_eps_sp500
  base_cf = base_earnings × payout_ratio

  growth_rates[t] = analyst_rate_year1..2, then linearly ramps to tbond_rate

  CF_t = base_cf × Π(1 + g_s) for s=1..t
  TV   = CF_5 × (1 + tbond_rate) / (r - tbond_rate)

  Solve: S&P_level = Σ CF_t/(1+r)^t + TV/(1+r)^5

LEGACY DDM METHOD (for backward compatibility):
───────────────────────────────────────────────
  Uses: base_cf = index_level × (div_yield + buyback_yield)
  With flat growth: CF_t = base_cf × (1+g)^t
  This is simpler but diverges more from Damodaran's published values.
"""

from dataclasses import dataclass, field
from typing import List, Optional
import warnings

import numpy as np
from scipy.optimize import brentq
try:
    from scipy.optimize import newton
    HAS_NEWTON = True
except ImportError:
    HAS_NEWTON = False

from config import (
    PROJECTION_YEARS,
    SOLVER_TOLERANCE,
    SOLVER_MAX_ITER,
    SOLVER_INITIAL_GUESS,
    SOLVER_BRACKET_LOW,
    SOLVER_BRACKET_HIGH,
    DEFAULT_PAYOUT_RATIO,
)


# ──────────────────────────────────────────────────────────────────────
# Data Container
# ──────────────────────────────────────────────────────────────────────

@dataclass
class ERPResult:
    """Container for a single ERP computation."""
    date: str
    implied_r: float               # Solved cost of equity
    implied_erp: float             # r - risk_free_rate
    sp500_level: float
    method: str                    # 'fcfe' or 'ddm'

    # FCFE-method inputs
    trailing_eps: float            # Base earnings (trailing EPS for S&P 500)
    payout_ratio: float            # Cash return ratio (default 78.85%)
    base_cash_flow: float          # = trailing_eps × payout_ratio

    # DDM-method inputs (legacy)
    total_yield: float             # div_yield + buyback_yield
    growth_high: float             # Stage-1 growth (year 1 analyst rate)
    growth_stable: float           # = T-bond rate (terminal/stable growth)
    risk_free_rate: float

    # Per-year growth schedule (5 values, ramped)
    annual_growth_rates: List[float]

    # Cash flows and valuation
    cash_flows: List[float]        # CF_1 .. CF_5
    terminal_value: float          # Undiscounted TV
    pv_stage1: float               # Sum of discounted stage-1 CFs
    pv_terminal: float             # Discounted TV

    solver_iterations: int
    solver_method: str             # 'newton' or 'brentq'

    def summary(self) -> str:
        lines = [
            f"══════════════════════════════════════════════════",
            f"  Implied ERP — {self.date}  [{self.method.upper()} Method]",
            f"══════════════════════════════════════════════════",
            f"  S&P 500 Level:        {self.sp500_level:>10,.2f}",
        ]
        if self.method == "fcfe":
            lines += [
                f"  Trailing EPS:         {self.trailing_eps:>10,.2f}",
                f"  Payout Ratio:         {self.payout_ratio:>10.2%}",
                f"  Base Cash Flow:       {self.base_cash_flow:>10,.2f}",
            ]
        else:
            lines += [
                f"  Total Cash Yield:     {self.total_yield:>10.2%}",
                f"  → Annual Cash Flow:   {self.base_cash_flow:>10,.2f}",
            ]
        lines += [
            f"  Analyst Growth Yr1:   {self.growth_high:>10.2%}",
            f"  Stable Growth (=Rf):  {self.growth_stable:>10.2%}",
            f"  Risk-Free Rate (10Y): {self.risk_free_rate:>10.2%}",
            f"──────────────────────────────────────────────────",
            f"  Year-by-Year Growth Rates (Damodaran Ramp-Down):",
        ]
        for i, g in enumerate(self.annual_growth_rates, 1):
            lines.append(f"    Year {i}: {g:>8.2%}")
        lines += [
            f"──────────────────────────────────────────────────",
            f"  Projected Cash Flows:",
        ]
        for i, cf in enumerate(self.cash_flows, 1):
            lines.append(f"    Year {i}: {cf:>10,.2f}")
        lines += [
            f"  Terminal Value:        {self.terminal_value:>10,.2f}",
            f"──────────────────────────────────────────────────",
            f"  PV of Stage 1 CFs:    {self.pv_stage1:>10,.2f}",
            f"  PV of Terminal Value:  {self.pv_terminal:>10,.2f}",
            f"  Total PV (= Index):   {self.pv_stage1 + self.pv_terminal:>10,.2f}",
            f"──────────────────────────────────────────────────",
            f"  Implied Cost of Eq:   {self.implied_r:>10.2%}",
            f"  Risk-Free Rate:       {self.risk_free_rate:>10.2%}",
            f"  ★ Implied ERP:        {self.implied_erp:>10.2%}",
            f"──────────────────────────────────────────────────",
            f"  Solver: {self.solver_method} ({self.solver_iterations} iterations)",
            f"══════════════════════════════════════════════════",
        ]
        return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────
# Growth Schedule
# ──────────────────────────────────────────────────────────────────────

def build_growth_schedule(
    analyst_growth: float,
    tbond_rate: float,
    n: int = PROJECTION_YEARS,
    analyst_years: int = 2,
) -> List[float]:
    """
    Build Damodaran's year-by-year growth ramp.

    Replicates the 'Expected growth rate' sheet in ERPJan26.xlsx:
      - Years 1-2: analyst consensus (e.g. 15.59%, 14.48%)
      - Years 3-5: linear interpolation from analyst_growth → tbond_rate

    In the spreadsheet, the ramp starts AFTER the analyst-estimate years.
    Since we only have one blended analyst estimate (not 2 separate years),
    we use analyst_growth for years 1-2 and linearly ramp from year 3 to n.

    Parameters:
        analyst_growth: Blended analyst consensus growth (decimal)
        tbond_rate:     10-year T-bond rate (used as terminal growth)
        n:              Number of projection years (default 5)
        analyst_years:  How many years to hold analyst rate before ramping

    Returns:
        List of n growth rates
    """
    rates = []
    ramp_years = n - analyst_years  # Number of years in the ramp-down

    for t in range(1, n + 1):
        if t <= analyst_years:
            rates.append(analyst_growth)
        else:
            # Linear interpolation from analyst_growth (at analyst_years)
            # to tbond_rate (at year n)
            ramp_position = t - analyst_years  # 1, 2, ... ramp_years
            frac = ramp_position / ramp_years  # 0 to 1
            rate = analyst_growth + frac * (tbond_rate - analyst_growth)
            rates.append(rate)

    return rates


def build_growth_schedule_detailed(
    year1_growth: float,
    year2_growth: float,
    tbond_rate: float,
    n: int = PROJECTION_YEARS,
) -> List[float]:
    """
    Build a precise ramp schedule when year-by-year analyst estimates are available.
    Matches Damodaran's ERPJan26.xlsx exactly when provided year1 and year2 estimates.

    Year 1: year1_growth
    Year 2: year2_growth
    Years 3-5: linear ramp from year2_growth to tbond_rate
    """
    rates = [year1_growth, year2_growth]
    ramp_years = n - 2
    for i in range(1, ramp_years + 1):
        frac = i / ramp_years
        rate = year2_growth + frac * (tbond_rate - year2_growth)
        rates.append(rate)
    return rates[:n]


# ──────────────────────────────────────────────────────────────────────
# Cash Flow Projection
# ──────────────────────────────────────────────────────────────────────

def project_cash_flows(
    base_cf: float,
    growth_rates: List[float],
) -> List[float]:
    """
    Project cash flows using Damodaran's compounding approach.

    CF_t = base_cf × (1+g_1) × (1+g_2) × ... × (1+g_t)

    This is NOT simply base_cf × (1+g)^t when growth rates vary per year.
    """
    cash_flows = []
    cumulative_factor = 1.0
    for g in growth_rates:
        cumulative_factor *= (1 + g)
        cash_flows.append(base_cf * cumulative_factor)
    return cash_flows


# ──────────────────────────────────────────────────────────────────────
# Objective Function
# ──────────────────────────────────────────────────────────────────────

def _objective(r: float, index_level: float, cash_flows: List[float],
               g_stable: float) -> float:
    """
    f(r) = PV(cash_flows, TV) - index_level  →  want = 0

    PV = Σ CF_t/(1+r)^t + TV/(1+r)^n
    TV = CF_n × (1+g_stable) / (r - g_stable)
    """
    if r <= g_stable:
        return 1e12  # Blow up — force solver away from invalid region

    n = len(cash_flows)
    pv = 0.0
    for t, cf in enumerate(cash_flows, 1):
        pv += cf / (1 + r) ** t

    cf_n = cash_flows[-1]
    tv = cf_n * (1 + g_stable) / (r - g_stable)
    pv += tv / (1 + r) ** n

    return pv - index_level


def _objective_derivative(r: float, index_level: float, cash_flows: List[float],
                           g_stable: float) -> float:
    """Analytical first derivative d(objective)/dr for Newton's method."""
    if r <= g_stable:
        return -1e12

    n = len(cash_flows)
    dpv = 0.0

    for t, cf in enumerate(cash_flows, 1):
        dpv += -t * cf / (1 + r) ** (t + 1)

    cf_n = cash_flows[-1]
    g = g_stable
    A = cf_n * (1 + g)
    denom = (r - g) ** 2 * (1 + r) ** (n + 1)
    numer = -((1 + r) + n * (r - g))
    dpv += A * numer / denom

    return dpv


# ──────────────────────────────────────────────────────────────────────
# Solver
# ──────────────────────────────────────────────────────────────────────

def _solve_for_r(index_level: float, cash_flows: List[float],
                 g_stable: float) -> tuple[float, int, str]:
    """
    Solve for implied cost of equity r using Newton-Raphson with brentq fallback.

    Returns: (r_solved, iterations, method_name)
    """
    method = "newton"
    iterations = 0

    if HAS_NEWTON:
        try:
            r_solved, result_info = newton(
                _objective,
                x0=SOLVER_INITIAL_GUESS,
                fprime=_objective_derivative,
                args=(index_level, cash_flows, g_stable),
                tol=SOLVER_TOLERANCE,
                maxiter=SOLVER_MAX_ITER,
                full_output=True,
            )
            iterations = result_info.iterations
            if r_solved <= g_stable or r_solved > 0.50 or r_solved < 0.0:
                raise ValueError(f"Newton out of bounds: r={r_solved:.4f}")
            return r_solved, iterations, method
        except (RuntimeError, ValueError):
            pass  # Fall through to brentq

    method = "brentq"
    r_solved, result_info = brentq(
        _objective,
        a=max(g_stable + 0.001, SOLVER_BRACKET_LOW),
        b=SOLVER_BRACKET_HIGH,
        args=(index_level, cash_flows, g_stable),
        xtol=SOLVER_TOLERANCE,
        maxiter=SOLVER_MAX_ITER,
        full_output=True,
    )
    iterations = result_info.iterations
    return r_solved, iterations, method


# ──────────────────────────────────────────────────────────────────────
# Main Computation — FCFE Method (Damodaran-faithful)
# ──────────────────────────────────────────────────────────────────────

def compute_erp_fcfe(
    dt: str,
    sp500_level: float,
    trailing_eps: float,
    analyst_growth: float,
    tbond_rate: float,
    payout_ratio: float = DEFAULT_PAYOUT_RATIO,
    year1_growth: Optional[float] = None,
    year2_growth: Optional[float] = None,
) -> ERPResult:
    """
    Damodaran-faithful FCFE-based ERP computation.

    Matches ERPJan26.xlsx methodology:
      - Cash flows = Earnings × Payout Ratio (not yield × index)
      - Year-by-year growth ramp-down to T-bond rate
      - Terminal growth = T-bond rate

    Parameters:
        dt:             Date string (YYYY-MM-DD)
        sp500_level:    Current S&P 500 index level
        trailing_eps:   S&P 500 trailing twelve-month earnings per unit
        analyst_growth: Blended analyst 5-yr CAGR (decimal, e.g. 0.1050)
        tbond_rate:     10-year T-bond rate (decimal)
        payout_ratio:   Earnings payout ratio (default 78.85%)
        year1_growth:   If available: year 1 analyst estimate (more precise)
        year2_growth:   If available: year 2 analyst estimate (more precise)

    Returns:
        ERPResult with all computation details
    """
    g_stable = tbond_rate  # Damodaran's key assumption

    # Base cash flow
    base_cf = trailing_eps * payout_ratio

    # Build growth schedule
    if year1_growth is not None and year2_growth is not None:
        growth_rates = build_growth_schedule_detailed(
            year1_growth, year2_growth, tbond_rate
        )
    else:
        growth_rates = build_growth_schedule(analyst_growth, tbond_rate)

    # Project cash flows
    cash_flows = project_cash_flows(base_cf, growth_rates)

    # Solve
    r_solved, iterations, solver_method = _solve_for_r(
        sp500_level, cash_flows, g_stable
    )

    # Decompose PV
    pv_stage1 = sum(cf / (1 + r_solved) ** t for t, cf in enumerate(cash_flows, 1))
    tv = cash_flows[-1] * (1 + g_stable) / (r_solved - g_stable)
    pv_tv = tv / (1 + r_solved) ** len(cash_flows)

    return ERPResult(
        date=dt,
        implied_r=r_solved,
        implied_erp=r_solved - tbond_rate,
        sp500_level=sp500_level,
        method="fcfe",
        trailing_eps=trailing_eps,
        payout_ratio=payout_ratio,
        base_cash_flow=base_cf,
        total_yield=base_cf / sp500_level,  # implied yield for display
        growth_high=analyst_growth,
        growth_stable=g_stable,
        risk_free_rate=tbond_rate,
        annual_growth_rates=growth_rates,
        cash_flows=cash_flows,
        terminal_value=tv,
        pv_stage1=pv_stage1,
        pv_terminal=pv_tv,
        solver_iterations=iterations,
        solver_method=solver_method,
    )


# ──────────────────────────────────────────────────────────────────────
# Legacy DDM Method (backward compatible)
# ──────────────────────────────────────────────────────────────────────

def compute_erp_ddm(
    dt: str,
    sp500_level: float,
    total_yield: float,
    growth_high: float,
    tbond_rate: float,
    ramped: bool = True,
) -> ERPResult:
    """
    DDM-based ERP computation using yield × index as base cash flow.

    Parameters:
        dt:          Date string (YYYY-MM-DD)
        sp500_level: Current S&P 500 index level
        total_yield: Dividend yield + buyback yield (decimal)
        growth_high: Analyst consensus 5-year growth (decimal)
        tbond_rate:  10-year T-bond rate (decimal)
        ramped:      If True (default), use ramped growth; if False, flat growth
    """
    g_stable = tbond_rate
    base_cf = sp500_level * total_yield

    if ramped:
        growth_rates = build_growth_schedule(growth_high, tbond_rate)
    else:
        # Legacy flat growth for backward compatibility
        growth_rates = [growth_high] * PROJECTION_YEARS

    cash_flows = project_cash_flows(base_cf, growth_rates)

    r_solved, iterations, solver_method = _solve_for_r(
        sp500_level, cash_flows, g_stable
    )

    pv_stage1 = sum(cf / (1 + r_solved) ** t for t, cf in enumerate(cash_flows, 1))
    tv = cash_flows[-1] * (1 + g_stable) / (r_solved - g_stable)
    pv_tv = tv / (1 + r_solved) ** len(cash_flows)

    return ERPResult(
        date=dt,
        implied_r=r_solved,
        implied_erp=r_solved - tbond_rate,
        sp500_level=sp500_level,
        method="ddm",
        trailing_eps=base_cf / max(0.001, 0.7785),  # approximate EPS
        payout_ratio=0.7785,
        base_cash_flow=base_cf,
        total_yield=total_yield,
        growth_high=growth_high,
        growth_stable=g_stable,
        risk_free_rate=tbond_rate,
        annual_growth_rates=growth_rates,
        cash_flows=cash_flows,
        terminal_value=tv,
        pv_stage1=pv_stage1,
        pv_terminal=pv_tv,
        solver_iterations=iterations,
        solver_method=solver_method,
    )


# ──────────────────────────────────────────────────────────────────────
# Unified Entry Point
# ──────────────────────────────────────────────────────────────────────

def compute_erp(
    dt: str,
    sp500_level: float,
    total_yield: float,
    growth_high: float,
    tbond_rate: float,
    method: str = "ddm",
    trailing_eps: Optional[float] = None,
    payout_ratio: float = DEFAULT_PAYOUT_RATIO,
) -> ERPResult:
    """
    Unified ERP computation entry point.

    Parameters:
        method: 'fcfe' for Damodaran-faithful (requires trailing_eps)
                'ddm'  for dividend-yield-based (legacy, default)
    """
    if method == "fcfe":
        if trailing_eps is None:
            raise ValueError("FCFE method requires trailing_eps parameter")
        return compute_erp_fcfe(
            dt=dt,
            sp500_level=sp500_level,
            trailing_eps=trailing_eps,
            analyst_growth=growth_high,
            tbond_rate=tbond_rate,
            payout_ratio=payout_ratio,
        )
    else:
        return compute_erp_ddm(
            dt=dt,
            sp500_level=sp500_level,
            total_yield=total_yield,
            growth_high=growth_high,
            tbond_rate=tbond_rate,
            ramped=True,
        )


# ──────────────────────────────────────────────────────────────────────
# Forward ERP Forecast
# ──────────────────────────────────────────────────────────────────────

def forecast_erp(
    base_sp500: float,
    base_eps: float,
    base_tbond: float,
    base_growth: float,
    horizon_years: int = 5,
    payout_ratio: float = DEFAULT_PAYOUT_RATIO,
    scenarios: Optional[dict] = None,
) -> dict:
    """
    Project implied ERP forward over a horizon under multiple scenarios.

    Each scenario specifies annual changes to key inputs:
        sp500_drift:   Annual % change in S&P 500 (e.g. 0.07 = +7%/yr)
        eps_growth:    Annual earnings growth (e.g. 0.08 = +8%/yr)
        rate_drift:    Annual change in T-bond rate (e.g. 0.005 = +50bps/yr)
        growth_drift:  Annual change in analyst growth estimate

    Default scenarios:
        base:  sp500=+7%, eps=+8%, rates flat, growth=current
        bull:  sp500=+12%, eps=+12%, rates -25bps, growth +2%
        bear:  sp500=-5%, eps=+3%, rates +50bps, growth -2%

    Returns dict with scenario names as keys and lists of
    (year, date_label, implied_erp) tuples as values.
    """
    from datetime import date, timedelta

    if scenarios is None:
        scenarios = {
            "base": {
                "sp500_drift": 0.07,
                "eps_growth": 0.08,
                "rate_drift": 0.00,
                "growth_drift": 0.00,
            },
            "bull": {
                "sp500_drift": 0.12,
                "eps_growth": 0.12,
                "rate_drift": -0.0025,
                "growth_drift": 0.02,
            },
            "bear": {
                "sp500_drift": -0.05,
                "eps_growth": 0.03,
                "rate_drift": 0.005,
                "growth_drift": -0.02,
            },
        }

    results = {}
    today = date.today()

    for scenario_name, params in scenarios.items():
        sp500_drift = params.get("sp500_drift", 0.07)
        eps_growth = params.get("eps_growth", 0.08)
        rate_drift = params.get("rate_drift", 0.00)
        growth_drift = params.get("growth_drift", 0.00)

        points = []
        sp500 = base_sp500
        eps = base_eps
        tbond = base_tbond
        growth = base_growth

        for yr in range(1, horizon_years + 1):
            # Advance inputs by one year
            sp500 = sp500 * (1 + sp500_drift)
            eps = eps * (1 + eps_growth)
            tbond = max(0.005, tbond + rate_drift)
            growth = max(0.01, min(0.30, growth + growth_drift))

            # Compute ERP at this future state
            try:
                result = compute_erp_fcfe(
                    dt=(today.replace(year=today.year + yr)).isoformat(),
                    sp500_level=sp500,
                    trailing_eps=eps,
                    analyst_growth=growth,
                    tbond_rate=tbond,
                    payout_ratio=payout_ratio,
                )
                forecast_date = (today.replace(year=today.year + yr)).isoformat()
                points.append({
                    "year": yr,
                    "date": forecast_date,
                    "sp500": round(sp500, 2),
                    "eps": round(eps, 2),
                    "tbond_rate": round(tbond, 4),
                    "analyst_growth": round(growth, 4),
                    "implied_erp": round(result.implied_erp, 4),
                    "implied_r": round(result.implied_r, 4),
                })
            except Exception as e:
                warnings.warn(f"Forecast failed for scenario {scenario_name} yr{yr}: {e}")

        results[scenario_name] = points

    return results


# ──────────────────────────────────────────────────────────────────────
# Breakeven Growth Analysis
# ──────────────────────────────────────────────────────────────────────

# Normal ERP definitions (from Damodaran's historical data 1960-2025)
NORMAL_ERP_LONGRUN = 0.0425    # Long-run average implied ERP (1960-present) ~4.25%
NORMAL_ERP_DECADE  = 0.0519    # Last-decade average implied ERP (2015-2025) ~5.19%

def compute_breakeven_growth(
    sp500_level: float,
    trailing_eps: float,
    tbond_rate: float,
    target_erp: Optional[float] = None,
    payout_ratio: float = DEFAULT_PAYOUT_RATIO,
    normal_erp_method: str = "longrun",
) -> dict:
    """
    Solve: what annual earnings growth rate would produce the "normal" ERP?

    This inverts the usual ERP solve — instead of solving for r given growth,
    we solve for the growth rate that makes ERP = normal_erp.

    "Normal" ERP definitions:
        'longrun'  → 4.25% (Damodaran's 1960-present average from histimpl.xls)
        'decade'   → 5.19% (average of last 10 years)
        'custom'   → user-supplied target_erp

    The breakeven growth answers: "What must S&P 500 earnings grow at annually
    over the next 5 years for the market to be fairly valued at its normal risk premium?"

    If current growth > breakeven growth → market is cheap (more growth priced in
    than needed for normal ERP).
    If current growth < breakeven growth → market is expensive (insufficient growth
    to justify current prices at normal risk premium).

    Parameters:
        sp500_level:        Current S&P 500 index level
        trailing_eps:       S&P 500 trailing EPS
        tbond_rate:         10-year T-bond rate
        target_erp:         Custom target ERP (use with normal_erp_method='custom')
        payout_ratio:       Default 78.85%
        normal_erp_method:  'longrun', 'decade', or 'custom'

    Returns:
        dict with breakeven_growth and context metrics
    """
    if normal_erp_method == "longrun":
        normal_erp = NORMAL_ERP_LONGRUN
    elif normal_erp_method == "decade":
        normal_erp = NORMAL_ERP_DECADE
    elif normal_erp_method == "custom" and target_erp is not None:
        normal_erp = target_erp
    else:
        normal_erp = NORMAL_ERP_LONGRUN

    target_r = tbond_rate + normal_erp

    # Objective: given growth rate g, compute ERP and find g such that ERP = normal_erp
    def erp_minus_target(g: float) -> float:
        if g < -0.20 or g > 0.50:
            return 1e6
        try:
            result = compute_erp_fcfe(
                dt="2099-01-01",  # dummy date
                sp500_level=sp500_level,
                trailing_eps=trailing_eps,
                analyst_growth=g,
                tbond_rate=tbond_rate,
                payout_ratio=payout_ratio,
            )
            return result.implied_erp - normal_erp
        except Exception:
            return 1e6

    try:
        breakeven_g = brentq(erp_minus_target, a=-0.10, b=0.40,
                              xtol=1e-6, maxiter=200)
    except ValueError:
        # If brentq fails (no sign change), compute at boundaries to diagnose
        erp_low = erp_minus_target(-0.10) + normal_erp
        erp_high = erp_minus_target(0.40) + normal_erp
        warnings.warn(
            f"Cannot solve breakeven growth. ERP range: [{erp_low:.3f}, {erp_high:.3f}]"
        )
        breakeven_g = float("nan")

    # Also compute current implied ERP for comparison
    try:
        current_result = compute_erp_fcfe(
            dt="2099-01-01",
            sp500_level=sp500_level,
            trailing_eps=trailing_eps,
            analyst_growth=tbond_rate * 2,  # neutral starting guess
            tbond_rate=tbond_rate,
            payout_ratio=payout_ratio,
        )
        implied_erp_at_neutral = current_result.implied_erp
    except Exception:
        implied_erp_at_neutral = float("nan")

    return {
        "breakeven_growth": round(breakeven_g, 4),
        "normal_erp": round(normal_erp, 4),
        "normal_erp_method": normal_erp_method,
        "normal_erp_longrun": NORMAL_ERP_LONGRUN,
        "normal_erp_decade": NORMAL_ERP_DECADE,
        "tbond_rate": tbond_rate,
        "target_implied_r": round(target_r, 4),
        "sp500_level": sp500_level,
        "trailing_eps": trailing_eps,
        "payout_ratio": payout_ratio,
        # Interpretation
        "interpretation": (
            f"The S&P 500 needs earnings to grow at {breakeven_g:.1%}/yr over 5 years "
            f"to earn a {normal_erp:.2%} ERP ({normal_erp_method} average). "
        ) if not np.isnan(breakeven_g) else "Could not solve breakeven growth.",
    }


# ──────────────────────────────────────────────────────────────────────
# Validation
# ──────────────────────────────────────────────────────────────────────

def validate_against_damodaran():
    """
    Reproduce Damodaran's Jan 2026 FCFE calculation from ERPJan26.xlsx.

    Inputs from spreadsheet:
      S&P = 5881.63
      Trailing EPS = 271.52
      Payout ratio = 78.85%
      Year 1 growth = 15.59%  (analyst consensus)
      Year 2 growth = 14.48%  (analyst consensus)
      Years 3-5: linear ramp to T-bond = 4.18%
      T-bond = 4.18%

    Expected: ERP = 4.23%, Implied r = 8.41%
    """
    print("=== Validation: Damodaran ERPJan26.xlsx ===\n")
    print("Parameters:")
    print("  S&P = 5881.63, EPS = 271.52, Payout = 78.85%")
    print("  Yr1 growth = 15.59%, Yr2 = 14.48%")
    print("  T-bond = 4.18%")
    print()

    result = compute_erp_fcfe(
        dt="2026-01-01",
        sp500_level=5881.63,
        trailing_eps=271.52,
        analyst_growth=0.1050,   # 5-yr CAGR from spreadsheet
        tbond_rate=0.0418,
        payout_ratio=0.7785,
        year1_growth=0.1559,
        year2_growth=0.1448,
    )
    print(result.summary())
    print()
    print(f"  Expected ERP: ~4.23%")
    print(f"  Our result:    {result.implied_erp:.2%}")
    print(f"  Difference:    {abs(result.implied_erp - 0.0423):.4f}")
    print()

    # Also test legacy DDM 1999 example
    print("=== Validation: Damodaran 1999 Example (legacy DDM) ===\n")
    result_99 = compute_erp_ddm(
        dt="1999-12-31",
        sp500_level=1469.0,
        total_yield=0.0168,
        growth_high=0.10,
        tbond_rate=0.065,
        ramped=False,  # 1999 used flat growth
    )
    print(f"  1999 dividends-only ERP: {result_99.implied_erp:.4f}  (expected ~0.0210)")

    # Test breakeven
    print("\n=== Breakeven Growth Analysis (Jan 2026) ===\n")
    bk = compute_breakeven_growth(
        sp500_level=5881.63,
        trailing_eps=271.52,
        tbond_rate=0.0418,
        normal_erp_method="longrun",
    )
    print(f"  Breakeven growth (for 4.25% ERP): {bk['breakeven_growth']:.2%}")
    print(f"  {bk['interpretation']}")


if __name__ == "__main__":
    validate_against_damodaran()
