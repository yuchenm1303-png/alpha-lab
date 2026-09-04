from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from math import ceil

from app.providers.base import BarProvider, PopularityProvider
from app.repository import MarketRepository


MAX_EVENT_HORIZON = 60


@dataclass(frozen=True)
class SyncSummary:
    start_date: date
    end_date: date
    bar_end_date: date
    popularity_rows: int
    bar_rows: int
    unique_symbols: int
    unsupported_symbols: tuple[str, ...]


def _bar_end_date(end_date: date, max_horizon: int) -> date:
    """Reserve enough calendar time to cover a future trading-day horizon.

    A trading week normally contributes five observations. The extra 30 calendar
    days cover long public-holiday gaps and make the buffer conservative without
    coupling the sync service to one provider's calendar API.
    """

    calendar_days = ceil(max_horizon * 7 / 5) + 30
    return end_date + timedelta(days=calendar_days)


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
        max_horizon: int = MAX_EVENT_HORIZON,
    ) -> SyncSummary:
        if start_date > end_date:
            raise ValueError("start_date must be on or before end_date")
        if max_rank < 1:
            raise ValueError("max_rank must be >= 1")
        if max_horizon < 1 or max_horizon > MAX_EVENT_HORIZON:
            raise ValueError(f"max_horizon must be between 1 and {MAX_EVENT_HORIZON}")

        popularity = list(
            self.popularity_provider.fetch_popularity(
                start_date,
                end_date,
                max_rank=max_rank,
            )
        )
        symbols = sorted({row[0] for row in popularity})

        # Popularity observations define the event window, but forward-return
        # calculations require market bars after the final event date. Pull a
        # conservative future buffer so events near end_date are not silently
        # dropped from 1/3/5/10/20/60-day statistics.
        bars_end = _bar_end_date(end_date, max_horizon)
        bars, unsupported = self.bar_provider.fetch_many_bars(symbols, start_date, bars_end)

        popularity_count = self.repository.upsert_popularity(popularity)
        bar_count = self.repository.upsert_bars(bars)
        return SyncSummary(
            start_date=start_date,
            end_date=end_date,
            bar_end_date=bars_end,
            popularity_rows=popularity_count,
            bar_rows=bar_count,
            unique_symbols=len(symbols),
            unsupported_symbols=tuple(unsupported),
        )
