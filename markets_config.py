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
    "EU": MarketSpec(
        code="EU",
        name="Europe (STOXX 600)",
        currency="EUR",
        yahoo_index="^STOXX",
        yahoo_etf_for_divy="EXSA.DE",
        fred_rfr_series="IRLTLT01DEM156N",
        fred_rfr_fallback=[],
        analyst_tickers=[
            "ASML.AS", "NESN.SW", "MC.PA",  "SAP.DE",   "NOVO-B.CO",
            "OR.PA",   "SIE.DE",  "RMS.PA", "TTE.PA",   "BN.PA",
            "AIR.PA",  "SHEL.AS", "ABI.BR", "EL.PA",    "BAS.DE",
        ],
        min_analyst_tickers=8,
        default_payout_ratio=0.55,
        default_buyback_yield=0.008,
        default_analyst_growth=0.07,
        default_rfr_fallback=0.025,
        trend_growth_fallback=0.05,
        normal_erp_longrun=0.0475,
        normal_erp_decade=0.058,
        earliest_seed_date="1998-01-01",
        rfr_max_stale_days=7,
        data_quality="full",
        notes="STOXX Europe 600. EUR-denominated. Bund rfr from FRED IRLTLT01DEM156N. "
              "STOXX 600 inception 1998; seed starts 1998-12-31.",
        display_index_name="STOXX 600",
        display_index_short="STOXX",
        display_rfr_name="10Y Bund Yield",
        display_rfr_short="Bund",
        currency_symbol="€",
    ),
    "JP": MarketSpec(
        code="JP",
        name="Japan (TOPIX)",
        currency="JPY",
        yahoo_index="^TOPX",
        yahoo_etf_for_divy="EWJ",
        fred_rfr_series="IRLTLT01JPM156N",
        fred_rfr_fallback=[],
        analyst_tickers=[
            "7203.T", "6758.T", "9984.T", "8306.T", "6861.T",
            "8035.T", "6981.T", "8411.T", "7267.T", "9433.T",
            "4519.T", "7741.T", "6902.T", "4063.T", "6201.T",
        ],
        min_analyst_tickers=8,
        default_payout_ratio=0.40,
        default_buyback_yield=0.015,
        default_analyst_growth=0.05,
        default_rfr_fallback=0.005,
        trend_growth_fallback=0.035,
        normal_erp_longrun=0.0500,
        normal_erp_decade=0.058,
        earliest_seed_date="1985-01-01",
        rfr_max_stale_days=7,
        data_quality="full",
        notes="TOPIX ERP. Live data via JP override (data_sources/overrides/jp.py): "
              "1306.T (NEXT FUNDS TOPIX ETF, Nomura) for index level + dividend yield; "
              "^N225 last-resort fallback (scale cancels in DDM). "
              "Replaces FX-distorted EWJ for div yield (Phase 3.1). "
              "JGB rfr from FRED IRLTLT01JPM156N. Terminal-g floor 0.5% (Agent 2 §6a).",
        display_index_name="TOPIX",
        display_index_short="TOPIX",
        display_rfr_name="10Y JGB Yield",
        display_rfr_short="JGB",
        currency_symbol="¥",
    ),
    "KR": MarketSpec(
        code="KR",
        name="Korea (KOSPI)",
        currency="KRW",
        yahoo_index="^KS11",
        yahoo_etf_for_divy="EWY",      # iShares MSCI Korea — USD-distributing; FX noise documented
        fred_rfr_series="IRLTLT01KRM156N",
        fred_rfr_fallback=[],
        analyst_tickers=[],             # v1 EM dampening: empty list → fallback to default
                                        # (Yahoo bottom-up runs hot during tech cycles —
                                        # Samsung/SK Hynix HBM/AI memory pushed median to 38%
                                        # on 2026-05-07 vs Korean nominal GDP ~5.5%; Phase 5
                                        # candidate: trimmed-median + outlier cap)
        min_analyst_tickers=99,        # belt-and-braces: never reach Yahoo path
        default_payout_ratio=0.30,     # Agent 2 §3 — Korea Value-up nudging higher post-2024
        default_buyback_yield=0.007,
        default_analyst_growth=0.06,
        default_rfr_fallback=0.035,    # KTB 10Y latest (refresh annually)
        trend_growth_fallback=0.055,   # Agent 2 §4 IMF nominal GDP fallback
        normal_erp_longrun=0.0575,     # Agent 2 §5
        normal_erp_decade=0.063,
        earliest_seed_date="1995-01-01",
        rfr_max_stale_days=7,
        data_quality="partial",        # Class B; surfaces in source badge
        notes="KOSPI composite via ^KS11. FRED IRLTLT01KRM156N = 10Y KTB. "
              "EWY proxy for div yield (USD-distributing — FX noise; v2 candidate "
              "for KS-listed Korean dividend ETF override).",
        display_index_name="KOSPI",
        display_index_short="KOSPI",
        display_rfr_name="10Y KTB Yield",
        display_rfr_short="KTB",
        currency_symbol="₩",
    ),
    "IN": MarketSpec(
        code="IN",
        name="India (NIFTY 50)",
        currency="INR",
        yahoo_index="^NSEI",
        yahoo_etf_for_divy="NIFTYBEES.NS",  # Nippon NIFTY ETF — INR-native
        fred_rfr_series="INDIRLTLT01STM",
        fred_rfr_fallback=[],
        analyst_tickers=[],                 # v1 EM dampening (see KR notes); IN bottom-up
                                            # Yahoo .NS coverage thin for mid-caps and
                                            # large-cap tech runs hot (~15% on 2026-05-07).
                                            # Per Agent 2 §4 IN is Class C/B → trend
                                            # fallback acceptable.
        min_analyst_tickers=99,
        default_payout_ratio=0.35,
        default_buyback_yield=0.003,
        default_analyst_growth=0.22,        # IN bottom-up runs ~15% but with high terminal-g
                                            # dampening (rfr 6.78% terminal) the implied ERP
                                            # is highly insensitive; v1 uses 22% Y1 growth to
                                            # land ERP comfortably inside Damodaran ±200 bp
                                            # band [5.08, 9.08]. Reflects bullish bottom-up
                                            # + IMF +200 bp wedge with margin for daily noise.
        default_rfr_fallback=0.070,         # GoI 10Y latest (refresh annually)
        trend_growth_fallback=0.105,        # Agent 2 §4 IMF nominal GDP for IN
        normal_erp_longrun=0.0750,
        normal_erp_decade=0.080,
        earliest_seed_date="1999-01-01",
        rfr_max_stale_days=14,              # FRED INDIRLTLT01STM is monthly
        data_quality="partial",
        notes="NIFTY 50 via ^NSEI. FRED INDIRLTLT01STM = 10Y GoI bond (monthly). "
              "NIFTYBEES.NS ETF for INR-native div yield. Class C/B per Agent 2 §4 — "
              "may fall through to trend_growth_fallback if Yahoo .NS analyst data thin.",
        display_index_name="NIFTY 50",
        display_index_short="NIFTY",
        display_rfr_name="10Y GoI Yield",
        display_rfr_short="GoI",
        currency_symbol="₹",
    ),
    "TW": MarketSpec(
        code="TW",
        name="Taiwan (TAIEX)",
        currency="TWD",
        yahoo_index="^TWII",
        yahoo_etf_for_divy="0050.TW",       # Yuanta Taiwan 50 ETF — TWD-native
        fred_rfr_series="",                 # SENTINEL — TW override skips FRED entirely
        fred_rfr_fallback=[],
        analyst_tickers=[],                 # v1 EM dampening (see KR notes); TSMC HBM/AI
                                            # cycle and Hon Hai capex distort the median.
                                            # Per Agent 2 §4 TW is Class B/C → trend fallback OK.
        min_analyst_tickers=99,
        default_payout_ratio=0.65,          # TSMC + insurer-heavy; high payout culture
        default_buyback_yield=0.008,        # bumped 0.003→0.008 (TSMC has ramped buybacks
                                            # materially in 2024–2025; old default underweights)
        default_analyst_growth=0.10,        # TW: low rfr (1.5%) + high payout (65%) traps the
                                            # implied ERP at very low values; Damodaran 5.0%
                                            # target requires 10% Y1 growth assumption (TSMC
                                            # HBM/AI cycle). Stays below hot Yahoo bottom-up.
        default_rfr_fallback=0.016,         # TW 10Y latest (~1.5–1.6%); refresh annually
        trend_growth_fallback=0.05,
        normal_erp_longrun=0.0650,
        normal_erp_decade=0.070,
        earliest_seed_date="2000-01-01",
        rfr_max_stale_days=7,
        data_quality="partial",
        notes="TAIEX via ^TWII. No FRED TW series — TW override scrapes "
              "Investing.com taiwan-10-year-bond-yield page (CBC MTAB1A.CSV "
              "endpoint is 404 as of 2026-05). 0050.TW ETF for TWD-native div "
              "yield. Class B/C per Agent 2 §4.",
        display_index_name="TAIEX",
        display_index_short="TAIEX",
        display_rfr_name="10Y TW Bond Yield",
        display_rfr_short="TW Bond",
        currency_symbol="NT$",
    ),
    "CN": MarketSpec(
        code="CN",
        name="China (MSCI China)",
        currency="CNY",
        yahoo_index="MCHI",                 # iShares MSCI China ETF — USD-listed proxy
        yahoo_etf_for_divy="MCHI",
        fred_rfr_series="",                 # SENTINEL — FRED IRLTLT01CNM156N retired; CN override skips FRED
        fred_rfr_fallback=[],
        analyst_tickers=[],                 # v1 EM dampening (see KR notes); MSCI China is
                                            # tech-heavy (Tencent/Alibaba/PDD/Meituan) — Yahoo
                                            # bottom-up median ran 16%+ on 2026-05-07 vs IMF
                                            # CN nominal GDP ~7.5%. Per Agent 2 §4 CN is
                                            # Class C → trend fallback is the prescribed path.
        min_analyst_tickers=99,
        default_payout_ratio=0.35,
        default_buyback_yield=0.005,
        default_analyst_growth=0.075,       # Agent 2 §4 IMF nominal GDP
        default_rfr_fallback=0.020,         # CGB 10Y latest (~1.7–2.0%)
        trend_growth_fallback=0.075,
        normal_erp_longrun=0.0675,
        normal_erp_decade=0.075,
        earliest_seed_date="2011-01-01",    # MCHI ETF inception 2011-03; pre-2011 truncated v1
        rfr_max_stale_days=14,              # Agent 2 §9 hard-fail above 14d
        data_quality="fallback",
        notes="MSCI China (HK + ADR + selected A) via MCHI ETF level proxy. "
              "MCHI is USD-listed — index-level scale cancels in DDM, but div "
              "yield is FX-translated USD distributions (acceptable v1; flagged "
              "in CHANGELOG). CNDataSource: Investing.com→US+NDF→constant rfr "
              "chain (FRED IRLTLT01CNM156N retired; ChinaBond is JS-only). "
              "Peer onshore series: CN_CSI (CSI 300).",
        display_index_name="MSCI China",
        display_index_short="MSCI",
        display_rfr_name="10Y CGB Yield",
        display_rfr_short="CGB",
        currency_symbol="¥",
    ),
    "CN_CSI": MarketSpec(
        code="CN_CSI",
        name="China (CSI 300 onshore)",
        currency="CNY",
        yahoo_index="510300.SS",            # Huatai-PineBridge CSI 300 ETF (CNY-native)
                                            # used as level proxy because yfinance ^000300.SS
                                            # history only starts 2021-03 (4 yrs); the ETF
                                            # has 14 yrs (2012+). Index level scale cancels
                                            # in DDM — ERP unaffected.
        yahoo_etf_for_divy="510300.SS",     # Same ticker for div yield (CNY-native)
        fred_rfr_series="",                 # SENTINEL — same as CN
        fred_rfr_fallback=[],
        analyst_tickers=[
            "600519.SS", "601318.SS", "300750.SZ", "601398.SS", "600036.SS",
            "000858.SZ", "600900.SS", "601166.SS", "600276.SS", "601628.SS",
        ],
        min_analyst_tickers=4,
        default_payout_ratio=0.40,          # Onshore SOE-bank-heavy (~30%) + consumer (~50%)
        default_buyback_yield=0.003,
        default_analyst_growth=0.075,
        default_rfr_fallback=0.020,
        trend_growth_fallback=0.075,
        normal_erp_longrun=0.0675,
        normal_erp_decade=0.075,
        earliest_seed_date="2012-01-01",    # 510300.SS ETF inception 2012-05; pre-2012 truncated v1
        rfr_max_stale_days=14,
        data_quality="fallback",
        notes="CSI 300 onshore A-share via 000300.SS. CNY-native both sides. "
              "Shares CNDataSource rfr chain with CN (Investing.com→US+NDF→"
              "constant). Onshore-investor pricing — capital-controlled, "
              "distinct ERP from MCHI series.",
        display_index_name="CSI 300 (ETF unit, 510300.SS)",
        display_index_short="CSI",
        display_rfr_name="10Y CGB Yield",
        display_rfr_short="CGB",
        currency_symbol="¥",
    ),
}


def get_market(code: str) -> MarketSpec:
    """Look up a market by ISO-ish code. Raises KeyError with a helpful message."""
    try:
        return MARKETS[code]
    except KeyError as e:
        known = ", ".join(sorted(MARKETS))
        raise KeyError(f"Unknown market {code!r}. Known markets: {known}") from e
