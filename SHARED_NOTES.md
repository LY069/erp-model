# Multi-Market ERP Expansion — Shared Working Notes

**Project:** Extend the existing SP500 ERP model to also cover Europe, China, Japan, India, Korea, Taiwan, UK — same Damodaran 2-stage FCFE/DDM methodology.
**Constraint:** User has Claude monthly plan only (no API calls). App must run locally; eventual GitHub deployment.
**Starting state:** SP500-only, Flask + SQLite + compiled React SPA. Frontend source is NOT in this repo (bundled artifact only).

---

## Agent 1 — Senior Full-Stack Dev + Data Scientist (Phase 1 Exploration)

### Stack
- **Backend:** Python 3 / Flask on port 5001 (server.py)
- **CLI:** main.py (argparse)
- **DB:** SQLite at `~/erp_model.db`
- **Solver:** scipy (erp_calculator.py, 829 lines — Damodaran 2-stage DDM via Newton-Raphson)
- **Frontend:** Pre-compiled React SPA (erp_dashboard.html + assets/) — source lives outside this folder at `/erp-dashboard/src/`

### Flask API surface (server.py)
`/`, `/api/status`, `/api/latest`, `/api/history`, `/api/stats`, `/api/update` (POST), `/api/compute` (POST), `/api/forecast` (POST), `/api/forecasts`, `/api/breakeven` (GET/POST), `/api/log`.

### Database schema — PARTIALLY multi-market ready
| Table | Current PK | Needed |
|---|---|---|
| `erp_inputs` | `date` | add `market` → PK `(date, market)` |
| `erp_computations` | `(date, method)` | add `market` → PK `(date, market, method)` |
| `erp_forecasts` | has `scenario` | add `market` column |
| `erp_breakeven` | OK | add `market` column |
| `calculation_log` | OK | global; no change |

### Methodology (see MODEL_SPECIFICATION.md + erp_calculator.py)
- Damodaran 2-stage augmented DDM / FCFE
- Base CF: FCFE = EPS × payout (78.85%)  |  DDM = Index × (divY + buybackY)
- Growth: years 1–2 = analyst consensus; years 3–5 linear ramp to terminal
- Terminal growth = risk-free (T-bond) rate — Damodaran's key assumption
- Solve for r such that Σ PV(CF) + PV(TV) = Index level. ERP = r − rfr.
- Normal ERP bands: long-run 4.25%, decade 5.19% (US-only historical)

### Current SP500-specific hardcodes
| Location | Value |
|---|---|
| config.py:29 | `YAHOO_SP500_TICKER = "^GSPC"` |
| config.py:32 | `FRED_TBOND_SERIES = "DGS10"` |
| config.py:40 | `DEFAULT_ANALYST_GROWTH = 0.08` |
| config.py:44 | `DEFAULT_BUYBACK_YIELD = 0.02` |
| config.py:47 | `DEFAULT_PAYOUT_RATIO = 0.7785` |
| data_fetcher.py:~120 | `yf.Ticker("SPY")` for div yield |
| data_fetcher.py:~155 | FRED DGS10 / ^TNX fallback |
| data_fetcher.py:327–341 | top-15 US constituent tickers for analyst growth |
| erp_calculator.py:647–648 | `NORMAL_ERP_LONGRUN`, `NORMAL_ERP_DECADE` (US only) |

### Proposed data sources per market
| Market | Index | ETF | Risk-free | Analyst growth | Notes |
|---|---|---|---|---|---|
| US | ^GSPC | SPY | FRED:DGS10 | Yahoo top-15 | ✓ working |
| UK | ^FTSE | VUKE.L | FRED:IRLTLT01GBM156N | Yahoo (HSBC, Unilever, BP, Shell, AZN…) | mostly-free |
| Europe | ^STOXX | EXSA.DE | ECB Bund (FRED:IRLTLT01DEM156N) | Yahoo (SAP, ASML, LVMH, Nestlé, Novo) | mostly-free |
| Japan | ^N225 | EWJ | FRED:IRLTLT01JPM156N | Yahoo (7203.T, 6758.T, 9984.T…) | EPS tricky |
| China | 000300.SS | FXI/MCHI | FRED:IRLTLT01CNM156N | Limited; fallback to fixed default | free data scarce |
| India | ^NSEI | INDA | FRED:INDIRLTLT01STM | Limited | fallback default |
| Korea | ^KS11 | EWY | FRED:IRLTLT01KRM156N | Yahoo (005930.KS, 000660.KS…) | partial |
| Taiwan | ^TWII | EWT | FRED proxy or KRW/TWD bond | Very limited | fallback default |

### Assumptions that hold vs. change across markets
**Hold:** terminal growth = rfr; 2-stage solver; 5yr horizon; ramped growth schedule
**Change:** payout ratio (EU ~65%, JP ~35%); buyback yield (mostly 0 outside US); analyst growth baseline; normal ERP benchmarks; rfr currency/instrument

### Files needing changes
- MODIFY: config.py, database.py, data_fetcher.py, erp_calculator.py, server.py, main.py, visualization.py, seed_historical.py
- CREATE: markets_config.py
- FRONTEND: rebuild from `/erp-dashboard/src/` (out of scope for first pass — can use query-param hack on existing bundle)

---

## Agent 2 — Senior Equity Analyst

**Scope:** calibrate the Damodaran 2-stage FCFE/DDM engine for 7 non-US markets. Same solver, different inputs. Below are developer-ready rules (tables first, prose second).

### 1. Index choice per market

| Market | Recommended index | Yahoo ticker | Alt. considered | Rationale |
|---|---|---|---|---|
| UK | FTSE 100 | `^FTSE` | FTSE All-Share | Liquid, deep analyst coverage, daily EPS aggregates via iShares ISF. FTSE 100 ~80% non-GBP revenue — flag for FX sensitivity. |
| Europe ex-UK | STOXX Europe 600 | `^STOXX` | Euro STOXX 50 | 600 is the broad measure Damodaran uses for "Europe"; 50 is too mega-cap skewed. Multi-currency but quoted EUR. |
| Japan | **TOPIX** | `^TOPX` | Nikkei 225 | **Use TOPIX.** Nikkei is price-weighted (distorted by Fast Retailing, SoftBank), not a valuation benchmark. TOPIX is cap-weighted, ~2,100 names, matches Damodaran's Japan aggregate. Flag: yfinance coverage of `^TOPX` is spottier than `^N225` — keep N225 as data fallback but compute ERP on TOPIX fundamentals. |
| China | **MSCI China** (via ETF `MCHI`) | `MCHI` as level proxy; `000300.SS` for onshore | CSI 300, SSE Composite | **Use MSCI China for ERP headline.** CSI 300 is onshore A-share only (capital-controlled, domestic-investor pricing); MSCI China includes H/ADR/A and matches Damodaran's "China" country row. Run CSI 300 as a secondary onshore-ERP series if useful — different risk-free (CGB) applies. |
| India | NIFTY 50 | `^NSEI` | NIFTY 500, BSE Sensex | NIFTY 50 has the best Yahoo EPS/dividend aggregation and analyst coverage on top names. Damodaran uses Sensex historically but NIFTY is the modern benchmark. |
| Korea | KOSPI (composite) | `^KS11` | KOSPI 200 | Composite gives broader earnings base; KOSPI 200 is the futures/ETF vehicle. Use `^KS11` for level, `EWY` as fallback. |
| Taiwan | TAIEX (TWSE weighted) | `^TWII` | MSCI Taiwan | TAIEX is the native market-cap index; TSMC ~30% weight — flag concentration risk in payout/growth calibration. |

### 2. Risk-free rate per market

Damodaran rule: 10-yr local-currency sovereign yield for the country, then strip default spread if the sovereign is not AAA (to get a "risk-free" rate). For mature AAA/AA markets use the raw yield; for EM use yield minus CDS/default spread.

| Market | Instrument | Tenor | Primary source | Fallback | Strip default spread? |
|---|---|---|---|---|---|
| UK | Gilt | 10Y | FRED `IRLTLT01GBM156N` (monthly OECD) | BoE daily yield curve CSV (free) | No (AA, ~20bp spread — ignore) |
| Europe | Bund | 10Y | FRED `IRLTLT01DEM156N` | ECB SDW (free API) | No (AAA) |
| Japan | JGB | 10Y | FRED `IRLTLT01JPM156N` | MoF Japan daily CSV (free) | No (A+, negligible) |
| **China** | **CGB onshore** | **10Y** | **No clean FRED series** | See fallback rule ↓ | **Yes, strip ~60–80 bp country risk** |
| India | GoI bond | 10Y | FRED `INDIRLTLT01STM` (monthly) | RBI daily bulletin (scrape) | Yes, strip India CDS/CRP |
| Korea | KTB | 10Y | FRED `IRLTLT01KRM156N` | BoK ECOS API (free, key) | Yes, strip Korea CRP (~30bp) |
| Taiwan | TW central govt bond | 10Y | **No FRED series** | See fallback ↓ | Yes, strip Taiwan CRP |

**China fallback (important, free):** FRED series `IRLTLT01CNM156N` exists but is monthly and often stale. Preferred chain:
1. Try FRED `IRLTLT01CNM156N`.
2. Else scrape ChinaBond 10Y yield from `chinabond.com.cn` (daily, free, Chinese site — stable HTML table).
3. Else Investing.com "China 10-Year" (free, needs user-agent header).
4. Last resort: `US 10Y + (USDCNY 10Y NDF-implied spread)`, documented in code.
Set a `stale_days_threshold = 7`; raise a warning if the China rfr is older than that.

**Taiwan fallback:** no FRED. Use Taiwan's central bank MoF Bond Yield Curve CSV (free, daily) OR proxy with `US 10Y + Taiwan 5Y CDS spread`. Document the proxy clearly in the row provenance.

### 3. Payout ratio calibration

Source anchors: Damodaran's country data tables (`ctryprem.html`, `countrystatret.html`), IMF WEO dividend payout, MSCI factsheets (payout on the index). These are **annual** and drift — set as defaults but allow per-run override.

| Market | Starting payout (div+bb) | Buyback yield material? | Rationale / source |
|---|---|---|---|
| US (ref) | 78.85% | Yes (~2.0%) | Damodaran Jan 2026; anchors the model. |
| UK | **60%** | Modest (~1.0–1.5%) | FTSE 100 div yield ~3.7%, payout ratio historically 45–55%; add ~10pp buyback contribution (BP, Shell, HSBC, AZN active repurchasers). Source: UK Dividend Study (Link/Computershare), Damodaran UK row. |
| Europe (STOXX 600) | **55%** | Small (~0.8%) | Dividend culture strong (div yield ~3.2%) but buybacks structurally lower than US; rising post-2020. Source: STOXX factsheet + JPM Europe payout study. |
| Japan | **40%** | **Rising — material (~1.5%)** | Historically 25–30%, but post-2023 TSE "PBR <1" reform push has lifted payouts; TOPIX aggregate ~35–40% for FY24. Flag: buybacks grew 2x in 2023–2025; include. Source: Nikkei/TSE disclosures, Damodaran Japan row. |
| China (MSCI China) | **35%** | Low (~0.5%) | Mainland dividend policy improving but still low; SOE banks pay ~30%, tech pays less. Buybacks historically de minimis but HK-listed tech (Tencent, Alibaba) started material programs 2023+. Source: MSCI China factsheet. |
| India | **35%** | Negligible (<0.3%) | Indian firms retain for reinvestment; NIFTY 50 payout ~30–35%. Buybacks exist (tech) but swamped by new issuance. Source: NSE, Damodaran India row. |
| Korea | **30%** | Small (~0.7%) | Chronic "Korea discount"; historically 20–25%. 2024–25 Corporate Value-up Program nudging to ~30%. Chaebol-heavy → buybacks by Samsung, Hyundai. |
| Taiwan | **65%** | Low (~0.3%) | Taiwan has high dividend culture (div yield ~3.5–4.0%); TSMC pays ~50% of EPS; insurers/banks higher. Payout ratio closer to UK than to Korea. |

**Developer rule:** store these as `DEFAULT_PAYOUT_RATIO[market]` and `DEFAULT_BUYBACK_YIELD[market]` in `markets_config.py`. Add a `payout_source_note` string field for provenance. Refresh annually against Damodaran's `ctryprem.html` update.

**Total-shareholder-yield construction (DDM method):**
```
total_yield[mkt] = div_yield_trailing + buyback_yield_default[mkt]
```
Markets where buyback_yield is nonzero default: US, UK, Europe, Japan, Korea. China/India/Taiwan default buyback to 0 but allow override.

### 4. Analyst growth input

Classification key: **(A)** Yahoo bottom-up works, **(B)** Partial + fallback, **(C)** No free analyst data, use trend-growth proxy.

| Market | Class | Top-5 tickers to verify Yahoo EPS-estimates coverage | Rule |
|---|---|---|---|
| UK | **A** | `SHEL.L`, `AZN.L`, `HSBA.L`, `ULVR.L`, `RIO.L` | Use top-15 FTSE100 by weight (matches US approach). Confirm `get_analyst_price_targets` and `earnings_estimate` on each. |
| Europe | **A** | `ASML.AS`, `NESN.SW`, `MC.PA`, `SAP.DE`, `NOVO-B.CO` | Top-15 STOXX 600 by weight. Multi-exchange — handle suffixes in a per-ticker list. |
| Japan | **B** | `7203.T` Toyota, `6758.T` Sony, `9984.T` SoftBank, `8306.T` MUFG, `6861.T` Keyence | Yahoo .T tickers have analyst data but **coverage is thinner** than US — often only FY1. Fallback: if ≥10 of top-15 return usable FY1+FY2, compute median; else fall back to `BoJ inflation target (2%) + real GDP trend (0.5%) + earnings leverage (1%)` ≈ 3.5% nominal. Damodaran has historically used ~5–6% for Japan. |
| China | **C** | `0700.HK` Tencent, `9988.HK` Alibaba, `BABA`, `PDD`, `3690.HK` Meituan | Yahoo coverage of A-shares is poor; HK/ADR coverage OK but not representative of MSCI China aggregate. **Rule: use country trend growth = IMF WEO nominal GDP forecast 5Y CAGR** (currently ~7–8% for China). Allow user override. |
| India | **C** (leaning B) | `RELIANCE.NS`, `TCS.NS`, `HDFCBANK.NS`, `INFY.NS`, `ICICIBANK.NS` | `.NS` tickers have spotty Yahoo forecast data; BSE (`.BO`) similar. **Rule: use IMF nominal GDP 5Y CAGR (~10–11%) as primary; blend with Yahoo median if ≥8 of top-15 return.** |
| Korea | **B** | `005930.KS` Samsung, `000660.KS` SK Hynix, `005380.KS` Hyundai, `035420.KS` Naver, `051910.KS` LG Chem | Yahoo `.KS` coverage moderate; chaebol names yes, mid-caps no. Require ≥8 of top-15 to use median; else nominal GDP trend (~5%). |
| Taiwan | **B/C** | `2330.TW` TSMC, `2317.TW` Hon Hai, `2454.TW` MediaTek, `2882.TW` Cathay FHC, `1301.TW` Formosa Plastics | TSMC dominates (~30%). Yahoo `.TW` analyst coverage acceptable for top-10, thin below. **Rule: median of top-10 if ≥7 return; else trend growth (~4–5%).** |

**Developer rule (concrete):**
```python
def fetch_analyst_growth(market):
    tickers = TOP_CONSTITUENTS[market]  # pre-curated top-15
    rates = [yf_fy1_fy2(t) for t in tickers]
    valid = [r for r in rates if r is not None and -0.2 < r < 0.6]
    min_required = MIN_TICKERS[market]   # 10 for A, 8 for B, 6 for C
    if len(valid) >= min_required:
        return median(valid)
    return TREND_GROWTH_FALLBACK[market]  # IMF WEO or historical average
```
`TREND_GROWTH_FALLBACK`: US 8.0%, UK 6.5%, EU 6.0%, JP 4.0%, CN 7.5%, IN 10.5%, KR 5.5%, TW 5.0%.

### 5. Normal ERP baseline per market

**Construction rule (Damodaran method):**
```
Normal_ERP[market] = Mature_Market_ERP_US + Country_Risk_Premium[market]
Mature_Market_ERP_US = 4.25% (US long-run implied avg)
CRP = λ × (country default spread)   where λ≈1.5 for EM equity vs bond
Country default spread comes from Damodaran ctryprem.html (sovereign CDS or Moody's rating → spread table)
```

| Market | Long-run ERP (point est.) | Decade avg (2015–25 est.) | Construction notes |
|---|---|---|---|
| US | 4.25% | 5.19% | Given (Damodaran). |
| UK | **4.75%** | ~5.5% | 4.25 + ~0.5 (Aa rating, modest post-Brexit premium). |
| Europe | **4.75%** | ~5.8% | Blended STOXX 600; heavier on Germany (AAA → 0) but meaningful Italy/Spain weight (+0.75–1.0). |
| Japan | **5.00%** | ~5.8% | 4.25 + ~0.75 (A+ rating default spread). Damodaran's Japan ERP has run 5.5–6.5% historically given Japan's deflationary legacy. |
| China | **6.75%** | ~7.5% | 4.25 + ~2.5 (A1 sovereign, but λ scaled up for EM equity vol). Check ctryprem — Damodaran Jan 2026 China ~6.5–7.0%. |
| India | **7.50%** | ~8.0% | 4.25 + ~3.25 (Baa3 sovereign spread ~2.2% × λ=1.5). |
| Korea | **5.75%** | ~6.3% | 4.25 + ~1.5 (Aa2 but EM classification + geopolitical premium). |
| Taiwan | **6.50%** | ~7.0% | 4.25 + ~2.25 (unrated sovereign; cross-strait political risk premium dominates). |

**Developer rule:** hard-code these as `NORMAL_ERP_LONGRUN[market]` and `NORMAL_ERP_DECADE[market]` in `markets_config.py` with a comment `# Refresh each January from Damodaran ctryprem.html`. Add a docstring pointer: `https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/ctryprem.html`. Point estimates above are my best reasoned reconstructions; the developer should verify against the Jan 2026 ctryprem file at build time and log any delta >25 bp.

### 6. Methodology adjustments

**(a) Terminal growth = rfr — holds, with two exceptions:**
- **Japan:** JGB 10Y has traded 0–1% for a decade. Using it as terminal g makes the perpetuity (r − g) blow up relative to a healthy r, but the model doesn't actually degenerate as long as r > g (typical r for Japan ~5–6% vs g ~1% → fine). **However**, a literal low g understates real long-run nominal growth relative to a plausible BoJ-target world. Damodaran's treatment: he uses the local 10Y yield as-is. *Recommendation: follow Damodaran — use JGB 10Y as terminal g; document that Japan ERP will look structurally high vs US because of this.*
- **Negative rates regime:** cap terminal g at max(rfr, 0.5%) as a numerical safeguard. Never let g be negative — the Gordon growth denominator must stay well-defined.

**(b) Country risk premium (CRP) — handled implicitly vs explicitly:**
- The implied solver already prices in CRP because the *local index level* embeds country risk. Solving `Index = Σ CF/(1+r)^t` gives you r that already compensates investors for the country risk. **So do NOT add CRP on top of the solved ERP — the solved ERP *is* the full ERP including CRP.**
- The CRP logic in section 5 is only for the **benchmark/normal ERP reference line**, not for the live solver output. Developer: keep this distinction clear in the UI — "Implied ERP" (solved) vs "Normal ERP benchmark" (4.25 + CRP).

**(c) Currency — local currency everywhere:**
- Rfr and index must be in the same currency. STOXX 600 is EUR → use Bund. FTSE is GBP → use Gilt. TOPIX is JPY → use JGB.
- Exception to flag: FTSE 100 earnings are ~80% non-GBP → EPS is nominally GBP but driven by USD/EUR. Accept the noise; don't attempt unhedging.
- **Do NOT convert to USD.** A USD-ERP requires re-discounting cash flows translated into USD with US rfr, which distorts the "local market pricing risk" interpretation. Report ERPs in local currency; optionally show `ERP_USD_hedged ≈ ERP_local + (CIP-implied FX hedge cost differential)` as a decorative metric if requested.

**(d) Inflation regime:**
- India high inflation → both nominal rfr (~7%) and nominal growth (~10%) are elevated. Model is self-consistent in nominal terms. No change needed.
- Japan low/deflation → same logic in reverse.
- **However:** the analyst-growth fallback should be **nominal GDP**, not real. `TREND_GROWTH_FALLBACK` numbers above are already nominal.
- Add a sanity check: `abs(terminal_g − nominal_gdp_5y) < 4%` — if violated, log a warning.

### 7. Seeding history

Damodaran's `ctrystatret.html` / `histimpl.xls` are US-only. For other markets, use Damodaran's annual country ERP spreadsheets (`ERPbyYear.xlsx`-style if it exists, otherwise manual rebuild) + per-market exchange historical data.

| Market | Realistic start | Primary data source (free) | Notes |
|---|---|---|---|
| UK | **1990** | FTSE 100 monthly levels (Yahoo `^FTSE` back to 1984), BoE 10Y Gilt (BoE stats, free from 1970s), div yield from ONS/FTSE factsheet archives | Clean from 1990. Earlier possible but EPS aggregates thin. |
| Europe | **1992** | STOXX 600 back-history on Yahoo from ~1998; pre-1998 splice from DS Europe total return (academic: Dimson-Marsh-Staunton datasets); Bund from Bundesbank | STOXX 600 inception 1998 — for earlier, splice Euro STOXX or accept 1998 start. |
| Japan | **1985** | TOPIX on `^TOPX` back to 1980s (Yahoo), MoF JGB 10Y from 1987, TSE EPS aggregates from TSE factbook (PDF, annual) | Covers bubble + lost decades — very valuable history. |
| China | **2005** | MSCI China TR (Damodaran country pages + MSCI factsheets), CGB 10Y from 2006 (ChinaBond), CSI 300 from 2005 inception | Pre-2005 data questionable quality. 2005 is a hard floor. |
| India | **1999** | NIFTY 50 (^NSEI) from 1996 on Yahoo, RBI 10Y yield from 1997 monthly, payout/div yield from NSE factbook | 1999 is when earnings aggregates became reliable. |
| Korea | **1995** | KOSPI (^KS11) full history Yahoo, KTB 10Y from 1995 (BoK ECOS), div yield from KRX factbook | Skip/flag 1997 Asian crisis — huge ERP dislocation. |
| Taiwan | **2000** | TAIEX Yahoo, TW 10Y from MoF, TWSE factbook for EPS/div | Pre-2000 available but EPS aggregate reconstruction fragile. |

**Seed strategy:** build one `histimpl_<market>.xlsx` file per market containing (year, index_level, eps, payout, div_yield, rfr). For each year, run `compute_erp()` to get implied ERP offline; store in SQLite with `market` PK. Where Damodaran publishes a country-year ERP directly, use his value as ground truth and reconcile.

**Honest caveat:** full Damodaran-style historical seeding for non-US markets is a multi-week data-engineering effort. For v1, seed only the last 10–15 years per market from Yahoo + FRED, and mark rows `provenance='bootstrap'` vs `provenance='damodaran'`. The UI historical band for non-US markets should disclose the shorter window.

### 8. Priority order for implementation

My ranking differs slightly from the expected US-analyst instinct:

| Rank | Market | Why this order |
|---|---|---|
| 1 | **UK** | Cleanest data (FRED Gilt, Yahoo FTSE), English-language sources, big overlap with US methodology. Lowest engineering risk. Ships the multi-market scaffolding. |
| 2 | **Europe (STOXX 600)** | Same scaffolding as UK. EUR rfr is FRED-clean. Analyst coverage good. Index-constituent list is the main work. |
| 3 | **Japan** | High analyst value (structural reform story, PBR <1 campaign = live thesis). Data is good. Terminal-g edge case documented. Differentiated insight. |
| 4 | **Korea** | Reasonable data, real thesis (Value-up program, Korea discount). Partial analyst coverage manageable. |
| 5 | **India** | Real analyst interest, but data-engineering heavy. Growth fallback rule carries more weight than analyst consensus. Worth it. |
| 6 | **Taiwan** | TSMC-dominated → limited portfolio diversification story, but geopolitical hedging angle. Data thin but doable. |
| 7 | **China** | **Last, intentionally.** Hardest data (onshore rfr, MSCI vs CSI 300 decision, A-share vs offshore behavioral split). Political risk signal is the interesting story but the model's implied ERP will be noisy. Ship only after infrastructure is stable. |

Rationale: ship the mature markets (1–3) in phase 1 to validate the multi-market refactor, then tackle EM (4–7) in phase 2 where data heuristics dominate.

### 9. Validation plan

For each newly implemented market, before declaring it production:

**Level checks:**
1. **Reproduce a known Damodaran point.** Pull Damodaran's January 2026 country ERP from `ctryprem.html` for the market. Our implied ERP for the same date should be within **±100 bp**. Log the delta.
2. **Sign check.** Implied ERP must be positive and in 2–12% range. If outside, flag the row as `status='suspect'` and don't display.
3. **Rfr plausibility.** Compare fetched rfr to OECD monthly reference — delta > 50 bp implies bad data.

**Cross-market sanity:**
4. **EM > DM.** For any date, median(EM ERP) > median(DM ERP). If violated, something's wrong.
5. **Monotonicity with risk.** India ERP > Korea ERP > Japan ERP > UK ERP on any given date (roughly). Persistent inversions = flag.

**Time-series checks:**
6. **Volatility.** Annual ERP change should be < 300 bp absent a named crisis (GFC, COVID, Asian crisis, 2022 inflation). Alert on larger moves.
7. **Correlation with VIX/MOVE proxy.** Monthly ERP changes should correlate positively with volatility regime. Weak correlation is OK; strong negative correlation = model bug.
8. **Terminal growth floor.** `terminal_g > -0.01` always. No negative terminal growth ever reaches the solver.

**Specific numerical checks per market (unit tests):**
- Japan: on 2020-12-31 with JGB ~0.02%, payout 35%, analyst growth ~5%, implied ERP should be in 5.5–7.0%.
- UK: 2025-01 with Gilt ~4.5%, payout 55%, growth ~7%, implied ERP should be in 4.5–6.0%.
- India: 2024-12 with GoI ~7%, payout 30%, growth ~12%, implied ERP should be in 6.5–9.0%.

**Regression guard:** freeze the US model's Jan 2026 output as a golden test (ERP = 4.23% per MODEL_SPECIFICATION.md §6). Any refactor that breaks this number fails CI.

**Known pitfalls to watch:**
- Yahoo `^TOPX` sometimes returns empty on long history requests → add retry + `^N225` splice with documented offset.
- FRED `IRLTLT01*` series are **monthly**. Our daily ERP will hold rfr constant for up to 30 days — flag this latency.
- China rfr staleness is the most likely silent failure mode. Hard-fail the compute if rfr is >14 days old for CN.

---

## Agent 3 — Senior Data Scientist

### TL;DR recommendations
| Question | Decision |
|---|---|
| Market key | Short string (`'US'`, `'UK'`, ...) as column. **No** `markets` ref table. 8 fixed values — a ref table adds a JOIN for zero integrity gain. Enforce with CHECK constraint. |
| PK strategy | Composite `(date, market)` on inputs; `(date, market, method)` on computations. Existing DB migrates cleanly. |
| Currency | Store **local-currency** values + `currency` column. Do NOT cache USD conversions — the solver is currency-local (rfr in local ccy, index in local ccy). Optional `fx_rates` cache only if USD overlay is added later. |
| Storage engine | **Keep SQLite.** 8 × daily × 65yr ≈ 130k rows. DuckDB adds a dependency and gives no win at this size. |
| Cache file | Replace `histimpl_cache.xls` with `data/seed/<MARKET>_historical.csv` — one per market. |
| Layout | Shallow refactor: add `data_sources/`, `migrations/`, `data/seed/`. Everything else stays flat. |
| Scheduling | Manual `python update_markets.py` via a double-clickable `.command` file. No cron/launchd by default. |

---

### 1. Schema redesign (authoritative DDL)

```sql
-- ---------------------------------------------------------------
-- erp_inputs: one row per (date, market). Values in LOCAL currency.
-- ---------------------------------------------------------------
CREATE TABLE erp_inputs (
    date                TEXT    NOT NULL,                 -- YYYY-MM-DD
    market              TEXT    NOT NULL,                 -- 'US','UK','EU','JP','CN','IN','KR','TW'
    currency            TEXT    NOT NULL,                 -- ISO 4217: USD,GBP,EUR,JPY,CNY,INR,KRW,TWD
    index_level         REAL    NOT NULL,                 -- renamed from sp500_level (local CCY)
    dividend_yield      REAL    NOT NULL,                 -- decimal
    buyback_yield       REAL    NOT NULL DEFAULT 0.0,
    total_yield         REAL    NOT NULL,                 -- div + buyback
    analyst_5yr_growth  REAL,
    year1_growth        REAL,
    year2_growth        REAL,
    rfr_rate            REAL    NOT NULL,                 -- renamed from tbond_10yr_rate (local 10Y govt)
    trailing_eps        REAL,
    payout_ratio        REAL,                             -- per-market default in markets_config
    -- provenance & quality -----------------------------------
    data_source         TEXT    NOT NULL DEFAULT 'auto',  -- 'yahoo'|'fred'|'damodaran_csv'|'manual'|'seed'
    growth_source       TEXT,
    index_source        TEXT,                             -- e.g. 'yahoo:^GSPC'
    rfr_source          TEXT,                             -- e.g. 'fred:DGS10'
    divy_source         TEXT,
    fetched_at          INTEGER NOT NULL,                 -- unix ts of network call
    stale_flag          INTEGER NOT NULL DEFAULT 0,       -- 1 if any field was fallback/defaulted
    quality_notes       TEXT,                             -- JSON: {"rfr_fallback":true,...}
    updated_at          INTEGER NOT NULL,
    PRIMARY KEY (date, market),
    CHECK (market IN ('US','UK','EU','JP','CN','IN','KR','TW')),
    CHECK (dividend_yield >= 0 AND dividend_yield < 0.25),
    CHECK (index_level > 0)
);
CREATE INDEX idx_inputs_market_date ON erp_inputs(market, date DESC);
CREATE INDEX idx_inputs_date        ON erp_inputs(date);   -- cross-market slice at a date

-- ---------------------------------------------------------------
-- erp_computations: solved ERP per (date, market, method)
-- ---------------------------------------------------------------
CREATE TABLE erp_computations (
    date                    TEXT    NOT NULL,
    market                  TEXT    NOT NULL,
    method                  TEXT    NOT NULL DEFAULT 'ddm',  -- 'ddm'|'fcfe'
    implied_cost_of_equity  REAL    NOT NULL,
    implied_erp             REAL    NOT NULL,
    pv_stage1               REAL,
    terminal_value          REAL,
    pv_terminal             REAL,
    annual_growth_rates     TEXT,                              -- JSON
    cash_flows              TEXT,                              -- JSON
    solver_iterations       INTEGER,
    solver_method           TEXT,                              -- 'newton'|'brentq'
    model_version           TEXT    NOT NULL DEFAULT 'v1',     -- pins methodology
    computed_at             INTEGER NOT NULL,
    PRIMARY KEY (date, market, method),
    FOREIGN KEY (date, market) REFERENCES erp_inputs(date, market),
    CHECK (implied_erp BETWEEN -0.05 AND 0.25)
);
CREATE INDEX idx_comp_market_date ON erp_computations(market, date DESC);
CREATE INDEX idx_comp_date        ON erp_computations(date);

-- ---------------------------------------------------------------
-- erp_forecasts: scenario projections, now market-scoped
-- ---------------------------------------------------------------
CREATE TABLE erp_forecasts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_at     INTEGER NOT NULL,
    market           TEXT    NOT NULL,
    base_date        TEXT    NOT NULL,
    scenario         TEXT    NOT NULL,
    forecast_year    INTEGER NOT NULL,
    forecast_date    TEXT    NOT NULL,
    index_projected  REAL,                                     -- renamed from sp500_projected
    eps_projected    REAL,
    rfr_projected    REAL,
    growth_projected REAL,
    implied_erp      REAL    NOT NULL,
    implied_r        REAL    NOT NULL,
    CHECK (market IN ('US','UK','EU','JP','CN','IN','KR','TW'))
);
CREATE INDEX idx_fc_market_base ON erp_forecasts(market, base_date, scenario);

-- ---------------------------------------------------------------
-- erp_breakeven: per-market now
-- ---------------------------------------------------------------
CREATE TABLE erp_breakeven (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    computed_at        INTEGER NOT NULL,
    date               TEXT    NOT NULL,
    market             TEXT    NOT NULL,
    index_level        REAL    NOT NULL,
    trailing_eps       REAL    NOT NULL,
    rfr_rate           REAL    NOT NULL,
    breakeven_growth   REAL    NOT NULL,
    normal_erp         REAL    NOT NULL,
    normal_erp_method  TEXT    NOT NULL,                       -- 'longrun'|'decade'|'custom'
    interpretation     TEXT,
    CHECK (market IN ('US','UK','EU','JP','CN','IN','KR','TW'))
);
CREATE INDEX idx_be_market_date ON erp_breakeven(market, date DESC);

-- ---------------------------------------------------------------
-- calculation_log: add market + level
-- ---------------------------------------------------------------
CREATE TABLE calculation_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT,
    market      TEXT,                                          -- NULL = global event
    step        TEXT NOT NULL,                                 -- fetch|compute|forecast|error|info|validate
    level       TEXT NOT NULL DEFAULT 'INFO',                  -- INFO|WARN|ERROR
    message     TEXT NOT NULL,
    created_at  INTEGER NOT NULL
);
CREATE INDEX idx_log_market_date ON calculation_log(market, created_at DESC);

-- ---------------------------------------------------------------
-- update_runs: audit each update_markets.py invocation
-- ---------------------------------------------------------------
CREATE TABLE update_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    INTEGER NOT NULL,
    finished_at   INTEGER,
    markets       TEXT NOT NULL,                               -- JSON array ['US','UK',...]
    status_json   TEXT NOT NULL,                               -- {'US':'ok','UK':'failed:429'}
    git_sha       TEXT,
    model_version TEXT
);
```

**Justifications.**
- **Short-string `market` vs. ref table.** 8 fixed values. A ref table adds a JOIN to every query for zero integrity gain; CHECK is equivalent. Reconsider only if markets ever exceed ~20.
- **Composite PKs.** `(date, market)` matches how every query filters. FK back to inputs from computations is cheap.
- **Indexes.** Three dominant access patterns — latest-by-market → `(market, date DESC)`; single-market history range → same index; cross-market slice at a date → `(date)`. Index overhead at 130k rows is negligible.
- **Currency.** Local-currency only. The Damodaran 2-stage solver is internally consistent only when cash flows, index level, and discount rate share a currency (Agent 2 §6c). An `fx_rates` cache can be joined at query time if a USD overlay is added later.
- **Provenance per field.** `index_source`, `rfr_source`, `divy_source` are separate because fallback chains pick different sources per field on the same date. `stale_flag=1` if ANY field was fallback → UI surfaces a warning badge.
- **`model_version`.** Pins methodology (payout-ratio change, terminal-growth tweak). Lets you re-solve old dates without clobbering the old result; if promoted into the PK later, that's non-breaking.

---

### 2. Migration strategy

`migrations/001_multi_market.py`. Idempotent, no data loss, aligned with Agent 4's Phase 0:

| Step | Action | Risk / mitigation |
|---|---|---|
| 0 | Probe with `BEGIN IMMEDIATE`; abort if Flask is holding the DB. | Prevents journal-file races. |
| 1 | Handle `erp_model.db-journal`: open+close a connection with `PRAGMA journal_mode=DELETE` to flush stale journals. Abort if flush fails. | Journal file = prior crash or live writer. |
| 2 | Copy DB to `~/erp_model.db.bak-pre0` (filename aligns with Agent 4 Risk #1). | Single point of recovery. |
| 3 | `PRAGMA foreign_keys=OFF` for migration body. | Avoids FK churn mid-rebuild. |
| 4 | For each table, probe `PRAGMA table_info`; if `market` absent, `ALTER TABLE ... ADD COLUMN market TEXT NOT NULL DEFAULT 'US'`. | SQLite requires a default for NOT NULL adds; 'US' is exactly the backfill value. |
| 5 | Add new columns in-place: `currency`, `index_source`, `rfr_source`, `divy_source`, `fetched_at`, `stale_flag`, `quality_notes`, `model_version`, `level`. All with safe defaults. | Same pattern as the existing migration at `database.py:105`. |
| 6 | Backfill: `UPDATE erp_inputs SET currency='USD' WHERE market='US' AND currency IS NULL`. `UPDATE ... SET fetched_at=updated_at WHERE fetched_at IS NULL`. | One UPDATE per table. Sub-second on 65yr of US data. |
| 7 | Rebuild tables to install composite PKs (SQLite can't ALTER PK). Pattern: rename → create new → `INSERT ... SELECT` → drop old → recreate indexes. Proven at `database.py:128`. | Wrap in single transaction. All tables < 100k rows — sub-second. |
| 8 | Column renames: `sp500_level → index_level`, `tbond_10yr_rate → rfr_rate`, `sp500_projected → index_projected`. Use `ALTER TABLE ... RENAME COLUMN` (SQLite ≥3.25; macOS ships 3.39+). | Breaks Python callers — do ALL renames + Python call-site edits in one PR. |
| 9 | Create new indexes with `CREATE INDEX IF NOT EXISTS`. | Idempotent. |
| 10 | `PRAGMA foreign_keys=ON`, `VACUUM`, `PRAGMA integrity_check`. | Final sanity. |
| 11 | Stamp `update_runs`: `{markets:['US'], status_json:{'US':'migrated'}}`. | Audit trail. |

**Idempotence guard.** Every step wrapped in `IF NOT EXISTS` or `PRAGMA table_info` probe. Re-running on an already-migrated DB is a no-op that logs "already migrated".

---

### 3. Data source abstraction

**`data_sources/base.py`**

```python
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from typing import Optional, Protocol

@dataclass(frozen=True)
class FetchResult:
    value: Optional[float]
    source: str                  # e.g. 'yahoo:^GSPC' or 'default:0.08'
    fetched_at: int              # unix ts
    is_fallback: bool = False
    note: str = ""

class DataSource(Protocol):
    market: str                  # 'US','UK',...

    def fetch_index_level(self, as_of: date) -> FetchResult: ...
    def fetch_rfr(self, as_of: date) -> FetchResult: ...
    def fetch_dividend_yield(self, as_of: date) -> FetchResult: ...
    def fetch_buyback_yield(self, as_of: date) -> FetchResult: ...
    def fetch_trailing_eps(self, as_of: date) -> FetchResult: ...
    def fetch_analyst_growth(self, as_of: date) -> FetchResult: ...
```

**`data_sources/yahoo_fred.py`** — single generic implementation parameterised by `markets_config`. Per-market quirks live in `data_sources/overrides/<mkt>.py` only when needed (e.g., `jp.py` for TOPIX EPS weighting, `cn.py` for ChinaBond HTML scraping per Agent 2 §2).

**`markets_config.py`**

```python
from dataclasses import dataclass, field

@dataclass(frozen=True)
class MarketSpec:
    code: str                                # 'US'
    name: str                                # 'United States'
    currency: str                            # 'USD'
    yahoo_index: str                         # '^GSPC'
    yahoo_etf_for_divy: str                  # 'SPY'
    fred_rfr_series: str                     # 'DGS10'
    fred_rfr_fallback: list[str] = field(default_factory=list)
    analyst_tickers: list[str] = field(default_factory=list)
    min_analyst_tickers: int = 8             # Agent 2 §4 A/B/C rule
    default_payout_ratio: float = 0.60       # Agent 2 §3
    default_buyback_yield: float = 0.0       # Agent 2 §3
    default_analyst_growth: float = 0.06
    trend_growth_fallback: float = 0.06      # IMF WEO nominal GDP 5Y (Agent 2 §4)
    normal_erp_longrun: float = 0.0475       # Agent 2 §5
    normal_erp_decade: float = 0.055         # Agent 2 §5
    earliest_seed_date: str = "1990-01-01"
    rfr_max_stale_days: int = 7              # CN hard-fails at 14 (Agent 2 §9)
    data_quality: str = "full"               # 'full'|'partial'|'fallback' (Agent 4 Phase 4)
    notes: str = ""

MARKETS: dict[str, MarketSpec] = { "US": ..., "UK": ..., "EU": ..., "JP": ...,
                                   "CN": ..., "IN": ..., "KR": ..., "TW": ... }
```

Concrete values (payouts, tickers, trend-growth fallbacks, normal-ERP anchors) are owned by Agent 2 §3–§5; Agent 3 only provides the container.

**Fallback chains (per field):**

| Field | Primary | Secondary | Tertiary | Final |
|---|---|---|---|---|
| `index_level` | Yahoo `yahoo_index` | Yahoo ETF proxy (`yahoo_etf_for_divy`) | Last DB value (stale=1) | Abort market for this date |
| `rfr_rate` | FRED `fred_rfr_series` | `fred_rfr_fallback[]` | Source-specific scrape (e.g., ChinaBond; Agent 2 §2) | DB last value (stale=1) |
| `dividend_yield` | Yahoo `ETF.info['dividendYield']` | Yahoo 12M trailing distribution ÷ price | DB last value | skip; mark `stale_flag=1` |
| `buyback_yield` | Optional `data/seed/<MKT>_buybacks.csv` | n/a | `market.default_buyback_yield` | 0.0 |
| `trailing_eps` | Weighted Yahoo constituent EPS | Yahoo `earnings_history` | DB last value | None (skip FCFE; DDM only) |
| `analyst_5yr_growth` | Median of Yahoo `earnings_estimate` across `analyst_tickers` (need ≥ `min_analyst_tickers` valid) | DB last value | `market.trend_growth_fallback` | `market.default_analyst_growth` |

Every fallback sets `stale_flag=1` and appends to `quality_notes` JSON. Flag surfaces in `/api/status`.

**Caching & rate limiting:**

| Rule | Value |
|---|---|
| Network budget | ≤ 1 Yahoo call per ticker per trading day; ≤ 1 FRED call per series per day |
| Cache lookup order | in-process memo → SQLite `erp_inputs` row for today → network |
| Staleness threshold | Exchange-calendar aware (via `pandas_market_calendars`): if `fetched_at` falls on the same trading day for the market's exchange, reuse |
| Yahoo throttle | 1.5s sleep between ticker fetches; exponential backoff on 429 (base 4s, cap 60s, 5 retries) |
| FRED throttle | ≥2 s/call (documented 20 req/min cap) |
| Batching | `yf.download(tickers=[...], group_by='ticker')` — one HTTP request per market's analyst list |

`data_fetcher.py` becomes a thin orchestrator that instantiates `DataSource(market)` from `MARKETS[market]` and calls the six fetch methods.

---

### 4. Historical seeding strategy

US keeps `histimpl.xls` + existing `seed_historical.py` path. For each other market, user places a CSV at `data/seed/<MARKET>_historical.csv`. Seeder (extended with `--market`) loads that CSV and runs `compute_erp()` per row. Dates and source notes align with Agent 2 §7.

| Market | Earliest | Free data source | Delivery |
|---|---|---|---|
| US  | 1961 | `histimpl.xls` (Damodaran) — already wired | **existing** |
| UK  | 1990 | FTSE 100 Yahoo back-history; Gilt 10Y BoE stats CSV; divy ONS/FTSE factsheet archives | **User uploads `data/seed/UK_historical.csv`** |
| EU  | 1998 | STOXX 600 Stoxx.com CSV (splice earlier via Euro STOXX); Bund 10Y ECB SDW / FRED; divy Stoxx factsheet | **User uploads `data/seed/EU_historical.csv`** |
| JP  | 1985 | TOPIX stooq daily; JGB 10Y MoF; TSE factbook PDFs for EPS/divy | **User uploads `data/seed/JP_historical.csv`** |
| CN  | 2005 | MSCI China TR (MSCI factsheets); CGB 10Y ChinaBond; CSI 300 stooq | **User uploads `data/seed/CN_historical.csv`** |
| IN  | 1999 | NIFTY 50 stooq/NSE; RBI 10Y monthly bulletin; divy NSE factbook | **User uploads `data/seed/IN_historical.csv`** |
| KR  | 1995 | KOSPI Yahoo full history; KTB 10Y BoK ECOS; divy KRX factbook | **User uploads `data/seed/KR_historical.csv`** |
| TW  | 2000 | TAIEX Yahoo; TW 10Y MoF; TWSE factbook for EPS/divy | **User uploads `data/seed/TW_historical.csv`** |

**Universal seed CSV schema** — `data/seed/<MARKET>_historical.csv`:

```
date,index_level,dividend_yield,buyback_yield,rfr_rate,trailing_eps,analyst_5yr_growth,payout_ratio,source,notes
2024-12-31,8173.02,0.0385,0.0050,0.0457,,0.08,0.65,FTSE factsheet + FRED,
2023-12-31,7733.24,0.0403,0.0045,0.0356,,0.07,0.65,FTSE factsheet + FRED,
```

- `date` ISO 8601.
- Yields and rates as decimals (0.0385, not 3.85).
- `trailing_eps` optional — if blank, seeder computes DDM only.
- `buyback_yield` defaults to 0 for markets where it's immaterial.
- `source` → `data_source` column; `notes` → `quality_notes` JSON field.

Every seeded row marked `data_source='seed:<MARKET>'` so it is distinguishable from live-fetched rows in quality reports.

---

### 5. Data pipeline architecture (local-first)

**`update_markets.py`** — one command, all markets, per-market error isolation.

```
python update_markets.py                    # today, all 8 markets
python update_markets.py --markets US,UK    # subset
python update_markets.py --date 2024-12-31  # backfill one historical date
python update_markets.py --dry-run          # fetch + validate but don't write
python update_markets.py --validate-only    # re-run quality checks over DB
```

**Execution flow:**

1. Open `update_runs` row with `status='running'`.
2. For each market (independent try/except — one failure doesn't abort others):
   1. Build `DataSource(market)` from `MARKETS[market]`.
   2. Fetch the 6 fields concurrently within the market (threads — network IO bound).
   3. Apply validation gates (table below).
   4. `upsert_inputs(market=...)`.
   5. `compute_erp(method='ddm')`; then `compute_erp(method='fcfe')` only if EPS present.
   6. Record `'US':'ok'` or `'UK':'failed: yahoo 429 after 5 retries'` in `status_json`.
3. Finalise `update_runs` (`finished_at`, final `status_json`).
4. Print summary table; exit non-zero if any market failed.

**Scheduling recommendation: MANUAL.**
- Ship a double-clickable `Update ERP Data.command` (mirrors `Start ERP Server.command`) that activates the venv and runs the CLI.
- cron/launchd is misfire-prone on a laptop that sleeps; Yahoo data is only meaningful post-close; the analyst runs this when they sit down to work.
- Provide a `launchd` recipe in the README as an optional advanced setup (aligns with Agent 4 Phase 5 automation) — don't configure by default for v1.

**Staleness detection** (surfaced via `/api/status`):
- `MAX(date)` per market in `erp_inputs`.
- Using `pandas_market_calendars` per exchange, if `(last_trading_day_before_now - max_date) > 1`, flag stale.
- Return `{"US": {"last_update": "2026-04-15", "stale": false}, ...}` to the frontend.

**Validation gates (applied before upsert):**

| Check | Reject range | Action |
|---|---|---|
| `index_level` | `<=0` or `>10×` prior day | reject row |
| `dividend_yield` | `<0` or `>0.10` | reject row |
| `buyback_yield` | `<0` or `>0.08` | clip to `[0, 0.08]`; stale_flag=1 |
| `rfr_rate` | `<-0.01` for markets ∉ {JP, EU} | reject row |
| `rfr_rate` | `>0.20` for all markets | reject row |
| `analyst_5yr_growth` | outside `[-0.05, 0.30]` | clip; stale_flag=1 |
| `implied_erp` (post-solve) | outside `[-0.02, 0.15]` | keep row, log ERROR, set quality_notes flag |
| Day-over-day `|Δg|` | `>5 pp` | WARN only (genuine revisions happen) |
| Day-over-day `|%Δindex|` | `>20%` | WARN (could be crisis — don't reject) |
| rfr staleness | `> market.rfr_max_stale_days` | WARN; CN hard-fail at >14 days (Agent 2 §9) |

Rejected rows log `level='ERROR'` to `calculation_log`; the previous good row remains latest.

---

### 6. Caching & performance

**Size math.** 8 markets × ~16,000 trading days (65 yr) × 1 input row = **≈ 130k rows**; × 2 methods for computations ≈ 260k rows. Total DB file projected < 50 MB.

**Recommendation: stay on SQLite.**
- DuckDB wins only above ~10M rows or heavy OLAP — neither applies.
- SQLite works with Flask's single-writer model; existing `PRAGMA journal_mode=DELETE` (chosen for FUSE/network compatibility at `database.py:25`) stays.
- Git-ignore the DB file (matches Agent 4 §4); commit only migrations and seed CSVs.

**Optional new cache tables (add only when needed):**

```sql
CREATE TABLE fx_rates (              -- add if/when USD overlay appears in UI
    date        TEXT NOT NULL,
    ccy         TEXT NOT NULL,       -- GBP, EUR, JPY, ...
    usd_per_ccy REAL NOT NULL,
    source      TEXT NOT NULL,
    PRIMARY KEY (date, ccy)
);

CREATE TABLE http_cache (            -- only if Yahoo throttling becomes painful
    url_hash   TEXT PRIMARY KEY,
    url        TEXT NOT NULL,
    payload    BLOB NOT NULL,
    fetched_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);
```

**Inline vs. separate cache tables.** Raw inputs stay inline in `erp_inputs` — they *are* the cache. Split out only (a) values shared across markets (FX) or (b) HTTP-level artefacts (http_cache). Do NOT create an `inputs_cache` shadow table — that's duplication.

---

### 7. Data quality monitoring

Run on every `update_markets.py` pass; also `python update_markets.py --validate-only`. Emit to `calculation_log`; write `output/quality_report_<YYYY-MM-DD>.md` summary.

| Check | Signal | Threshold |
|---|---|---|
| Missing weekday rows per market | gaps in last 30 trading days (exchange-calendar aware) | >2 gaps → WARN |
| rfr day-over-day move | `|Δrfr|` | >50 bp → WARN; >150 bp → ERROR |
| Index day-over-day move | `|%Δ|` | >5% → WARN; >15% → ERROR |
| Analyst-growth jump | `|Δg|` | >5 pp → WARN |
| ERP plausibility | in `[-2%, +15%]` | outside → ERROR (flag, keep row) |
| EM > DM ordering | median(ERP_EM) vs median(ERP_DM) at a date | EM < DM → WARN (Agent 2 §9 sanity) |
| Cross-market correlation | `corr(ΔERP_US, ΔERP_EU)` over 60 trading days | `< -0.3` → WARN |
| Same-day divergence | `|ΔERP_US − ΔERP_EU|` day-over-day on non-crisis days | `>3 pp` → WARN |
| Benchmark recon (monthly) | US ERP vs Damodaran's published monthly implied ERP | `|Δ| > 30 bp` → WARN |
| Seed coverage | every year ≥ `market.earliest_seed_date` has ≥1 row | missing year → ERROR (block production) |

No external CI-driven hard-fail for cross-market checks (Agent 4 §6 explicitly excludes this) — log WARN only. Local-only by constraint.

---

### 8. File layout recommendation

**Recommended: shallow refactor.** Current flat layout stops working once we add 8 configs, per-source modules, migrations, and seed CSVs. Top-level Python stays flat (that's the public import surface); fold new *collections* into folders.

```
ERP Model/
├── config.py                        # global config (DB path, solver, API keys)
├── markets_config.py                # NEW — MarketSpec registry for 8 markets
├── database.py                      # schema + DAL (market-aware)
├── data_fetcher.py                  # thin orchestrator over data_sources/
├── erp_calculator.py                # unchanged solver
├── server.py                        # Flask API (accepts ?market=XX)
├── main.py                          # CLI (--market flag)
├── update_markets.py                # NEW — multi-market daily refresh
├── seed_historical.py               # extended with --market flag
├── visualization.py
│
├── data_sources/                    # NEW
│   ├── __init__.py
│   ├── base.py                      # Protocol + FetchResult
│   ├── yahoo_fred.py                # generic impl driven by MarketSpec
│   └── overrides/                   # per-market quirks only when needed
│       ├── jp.py                    # TOPIX EPS weighting
│       └── cn.py                    # ChinaBond fallback scraping
│
├── migrations/                      # NEW
│   ├── 001_multi_market.py
│   └── README.md
│
├── data/                            # NEW — git-tracked inputs
│   └── seed/
│       ├── US_historical.csv        # optional; keep histimpl_cache.xls if preferred
│       ├── UK_historical.csv
│       ├── EU_historical.csv
│       ├── JP_historical.csv
│       ├── CN_historical.csv
│       ├── IN_historical.csv
│       ├── KR_historical.csv
│       └── TW_historical.csv
│
├── output/                          # existing
├── assets/                          # existing (frontend bundle)
├── erp_dashboard.html               # existing
└── tests/                           # NEW — minimal smoke tests
    ├── test_database.py
    ├── test_data_sources.py
    └── test_validation.py
```

**Flat:** `config.py`, `database.py`, `server.py`, etc. — moving them churns every import for no gain.
**Folder:** only things that come in multiples and share a pattern (data sources, migrations, seed files, tests).

---

### Handoff notes to Agent 4 (PM)

- Migration is a one-shot chore. Sequence: write `migrations/001_multi_market.py` → run on a copy of `~/erp_model.db` → verify → run on live → **then** start touching `data_fetcher.py`. Do not overlap (aligns with Agent 4 Phase 0 → Phase 1 split).
- `markets_config.py` is the single choke point controlling which markets exist. Must land **before** `update_markets.py`. Phase 0 ships it as a US-only stub per Agent 4.
- Biggest unknown: buyback yield outside US. Default to 0 and add a manual override CSV (`data/seed/<MKT>_buybacks.csv`) later if the analyst wants it (matches Agent 2 §3).
- EPS quality for CN/IN/TW limits FCFE coverage. DDM works everywhere; for v1 ship FCFE in US+UK+EU+JP+KR only.
- Agent 2's market priority (UK → EU → JP → KR → IN → TW → CN) is also the right ship sequence for this schema — each market is independent once the migration and config exist. Matches Agent 4's Phase 1 → Phase 4 ordering.

---

## Agent 4 — Project Manager

### 1. Phasing plan (6 phases, each shippable)

**Phase 0 — Git + DB migration scaffold (backward-compatible).**
- Goal: repo under version control; schema gains `market` column with `'US'` default; nothing user-visible changes.
- Scope: create `.gitignore`, `git init`, initial commit. Modify `database.py` (idempotent migration runner that ALTERs existing tables, backfills `market='US'`), add `markets_config.py` stub with only US entry, add `CHANGELOG.md` + `MIGRATION.md`.
- Exit criteria: `python server.py` still starts; dashboard still loads 65yr SP500 history; `sqlite3 ~/erp_model.db ".schema erp_inputs"` shows `market` column; `git log` has one commit.
- Risk: migration corrupts user's existing `~/erp_model.db`. Mitigation: migration backs up to `~/erp_model.db.bak-pre0` before any ALTER, and short-circuits if `market` column already exists.

**Phase 1 — UK end-to-end (second market, proves the pattern).**
- Goal: one non-US market fully working through the stack.
- Scope: `markets_config.py` UK entry (FTSE 100, VUKE.L, Gilt rfr chain, payout 0.60, buyback 0.012, top-15 UK constituents per Agent 2 §1). `data_fetcher.py` fully parameterised by market. `erp_calculator.py` pulls normal-ERP bands from market config. `server.py` accepts `?market=UK` on every GET endpoint and `"market"` on every POST body. `main.py` gains `--market UK`. Seed UK history from 1990 (Agent 2 §7).
- Exit criteria: `python main.py --update --market UK --report` prints a UK ERP in [4.0%, 6.5%] (Agent 2 §9 unit test). `curl 'localhost:5001/api/history?market=UK'` returns ≥30 annual points. US path unchanged when `--market` omitted (default `'US'`).
- Risk: FRED IRLTLT01GBM156N is monthly (stale up to 30 days); Yahoo FTSE EPS aggregates thin pre-2000. Mitigation: Agent 2's fallback chain (BoE daily curve); seed floor = 1990.

**Phase 2 — Frontend market switcher (without rebuilding the React bundle).**
- Goal: user picks market in the browser.
- Scope: since `/erp-dashboard/src/` is off-repo, add a top-strip `<div>` injected into `erp_dashboard.html` with a `<select>` that sets `window.__ERP_MARKET__` + `localStorage.market` and monkey-patches `window.fetch` to append `?market=X` (or merge into POST JSON) for any URL containing `/api/`. If the minified bundle fights the patch, fallback is a server-side session default: `POST /api/set_market` + page reload.
- Exit criteria: Open dashboard, pick "UK" from the visible selector, chart redraws to UK series (starts ~1990), current-ERP card shows a UK number within Agent 2's plausibility bands. Flip back to "US" — 65yr chart returns unchanged.
- Risk: compiled bundle's bundled React refuses the fetch monkey-patch. Mitigation: fallback to two hardcoded HTMLs (`erp_dashboard.html`, `erp_dashboard_uk.html`) and flag the React-source recovery as a separate user task (see Risk #3 below).

**Phase 3 — Developed markets tier (Europe, Japan).**
- Goal: add STOXX 600 and TOPIX (not Nikkei — Agent 2 §1).
- Scope: two entries in `markets_config.py`; Bund and JGB rfr chains; EU payout 0.55 + buyback 0.008; JP payout 0.40 + buyback 0.015 (Agent 2 §3). Seed EU from 1992, JP from 1985. Zero new code — config-only phase.
- Exit criteria: dropdown shows 4 markets; each hits Agent 2 §9 numerical checks (JP 2020-12-31 in [5.5%, 7.0%]); no 500s when cycling markets in the UI.
- Risk: yfinance `^TOPX` long-history gaps. Mitigation: Agent 2's `^N225` splice with documented offset; unit-test the splice date.

**Phase 4 — Emerging markets tier (China, India, Korea, Taiwan).**
- Goal: all 8 markets live, accepting degraded analyst-growth inputs per Agent 2's Class C rule.
- Scope: 4 config entries. Each declares `data_quality` ∈ `{full, partial, fallback}`. China's rfr uses Agent 2's 4-step fallback chain (FRED → ChinaBond scrape → Investing.com → US+NDF spread). Taiwan uses MoF CSV or US+CDS proxy. India and Korea allow Yahoo median with fallback to IMF WEO nominal GDP.
- Exit criteria: all 8 markets return a number; EM markets display a "data quality: partial/fallback" badge in the UI; Agent 2's cross-market sanity checks pass (EM median > DM median; IN > KR > JP > UK on the same day).
- Risk: FRED EM series go stale or disappear; ChinaBond HTML changes. Mitigation: `stale_days_threshold = 7` with hard-fail above 14 days for CN (Agent 2 §9); fallback chain; weekly CI smoke test catches breakage within a day.

**Phase 5 — Scheduled local data refresh + GitHub publication.**
- Goal: app stays fresh without user running commands; code + snapshot JSON public on GitHub.
- Scope: `launchd` plist at `~/Library/LaunchAgents/local.erp.refresh.plist` running `python main.py --update --all-markets` daily at 18:00 local (macOS). `scripts/publish_snapshot.py` dumps latest + history to `docs/data/{market}.json`. GitHub Actions: `lint.yml` (ruff + import smoke), `smoke.yml` (`--validate` against Damodaran 1999 + golden test for Jan 2026 US = 4.23% per Agent 2 regression guard), `snapshot.yml` (nightly fetch + commit JSON to `docs/`). Push repo public.
- Exit criteria: repo public on GitHub; Actions green on `main`; after 24h, `docs/data/US.json` has today's date; `launchctl list | grep erp` shows the job; `docs/index.html` (minimal static reader) renders all 8 markets from the committed JSON.
- Risk: launchd fires while Mac is asleep. Mitigation: `StartCalendarInterval` + `RunAtLoad`; updater is idempotent (skips if today already computed per market).

### 2. Per-phase validation (concrete user actions)

| Phase | User does | Passes if |
|---|---|---|
| 0 | `git log --oneline` then `python server.py` and open dashboard | Exactly 1 commit; dashboard still shows 65yr US chart; no behavioural change |
| 1 | `python main.py --update --market UK --report` then `curl 'localhost:5001/api/history?market=UK' \| jq '.count'` | UK ERP in [4.0%, 6.5%]; history count ≥30 |
| 2 | Open `erp_dashboard.html`, pick UK, pick back to US | Both redraws < 2s, no console errors, current-ERP cards differ by market |
| 3 | Cycle dropdown US → UK → EU → JP | Each renders within 2s; JP on last trading day shows a finite ERP in [5.0%, 7.5%]; no 500s in server log |
| 4 | Cycle all 8 markets | All render; EM shows data-quality badge; Agent 2 §9 cross-market checks visible and passing in `/api/log` |
| 5 | `launchctl list \| grep erp`; next morning open dashboard; open GitHub repo page | Job present; each market's `last_updated` from overnight; CI last run green; `docs/data/US.json` has yesterday's UTC date |

### 3. Claude monthly-plan workflow

**Hand-off rule:** give Claude one phase at a time, only if (a) it fits in one 5-hour session window and (b) you can validate the exit criteria within 10 minutes. Never hand off "the whole rollout."

**Session opener template** (paste verbatim at the start of every new Claude conversation):
```
Read /Users/yelintao/Work/DAA/Equity/ERP\ Model/SHARED_NOTES.md first, especially the Status Log at the bottom.
We are at Phase N. Last session ended with: <paste last Status Log line>.
Task this session: <one phase, copy its Scope + Exit criteria from SHARED_NOTES.md>.
Do not modify Agent 1/2/3 sections of SHARED_NOTES.md.
At the end, append a Status Log line and confirm the exit criterion by running the app locally.
```

**Session budget (order-of-magnitude):** Phase 0 = 1 session. Phase 1 = 2 sessions (backend; seed + validation). Phase 2 = 1–2 sessions (bundle fight risk). Phase 3 = 1 session. Phase 4 = 2 sessions (data fallbacks + validation). Phase 5 = 1 session. Total ~8–10 Claude sessions across the project.

**Handoff memory.** End every session by appending to a new `## Status Log` section at the bottom of `SHARED_NOTES.md`:
```
2026-04-17  Phase 1 backend done. Files touched: markets_config.py, data_fetcher.py, server.py, main.py. UK --report works. TODO: seed 1990–2020 UK history. Open question: FRED 429s — add retry or ask user for FRED key.
```
Treat the Status Log as the single source of truth between sessions. Do not rely on Claude's conversational memory.

**When to `/clear`.** Clear between phases, always. Do not clear mid-phase (keep just-read file context in the conversation). After a clear, the opener template rebuilds context from `SHARED_NOTES.md` + named files.

**Do manually (don't burn Claude sessions on these):** adding a single market row in config, `git commit`, `python main.py --update`, SQLite inspection, approving the launchd plist, pushing to GitHub. Each is under 5 minutes of user time.

### 4. Git & GitHub strategy

**Init now.** `ls -la` confirms no `.git/` — Phase 0 must `git init` and commit.

**`.gitignore` (commit this):**
```
__pycache__/
*.pyc
.DS_Store
.venv/
venv/
output/
*.log
# Local DB and cache — regeneratable from seed + fetch
erp_model.db
erp_model.db-journal
erp_model.db.bak-*
test.db
test.db-journal
# Damodaran cache — large binary, regeneratable
histimpl_cache.xls
# Secrets
.env
.envrc
FRED_API_KEY
```

**Commit:** all `.py`, `.md`, `erp_dashboard.html`, `assets/`, `start_server.sh`, `Start ERP Server.command`, `.gitignore`, `CHANGELOG.md`, `MIGRATION.md`, eventually `docs/data/*.json` + `docs/index.html` (Phase 5). **Do not commit:** the SQLite DB (rebuilt via `seed_historical.py`), the xls cache, FRED keys, `output/` charts.

**Branch strategy:** single-branch `main` with tagged phases. Rationale: solo user, small scope, every phase exits with a runnable app. Tag each phase (`v0.phase0`, `v0.phase1`, …) so rollback is `git checkout v0.phase1`. Feature branches per market add overhead without value.

**Pre-commit hook (lightweight only):** a single `.git/hooks/pre-commit` shell script:
- `ruff check .` (fast, catches real bugs)
- `python -c "import config, database, data_fetcher, erp_calculator, server, main"` (import smoke — catches syntax errors across the module graph)
- Skip mypy (codebase isn't typed; retrofit is out of scope). Skip black (ruff format optional, don't block commits on style).
No `pre-commit` framework — avoid the extra dependency for a solo project.

### 5. GitHub deployment plan — recommend Option A + D hybrid

**Recommendation: Option A (code-only public repo) with an optional Option D static snapshot layer from Phase 5 onward.**

- **Primary (from Phase 0):** public GitHub repo, users clone + `python server.py` locally. Zero hosting cost, zero runtime secrets, privacy preserved. Aligns perfectly with the Claude-monthly constraint — nothing to monitor remotely.
- **Addon (Phase 5):** a GitHub Action dumps nightly `docs/data/{market}.json` and GitHub Pages serves a minimal read-only viewer (`docs/index.html`) that reads those static files. Gives a public demo URL for the 8-market ERP snapshots without hosting a backend. The fully interactive app (scenarios, `/api/compute`, `/api/update`) still requires local Flask — that's fine and clearly labeled.

**Why not B (static frontend on Pages + local backend):** breaks `/api/compute` for anyone not running Flask; the dashboard becomes partially broken for the public.

**Why not C (Render/Railway/Fly free tier):** (a) hosting env needs the FRED key as a secret, (b) local DB and hosted DB diverge, (c) debugging remote failures without Claude-in-the-loop monitoring is painful, (d) the `/api/update` endpoint becomes a public rate-limit burner for Yahoo/FRED. Not worth the complexity for a solo project.

**Option D publishing workflow sketch (Phase 5):**
```
scripts/publish_snapshot.py
  for market in MARKETS:
      rows = db.history(market)
      json.dump({
          "market": market,
          "latest": rows[-1],
          "history": rows,
          "data_quality": markets_config[market]["data_quality"],
          "last_updated": datetime.utcnow().isoformat(),
      }, open(f"docs/data/{market}.json", "w"))
  # also docs/data/index.json with market list + freshness timestamps
```
`.github/workflows/snapshot.yml`: runs on cron `0 23 * * *` UTC + manual dispatch; runs `python main.py --update --all-markets` (uses the runner's fresh state; no persistent DB needed if CI uses `--refresh-from-seed`), then `python scripts/publish_snapshot.py`, then commits `docs/data/*.json` back with `[skip ci]`. Pages serves `docs/`.

Note: cron Actions fetch Yahoo/FRED from GitHub runners — no Claude involvement, no Claude API key needed. Pure deterministic Python.

### 6. GitHub Actions plan

**Automate (safe, deterministic):**
- `lint.yml` on every PR + push: `ruff check .` + `python -m py_compile $(git ls-files '*.py')`.
- `smoke.yml` on every push: `python main.py --validate` (Damodaran 1999 replication, sub-second, no network); plus Agent 2's golden test — Jan 2026 US ERP must equal 4.23% ± 10 bp.
- `snapshot.yml` nightly (Phase 5): fetch + recompute + commit `docs/data/*.json`.
- `release.yml` on tag push `v*`: auto-generate GitHub Release from `CHANGELOG.md` section matching the tag.
- Enable Dependabot (free tier) for `pip` + `github-actions` ecosystems.

**Explicitly NOT automated:**
- Any LLM call (no Claude API by constraint; do not smuggle in OpenAI or any other vendor).
- Seeding the user's local DB (one-time manual op; CI uses ephemeral DB).
- Auto-merging PRs (solo repo — user reviews).
- Deploying to any cloud host (see Option A rationale above).
- Cross-market sanity checks with hard-fail in CI (Agent 2 §9 — log warnings only; don't block a commit because India ERP temporarily inverted Korea during a data glitch).

### 7. Documentation deliverables

| Artifact | Updated in phase | Content |
|---|---|---|
| `CHANGELOG.md` | every phase | Keep-a-Changelog format. One entry per tagged phase with Added / Changed / Fixed. |
| `README.md` | Phases 1, 3, 4, 5 | Add "Supported Markets" table with data-quality tier + per-market data-source line. |
| `MODEL_SPECIFICATION.md` | Phases 1, 3, 4 | Per-market subsection documenting payout, buyback yield, rfr instrument + provenance, growth-input class (A/B/C per Agent 2 §4), any methodology deviation (e.g. JP terminal-g note). |
| `MIGRATION.md` | Phase 0, and any later schema change | SQL diffs + backup file name + rollback command (`mv ~/erp_model.db.bak-preN ~/erp_model.db`). |
| `QUICKSTART.md` | Phase 2 | Add market dropdown to the 30-second flow. |
| `FLASK_SERVER.md` | Phase 1, Phase 2 | Document `?market=` on every GET and `"market"` field on every POST; document the `/api/set_market` session fallback if used. |

### 8. Risk register (top 5 shipping risks)

| # | Risk | L × I | Mitigation |
|---|---|---|---|
| 1 | DB migration corrupts the 65yr seeded US data | Low × High | Phase 0 backup to `~/erp_model.db.bak-pre0` before any ALTER. Migration is idempotent, ALTER-only, never DROP. `MIGRATION.md` documents one-line rollback. CI smoke test runs migration against a fresh DB + against a pre-migration seeded DB. |
| 2 | Yahoo ticker or schema changes mid-rollout (esp. international tickers `VUKE.L`, `7203.T`, `^TOPX`, `.HK`, `.NS`) | Medium × Medium | Every market config has `primary_ticker` + `fallback_tickers` list. Fetcher tries in order and logs which one won. `snapshot.yml` in CI catches breakage within 24h. Freeze top-constituent lists in code (not dynamic from Yahoo) — Agent 2 §4 prescribed. |
| 3 | React bundle can't be made market-aware without the `/erp-dashboard/src/` source tree | Medium × Medium | Phase 2 primary path = injected top-strip selector + `fetch` monkey-patch. Fallback = per-market HTML copies (`erp_dashboard_uk.html` etc.) until React source is recovered. **Action for user: before Phase 2, locate the React source and either commit it as `erp-dashboard/` subfolder or confirm we're on the fallback path.** |
| 4 | FRED discontinues a non-US long-rate series (has happened for some OECD series) | Low × High per affected market | Each market declares primary + secondary rfr source with a fallback chain (Agent 2 §2). Fetcher emits WARN to `calculation_log` when it falls back. Dashboard shows "stale rfr" badge when `stale_days > threshold`. Hard-fail China if >14 days stale. |
| 5 | Damodaran revises methodology (e.g., cash-return-adjusted buyback measure) and our US numbers drift from his published figure | Low × Low-Medium | `--validate` replicates his 1999 example every CI run. Annual manual diff of our latest US ERP vs. his Jan-1 post, tracked in `CHANGELOG.md` under "Calibration notes". Golden test locks Jan 2026 US = 4.23% (Agent 2 regression guard). |

Honourable mention: Claude monthly plan session limits. If a phase exceeds one session mid-edit, the Status Log handoff is the only recovery mechanism — do not skip it.

### 9. Definition of Done (whole project shipped)

1. All 8 markets return a current ERP via `GET /api/latest?market=X` and a history via `GET /api/history?market=X`, every weekday, with no manual intervention for ≥7 consecutive days.
2. `erp_dashboard.html` lets the user switch any of the 8 markets via a visible selector; chart and current-value card redraw correctly for each, with a data-quality badge on EM markets.
3. Repo is public on GitHub; CI (`lint`, `smoke`, `snapshot`) is green on `main`; `README.md` lists all 8 markets with their data-quality tier; `CHANGELOG.md` has entries through Phase 5; tag `v0.phase5` exists.
4. `MODEL_SPECIFICATION.md` documents every per-market methodology deviation (JP terminal-g note, EM CRP-vs-implied distinction per Agent 2 §6); `MIGRATION.md` documents every schema change with rollback.
5. Clean-machine acceptance: `git clone && pip install -r requirements.txt && python seed_historical.py && python server.py` reaches a working 8-market dashboard in under 5 minutes, no additional setup required (FRED key optional, not required — fallbacks handle it).

---

## Consolidated Plan

> Synthesised from Agents 1–4. This section is the single handoff document. Every future Claude session should start by reading the **Status Log** at the bottom, then this section.

---

### Architecture in one paragraph
The app is a local Flask + SQLite + pre-built React SPA. The core Damodaran 2-stage FCFE/DDM solver (`erp_calculator.py`) is **market-agnostic already** — all changes are at the *data layer* (parameterised inputs) and the *schema layer* (add `market` column). No solver math changes. The React frontend source is not in this repo; a minimal market-switcher will be injected into the existing bundle via a top-strip `<select>` (Phase 2). All computation stays local; nothing goes to the cloud.

---

### The 8 markets — summary config table

| Code | Index | Yahoo ticker | RFR instrument | FRED series | Payout | Buyback | Growth class | Normal ERP (LR) | Priority |
|---|---|---|---|---|---|---|---|---|---|
| US | S&P 500 | `^GSPC` | 10Y Treasury | `DGS10` | 78.85% | 2.0% | A | 4.25% | ✓ live |
| UK | FTSE 100 | `^FTSE` | 10Y Gilt | `IRLTLT01GBM156N` | 60% | 1.2% | A | 4.75% | **Phase 1** |
| EU | STOXX 600 | `^STOXX` | 10Y Bund | `IRLTLT01DEM156N` | 55% | 0.8% | A | 4.75% | **Phase 3** |
| JP | TOPIX | `^TOPX` / `^N225` fallback | 10Y JGB | `IRLTLT01JPM156N` | 40% | 1.5% | B | 5.00% | **Phase 3** |
| KR | KOSPI | `^KS11` | 10Y KTB | `IRLTLT01KRM156N` | 30% | 0.7% | B | 5.75% | **Phase 4** |
| IN | NIFTY 50 | `^NSEI` | 10Y GoI | `INDIRLTLT01STM` | 35% | 0.3% | C | 7.50% | **Phase 4** |
| TW | TAIEX | `^TWII` | 10Y TW Gov | MoF CSV / CDS proxy | 65% | 0.3% | B/C | 6.50% | **Phase 4** |
| CN | MSCI China | `MCHI` / `000300.SS` | 10Y CGB | 4-step fallback chain | 35% | 0.5% | C | 6.75% | **Phase 4 (last)** |

> Growth class A = Yahoo bottom-up works. B = partial + fallback. C = IMF WEO nominal GDP.
> Full calibration detail → Agent 2. Source fallback chains → Agent 2 §2 + Agent 3 §3.

---

### Key methodology decisions (locked)

| Decision | Ruling | Owner |
|---|---|---|
| Solver | Unchanged (Newton-Raphson 2-stage FCFE/DDM) | Agent 1 |
| Currency | Local-currency everywhere — no USD conversion | Agent 2 §6c |
| Terminal growth | = local rfr; floor at `max(rfr, 0.5%)` for JP/EU low-rate edge case | Agent 2 §6a |
| CRP | Solved ERP already embeds CRP. CRP only feeds the *benchmark band*, not the solver | Agent 2 §6b |
| EPS / FCFE | Ship FCFE for US + UK + EU + JP + KR; DDM-only for IN + TW + CN (EPS data too thin) | Agent 3 §3 |
| Payout / buyback | Per-market defaults in `markets_config.py`; refresh annually vs. Damodaran ctryprem | Agents 2 + 3 |

---

### Files to create / modify

| File | Action | Phase |
|---|---|---|
| `.gitignore` | **CREATE** (excludes erp_model.db, histimpl_cache.xls, .env, output/) | 0 |
| `CHANGELOG.md`, `MIGRATION.md` | **CREATE** | 0 |
| `markets_config.py` | **CREATE** — `MarketSpec` dataclass + `MARKETS` dict, US stub first | 0 |
| `migrations/001_multi_market.py` | **CREATE** — idempotent ALTER + composite PK rebuild (see Agent 3 §2) | 0 |
| `database.py` | **MODIFY** — update schema DDL, add `market` param to all queries | 0 |
| `data_sources/base.py` | **CREATE** — `DataSource` Protocol + `FetchResult` dataclass | 1 |
| `data_sources/yahoo_fred.py` | **CREATE** — generic impl driven by `MarketSpec` | 1 |
| `data_sources/overrides/jp.py` | **CREATE** — TOPIX EPS weighting quirk | 3 |
| `data_sources/overrides/cn.py` | **CREATE** — ChinaBond HTML fallback scraping | 4 |
| `data_fetcher.py` | **MODIFY** — thin orchestrator over `DataSource(market)` | 1 |
| `erp_calculator.py` | **MODIFY** — accept market param; pull normal-ERP bands from config | 1 |
| `server.py` | **MODIFY** — add `?market=` to all GETs, `"market"` to all POST bodies | 1 |
| `main.py` | **MODIFY** — add `--market` flag; default = `'US'` | 1 |
| `update_markets.py` | **CREATE** — multi-market daily refresh CLI with per-market error isolation | 1 |
| `erp_dashboard.html` | **MODIFY** — inject top-strip `<select>` + fetch monkey-patch | 2 |
| `seed_historical.py` | **MODIFY** — accept `--market` flag; read `data/seed/<MKT>_historical.csv` | 1–4 |
| `visualization.py` | **MODIFY** — add `market` param; support multi-market overlay chart | 3 |
| `data/seed/*.csv` | **CREATE** — one CSV per new market (user provides; schema in Agent 3 §4) | 1–4 |
| `tests/` | **CREATE** — smoke tests for DB, data sources, validation; Agent 2 regression guard | 1 |
| `scripts/publish_snapshot.py` | **CREATE** | 5 |
| `docs/data/*.json` + `docs/index.html` | **CREATE** | 5 |
| `.github/workflows/` | **CREATE** — lint, smoke, snapshot, release YAMLs | 0, 5 |

> Detailed DDL → Agent 3 §1. Fallback chains → Agent 3 §3. Full file layout → Agent 3 §8.

---

### Schema changes (summary)

```
erp_inputs        PK: (date)              →  (date, market)   + market + currency + provenance cols
erp_computations  PK: (date, method)      →  (date, market, method)
erp_forecasts     no market col           →  + market
erp_breakeven     no market col           →  + market
calculation_log   no market col           →  + market + level
update_runs       NEW table               —  audit each update_markets.py run
```
> Exact DDL → Agent 3 §1. Migration steps (idempotent, safe) → Agent 3 §2.

---

### 6-phase delivery plan

| Phase | Goal | Exit criterion |
|---|---|---|
| **0** | Git init + DB migration, US-only unchanged | `python server.py` still works; `market` column present; git log has 1 commit |
| **1** | UK end-to-end through backend | `python main.py --update --market UK --report` → ERP ∈ [4.0%, 6.5%]; `/api/history?market=UK` returns ≥30 points |
| **2** | Frontend market switcher (no bundle rebuild) | Dashboard shows market dropdown; chart redraws for UK and US; no console errors |
| **3** | Europe + Japan (config-only) | 4 markets in dropdown; JP 2020-12-31 ERP ∈ [5.5%, 7.0%]; no 500s |
| **4** | Korea, India, Taiwan, China (EM tier) | All 8 markets return ERP; EM shows data-quality badge; cross-market sanity checks pass |
| **5** | launchd auto-refresh + GitHub publication | Repo public; CI green; `docs/data/*.json` updated overnight; Pages serves read-only viewer |

> Full scope + risk + mitigation for each phase → Agent 4 §1. Per-phase validation steps → Agent 4 §2.

---

### Claude session workflow (how to use this project with monthly plan only)

1. **Start each session** with this opener:
   > "Read `/Users/yelintao/Work/DAA/Equity/ERP Model/SHARED_NOTES.md` first, especially the Status Log below. We are at Phase N. Task this session: [copy the Scope + Exit criteria for that phase]. Do not modify Agent 1/2/3/4 sections."

2. **One phase per session** (or one sub-task for Phase 1/4 which may need two).

3. **End every session** by appending a Status Log line (see format below).

4. **`/clear` between phases** — always. Never clear mid-phase.

5. **Do manually** (don't burn Claude on these): `git commit`, `python main.py --update`, SQLite schema inspection, adding a market row in config, approving the launchd plist.

> Detailed workflow, session budget (~8–10 total sessions), and when-to-clear rules → Agent 4 §3.

---

### Git + GitHub strategy

- **Init now** (Phase 0) — project has no `.git/` yet.
- **Single branch `main`** with phase tags (`v0.phase0` … `v0.phase5`). No feature branches — solo project.
- **`.gitignore`** must exclude: `erp_model.db`, `erp_model.db-journal`, `histimpl_cache.xls`, `test.db*`, `output/`, `.env`, `FRED_API_KEY`.
- **Pre-commit hook** (lightweight): `ruff check .` + import smoke. No mypy, no black enforcement.
- **GitHub Actions** (deterministic Python only, no Claude API):
  - `lint.yml` — ruff on every push
  - `smoke.yml` — Damodaran 1999 repro + Jan 2026 US golden test (ERP = 4.23% ± 10 bp)
  - `snapshot.yml` — nightly fetch + commit `docs/data/*.json` (Phase 5)
  - `release.yml` — auto GitHub Release from CHANGELOG on version tag

> `.gitignore` contents + pre-commit script + GH Actions YAMLs → Agent 4 §4–§6.

---

### Validation checklist (before declaring any market "done")

- [ ] Reproduce a Damodaran published ERP within ±100 bp
- [ ] Implied ERP positive, in [2%, 12%] range
- [ ] RFR within 50 bp of OECD monthly reference for that market
- [ ] Cross-market: EM median > DM median on same date
- [ ] Monotonicity: India > Korea > Japan > UK on any given date
- [ ] Unit test with fixed inputs passes (Agent 2 §9 specific ranges per market)
- [ ] US Jan 2026 golden test still passes (ERP = 4.23% ± 10 bp)

---

### Top risks

| Risk | Mitigation |
|---|---|
| DB migration corrupts 65yr US data | Backup to `~/erp_model.db.bak-pre0` before any ALTER; migration is idempotent |
| Yahoo ticker/schema changes for intl tickers | Primary + fallback tickers per market in `MarketSpec`; `snapshot.yml` catches within 24h |
| React bundle resists market-switcher injection | Fallback: per-market HTML copies; flag React-source recovery as a user task before Phase 2 |
| FRED discontinues a non-US long-rate series | Per-market fallback chain declared in `MarketSpec`; hard-fail if CN rfr > 14 days stale |
| China data unreliable in production | Ship China last (Phase 4 final); 4-step rfr fallback chain; data-quality badge in UI |

---

## Status Log

_Append one line here at the end of every Claude session. Format: `YYYY-MM-DD  PhaseN: <what was done>. Files touched: <list>. Next: <what to do next session>. Open: <any unresolved questions>._

```
2026-04-17  Planning complete. All 4 agents contributed to SHARED_NOTES.md. Consolidated plan written.
            dev server configured (.claude/launch.json), Flask running on port 5001.
            No code changes yet. Next: Phase 0 — git init, write .gitignore, markets_config.py US stub,
            migrations/001_multi_market.py, run migration on ~/erp_model.db, confirm server still works.
            Open: React source location (confirm /erp-dashboard/src/ exists before Phase 2).

2026-04-18  Phase 0 complete. Repo under git (branch=main, 1 commit: 4cdd1ed). Created .gitignore,
            markets_config.py (US stub mirroring config.py), migrations/001_multi_market.py (idempotent
            ALTER + composite-PK rebuild + update_runs + market-aware indexes; column renames DEFERRED
            to Phase 1), CHANGELOG.md, MIGRATION.md. Backed up ~/erp_model.db → ~/erp_model.db.bak-pre0
            before ALTERs. Migration applied on ~/erp_model.db: 68 inputs + 68 comps preserved,
            integrity_check=ok. Server verified: python3 server.py → :5001 serves /, /api/latest,
            /api/history?method=ddm returns 67 points (1961-12-31 → 2026-04-16). Files touched:
            .gitignore, markets_config.py, migrations/001_multi_market.py, migrations/__init__.py,
            CHANGELOG.md, MIGRATION.md, SHARED_NOTES.md (status log only). Next: Phase 1 — UK
            end-to-end; add data_sources/base.py + yahoo_fred.py, extend markets_config with UK,
            rename sp500_level/tbond_10yr_rate/sp500_projected in schema + all call-sites in one
            commit, wire ?market= + "market" through server.py, seed UK history.
            Open: React source location (confirm /erp-dashboard/src/ before Phase 2); also confirm
            the 'fcfe' method only has 1 row by design (current-value cache) vs needs re-seeding.

2026-04-19  Phase 1 Session A complete. UK end-to-end; 2 commits on main:
            c15fa08 (column rename: sp500_level→index_level, tbond_10yr_rate→rfr_rate,
            sp500_projected→index_projected; ~/erp_model.db.bak-pre1 backup; behaviour-neutral
            verified via stash/pop), 1cb4345 (data_sources/{base,yahoo_fred}.py DataSource
            Protocol, US delegates to existing helpers for bit-identical numerics, UK MarketSpec
            wired). UK exit criteria met: ERP=4.56% in [4.0%, 6.5%]; /api/latest?market=UK returns
            UK row, /api/latest still returns US row unchanged. Robustness fixes during smoke
            test: MarketSpec.default_rfr_fallback (mirrors default_buyback_yield) for envs
            without FRED_API_KEY; FY2 falls back when FY1 falls back to prevent absurd blended
            growth on small ticker pools (UK had 5 tickers → blended 20%→5.7%). Files touched:
            database.py, data_fetcher.py, erp_calculator.py, server.py, main.py, visualization.py,
            seed_historical.py, markets_config.py, data_sources/{__init__,base,yahoo_fred}.py.
            Next: Phase 1 Session B — seed UK history (seed_historical.py per-market loop,
            VUKE.L div history is short ~2012+; FTSE 100 from ^FTSE goes back to 1984), and
            fix server.py response.currency (currently hardcoded 'USD' → should read from
            MarketSpec). Open: React source location (still need /erp-dashboard/src/ for
            Phase 2); UK rfr currently uses 0.045 default in this dev env — set FRED_API_KEY=...
            for the live IRLTLT01GBM156N path.

2026-04-25  Phase 1 Session B complete. UK history seeded 1990–2025 + currency leak fixed.
            Steps: (1) server.py currency overlay — added markets_config.get_market import +
            _market_currency() helper, /api/latest now overrides DB-row 'USD' default with
            MarketSpec.currency (UK=GBP verified). (2) database.py upsert_inputs now
            writes the correct currency from get_market(market).currency (so new rows are
            authoritative; the server overlay is belt-and-suspenders for legacy rows).
            (3) seed_historical.py refactored for per-market dispatch: --market US keeps
            existing Damodaran XLS path; --market UK is a new bootstrap that pulls
            ^FTSE year-end closes from yfinance and IRLTLT01GBM156N year-end Dec values
            from FRED (via requests; Py3.14 fredapi has SSL-cert issues), with constant
            div_yield=3.5% / buyback=1.2% / growth=6% / payout=60% from MarketSpec, tagged
            data_source='seed:UK:bootstrap'. (4) config.py adds a small .env loader so
            FRED_API_KEY can live in the gitignored .env (.env is in .gitignore — key
            NOT committed). Seed run: 36 UK annual rows seeded, 0 skipped, ERP range
            4.56%–5.52%. Backed up ~/erp_model.db → ~/erp_model.db.bak-pre1b before run.
            Also UPDATEd 2 legacy UK rows (from Phase 1A live fetch) currency='USD'→'GBP'.
            Agent 2 §9 validation: ALL pass — 0 ERPs out of [2%,12%]; 0 yoy jumps >300bp;
            2024-12-31 ERP=5.12% in [4.5%,6.0%] unit-test band; min rfr=0.32% > -0.01
            terminal-g floor; US history untouched (70 inputs). Files touched: config.py,
            database.py, server.py, seed_historical.py, .env (gitignored), SHARED_NOTES.md.
            Next: Phase 2 — confirm /erp-dashboard/src/ React source location; wire the
            market-picker UI and historical band overlay for UK; seed v1 UK bootstrap is
            time-flat in inputs (only rfr varies year-to-year), so the historical ERP
            series captures level but not dynamics — flag this in UI quality_notes when
            we expose data_source. Open: real FTSE 100 div-yield + payout time series
            (LSEG/Refinitiv key or FTSE Russell factsheet archive) before Phase 5
            production hardening; cleanup TODO — server.py currency overlay can be
            retired once we're confident no legacy rows leak through.
```
