"""DataSource Protocol + FetchResult container.

Mirrors Agent 3 §3 of SHARED_NOTES.md. Every concrete fetcher
(`yahoo_fred.YahooFredDataSource`, future per-market overrides) implements
this Protocol. Callers (`data_fetcher.fetch_all_inputs`) program against
the Protocol so that adding a new market requires no edits to the
orchestration layer — only a new MarketSpec entry and, if the data shape
is unusual, an override module.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional, Protocol


@dataclass(frozen=True)
class FetchResult:
    """One fetch outcome with provenance.

    `value` may be None when even the final fallback fails; callers decide
    whether to abort, mark `stale_flag=1`, or substitute a default.
    """
    value: Optional[float]
    source: str            # e.g. 'yahoo:^GSPC' or 'default:0.06'
    fetched_at: int        # unix timestamp
    is_fallback: bool = False
    note: str = ""


class DataSource(Protocol):
    """Contract every per-market fetcher must satisfy."""
    market: str

    def fetch_index_level(self, as_of: Optional[date] = None) -> FetchResult: ...
    def fetch_rfr(self, as_of: Optional[date] = None) -> FetchResult: ...
    def fetch_dividend_yield(self, as_of: Optional[date] = None) -> FetchResult: ...
    def fetch_buyback_yield(self, as_of: Optional[date] = None) -> FetchResult: ...
    def fetch_trailing_eps(
        self, as_of: Optional[date] = None, index_level: Optional[float] = None
    ) -> FetchResult: ...
    def fetch_analyst_growth(self, as_of: Optional[date] = None) -> dict: ...
