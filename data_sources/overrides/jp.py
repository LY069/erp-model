"""JP-specific overrides for the Yahoo+FRED DataSource.

Why this module exists (Phase 3.1):
- yfinance ^TOPX is dead → use 1306.T (NEXT FUNDS TOPIX ETF, Nomura).
- EWJ div yield is FX-distorted (USD distributions + 30% US withholding) →
  use 1306.T's JPY-native distribution yield instead.
- ^N225 retained ONLY as last-resort circuit-breaker (scale cancels in DDM).

Design notes:
- 1306.T is the largest TOPIX ETF in Japan (JPY 30tn AUM, Nomura), tracking
  error <0.1% pa. Daily price history on yfinance back to 2008-01-04.
- Index level scale (1306.T price ≈ TOPIX/3,400) does NOT affect implied
  ERP because the index level cancels in the DDM/FCFE solver objective
  (verified in erp_calculator.py:_objective).
- MSCI Japan as a fallback was rejected: only working source is EWJ
  (the very ticker being replaced). Tokyo-listed 1329.T and 2521.T have
  been rebranded away from MSCI Japan.
"""
from __future__ import annotations

import warnings
from datetime import date, timedelta
from typing import Optional

import pandas as pd
import yfinance as yf

from data_sources.base import FetchResult
from data_sources.yahoo_fred import YahooFredDataSource, _now


# Fallback chain for JP index level: tried in order, first non-empty wins.
JP_INDEX_TICKERS = ("1306.T", "1308.T", "^N225")
JP_DIVY_ETF      = "1306.T"   # NEXT FUNDS TOPIX ETF


class JPDataSource(YahooFredDataSource):
    """Yahoo+FRED data source with JP-specific TOPIX ETF substitutions."""

    def fetch_index_level(self, as_of: Optional[date] = None) -> FetchResult:
        for sym in JP_INDEX_TICKERS:
            t = yf.Ticker(sym)
            if as_of is not None:
                target = pd.Timestamp(as_of)
                hist = t.history(
                    start=(target - timedelta(days=10)).strftime("%Y-%m-%d"),
                    end=(target + timedelta(days=1)).strftime("%Y-%m-%d"),
                )
            else:
                hist = t.history(period="5d")
            if not hist.empty:
                is_fallback = (sym != JP_INDEX_TICKERS[0])
                note = None
                if is_fallback:
                    note = f"{JP_INDEX_TICKERS[0]} unavailable; used {sym}"
                    warnings.warn(
                        f"JP index: {JP_INDEX_TICKERS[0]} unavailable; "
                        f"using {sym} (scale cancels in DDM — ERP unaffected)"
                    )
                return FetchResult(
                    value=float(hist["Close"].iloc[-1]),
                    source=f"yahoo:{sym}",
                    fetched_at=_now(),
                    is_fallback=is_fallback,
                    note=note,
                )
        raise ValueError(
            f"No JP index data found from any of {JP_INDEX_TICKERS}"
        )

    def fetch_dividend_yield(self, as_of: Optional[date] = None) -> FetchResult:
        # Primary: 1306.T trailing distribution yield (JPY-native; no FX/withholding).
        try:
            t = yf.Ticker(JP_DIVY_ETF)
            info = t.info or {}
            dy = info.get("trailingAnnualDividendYield") or info.get("dividendYield")
            if dy and dy > 0:
                value = float(dy)
                # yfinance occasionally returns dividendYield as a percent
                # (e.g. 1.87) rather than a fraction (0.0187). Normalise.
                if value > 1.0:
                    value /= 100.0
                return FetchResult(
                    value=value,
                    source=f"yahoo:{JP_DIVY_ETF}.info",
                    fetched_at=_now(),
                )
        except Exception as e:
            warnings.warn(f"{JP_DIVY_ETF} dividend yield fetch failed: {e}")

        # Fallback: parent's generic path (will hit EWJ → spec.default_buyback_yield).
        return super().fetch_dividend_yield(as_of=as_of)
