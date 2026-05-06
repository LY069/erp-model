"""
Per-market configuration for the Damodaran 2-stage ERP solver.

Phase 0: US stub only. Other markets (UK/EU/JP/KR/IN/TW/CN) get their
MarketSpec entries added in Phases 1, 3, 4. Container and field set
come from Agent 3 §3 of SHARED_NOTES.md; concrete US values mirror
what currently lives in config.py so migration stays behaviour-neutral.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MarketSpec:
    code: str
    name: str
    currency: str
    yahoo_index: str
    yahoo_etf_for_divy: str
    fred_rfr_series: str
    fred_rfr_fallback: list[str] = field(default_factory=list)
    analyst_tickers: list[str] = field(default_factory=list)
    min_analyst_tickers: int = 8
    default_payout_ratio: float = 0.60
    default_buyback_yield: float = 0.0
    default_analyst_growth: float = 0.06
    default_rfr_fallback: float | None = None
    trend_growth_fallback: float = 0.06
    normal_erp_longrun: float = 0.0475
    normal_erp_decade: float = 0.055
    earliest_seed_date: str = "1990-01-01"
    rfr_max_stale_days: int = 7
    data_quality: str = "full"
    notes: str = ""
    # Display fields used by the dashboard's per-market label rewrite
    # (Phase 2.1). The bundle in assets/ has US-specific strings hardcoded;
    # these supply the per-market replacements. New markets added in
    # Phases 3/4 only need to fill these to get correct UI labels.
    #
    # Why two index forms and two rfr forms: the bundle uses both a long
    # form (page heading, card label, input label) and a short form
    # (table column header, scenario preset, formula text). Examples in
    # the compiled bundle: "S&P 500 Implied Equity Risk Premium",
    # "S&P 500 Level", "S&P aggregate", and bare "S&P" / "T-Bond" /
    # "T-bond" (lowercase, in `ERP + T-bond`).
    display_index_name:  str = ""    # long, e.g. "S&P 500", "FTSE 100"
    display_index_short: str = ""    # short, e.g. "S&P", "FTSE"; auto-default = first word of display_index_name
    display_rfr_name:    str = ""    # long,  e.g. "T-Bond Rate", "10Y Gilt Yield"
    display_rfr_short:   str = ""    # short, e.g. "T-Bond", "Gilt"
    currency_symbol:     str = "$"   # e.g. "$", "£", "€", "¥", "₩", "₹", "NT$"


MARKETS: dict[str, MarketSpec] = {
    "US": MarketSpec(
        code="US",
        name="United States",
        currency="USD",
        yahoo_index="^GSPC",
        yahoo_etf_for_divy="SPY",
        fred_rfr_series="DGS10",
        fred_rfr_fallback=[],
        analyst_tickers=[],
        min_analyst_tickers=8,
        default_payout_ratio=0.7785,
        default_buyback_yield=0.02,
        default_analyst_growth=0.08,
        trend_growth_fallback=0.06,
        normal_erp_longrun=0.0425,
        normal_erp_decade=0.055,
        earliest_seed_date="1960-01-01",
        rfr_max_stale_days=7,
        data_quality="full",
        notes="Matches Damodaran Jan 2026 snapshot (ERP=4.23%). "
              "Values mirror config.py defaults so Phase 0 is behaviour-neutral.",
        display_index_name="S&P 500",
        display_index_short="S&P",
        display_rfr_name="T-Bond Rate",
        display_rfr_short="T-Bond",
        currency_symbol="$",
    ),
    "UK": MarketSpec(
        code="UK",
        name="United Kingdom",
        currency="GBP",
        yahoo_index="^FTSE",
        yahoo_etf_for_divy="VUKE.L",
        fred_rfr_series="IRLTLT01GBM156N",
        fred_rfr_fallback=[],
        analyst_tickers=["SHEL.L", "AZN.L", "HSBA.L", "ULVR.L", "RIO.L"],
        min_analyst_tickers=8,
        default_payout_ratio=0.60,
        default_buyback_yield=0.012,
        default_analyst_growth=0.06,
        default_rfr_fallback=0.045,
        trend_growth_fallback=0.04,
        normal_erp_longrun=0.0475,
        normal_erp_decade=0.055,
        earliest_seed_date="1990-01-01",
        rfr_max_stale_days=7,
        data_quality="full",
        notes="FTSE 100 + VUKE.L (Vanguard FTSE 100 UCITS) for div yield. "
              "FRED IRLTLT01GBM156N = UK 10Y Gilt. GBP local currency.",
        display_index_name="FTSE 100",
        display_index_short="FTSE",
        display_rfr_name="10Y Gilt Yield",
        display_rfr_short="Gilt",
        currency_symbol="£",
    ),
}


def get_market(code: str) -> MarketSpec:
    """Look up a market by ISO-ish code. Raises KeyError with a helpful message."""
    try:
        return MARKETS[code]
    except KeyError as e:
        known = ", ".join(sorted(MARKETS))
        raise KeyError(f"Unknown market {code!r}. Known markets: {known}") from e
