"""Per-market data fetchers built on the DataSource Protocol.

Phase 1: ships the generic Yahoo+FRED implementation used by US and UK.
Other markets and per-market overrides land in later phases.
"""
from .base import DataSource, FetchResult
from .yahoo_fred import YahooFredDataSource, get_data_source

__all__ = ["DataSource", "FetchResult", "YahooFredDataSource", "get_data_source"]
