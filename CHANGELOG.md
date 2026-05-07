# Changelog

All notable changes to the Forward-Looking ERP Model.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

The project uses phase tags (`v0.phase0` … `v0.phase5`) rather than SemVer.
Each phase is shippable; see `SHARED_NOTES.md` → "Consolidated Plan" for
the overall delivery plan.

## [Unreleased]

## [v0.phase3] — 2026-05-06

Developed-market tier: Europe (STOXX 600) and Japan (TOPIX) added as live
markets. Zero net-new infrastructure — all scaffolding (DataSource protocol,
seed CSV pattern, Flask market routing, DOM relabeller) was built in Phases
1–2.1; Phase 3 is config + data.

### Added
- `markets_config.py`: `EU` and `JP` `MarketSpec` entries with fully
  populated display fields (STOXX/Bund/€ and TOPIX/JGB/¥). All downstream
  label injection and API routing picks these up automatically.
- `data/seed/EU_historical.csv`: 28 rows (1998-12-31 → 2025-12-31). STOXX
  600 div yields hand-keyed from STOXX Ltd. factsheets and ECB Statistical
  Warehouse. Index level pre-filled for 1998–2003 (STOXX Ltd. historical
  stats; Yahoo ^STOXX begins ~Apr 2004); 2004+ filled at seed time.
- `data/seed/JP_historical.csv`: 41 rows (1985-12-31 → 2025-12-31). TOPIX
  div yields hand-keyed from TSE Annual Statistics Book. Index level
  pre-filled for 1985–1999 (TSE Factbook; Yahoo ^TOPX unreliable for this
  era); 2000+ uses ^N225 fallback (^TOPX unavailable on yfinance).
  Buyback yield: 0.000 (1985–2012), 0.005 (2013–2020, Abenomics),
  0.015 (2021+, TSE PBR<1 reform).
- `seed_historical.py`: `_fetch_ftse_yearend_closes` renamed to
  `_fetch_yearend_closes(ticker_sym, ...)` (parameterised). New generic
  `seed_csv_market(market_code, ...)` replaces the UK-specific seeder;
  `seed_uk()` delegates to it. Added `seed_eu()` and `seed_jp()` thin
  wrappers. JP terminal-g floor `max(rfr, 0.005)` applied per Agent 2 §6a.
  JP fallback: if `^TOPX` returns < ½ expected years, supplements from
  `^N225` (scale-invariant for DDM ERP). Argparse `--market` choices
  extended to `[US, UK, EU, JP]`.
- `data_sources/yahoo_fred.py`: `fetch_index_level` gains JP-specific
  `^N225` fallback when `^TOPX` is unavailable. Fallback is flagged in
  `FetchResult.is_fallback` and a warning is emitted.
- `erp_dashboard.html`: EU and JP `<option>` elements un-disabled (removed
  `disabled` attribute and "(Phase 3+)" suffix).

### Validation
- EU seeded 28/28 rows (DDM); ERPs 3.25%–6.48%; live FCFE ERP 6.89%.
- JP seeded 41/41 rows (DDM); ERPs post-2020 3.99%–4.23%; live FCFE ERP
  4.93% (7 bp below [5%, 7.5%] target; see v1 shortfalls below).
- US `/api/latest` (no market) ≡ `/api/latest?market=US` byte-identical. ✓
- `__ERP_LABELS__` in dashboard includes all four markets. ✓
- No 500s cycling US → UK → EU → JP in the UI. ✓

### Known v1 Shortfalls (documented)
- EU rfr: FRED `IRLTLT01DEM156N` SSL error on this machine → fallback 2.5%.
  All EU seed rows and live update use 2.5% Bund proxy.
- JP rfr: FRED `IRLTLT01JPM156N` same SSL error → fallback 0.5%.
- JP live div yield: `EWJ` (iShares MSCI Japan) reports 0.79% vs actual
  TOPIX ~2.2%. The ETF's USD-hedged structure compresses the reported yield.
  Contributes to JP live ERP landing at 4.93% (just below 5.0% criterion).
- JP historical seed: `default_analyst_growth=0.05` flat for all years.
  JP 2020-12-31 ERP = 2.91% vs criterion [5.5%, 7.0%]. Post-COVID analyst
  consensus was ~20–30% — not seeded for historical rows per Agent 2 §4.
- Buyback yield (EU/JP) and payout ratio are constants, not yearly series.
- Trailing EPS not seeded historically → DDM-only seed rows; FCFE deferred.
- `^TOPX` fully unavailable on yfinance (shows "possibly delisted"); all JP
  index levels use `^N225` scale. Level cancels in DDM — ERP unaffected.

## [v0.phase2.1] — 2026-05-06

Per-market UI label rewrite. Phase 2 routed `/api/*` calls correctly to the
chosen market, but the compiled React bundle had US-specific strings baked in
("S&P 500", "T-Bond Rate", etc.), so picking UK still showed the SP500 chart
title. The bundle is read-only (no source tree). Fix is a DOM relabel driven
by a single source of truth in `markets_config.MARKETS`.

### Added
- `markets_config.MarketSpec` gains four display fields:
  `display_index_name` (long, e.g. "FTSE 100"), `display_index_short`
  (e.g. "FTSE"), `display_rfr_name` (long, e.g. "10Y Gilt Yield"),
  `display_rfr_short` (e.g. "Gilt"), and `currency_symbol`
  (e.g. "£"). Defaults are safe so existing entries stay valid.
  All five are populated for US and UK; future markets fill them when
  their `MarketSpec` entries land.
- `server.py` `serve_dashboard()` rewritten to inject
  `<script>window.__ERP_LABELS__ = {...};</script>` at the
  `<!-- __ERP_LABELS__ -->` placeholder. Payload is built from
  `MARKETS` so the dashboard never duplicates label data.
- `erp_dashboard.html` extends the inline patch with `buildReps()` +
  `relabelTree()` + `MutationObserver` so the bundle's hardcoded
  US strings get text-substituted for any non-US market on every
  React re-render. US is the strict identity transform (no replacements
  fire), preserving the Phase 1 byte contract.

### Validation (all ✅)
- `/api/latest` (no market) ≡ `/api/latest?market=US` byte-identical.
- `/api/history` (no market) ≡ `/api/history?market=US` byte-identical.
- US selected: S&P 500 long + short + aggregate visible, T-Bond + T-bond
  visible, no FTSE leakage. Badge: "Source: fcfe (USD)".
- UK selected: every variant ("S&P 500", "S&P", "S&P aggregate",
  "T-Bond Rate", "T-Bond", "T-bond") replaced; FTSE 100, FTSE,
  FTSE aggregate, Gilt all visible. Badge: "Source: fcfe (GBP)".
- No console errors on either market. Switching markets stays under 2 s.

### Future-market contract
Adding a market in Phase 3 / 4 = appending a `MarketSpec` entry with
`display_index_name`, `display_index_short`, `display_rfr_name`,
`display_rfr_short`, `currency_symbol` populated. No HTML or relabel-code
edits required.

### Files touched
- `markets_config.py` — `+5` MarketSpec fields, populated for US+UK.
- `server.py` — `serve_dashboard()` rewritten; new `_build_label_payload()`.
- `erp_dashboard.html` — `<!-- __ERP_LABELS__ -->` placeholder; `+~120 lines`
  in inline script for relabel + MutationObserver.
- `CHANGELOG.md`, `SHARED_NOTES.md` (status log only).

### Compiled bundle untouched
`assets/index-PEBk7cqj.js` not modified. Recovery still
`cp -r ~/.erp_backup/assets.pre2/* assets/`.

## [v0.phase2] — 2026-05-02

Frontend market switcher injected into the existing React bundle.
The `/erp-dashboard/src/` source tree could not be located on the machine,
so this phase is implemented as a non-invasive injection into
`erp_dashboard.html` (compiled bundle in `assets/` is read-only).

### Added
- `erp_dashboard.html` — top-strip market `<select>` (US, UK enabled; EU/JP/KR/IN/TW/CN disabled with `(Phase 3+)` suffix), source badge, and inline classic-script monkey-patch installed before the deferred `<script type="module">` runs:
  - `window.fetch` wrapped: GET/HEAD requests to any URL containing `/api/` get `?market=<chosen>` appended (idempotent — skipped if `market=` already present); POSTs with JSON bodies get `"market"` merged into the body.
  - `XMLHttpRequest.prototype.open` and `.send` patched with the same logic as a belt-and-suspenders for axios/xhr.
  - `localStorage['erp_market']` is the source of truth; defaults to `'US'`. On `<select>` change, the new value is stored and `location.reload()` repaints the React tree against the new market.
  - `#erp-source-badge` polls `/api/latest` after each load and surfaces `data_source (currency)` plus `quality_notes` when present (Phase-1-deferred UI work).

### Validation (Phase 2 exit criteria, all ✅)
- `localhost:5001/` shows visible market `<select>`; default `US`.
- Pick UK → 5/5 `/api/*` requests carry `market=UK` (`/api/latest`, `/api/status`, `/api/latest?method=fcfe`, `/api/stats?method=fcfe`, `/api/history?method=fcfe`); current-ERP card redraws to UK series; badge → `Source: fcfe (GBP)`. UK FCFE ERP=4.69% ∈ [4.0%, 6.5%] band.
- Pick US → 5/5 `/api/*` requests carry `market=US`; chart redraws to 65yr US series (count=68); badge → `Source: fcfe (USD)`. US FCFE ERP=6.80% — identical to Phase 1.
- Both round-trips < 2s. No console errors on either market.
- Backend invariant preserved: `/api/latest` (no market) ≡ `/api/latest?market=US` byte-identical; `/api/history` (no market) ≡ `/api/history?market=US` byte-identical (count=68).

### Files touched
- `erp_dashboard.html` — `+~120 / -0` (style + inline script injected into `<head>`, root body unchanged).
- `CHANGELOG.md`, `SHARED_NOTES.md` (status log only).

### Pre-edit safety
- `~/.erp_backup/erp_dashboard.html.pre2` and `~/.erp_backup/assets.pre2/` snapshots taken before edit. Compiled bundle in `assets/` not modified — recovery is `cp -r ~/.erp_backup/assets.pre2/* assets/`.

### Documented Phase 3 risks
- Each disabled `<option>` (EU/JP/KR/IN/TW/CN) must be enabled one at a time as the corresponding market lands in `markets_config.py`.
- The `location.reload()` on switch is a UX wart (~200ms flash). Acceptable; cleanup blocked on recovering the React source.
- Source badge currently only renders `data_source / currency / quality_notes`. EM data-quality tier badge (Phase 4) will need richer styling.

## [v0.phase1] — 2026-04-25

UK end-to-end as the second market through the multi-market scaffold.

### Added
- `markets_config.MARKETS["UK"]` — FTSE 100 / VUKE.L / FRED `IRLTLT01GBM156N` / payout 0.60 / buyback 0.012, GBP local currency. `default_rfr_fallback=0.045` for envs without `FRED_API_KEY`.
- `data_sources/base.py` — `DataSource` Protocol + `FetchResult` dataclass.
- `data_sources/yahoo_fred.py` — generic implementation parameterised by `MarketSpec`. US delegates to existing helpers for bit-identical numerics; UK is the first non-US wiring.
- `?market=` query parameter on every GET endpoint and `"market"` field on every POST body in `server.py`. Default `'US'` keeps existing callers behaviour-neutral.
- `--market` flag on `main.py` and `seed_historical.py`.
- `data/seed/UK_historical.csv` — 36 annual rows (1990-12-31 → 2025-12-31) of FTSE 100 dividend yield (BoE / Barclays / FTSE Russell / Vanguard sources cited in the CSV header), buyback yield (two-bucket bootstrap), payout ratio. Index level + rfr filled live from yfinance `^FTSE` and FRED at seed time.
- `config.py` — minimal `.env` loader so `FRED_API_KEY` lives in a gitignored file.
- `MIGRATION.md` UK seed section — citation table + documented v1 shortfalls.

### Changed
- Schema column renames `sp500_level → index_level`, `tbond_10yr_rate → rfr_rate`, `sp500_projected → index_projected` applied across `database.py`, `server.py`, `main.py`, `data_fetcher.py`, `erp_calculator.py`, `visualization.py`, `seed_historical.py`. Behaviour-neutral; verified via stash/pop.
- `database.upsert_inputs()` now derives `currency` from `MarketSpec` at write time (not the column default).
- `server.py` `/api/latest` (and friends) overlay the row `currency` with `MarketSpec.currency` so legacy rows do not leak `'USD'` for non-US markets.
- `data_fetcher.py` analyst growth: when FY1 falls back, FY2 also falls back (prevents absurd blended growth on small ticker pools).
- `seed_historical.py --market UK` switched from constant-input bootstrap to CSV-driven (`data/seed/UK_historical.csv`). Replaces the bootstrap rows committed in `6c467b9` so the implied UK ERP captures real time-varying dynamics.

### Calibration notes (Agent 2 §9 UK validation, 2026-04-25)

- **Sign check:** 0 of 36 ERPs outside [2%, 12%]. ✅
- **YoY moves >300bp:** 0. ✅
- **2-year moves >4pp:** 0. ✅
- **2008-12-31 in [6%, 9%]:** 6.52%. ✅
- **2020-12-31 in [5%, 8%]:** 5.75%. ✅
- **Latest seeded (2025-12-31) in [4.0%, 6.5%]:** 5.33%. ✅
- **Live `main.py --update --market UK --report` on 2026-04-25:** 4.69% FCFE. ✅
- **Damodaran ctryprem.html UK reconciliation:** deferred (needs live page fetch).

### Documented v1 shortfalls (carried to Phase 5 hardening)

- UK dividend yields hand-keyed from published documents (±0.3pp tolerance per year).
- Buyback yield is a two-bucket constant (0.5% pre-2010 / 1.2% post-2010), not a yearly series.
- UK payout ratio held flat at 0.60 (Agent 2 §3 anchor).
- Trailing EPS blank pre-2012 → seed produces DDM-only rows; FCFE coverage starts 2012.
- React frontend market-switcher (Phase 2) requires `/erp-dashboard/src/` source location confirmation.

## [v0.phase0] — 2026-04-18

Scaffolding for multi-market support. No user-visible change.

### Added
- `.gitignore` — excludes local DBs, cached Damodaran workbooks, secrets, and generated output.
- `markets_config.py` — `MarketSpec` dataclass and `MARKETS` registry, US stub only. Values mirror existing `config.py` defaults so Phase 0 is behaviour-neutral.
- `migrations/001_multi_market.py` — idempotent schema migration:
  - adds `market TEXT NOT NULL DEFAULT 'US'` to every data table,
  - adds per-field provenance columns to `erp_inputs` (`currency`, `index_source`, `rfr_source`, `divy_source`, `fetched_at`, `stale_flag`, `quality_notes`),
  - rebuilds `erp_inputs` with composite PK `(date, market)` and `erp_computations` with `(date, market, method)`,
  - adds `model_version` to `erp_computations`, `level` to `calculation_log`,
  - creates the `update_runs` audit table,
  - installs market-aware indexes.
- `MIGRATION.md` — SQL diffs, backup filename, rollback command.
- `CHANGELOG.md` (this file).

### Changed
- None at the Python layer. `database.py`, `server.py`, and the frontend bundle continue to read/write the legacy column names (`sp500_level`, `tbond_10yr_rate`, `sp500_projected`). The column renames called for by Agent 3 §1 are deferred to Phase 1, where Python call-sites are updated in the same commit to keep the app runnable at every commit.

### Notes
- `~/erp_model.db` backed up to `~/erp_model.db.bak-pre0` before the ALTERs.
- Migration verified against a copy before applying; idempotent on re-run.

### Calibration notes
- None. Phase 0 does not touch the solver.
