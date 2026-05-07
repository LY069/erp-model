"""TW-specific override for the Yahoo+FRED DataSource.

Why this module exists (Phase 4):
- FRED has no Taiwan 10Y govt bond series (Agent 2 §2). The Taiwan
  central bank (CBC) public statistics endpoint we wanted to use
  (MTAB1A.CSV) returns 404 as of 2026-05; the CBC site front-end
  has shifted to interactive query forms. yfinance has no TW10Y
  ticker either ("possibly delisted" for every variant tried).
- Investing.com's daily TW 10Y page renders the latest yield in a
  data-attribute (data-test="instrument-price-last") that is stable
  enough to scrape without JavaScript. No auth needed; UA header
  required to avoid bot blocks.

Fallback chain:
  1. Investing.com `taiwan-10-year-bond-yield` (preferred — daily, free)
  2. spec.default_rfr_fallback (manual annual refresh against TWSE/CBC)
"""
from __future__ import annotations

import re
import warnings
from datetime import date
from typing import Optional

import requests

from data_sources.base import FetchResult
from data_sources.yahoo_fred import YahooFredDataSource, _now


INVESTING_TW_URL = "https://www.investing.com/rates-bonds/taiwan-10-year-bond-yield"
DEFAULT_TIMEOUT  = 8
UA = {"User-Agent": "Mozilla/5.0 (compatible; ERPModel/0.4 research)"}
LAST_RE = re.compile(r'data-test="instrument-price-last"[^>]*>([0-9]+\.[0-9]+)')


class TWDataSource(YahooFredDataSource):
    """Yahoo (index/divy/eps) + Investing.com (rfr) data source."""

    def fetch_rfr(self, as_of: Optional[date] = None) -> FetchResult:
        try:
            r = requests.get(INVESTING_TW_URL, headers=UA, timeout=DEFAULT_TIMEOUT)
            r.raise_for_status()
            m = LAST_RE.search(r.text)
            if m:
                value = float(m.group(1)) / 100.0
                return FetchResult(
                    value=value,
                    source="investing:taiwan-10y",
                    fetched_at=_now(),
                )
            warnings.warn("TW Investing.com page parsed but no yield value found")
        except Exception as e:
            warnings.warn(f"TW Investing.com fetch failed: {e}")

        if self.spec.default_rfr_fallback is None:
            raise RuntimeError("TW rfr fallback chain exhausted; no constant set")
        return FetchResult(
            value=self.spec.default_rfr_fallback,
            source="manual:tw_const",
            fetched_at=_now(),
            is_fallback=True,
            note="Investing.com fetch failed; using spec.default_rfr_fallback",
        )
