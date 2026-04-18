# Forward-Looking Equity Risk Premium (ERP) Model
## Model Specification Document

**Based on:** Damodaran (NYU Stern), "Equity Risk Premiums: Determinants, Estimation and Implications"  
**Reference spreadsheet:** ERPJan26.xlsx (January 2026)  
**Last updated:** April 2026

---

## 1. Model Overview

This model estimates the **implied Equity Risk Premium (ERP)** for the S&P 500 by treating the index as a stock and solving for the internal rate of return (IRR) that equates the present value of expected future cash flows to the current index level.

The implied ERP is then:

```
ERP = Implied Cost of Equity  −  Risk-Free Rate (10-Year T-Bond)
```

This is Damodaran's preferred "forward-looking" measure, as it reflects what investors are **currently pricing in**, rather than relying on historical excess returns (which are backward-looking and noisy).

---

## 2. Formula: The 2-Stage Augmented DDM

### Stage 1 (Years 1–5): High Growth
The S&P 500 index level equals the present value of projected cash flows:

```
S&P_level = Σ [CF_t / (1 + r)^t]  for t = 1..5  +  TV / (1 + r)^5
```

Where `r` is solved numerically (Newton-Raphson with brentq fallback).

### Stage 2 (Terminal Value): Stable Growth
```
TV = CF_5 × (1 + g_terminal) / (r − g_terminal)
```

**Key assumption:** `g_terminal = T-bond rate` (Damodaran's long-run nominal GDP growth proxy)

### Implied ERP
```
ERP = r − T-bond rate
```

---

## 3. Cash Flow Definition

### FCFE Method (Damodaran-Faithful, Recommended)

Cash flows are defined as **Earnings × Payout Ratio**, NOT raw dividends:

```
Base Cash Flow = Trailing EPS × Payout Ratio
CF_t = Base CF × (1 + g_1) × (1 + g_2) × ... × (1 + g_t)
```

This captures both dividends AND buybacks as a fraction of earnings, using the payout ratio as a stable long-run measure.

**Why not raw dividends?** Dividends alone understate total cash returned to shareholders. Buybacks have grown from ~0.5% of index value in 1990 to ~2-3% today. Damodaran's payout ratio approach captures this holistically.

### DDM Method (Legacy)

```
Base Cash Flow = S&P_level × (Dividend Yield + Buyback Yield)
CF_t = Base CF × (1 + g_1) × (1 + g_2) × ... × (1 + g_t)
```

Less accurate than FCFE but usable when trailing EPS is unavailable.

---

## 4. Parameters

### 4.1 S&P 500 Level

| Attribute | Value |
|-----------|-------|
| Symbol | ^GSPC |
| Source | Yahoo Finance (`yfinance`) |
| Damodaran Jan 2026 | 5,881.63 |
| Frequency | Daily close |
| Notes | Use end-of-period value for monthly/annual computations |

### 4.2 Trailing EPS (FCFE Method Only)

| Attribute | Value |
|-----------|-------|
| Definition | S&P 500 trailing 12-month earnings per "unit" of the index |
| Damodaran Jan 2026 | 271.52 |
| Source (Damodaran) | Standard & Poor's S&P 500 Earnings and Estimates |
| Free-tier proxy | Yahoo Finance SPY trailing EPS × (S&P level / SPY price) |
| Fallback | S&P level / 21.0 (assumes ~21x trailing P/E) |
| Notes | Damodaran uses net income aggregated across all S&P 500 companies, divided by total index units |

### 4.3 Payout Ratio (FCFE Method Only)

| Attribute | Value |
|-----------|-------|
| Definition | (Dividends + Buybacks) / Net Income, S&P 500 aggregate |
| Damodaran Jan 2026 | **78.85%** (0.7785) |
| Source | Damodaran's 'Buyback & Dividend computation' sheet in ERPJan26.xlsx |
| Historical range | 50–90% depending on economic cycle |
| Default in model | 0.7785 |
| Notes | This is NOT the same as the dividend payout ratio. It includes buybacks. Higher ratios signal more mature market/fewer reinvestment opportunities. |

### 4.4 Analyst Growth Estimate

| Attribute | Value |
|-----------|-------|
| Definition | Consensus analyst estimate for S&P 500 earnings growth |
| Damodaran Jan 2026 (Year 1) | **15.59%** |
| Damodaran Jan 2026 (Year 2) | **14.48%** |
| Damodaran Jan 2026 (5-yr CAGR) | **10.50%** |
| Damodaran's sources | **S&P Capital IQ** (primary — bottom-up consensus), Yardeni, Thomson Reuters, FactSet |
| Our free-tier source | Yahoo Finance FY1/FY2 EPS estimates, median of top-15 S&P 500 constituents |
| Fallback default | 8.0% (long-run nominal earnings growth) |
| Notes | Damodaran explicitly uses bottom-up analyst estimates aggregated across individual companies. This is the single most impactful parameter for the implied ERP. Manual override via `--growth` CLI flag is recommended for accuracy. |

**Where to get better estimates (free):**
- [Yardeni Research](https://www.yardeni.com/pub/peacockfv.pdf) — publishes quarterly S&P 500 earnings estimates
- [FactSet Earnings Insight](https://advantage.factset.com/hubfs/Website/Resources%20Section/Research%20Desk/Earnings%20Insight/EarningsInsight_041125.pdf) — free weekly PDF
- [S&P Global](https://www.spglobal.com/spdji/en/) — publishes quarterly earnings data

### 4.5 Growth Ramp Schedule (Year-by-Year)

**This is the most critical difference from a naive DDM.**

Damodaran does NOT use a flat growth rate for all 5 years. He ramps down linearly:

| Year | Rate | Method |
|------|------|--------|
| 1 | Analyst consensus year 1 | e.g. 15.59% |
| 2 | Analyst consensus year 2 | e.g. 14.48% |
| 3 | Linear interpolation | e.g. 11.05% |
| 4 | Linear interpolation | e.g. 7.61% |
| 5 | T-bond rate (terminal) | e.g. 4.18% |

Formula for years 3–5:
```
g_t = g_analyst + (t − 2) / 3 × (g_terminal − g_analyst)
```

This reflects the assumption that near-term analyst estimates are reliable, but long-run growth must converge to the economy's nominal growth rate (proxied by the T-bond rate).

### 4.6 Risk-Free Rate / T-Bond Rate

| Attribute | Value |
|-----------|-------|
| Definition | 10-year U.S. Treasury constant maturity yield |
| Damodaran Jan 2026 | **4.18%** |
| Source (primary) | FRED API, series DGS10 |
| Source (fallback) | Yahoo Finance ^TNX |
| Dual role | (1) Discount rate floor; (2) Terminal/stable growth rate |
| Notes | Damodaran uses the beginning-of-year T-bond rate for annual ERP computations. The choice of T-bill vs T-bond matters — Damodaran uses 10-year bonds as the equity risk-free benchmark. |

### 4.7 Dividend Yield

| Attribute | Value |
|-----------|-------|
| Definition | Trailing 12-month dividend yield for S&P 500 |
| Source | Yahoo Finance SPY trailing annual dividend yield |
| Damodaran Jan 2026 | ~1.20% |
| Notes | Used in DDM method only. In FCFE method, dividends are captured via the payout ratio. |

### 4.8 Buyback Yield

| Attribute | Value |
|-----------|-------|
| Definition | Net stock buybacks / S&P 500 market cap |
| Source | No reliable free source — configurable default |
| Default | **2.0%** |
| Historical range | 1.0–3.5% (2000–2025) |
| Override | CLI: `--buyback-yield 0.025` |
| Notes | Used in DDM method only. Damodaran sources this from S&P quarterly buyback data. In FCFE method, buybacks are included in the payout ratio. |

---

## 5. "Normal" ERP — Reference Benchmarks

The model includes a **breakeven growth analysis** that answers:
> *"What earnings growth rate does the market need to achieve to earn a normal ERP?"*

Two definitions of "normal" ERP are provided:

| Benchmark | Value | Definition |
|-----------|-------|------------|
| Long-run average | **4.25%** | Damodaran's implied ERP average 1960–present (from histimpl.xls) |
| Last-decade average | **5.19%** | Average implied ERP 2015–2025 |

**Why 4.25%?** This is Damodaran's published long-run average from his historical ERP time series, covering multiple full market cycles. It represents what equity investors have historically demanded above the risk-free rate.

**Interpretation:**
- If `current growth estimate > breakeven growth` → Market is pricing in MORE growth than needed for normal ERP → Relatively attractive
- If `current growth estimate < breakeven growth` → Market is pricing in LESS growth than needed → Relatively expensive

---

## 6. Validation — ERPJan26.xlsx

Full reproduction of Damodaran's January 2026 calculation:

| Parameter | Damodaran's Value | Our Model |
|-----------|-------------------|-----------|
| S&P 500 | 5,881.63 | same |
| Trailing EPS | 271.52 | fetched |
| Payout ratio | 78.85% | 78.85% |
| Base cash flow | 198.99 | computed |
| Year 1 growth | 15.59% | fetched/override |
| Year 2 growth | 14.48% | fetched/override |
| Year 3 growth | 11.05% | computed (ramp) |
| Year 4 growth | 7.61% | computed (ramp) |
| Year 5 growth | 4.18% | = T-bond rate |
| T-bond rate | 4.18% | fetched |
| Implied ERP | **4.23%** | **~4.23%** |

Run `python3 erp_calculator.py` to reproduce this validation.

---

## 7. Computation Flow

```
1. Fetch inputs (data_fetcher.py)
       ↓
2. Build year-by-year growth schedule
   [analyst_yr1, analyst_yr2, ramp, ramp, tbond_rate]
       ↓
3. Compute cash flows
   CF_t = base_cf × cumulative_product(1 + g_s for s=1..t)
       ↓
4. Solve for r (Newton-Raphson → brentq fallback)
   S&P_level = Σ CF_t/(1+r)^t + TV/(1+r)^5
       ↓
5. ERP = r − T-bond rate
       ↓
6. Store in SQLite (database.py)
       ↓
7. Optional: Forecast ERP over horizon (forecast_erp)
             Compute breakeven growth (compute_breakeven_growth)
```

---

## 8. Known Limitations and Data Quality Notes

1. **Analyst growth estimates** are the most uncertain input. Free-tier Yahoo Finance data is a noisy proxy for the bottom-up S&P Capital IQ consensus Damodaran uses. For production use, obtain the FactSet Earnings Insight or Yardeni PDF weekly.

2. **Trailing EPS** from Yahoo Finance is estimated by scaling SPY's per-share EPS. This introduces ~1–3% error vs. Damodaran's direct S&P aggregate calculation.

3. **Buyback yield** uses a fixed default (2.0%). Actual quarterly variation of ±50bp can affect the DDM-method ERP by ~20bp. The FCFE method avoids this issue by using the payout ratio.

4. **Payout ratio** is held constant at 78.85% (Damodaran's Jan 2026 value). This changes slowly but could deviate in recession years (when earnings fall but companies maintain dividends).

5. **T-bond rate** is fetched in real-time — this is the highest-frequency input and the most reliable.

6. **Historical seeding** (seed_historical.py) uses Damodaran's published annual data from histimpl.xls, which ensures the long-run time series is faithful to his methodology.

---

## 9. References

- Damodaran, A. (2025). "Equity Risk Premiums (ERP): Determinants, Estimation and Implications — The 2025 Edition." NYU Stern. https://pages.stern.nyu.edu/~adamodar/
- Damodaran, A. (January 2026). ERPJan26.xlsx. https://pages.stern.nyu.edu/~adamodar/pc/implprem/ERPJan26.xlsx
- Damodaran, A. Historical Implied ERP. https://pages.stern.nyu.edu/~adamodar/pc/implprem/histimpl.xls
- FactSet Earnings Insight (weekly, free): https://advantage.factset.com/earnings-insight
- Yardeni Research S&P 500 Earnings Estimates (free): https://www.yardeni.com/
