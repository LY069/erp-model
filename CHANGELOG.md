# Changelog

All notable changes to the Forward-Looking ERP Model.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

The project uses phase tags (`v0.phase0` … `v0.phase5`) rather than SemVer.
Each phase is shippable; see `SHARED_NOTES.md` → "Consolidated Plan" for
the overall delivery plan.

## [Unreleased]

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
