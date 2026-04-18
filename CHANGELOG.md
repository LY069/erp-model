# Changelog

All notable changes to the Forward-Looking ERP Model.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

The project uses phase tags (`v0.phase0` … `v0.phase5`) rather than SemVer.
Each phase is shippable; see `SHARED_NOTES.md` → "Consolidated Plan" for
the overall delivery plan.

## [Unreleased]

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
