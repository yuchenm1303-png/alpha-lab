from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from math import ceil

from app.providers.base import BarProvider, FactorValueProvider, PopularityProvider
from app.repository import MarketRepository


MAX_EVENT_HORIZON = 60
BAR_LOOKBACK_TRADING_DAYS = 5


@dataclass(frozen=True)
class SyncSummary:
    start_date: date
    end_date: date
    bar_start_date: date
    bar_end_date: date
    popularity_rows: int
    bar_rows: int
    factor_rows: int
    unique_symbols: int
    unsupported_symbols: tuple[str, ...]


def _bar_start_date(start_date: date, lookback: int = BAR_LOOKBACK_TRADING_DAYS) -> date:
    """Pull enough pre-event calendar history for lagged/rolling factors."""

    calendar_days = ceil(lookback * 7 / 5) + 7
    return start_date - timedelta(days=calendar_days)


def _bar_end_date(end_date: date, max_horizon: int) -> date:
    """Reserve enough calendar time to cover a future trading-day horizon."""

    calendar_days = ceil(max_horizon * 7 / 5) + 30
    return end_date + timedelta(days=calendar_days)


class HistoricalSignalSyncService:
    """Join popularity, market-bar and sparse factor providers into normalized storage."""

    def __init__(
        self,
        popularity_provider: PopularityProvider,
        bar_provider: BarProvider,
        repository: MarketRepository,
        *,
        factor_provider: FactorValueProvider | None = None,
    ) -> None:
        self.popularity_provider = popularity_provider
        self.bar_provider = bar_provider
        self.repository = repository
        self.factor_provider = factor_provider

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

        bars_start = _bar_start_date(start_date)
        bars_end = _bar_end_date(end_date, max_horizon)
        bars, unsupported = self.bar_provider.fetch_many_bars(symbols, bars_start, bars_end)

        factor_values = []
        if self.factor_provider is not None and symbols:
            factor_values = list(
                self.factor_provider.fetch_factor_values(
                    start_date,
                    end_date,
                    symbols=symbols,
                )
            )

        popularity_count = self.repository.upsert_popularity(popularity)
        bar_count = self.repository.upsert_bars(bars)
        factor_count = self.repository.upsert_factor_values(factor_values)
        return SyncSummary(
            start_date=start_date,
            end_date=end_date,
            bar_start_date=bars_start,
            bar_end_date=bars_end,
            popularity_rows=popularity_count,
            bar_rows=bar_count,
            factor_rows=factor_count,
            unique_symbols=len(symbols),
            unsupported_symbols=tuple(unsupported),
        )
