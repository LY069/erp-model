"""Generic Yahoo Finance + FRED DataSource driven by a MarketSpec.

This is the single implementation Phase 1 ships for both US and UK.
Other markets (EU/JP/KR/IN/TW/CN) come online by adding a MarketSpec
entry; only when a market needs source-specific scraping (e.g.,
ChinaBond for CN rfr) does it earn an override module under
`data_sources/overrides/`.

Behaviour-preservation note: when `market.code == "US"`, every fetch
delegates to the existing US-specific helpers in `data_fetcher.py`
(`fetch_sp500_level`, `fetch_dividend_yield`, `fetch_tbond_rate`,
`fetch_trailing_eps`, `fetch_analyst_growth_detailed`, `fetch_buyback_yield`).
That keeps the US numerics bit-for-bit identical to pre-Phase-1.
"""
from __future__ import annotations

import time
import warnings
from datetime import date, datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

from config import FRED_API_KEY
from markets_config import MarketSpec, get_market

from .base import FetchResult


def _now() -> int:
    return int(time.time())


class YahooFredDataSource:
    """MarketSpec-parameterised Yahoo+FRED fetcher."""

    def __init__(self, spec: MarketSpec):
        self.spec = spec
        self.market = spec.code

    # ── index_level ────────────────────────────────────────────────
    def fetch_index_level(self, as_of: Optional[date] = None) -> FetchResult:
        if self.market == "US":
            from data_fetcher import fetch_sp500_level
            value = fetch_sp500_level(as_of.isoformat() if as_of else None)
            return FetchResult(value=value, source=f"yahoo:{self.spec.yahoo_index}",
                               fetched_at=_now())

        ticker = yf.Ticker(self.spec.yahoo_index)
        if as_of is not None:
            target = pd.Timestamp(as_of)
            start = target - timedelta(days=10)
            hist = ticker.history(
                start=start.strftime("%Y-%m-%d"),
                end=(target + timedelta(days=1)).strftime("%Y-%m-%d"),
            )
        else:
            hist = ticker.history(period="5d")
        if hist.empty:
            raise ValueError(
                f"No {self.spec.yahoo_index} data found"
                + (f" near {as_of}" if as_of else "")
            )
        return FetchResult(
            value=float(hist["Close"].iloc[-1]),
            source=f"yahoo:{self.spec.yahoo_index}",
            fetched_at=_now(),
        )

    # ── rfr ────────────────────────────────────────────────────────
    def fetch_rfr(self, as_of: Optional[date] = None) -> FetchResult:
        if self.market == "US":
            from data_fetcher import fetch_tbond_rate
            value = fetch_tbond_rate()
            return FetchResult(value=value,
                               source=f"fred:{self.spec.fred_rfr_series}",
                               fetched_at=_now())

        if FRED_API_KEY:
            for series in [self.spec.fred_rfr_series, *self.spec.fred_rfr_fallback]:
                try:
                    from fredapi import Fred
                    fred = Fred(api_key=FRED_API_KEY)
                    s = fred.get_series(series).dropna()
                    if not s.empty:
                        return FetchResult(
                            value=float(s.iloc[-1]) / 100.0,
                            source=f"fred:{series}",
                            fetched_at=_now(),
                            is_fallback=(series != self.spec.fred_rfr_series),
                        )
                except Exception as e:
                    warnings.warn(f"FRED {series} fetch failed: {e}")

        if self.spec.default_rfr_fallback is not None:
            warnings.warn(
                f"FRED unavailable for {self.market}; "
                f"using MarketSpec.default_rfr_fallback={self.spec.default_rfr_fallback:.3f}"
            )
            return FetchResult(
                value=self.spec.default_rfr_fallback,
                source=f"market_default:{self.market}",
                fetched_at=_now(),
                is_fallback=True,
                note="No FRED key; falling back to MarketSpec.default_rfr_fallback",
            )

        raise ValueError(
            f"Cannot fetch risk-free rate for {self.market}. "
            f"Set FRED_API_KEY or add a market-specific fetcher."
        )

    # ── dividend_yield ─────────────────────────────────────────────
    def fetch_dividend_yield(self, as_of: Optional[date] = None) -> FetchResult:
        if self.market == "US":
            from data_fetcher import fetch_dividend_yield
            value = fetch_dividend_yield()
            return FetchResult(value=value,
                               source=f"yahoo:{self.spec.yahoo_etf_for_divy}",
                               fetched_at=_now())

        ticker = yf.Ticker(self.spec.yahoo_etf_for_divy)
        info = ticker.info or {}
        div_yield = info.get("trailingAnnualDividendYield") or info.get("dividendYield")
        if div_yield and div_yield > 0:
            value = float(div_yield)
            # Yahoo sometimes returns dividendYield as a percent (e.g. 3.85)
            # rather than a fraction (0.0385). Normalise.
            if value > 1.0:
                value = value / 100.0
            return FetchResult(value=value,
                               source=f"yahoo:{self.spec.yahoo_etf_for_divy}.info",
                               fetched_at=_now())

        # Fallback: trailing 12M distribution / current price
        end = datetime.now()
        divs = ticker.dividends
        if len(divs) == 0:
            warnings.warn(
                f"No dividend data for {self.spec.yahoo_etf_for_divy}; using 1.5% default")
            return FetchResult(value=0.015, source="default:1.5%",
                               fetched_at=_now(), is_fallback=True)

        recent = divs[divs.index >= (end - timedelta(days=365))]
        annual_div = float(recent.sum())
        price = float(ticker.history(period="1d")["Close"].iloc[-1])
        return FetchResult(
            value=annual_div / price,
            source=f"yahoo:{self.spec.yahoo_etf_for_divy} 12M trailing",
            fetched_at=_now(),
            is_fallback=True,
        )

    # ── buyback_yield ──────────────────────────────────────────────
    def fetch_buyback_yield(self, as_of: Optional[date] = None) -> FetchResult:
        if self.market == "US":
            from data_fetcher import fetch_buyback_yield
            value = fetch_buyback_yield()
            return FetchResult(value=value, source="config_default",
                               fetched_at=_now())
        return FetchResult(
            value=self.spec.default_buyback_yield,
            source=f"market_default:{self.market}",
            fetched_at=_now(),
        )

    # ── trailing_eps ───────────────────────────────────────────────
    def fetch_trailing_eps(
        self, as_of: Optional[date] = None, index_level: Optional[float] = None
    ) -> FetchResult:
        if self.market == "US":
            from data_fetcher import fetch_trailing_eps
            value = fetch_trailing_eps(sp500_level=index_level)
            return FetchResult(value=value, source="yahoo:SPY trailingEps × scale",
                               fetched_at=_now())

        # Generic (UK and beyond): try ETF trailingEps, then ETF P/E, then index
        # P/E. EPS = price / PE.
        try:
            etf = yf.Ticker(self.spec.yahoo_etf_for_divy)
            info = etf.info or {}
            eps = info.get("trailingEps")
            if eps and eps > 0 and index_level:
                price = info.get("regularMarketPrice") or info.get("previousClose")
                if price and price > 0:
                    return FetchResult(
                        value=float(eps) * (index_level / float(price)),
                        source=f"yahoo:{self.spec.yahoo_etf_for_divy}.trailingEps × scale",
                        fetched_at=_now(),
                    )
            pe = info.get("trailingPE") or info.get("forwardPE")
            if pe and pe > 0 and index_level:
                return FetchResult(
                    value=float(index_level) / float(pe),
                    source=f"yahoo:{self.spec.yahoo_etf_for_divy} index/PE",
                    fetched_at=_now(),
                    is_fallback=True,
                )
        except Exception:
            pass

        try:
            idx = yf.Ticker(self.spec.yahoo_index)
            info = idx.info or {}
            pe = info.get("trailingPE") or info.get("forwardPE")
            if pe and pe > 0:
                level = index_level or info.get("regularMarketPrice")
                if level:
                    return FetchResult(
                        value=float(level) / float(pe),
                        source=f"yahoo:{self.spec.yahoo_index} index/PE",
                        fetched_at=_now(),
                        is_fallback=True,
                    )
        except Exception:
            pass

        if index_level:
            return FetchResult(
                value=index_level / 17.0,
                source="fallback:17x P/E",
                fetched_at=_now(),
                is_fallback=True,
                note="No EPS source; using long-run average P/E",
            )
        return FetchResult(value=None, source="none", fetched_at=_now(),
                           is_fallback=True, note="No EPS source available")

    # ── analyst_growth ─────────────────────────────────────────────
    def fetch_analyst_growth(self, as_of: Optional[date] = None) -> dict:
        """Return the same dict shape as data_fetcher.fetch_analyst_growth_detailed.

        For US, delegates to the existing implementation. For other markets,
        builds the same fy1/fy2/blended growth from the market's
        `analyst_tickers` list using Yahoo earningsGrowth + fwd/trailing PE,
        falling back to `default_analyst_growth` when there aren't enough
        valid samples.
        """
        if self.market == "US":
            from data_fetcher import fetch_analyst_growth_detailed
            return fetch_analyst_growth_detailed()

        tickers = self.spec.analyst_tickers
        fy1, fy2 = [], []
        for sym in tickers:
            try:
                t = yf.Ticker(sym)
                info = t.info or {}
                g = info.get("earningsGrowth")
                if g is not None and -0.5 < g < 2.0:
                    fy1.append(float(g))
                fwd = info.get("forwardPE")
                trail = info.get("trailingPE")
                if fwd and trail and fwd > 0 and trail > 0:
                    implied = trail / fwd - 1
                    if -0.30 < implied < 0.60:
                        fy2.append(implied)
            except Exception:
                continue

        result = {
            "source": f"Yahoo info (top-{len(tickers)} {self.market} constituents median)",
            "note": "Free-tier proxy for consensus analyst estimates",
        }

        min_n = max(3, self.spec.min_analyst_tickers // 2)
        fy1_fellback = len(fy1) < min_n
        if not fy1_fellback:
            yr1 = float(np.median(fy1))
            yr1 = max(0.01, min(0.40, yr1))
            result["year1_growth"] = yr1
        else:
            result["year1_growth"] = self.spec.default_analyst_growth
            result["source"] += " [FY1 fallback]"

        # If FY1 fell back, FY2 should too — independent FY2 noise
        # (PE-ratio implied growth) on a tiny ticker pool can produce
        # absurdly high blended growth.
        if len(fy2) >= min_n and not fy1_fellback:
            yr2 = float(np.median(fy2))
            yr2 = max(0.01, min(0.35, yr2))
            result["year2_growth"] = yr2
        else:
            result["year2_growth"] = result["year1_growth"] * 0.90
            result["source"] += " [FY2 fallback]"

        result["blended_growth"] = (
            result["year1_growth"] * 0.5 + result["year2_growth"] * 0.5
        )
        return result


def get_data_source(market: str) -> YahooFredDataSource:
    """Factory: return a configured DataSource for the given market code."""
    return YahooFredDataSource(get_market(market))
