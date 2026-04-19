from __future__ import annotations
"""
Data fetching module — pulls all inputs from free-tier sources.

Sources:
  - S&P 500 level           → Yahoo Finance (yfinance) ^GSPC
  - Dividend yield          → Yahoo Finance SPY
  - 10-Year Treasury rate   → FRED API (fredapi) or Yahoo Finance ^TNX fallback
  - Analyst growth estimate → Yahoo Finance earnings estimates (FY1, FY2)
  - Trailing EPS            → Yahoo Finance SPY / S&P 500 constituents
  - Buyback yield           → Configurable default (hard to get free-tier)

ANALYST GROWTH METHODOLOGY:
────────────────────────────────────────────────────────────────────────
Damodaran uses S&P Capital IQ bottom-up consensus (not freely available),
cross-referenced with Yardeni, Thomson Reuters, and FactSet.

For our free-tier implementation, we use Yahoo Finance earnings estimates:
  1. Fetch FY1 (current fiscal year) and FY2 (next fiscal year) EPS estimates
     for a basket of large S&P 500 stocks
  2. Compute the implied 1-year growth (FY2/FY1 - 1) as a proxy for analyst
     consensus near-term growth
  3. Use this as the "analyst_growth" input to the ramped growth schedule

This is a reasonable proxy when the actual analyst consensus rate isn't
available from free sources. Users can always override with --growth.

TRAILING EPS METHODOLOGY:
────────────────────────────────────────────────────────────────────────
Damodaran's Jan 2026 value: 271.52 (trailing 12-month earnings per S&P 500 unit)
This is S&P 500 aggregate earnings divided by the number of units in the index.

Free-tier proxy: use SPY's trailing EPS or estimate from index level and P/E.
"""
import warnings
from datetime import date, datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

from config import (
    YAHOO_SP500_TICKER,
    FRED_API_KEY,
    FRED_TBOND_SERIES,
    DEFAULT_BUYBACK_YIELD,
    DEFAULT_ANALYST_GROWTH,
    DEFAULT_PAYOUT_RATIO,
)


# ── S&P 500 Price ─────────────────────────────────────────────────
def fetch_sp500_level(as_of: Optional[str] = None) -> float:
    """
    Fetch the S&P 500 closing price.
    If as_of is given (YYYY-MM-DD), returns the close on or before that date.
    Otherwise returns the most recent close.
    """
    ticker = yf.Ticker(YAHOO_SP500_TICKER)

    if as_of:
        target = pd.Timestamp(as_of)
        start = target - timedelta(days=10)
        hist = ticker.history(start=start.strftime("%Y-%m-%d"),
                              end=(target + timedelta(days=1)).strftime("%Y-%m-%d"))
        if hist.empty:
            raise ValueError(f"No S&P 500 data found near {as_of}")
        return float(hist["Close"].iloc[-1])
    else:
        hist = ticker.history(period="5d")
        if hist.empty:
            raise ValueError("Cannot fetch current S&P 500 level")
        return float(hist["Close"].iloc[-1])


# ── Dividend Yield ─────────────────────────────────────────────────
def fetch_dividend_yield() -> float:
    """
    Calculate trailing 12-month dividend yield for the S&P 500.
    Uses actual dividend payments from Yahoo Finance SPY.
    """
    ticker = yf.Ticker("SPY")
    info = ticker.info

    div_yield = info.get("trailingAnnualDividendYield") or info.get("dividendYield")
    if div_yield and div_yield > 0:
        return float(div_yield)

    # Fallback: compute from dividend history
    end = datetime.now()
    divs = ticker.dividends
    if len(divs) == 0:
        warnings.warn("No dividend data found; using 1.5% default")
        return 0.015

    recent = divs[divs.index >= (end - timedelta(days=365))]
    annual_div = float(recent.sum())
    current_price = float(ticker.history(period="1d")["Close"].iloc[-1])
    return annual_div / current_price


# ── 10-Year Treasury Rate ─────────────────────────────────────────
def fetch_tbond_rate() -> float:
    """
    Fetch current 10-year Treasury rate.
    Primary: FRED API (requires free API key from fred.stlouisfed.org).
    Fallback: Yahoo Finance ^TNX ticker.
    """
    if FRED_API_KEY:
        try:
            from fredapi import Fred
            fred = Fred(api_key=FRED_API_KEY)
            series = fred.get_series(FRED_TBOND_SERIES)
            rate = series.dropna().iloc[-1]
            return float(rate) / 100.0
        except Exception as e:
            warnings.warn(f"FRED fetch failed ({e}), falling back to Yahoo Finance")

    try:
        tnx = yf.Ticker("^TNX")
        hist = tnx.history(period="5d")
        if not hist.empty:
            rate = float(hist["Close"].iloc[-1])
            return rate / 100.0
    except Exception:
        pass

    raise ValueError("Cannot fetch 10-year Treasury rate. "
                     "Set FRED_API_KEY or check internet connection.")


# ── Trailing EPS ──────────────────────────────────────────────────
def fetch_trailing_eps(sp500_level: Optional[float] = None) -> float:
    """
    Estimate trailing 12-month EPS for the S&P 500.

    Damodaran's Jan 2026 value: 271.52
    (S&P 500 aggregate net income / index units, trailing 12 months)

    Free-tier approaches (in order of preference):
      1. SPY trailing EPS from Yahoo Finance info
      2. Implied from S&P 500 P/E ratio (level / PE = EPS)
      3. Weighted average of top S&P 500 constituents (rough proxy)

    Note: SPY EPS is not exactly the same as S&P 500 index EPS because
    SPY holds fractional shares, but it's a reasonable proxy.
    """
    # Method 1: SPY trailing EPS
    try:
        spy = yf.Ticker("SPY")
        info = spy.info
        trailing_eps = info.get("trailingEps")
        if trailing_eps and trailing_eps > 0:
            # SPY EPS needs to be scaled to S&P 500 index level
            # SPY price ≈ S&P_level / 10, so S&P EPS ≈ SPY_EPS * 10
            spy_price = info.get("regularMarketPrice") or info.get("previousClose", 500)
            if sp500_level and spy_price:
                scale_factor = sp500_level / spy_price
                return float(trailing_eps) * scale_factor
            return float(trailing_eps) * 10.0  # rough scale
    except Exception:
        pass

    # Method 2: Implied from P/E ratio
    try:
        sp500_ticker = yf.Ticker(YAHOO_SP500_TICKER)
        info = sp500_ticker.info
        pe_ratio = info.get("trailingPE") or info.get("forwardPE")
        level = sp500_level or info.get("regularMarketPrice", 5000)
        if pe_ratio and pe_ratio > 0:
            return float(level) / float(pe_ratio)
    except Exception:
        pass

    # Method 3: Estimate from current level and historical P/E
    # S&P 500 long-run average P/E ~17x; use this as fallback
    if sp500_level:
        historical_pe = 21.0  # Recent (2020-2025) average forward P/E
        warnings.warn(f"Using estimated trailing EPS = S&P/{historical_pe:.0f}x P/E")
        return sp500_level / historical_pe

    warnings.warn("Cannot fetch trailing EPS; using Damodaran Jan 2026 value 271.52")
    return 271.52


# ── Analyst Growth Estimates ──────────────────────────────────────
def fetch_analyst_growth_detailed() -> dict:
    """
    Fetch year-by-year analyst EPS growth estimates for the S&P 500.

    Returns a dict with:
        blended_growth: float  — blended 1-2yr consensus estimate
        year1_growth:   float  — FY1 implied growth
        year2_growth:   float  — FY2 implied growth
        source:         str    — data source description

    Methodology:
      - Fetch FY1 and FY2 EPS estimates for a basket of top S&P 500 stocks
      - Compute median implied growth rates
      - This proxies S&P Capital IQ bottom-up consensus

    Damodaran's sources: S&P Capital IQ, Yardeni, Thomson Reuters, FactSet.
    These are not freely available; this function provides the best free proxy.
    """
    top_tickers = [
        "AAPL", "MSFT", "NVDA", "AMZN", "META",
        "GOOGL", "BRK-B", "LLY", "AVGO", "JPM",
        "TSLA", "V", "UNH", "XOM", "MA",
    ]

    fy1_growths = []
    fy2_growths = []

    for sym in top_tickers:
        try:
            t = yf.Ticker(sym)
            # earnings_trend has analyst EPS estimates by period
            trend = t.earnings_estimate
            if trend is not None and not trend.empty:
                # columns: 'Current Year', 'Next Year' (FY1, FY2)
                if hasattr(trend, 'columns'):
                    cols = trend.columns.tolist()
                    # Try to extract growth from avg estimates
                    if '0y' in cols and '+1y' in cols:
                        fy1_avg = trend['0y'].get('avg', None)
                        fy2_avg = trend['+1y'].get('avg', None)
                        if fy1_avg and fy2_avg and fy1_avg > 0:
                            fy1_growths.append(float(fy2_avg / fy1_avg - 1))

            # Alternative: use earningsGrowth from info
            info = t.info
            g = info.get("earningsGrowth")
            if g and -0.5 < g < 2.0:
                fy1_growths.append(float(g))

            # Forward vs trailing P/E implied growth
            fwd_pe = info.get("forwardPE")
            trail_pe = info.get("trailingPE")
            if fwd_pe and trail_pe and fwd_pe > 0 and trail_pe > 0:
                implied_g = trail_pe / fwd_pe - 1
                if -0.30 < implied_g < 0.60:
                    fy2_growths.append(implied_g)

        except Exception:
            continue

    result = {
        "source": "Yahoo Finance (SPY/top-15 constituents median — proxy for S&P Capital IQ consensus)",
        "note": "For more accurate estimates, use: Yardeni.com, FactSet Earnings Insight, or Bloomberg EARN",
    }

    if len(fy1_growths) >= 3:
        yr1 = float(np.median(fy1_growths))
        yr1 = max(0.01, min(0.40, yr1))  # clip to reasonable range
        result["year1_growth"] = yr1
    else:
        result["year1_growth"] = DEFAULT_ANALYST_GROWTH
        result["source"] += " [FY1 fallback]"

    if len(fy2_growths) >= 3:
        yr2 = float(np.median(fy2_growths))
        yr2 = max(0.01, min(0.35, yr2))
        result["year2_growth"] = yr2
    else:
        result["year2_growth"] = result["year1_growth"] * 0.90  # modest fade
        result["source"] += " [FY2 fallback]"

    # Blended 5-yr growth: weight yr1 and yr2 heavily; ramp implied by scheduler
    result["blended_growth"] = (result["year1_growth"] * 0.5 + result["year2_growth"] * 0.5)

    return result


def fetch_analyst_growth() -> float:
    """
    Simple interface: return a single blended analyst growth estimate.

    For the full year-by-year breakdown, use fetch_analyst_growth_detailed().
    """
    try:
        detail = fetch_analyst_growth_detailed()
        return detail["blended_growth"]
    except Exception:
        warnings.warn(f"Cannot fetch analyst growth; using default {DEFAULT_ANALYST_GROWTH:.1%}")
        return DEFAULT_ANALYST_GROWTH


# ── Buyback Yield ──────────────────────────────────────────────────
def fetch_buyback_yield() -> float:
    """
    Buyback yield for the S&P 500.

    The buyback yield is the hardest metric to get from free sources.
    S&P publishes quarterly buyback data, but it's behind a paywall.

    Current approach: use a configurable default.
    Override via CLI: --buyback-yield 0.025

    Historical S&P 500 buyback yields:
      2000-2009: ~1.0-3.5%
      2010-2019: ~2.5-3.0%
      2020 (COVID dip): ~1.0%
      2021-2025: ~2.0-2.5%

    Note: Damodaran combines dividends + buybacks into a "payout ratio"
    (% of earnings returned), rather than separating them. In the FCFE
    method, the payout ratio captures this holistically.
    """
    return DEFAULT_BUYBACK_YIELD


# ── Bundled Fetch ──────────────────────────────────────────────────
def fetch_all_inputs(
    as_of: Optional[str] = None,
    buyback_override: Optional[float] = None,
    growth_override: Optional[float] = None,
    method: str = "fcfe",
) -> dict:
    """
    Fetch all model inputs in one call.

    Parameters:
        as_of:            Historical date override (YYYY-MM-DD)
        buyback_override: Manual buyback yield override
        growth_override:  Manual analyst growth override
        method:           'fcfe' (default) or 'ddm'

    Returns dict with keys:
        date, index_level, dividend_yield, buyback_yield, total_yield,
        analyst_5yr_growth, rfr_rate,
        trailing_eps (FCFE method),
        year1_growth, year2_growth (if available)
    """
    index_level = fetch_sp500_level(as_of)
    div_yield = fetch_dividend_yield()
    buyback = buyback_override if buyback_override is not None else fetch_buyback_yield()
    rfr_rate = fetch_tbond_rate()

    dt = as_of or date.today().isoformat()

    # Fetch growth details
    if growth_override is not None:
        growth = growth_override
        year1_growth = growth_override
        year2_growth = growth_override * 0.90
        growth_source = "manual override"
    else:
        try:
            growth_detail = fetch_analyst_growth_detailed()
            growth = growth_detail["blended_growth"]
            year1_growth = growth_detail.get("year1_growth", growth)
            year2_growth = growth_detail.get("year2_growth", growth * 0.90)
            growth_source = growth_detail.get("source", "Yahoo Finance")
        except Exception as e:
            warnings.warn(f"Growth fetch failed: {e}")
            growth = DEFAULT_ANALYST_GROWTH
            year1_growth = growth
            year2_growth = growth
            growth_source = "default fallback"

    # Fetch trailing EPS for FCFE method
    trailing_eps = None
    if method == "fcfe":
        try:
            trailing_eps = fetch_trailing_eps(sp500_level=index_level)
        except Exception as e:
            warnings.warn(f"Trailing EPS fetch failed: {e}; using estimate from P/E")
            trailing_eps = index_level / 21.0  # rough fallback: ~21x P/E

    return {
        "date": dt,
        "index_level": index_level,
        "dividend_yield": div_yield,
        "buyback_yield": buyback,
        "total_yield": div_yield + buyback,
        "analyst_5yr_growth": growth,
        "year1_growth": year1_growth,
        "year2_growth": year2_growth,
        "growth_source": growth_source,
        "rfr_rate": rfr_rate,
        "trailing_eps": trailing_eps,
        "payout_ratio": DEFAULT_PAYOUT_RATIO,
        "method": method,
    }


if __name__ == "__main__":
    print("Fetching all ERP model inputs (FCFE method)...")
    data = fetch_all_inputs(method="fcfe")
    for k, v in data.items():
        if isinstance(v, float):
            print(f"  {k}: {v:.4f}")
        else:
            print(f"  {k}: {v}")
