from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from typing import Protocol

from app.repository import BarRow, PopularityRow


class PopularityProvider(Protocol):
    """Normalized historical popularity source."""

    def fetch_popularity(
        self,
        start_date: date,
        end_date: date,
        *,
        max_rank: int | None = None,
    ) -> Iterable[PopularityRow]: ...


class BarProvider(Protocol):
    """Normalized historical OHLC + turnover-rate source."""

    def fetch_many_bars(
        self,
        symbols: Sequence[str],
        start_date: date,
        end_date: date,
    ) -> tuple[list[BarRow], list[str]]: ...
