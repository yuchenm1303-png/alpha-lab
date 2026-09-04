from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Protocol

from app.repository import BarRow, PopularityRow


class MarketDataProvider(Protocol):
    """Contract for future HiThink/a-stock-data adapters."""

    def fetch_bars(self, start_date: date, end_date: date) -> Iterable[BarRow]: ...

    def fetch_popularity(self, start_date: date, end_date: date) -> Iterable[PopularityRow]: ...
