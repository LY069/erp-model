"""Per-market DataSource overrides.

Phase 3.1 introduces this directory for markets that need source-specific
behaviour beyond the generic Yahoo+FRED path in `data_sources/yahoo_fred.py`.

Currently:
    jp.py — JPDataSource: 1306.T (TOPIX ETF) replaces broken ^TOPX and
            FX-distorted EWJ for index level + dividend yield.
"""
