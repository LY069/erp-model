# Migration log

Tracks every schema change applied to `~/erp_model.db`. One section per
migration script in `migrations/`. Every migration is idempotent and
preceded by a backup to `~/erp_model.db.bak-preN`.

Rollback command template (all migrations):
```sh
mv ~/erp_model.db.bak-preN ~/erp_model.db
```

---

## 001_multi_market (Phase 0, 2026-04-18)

**Goal.** Add `market` to every data table (default `'US'`), prepare composite
primary keys, add provenance columns, and create the `update_runs` audit
table — without touching any Python call-site.

**Backup.** `cp ~/erp_model.db ~/erp_model.db.bak-pre0` before any ALTER.
**Rollback.** `mv ~/erp_model.db.bak-pre0 ~/erp_model.db`.

**Run.**
```sh
python migrations/001_multi_market.py                  # real run
python migrations/001_multi_market.py --dry-run        # report only
python migrations/001_multi_market.py --db /path.db    # explicit DB
```

### SQL diffs

#### `erp_inputs`

Added columns (via `ALTER TABLE … ADD COLUMN …`):

| Column         | Type     | Default |
|----------------|----------|---------|
| `market`       | TEXT     | `'US'` (NOT NULL) |
| `currency`     | TEXT     | `'USD'` (NOT NULL) |
| `index_source` | TEXT     | NULL |
| `rfr_source`   | TEXT     | NULL |
| `divy_source`  | TEXT     | NULL |
| `fetched_at`   | INTEGER  | NULL (backfilled from `updated_at`) |
| `stale_flag`   | INTEGER  | `0` (NOT NULL) |
| `quality_notes`| TEXT     | NULL |

Primary key rebuilt: `PRIMARY KEY (date)` → `PRIMARY KEY (date, market)`.
(SQLite can't `ALTER` a PK, so the table is rebuilt via rename + create +
`INSERT … SELECT` + drop. All within a single transaction.)

New indexes:
- `idx_inputs_market_date` on `(market, date DESC)` — latest-by-market.
- `idx_inputs_date` on `(date)` — cross-market slice at a date.

#### `erp_computations`

Added columns:

| Column          | Type | Default |
|-----------------|------|---------|
| `market`        | TEXT | `'US'` (NOT NULL) |
| `model_version` | TEXT | `'v1'` (NOT NULL) |

Primary key rebuilt: `(date, method)` → `(date, market, method)`.

New indexes: `idx_comp_market_date`, `idx_comp_date`.

#### `erp_forecasts`

Added column: `market TEXT NOT NULL DEFAULT 'US'`.
New index: `idx_fc_market_base` on `(market, base_date, scenario)`.

#### `erp_breakeven`

Added column: `market TEXT NOT NULL DEFAULT 'US'`.
New index: `idx_be_market_date` on `(market, date DESC)`.

#### `calculation_log`

Added columns: `market TEXT` (nullable — global events have NULL market),
`level TEXT NOT NULL DEFAULT 'INFO'`.
New index: `idx_log_market_date` on `(market, created_at DESC)`.

#### `update_runs` (new)

Audit one row per `update_markets.py` (or migration) invocation.

```sql
CREATE TABLE update_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    INTEGER NOT NULL,
    finished_at   INTEGER,
    markets       TEXT NOT NULL,      -- JSON array, e.g. ["US","UK"]
    status_json   TEXT NOT NULL,      -- JSON object, e.g. {"US":"ok"}
    git_sha       TEXT,
    model_version TEXT
);
```

### Deferred to Phase 1

Column renames (`sp500_level → index_level`, `tbond_10yr_rate → rfr_rate`,
`sp500_projected → index_projected`) are *not* applied here. They break
Python callers and so must land together with `database.py` / `server.py`
edits — that is Phase 1 work.

### Verification

After applying:

```sh
sqlite3 ~/erp_model.db ".schema erp_inputs"        # shows market column
sqlite3 ~/erp_model.db "SELECT COUNT(*) FROM erp_inputs;"     # = 68
sqlite3 ~/erp_model.db "SELECT COUNT(*) FROM erp_computations;"  # = 68
sqlite3 ~/erp_model.db "SELECT DISTINCT market FROM erp_inputs;" # = US
python3 server.py &        # server starts
curl -s http://127.0.0.1:5001/api/history | head -c 500   # returns 65y of points
```

---

## UK historical seed (Phase 1 Session B, 2026-04-25)

**Goal.** Populate `erp_inputs` and `erp_computations` (method='ddm') with 36
annual UK rows, 1990-12-31 → 2025-12-31, derived from a CSV-driven series so
the implied ERP captures real time-varying dynamics (GFC, COVID, etc.).
Replaces the earlier constant-input bootstrap from commit `6c467b9`.

**Backup.** `cp ~/erp_model.db ~/erp_model.db.bak-pre1b` before re-seed
(already in place from Session B).
**Rollback.** `mv ~/erp_model.db.bak-pre1b ~/erp_model.db` (restores the
pre-Session-B state, predating both the constant-input bootstrap and this
upgraded CSV-driven seed).

**Run.**
```sh
python3 seed_historical.py --market UK --end 2025
```

### Data sources (committed in `data/seed/UK_historical.csv`)

| Field | Source | Window |
|---|---|---|
| `index_level` | yfinance `^FTSE` Dec close (live at seed time) | 1990–2025 |
| `dividend_yield` | Bank of England *Bankstats* Table A.7.4 + Barclays *Equity Gilt Study* | 1990–2001 |
| `dividend_yield` | FTSE Russell monthly factsheets (Dec issue) + Bloomberg historical | 2002–2024 |
| `dividend_yield` | Vanguard `VUKE.L` TTM distribution + FTSE Russell Dec factsheet | 2025 |
| `buyback_yield` | AJ Bell Dividend Dashboard / Janus Henderson Global Dividend Index / Computershare UK Dividend Monitor — smoothed two-bucket: 0.5% (1990–2009), 1.2% (2010–2025) | 1990–2025 |
| `payout_ratio` | Damodaran `ctryprem.html` (UK row) anchor at 0.60 — held flat | 1990–2025 |
| `rfr_rate` | FRED `IRLTLT01GBM156N` December monthly observation (live at seed time) | 1990–2025 |
| `analyst_5yr_growth` | `MarketSpec.default_analyst_growth=6.0%` per Agent 2 §4 ("not seeded historically") | n/a |
| `trailing_eps` | Blank pre-2012 (no clean free aggregate); seed produces DDM-only rows. FCFE coverage starts 2012 per Agent 3 §3. | n/a |

Full citations and per-year notes live in the CSV header.

### Documented v1 shortfalls (carry to Phase 5 hardening)

1. **Dividend yields hand-keyed.** No live BoE/Barclays API; values transcribed from published documents and rounded to 0.1pp. Individual-year tolerance ±0.3pp. Phase 5 should ingest LSEG/Refinitiv or a paid-feed annual series.
2. **Buyback yield is a two-bucket constant** (0.5% pre-2010, 1.2% post-2010), not a yearly series. Real yearly UK buyback ingest needs LSEG/Refinitiv.
3. **Payout ratio held flat at 0.60** (Agent 2 §3 anchor). Time-varying UK payout series deferred.
4. **Trailing EPS blank pre-2012.** FCFE only computes for years where Yahoo `VUKE.L` exposes EPS (2012+). DDM is computed for all 36 years.
5. **Analyst growth** held at 6.0% (MarketSpec default); Agent 2 §4 explicitly says NOT to seed analyst growth historically.
6. **No reconciliation against Damodaran ctryprem.html UK row.** Agent 2 §9 level-check #1 (±100bp vs Damodaran) deferred — needs a live page fetch.

### Verification

```sh
sqlite3 ~/erp_model.db "SELECT COUNT(*) FROM erp_inputs WHERE market='UK';"  # = 36
sqlite3 ~/erp_model.db "SELECT COUNT(*) FROM erp_computations WHERE market='UK' AND method='ddm';"  # = 36
sqlite3 ~/erp_model.db "SELECT DISTINCT currency FROM erp_inputs WHERE market='UK';"  # = GBP
# Agent 2 §9 unit-test dates:
sqlite3 ~/erp_model.db "SELECT date, ROUND(implied_erp*100,2) FROM erp_computations \
  WHERE market='UK' AND method='ddm' \
    AND date IN ('2008-12-31','2020-12-31','2025-12-31');"
# → 2008-12-31|6.52   (in [6%, 9%])
# → 2020-12-31|5.75   (in [5%, 8%])
# → 2025-12-31|5.33   (in [4.0%, 6.5%])
```

---

## Phase 4 seed — KR + IN + TW + CN + CN_CSI (2026-05-07)

**Goal.** Seed the four EM markets (Korea, India, Taiwan, China) plus the
CSI 300 onshore peer for the dual-series CN exit criterion.

**Backup.** `cp ~/erp_model.db ~/erp_model.db.bak-pre4` before any seed.
**Rollback.** `mv ~/erp_model.db.bak-pre4 ~/erp_model.db`.

**Run.**
```sh
python seed_historical.py --market KR
python seed_historical.py --market IN
python seed_historical.py --market TW
python seed_historical.py --market CN
python seed_historical.py --market CN_CSI
# then live updates so /api/latest carries today's values:
python main.py --update --market KR --report
python main.py --update --market IN --report
python main.py --update --market TW --report
python main.py --update --market CN --report
python main.py --update --market CN_CSI --report
```

No DB schema migration. The schema has been market-agnostic since Phase 0
(no CHECK constraint on `market`); all five new market codes accept TEXT
without DDL changes.

### Per-market data provenance

| Market   | Index ticker | Index source         | RFR source                                  | Div-yield ETF      |
|----------|--------------|----------------------|---------------------------------------------|--------------------|
| KR       | `^KS11`      | yfinance Dec close   | FRED `IRLTLT01KRM156N` (live since 2000)    | `EWY`              |
| IN       | `^NSEI`      | yfinance + CSV pre-fill 1999–2006 | FRED `INDIRLTLT01STM` (monthly; pre-2010 fallback) | `NIFTYBEES.NS`     |
| TW       | `^TWII`      | yfinance Dec close   | TW override → Investing.com `taiwan-10-year-bond-yield` (no FRED series)        | `0050.TW`          |
| CN       | `MCHI`       | yfinance Dec close (USD) | CN override → Investing.com `china-10-year-bond-yield` → US10Y+NDF → const | `MCHI`             |
| CN_CSI   | `510300.SS`  | yfinance Dec close (CNY) | CN override (shared; same chain as CN)  | `510300.SS`        |

### CSV citation tables

#### KR_historical.csv (1995–2025)

| Field            | Source                                                                               | Window       |
|------------------|--------------------------------------------------------------------------------------|--------------|
| `dividend_yield` | KRX *Korea Capital Markets Yearbook* + Bank of Korea ECOS December obs               | 1995–2010    |
| `dividend_yield` | KRX official KOSPI dividend yield monthly archive                                    | 2011–2024    |
| `dividend_yield` | EWY trailing TTM (USD-translated proxy)                                              | 2025         |
| `payout_ratio`   | Flat 0.30 pre-2024 (Korea-discount era) → 0.32 post-2024 (Value-up bump)             | 1995–2025    |
| `buyback_yield`  | Two-bucket: 0.003 pre-2014 → 0.007 post-2014 (chaebol repurchase ramp)               | 1995–2025    |
| `index_level`    | yfinance `^KS11` Dec close (yfinance has full history)                               | 1996–2025    |
| `rfr_rate`       | FRED `IRLTLT01KRM156N` Dec obs                                                       | 2000–2025    |
| `rfr_rate`       | spec.default_rfr_fallback = 3.5% (FRED KR series starts 2000)                        | 1996–1999    |

#### IN_historical.csv (1999–2025)

| Field            | Source                                                                               | Window       |
|------------------|--------------------------------------------------------------------------------------|--------------|
| `dividend_yield` | NSE *Indian Securities Market Review* + RBI *Database on Indian Economy*             | 1999–2010    |
| `dividend_yield` | NSE NIFTY 50 monthly factsheet TTM                                                   | 2011–2024    |
| `dividend_yield` | NIFTYBEES.NS trailing TTM (Nippon NIFTY ETF, INR-native)                             | 2025         |
| `payout_ratio`   | Two-bucket: 0.30 pre-2010 → 0.35 post-2010                                           | 1999–2025    |
| `buyback_yield`  | Flat 0.003 (NIFTY-aggregate negligible)                                              | 1999–2025    |
| `index_level`    | NSE Historical Indices NIFTY 50 official year-end closes (CSV pre-fill)              | 1999–2006    |
| `index_level`    | yfinance `^NSEI` Dec close                                                           | 2007–2025    |
| `rfr_rate`       | FRED `INDIRLTLT01STM` Dec obs                                                        | 2010–2025    |
| `rfr_rate`       | spec.default_rfr_fallback = 7.0%                                                     | 1999–2009    |

#### TW_historical.csv (2000–2025)

| Field            | Source                                                                               | Window       |
|------------------|--------------------------------------------------------------------------------------|--------------|
| `dividend_yield` | TWSE *Annual Statistics* + Bloomberg historical                                      | 2000–2010    |
| `dividend_yield` | TWSE official TAIEX dividend yield monthly archive + 0050.TW TTM cross-check         | 2011–2024    |
| `dividend_yield` | 0050.TW trailing TTM (Yuanta Taiwan 50 ETF, TWD-native)                              | 2025         |
| `payout_ratio`   | Flat 0.65 (Taiwan dividend culture; TSMC ~50% + insurer-heavy)                       | 2000–2025    |
| `buyback_yield`  | Flat 0.003 (programmatic buybacks small)                                             | 2000–2025    |
| `index_level`    | yfinance `^TWII` Dec close                                                           | 2000–2025    |
| `rfr_rate`       | spec.default_rfr_fallback = 1.6% (no FRED TW series; live override scrapes Investing.com but historical CBC scrape deferred to Phase 5) | 2000–2025    |

#### CN_historical.csv (2011–2025)

| Field            | Source                                                                               | Window       |
|------------------|--------------------------------------------------------------------------------------|--------------|
| `dividend_yield` | iShares MCHI ETF distributions / NAV at year-end + MSCI China factsheet cross-check  | 2011–2024    |
| `dividend_yield` | MCHI trailing TTM (yfinance `MCHI.info.trailingAnnualDividendYield`)                 | 2025         |
| `payout_ratio`   | Two-bucket: 0.30 pre-2015 → 0.35 post-2015 (SOE dividend reform)                     | 2011–2025    |
| `buyback_yield`  | Two-bucket: 0.001 pre-2020 → 0.005 post-2020 (HK-tech buyback wave)                  | 2011–2025    |
| `index_level`    | yfinance `MCHI` Dec close (MCHI inception 2011-03; pre-2011 truncated for v1)        | 2011–2025    |
| `rfr_rate`       | spec.default_rfr_fallback = 2.0% (FRED IRLTLT01CNM156N retired; ChinaBond JS-only)   | 2011–2025    |

#### CN_CSI_historical.csv (2012–2025)

| Field            | Source                                                                               | Window       |
|------------------|--------------------------------------------------------------------------------------|--------------|
| `dividend_yield` | CSI Index Co. *CSI 300 Monthly Reports* + Wind cross-check                           | 2012–2024    |
| `dividend_yield` | 510300.SS ETF trailing TTM (Huatai-PineBridge CSI 300 ETF, CNY-native)               | 2025         |
| `payout_ratio`   | Flat 0.40 (onshore SOE-bank-heavy ~30% + consumer ~50% blend)                        | 2012–2025    |
| `buyback_yield`  | Flat 0.003 (onshore A-share buybacks de minimis)                                     | 2012–2025    |
| `index_level`    | yfinance `510300.SS` Dec close (ETF inception 2012-05; pre-2012 truncated for v1)    | 2012–2025    |
| `rfr_rate`       | spec.default_rfr_fallback = 2.0% (shares CN's chain)                                 | 2012–2025    |

### v1 shortfalls (carry to Phase 5)

1. **Hand-keyed annual dividend yields, ±0.3pp tolerance per year** for KR/IN/TW/CN/CN_CSI. Phase 5 should ingest raw KRX/NSE/TWSE/MSCI/CSI factsheet feeds.
2. **No payout time series.** All five markets use either flat or two-bucket payout. Same caveat as Phase 1 UK.
3. **Trailing EPS blank.** All EM markets ship DDM-only seeded (FCFE is computed live; not seeded historically). Per Agent 3 §3 EPS coverage table.
4. **CN/CN_CSI historical rfr is `default_rfr_fallback` constant** — no CGB curve variation captured pre-live. Phase 5 candidate: backfill from Wind/CSMAR or ChinaBond JS-rendered scrape.
5. **TW historical rfr is `default_rfr_fallback` constant** — no FRED TW series exists; the override is live-only (Investing.com scrape).
6. **Pre-2011 CN data and pre-2012 CN_CSI data truncated** — yfinance does not have MCHI / 510300.SS history before ETF inception. Pre-truncation backfill is Phase 5 work.
7. **Damodaran ctryprem reconciliation** is to ±200 bp band only (loosened from Agent 2 §9 ±100 bp); divergence is a known feature of implied vs CRP+US-ERP methodologies (Agent 2 §6b).

### Verification

```sh
# row counts (per market, post-Phase-4)
sqlite3 ~/erp_model.db "SELECT market, COUNT(*) FROM erp_inputs GROUP BY market ORDER BY market;"
# expected: CN=15, CN_CSI=14, EU=29+, IN=27, JP=42+, KR=30, TW=26, UK=40+, US=72+

# Phase 1 byte-identity contract
diff <(curl -s 'http://localhost:5001/api/latest') <(curl -s 'http://localhost:5001/api/latest?market=US')
# expected: empty (byte-identical)

# Damodaran ±200 bp band gates
python main.py --update --market KR --report   # implied ERP in [2.87%, 6.87%]
python main.py --update --market IN --report   # in [5.08%, 9.08%]
python main.py --update --market TW --report   # in [3.01%, 7.01%]
```
