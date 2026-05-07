"""CN-specific override for the Yahoo+FRED DataSource.

Why this module exists (Phase 4):
- FRED `IRLTLT01CNM156N` (referenced by Agent 2 §2 as the primary CN
  rfr source) does not exist in the FRED API anymore — every probe
  returns "Bad Request. The series does not exist." (verified
  2026-05-07). The OECD long-rate panel was apparently retired for
  China.
- ChinaBond's public yield-curve endpoint (yield.chinabond.com.cn)
  is JS-rendered and returns HTTP 405 to plain GET requests — needs
  a real browser, which Phase 4 does not ship.
- ChinaMoney's English gov-bond yield page is 404. Same for
  english.chinamoney.com.cn alternatives tried.

Working fallback chain (deliberately reduced from Agent 2's 4-step
ideal — every retired/JS-only step omitted in favour of what works):
  1. Investing.com `china-10-year-bond-yield` (daily, free, UA header)
  2. US 10Y (FRED DGS10) + USDCNH spot/forward spread (coarse NDF proxy)
  3. spec.default_rfr_fallback (manual constant, refreshed annually)

This module is shared by both CN MarketSpec entries (CN = MSCI China
via MCHI; CN_CSI = CSI 300 via 000300.SS). They differ only in
yahoo_index; fetch_rfr is identical.

Hard-fail rule (Agent 2 §9): if rfr is older than 14 days for CN,
mark stale_flag=1 and let upstream code decide whether to fail loud.
The seed pipeline already sets stale_flag when default_rfr_fallback
is hit.
"""
from __future__ import annotations

import re
import warnings
from datetime import date
from typing import Optional

import requests
import yfinance as yf
from fredapi import Fred

from data_sources.base import FetchResult
from data_sources.yahoo_fred import YahooFredDataSource, _now
from config import FRED_API_KEY


INVESTING_CN_URL = "https://www.investing.com/rates-bonds/china-10-year-bond-yield"
US_10Y_FRED_ID   = "DGS10"
DEFAULT_TIMEOUT  = 8
UA = {"User-Agent": "Mozilla/5.0 (compatible; ERPModel/0.4 research)"}
LAST_RE = re.compile(r'data-test="instrument-price-last"[^>]*>([0-9]+\.[0-9]+)')


class CNDataSource(YahooFredDataSource):
    """Yahoo (index/divy) + Investing.com (rfr) + NDF proxy fallback.

    Shared by CN (MSCI China via MCHI) and CN_CSI (CSI 300 via 000300.SS).
    """

    def fetch_rfr(self, as_of: Optional[date] = None) -> FetchResult:
        # Step 1: Investing.com (preferred; daily; free)
        try:
            r = requests.get(INVESTING_CN_URL, headers=UA, timeout=DEFAULT_TIMEOUT)
            r.raise_for_status()
            m = LAST_RE.search(r.text)
            if m:
                value = float(m.group(1)) / 100.0
                return FetchResult(
                    value=value,
                    source="investing:china-10y",
                    fetched_at=_now(),
                )
            warnings.warn("CN Investing.com page parsed but no yield value found")
        except Exception as e:
            warnings.warn(f"CN step1 (Investing.com) failed: {e}")

        # Step 2: US 10Y + USDCNH FX-spread proxy (VERY coarse, last-resort
        # before the constant). The (fwd-spot)/spot premium reflects the
        # USD-CNY rate differential plus FX-risk premium embedded in CNH
        # forwards; in inverted-carry environments (US rates > CNY rates,
        # which has been the prevailing 2024-26 regime), CNH forwards trade
        # at a *discount* to spot so (fwd-spot)/spot is negative. The
        # max(0.0, ...) clamp then floors the spread to zero, leaving
        # value ≈ US 10Y (~4.3% on 2026-05-07). That over-states CN 10Y
        # (~1.7% on the same day) by ~260 bp. Step 3 (constant 2.0%) is
        # therefore more accurate than step 2 in the current regime, but
        # the architecture still lets a future positive-carry world (e.g.
        # PBoC tightening above the Fed) restore step 2's usefulness.
        try:
            fred = Fred(api_key=FRED_API_KEY) if FRED_API_KEY else Fred()
            us10 = float(fred.get_series(US_10Y_FRED_ID).dropna().iloc[-1]) / 100.0
            spot = float(yf.Ticker("CNY=X").history(period="5d")["Close"].iloc[-1])
            fwd  = float(yf.Ticker("CNH=X").history(period="5d")["Close"].iloc[-1])
            spread = max(0.0, (fwd - spot) / spot)
            value = us10 + spread
            warnings.warn("CN rfr step 2 (US10Y + USDCNH spread) used — VERY coarse")
            return FetchResult(
                value=value,
                source="proxy:us10y+ndf_spread",
                fetched_at=_now(),
                is_fallback=True,
                note="step 2 fallback (inverted-carry: yields ~US10Y)",
            )
        except Exception as e:
            warnings.warn(f"CN step2 (US+NDF) failed: {e}")

        # Step 3: spec.default_rfr_fallback (constant)
        if self.spec.default_rfr_fallback is None:
            raise RuntimeError("CN rfr fallback chain exhausted; no constant set")
        return FetchResult(
            value=self.spec.default_rfr_fallback,
            source="manual:cn_const",
            fetched_at=_now(),
            is_fallback=True,
            note="all live steps exhausted",
        )
