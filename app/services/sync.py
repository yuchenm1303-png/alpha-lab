from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.providers.base import BarProvider, PopularityProvider
from app.repository import MarketRepository


@dataclass(frozen=True)
class SyncSummary:
    start_date: date
    end_date: date
    popularity_rows: int
    bar_rows: int
    unique_symbols: int
    unsupported_symbols: tuple[str, ...]


class HistoricalSignalSyncService:
    """Join independent popularity and market-bar providers into normalized storage."""

    def __init__(
        self,
        popularity_provider: PopularityProvider,
        bar_provider: BarProvider,
        repository: MarketRepository,
    ) -> None:
        self.popularity_provider = popularity_provider
        self.bar_provider = bar_provider
        self.repository = repository

    def sync(
        self,
        start_date: date,
        end_date: date,
        *,
        max_rank: int = 100,
    ) -> SyncSummary:
        if start_date > end_date:
            raise ValueError("start_date must be on or before end_date")
        if max_rank < 1:
            raise ValueError("max_rank must be >= 1")

        popularity = list(
            self.popularity_provider.fetch_popularity(
                start_date,
                end_date,
                max_rank=max_rank,
            )
        )
        symbols = sorted({row[0] for row in popularity})
        bars, unsupported = self.bar_provider.fetch_many_bars(symbols, start_date, end_date)

        popularity_count = self.repository.upsert_popularity(popularity)
        bar_count = self.repository.upsert_bars(bars)
        return SyncSummary(
            start_date=start_date,
            end_date=end_date,
            popularity_rows=popularity_count,
            bar_rows=bar_count,
            unique_symbols=len(symbols),
            unsupported_symbols=tuple(unsupported),
        )
