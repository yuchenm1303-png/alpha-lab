from datetime import date

import pytest

from app.db import Database
from app.repository import MarketRepository
from app.services.sync import HistoricalSignalSyncService, _bar_end_date


class PopularityProvider:
    def fetch_popularity(self, start_date, end_date, *, max_rank=None):
        assert start_date == date(2026, 9, 1)
        assert end_date == date(2026, 9, 2)
        assert max_rank == 20
        return [
            ("000001.SZ", "2026-09-01", 5, None),
            ("600519.SH", "2026-09-01", 10, None),
        ]


class BarProvider:
    def __init__(self):
        self.requested_range = None

    def fetch_many_bars(self, symbols, start_date, end_date):
        assert symbols == ["000001.SZ", "600519.SH"]
        self.requested_range = (start_date, end_date)
        return [
            ("000001.SZ", "2026-09-01", 10.0, 11.0, 9.5, 10.5, 8.0),
            ("600519.SH", "2026-09-01", 100.0, 102.0, 99.0, 101.0, 1.5),
        ], []


def test_sync_joins_sources_and_fetches_forward_bar_buffer(tmp_path):
    db = Database(tmp_path / "sync.duckdb")
    db.initialize()
    repo = MarketRepository(db)
    bar_provider = BarProvider()
    service = HistoricalSignalSyncService(PopularityProvider(), bar_provider, repo)

    summary = service.sync(date(2026, 9, 1), date(2026, 9, 2), max_rank=20)

    expected_bar_end = _bar_end_date(date(2026, 9, 2), 60)
    assert expected_bar_end == date(2026, 12, 25)
    assert bar_provider.requested_range == (date(2026, 9, 1), expected_bar_end)
    assert summary.bar_end_date == expected_bar_end
    assert summary.popularity_rows == 2
    assert summary.bar_rows == 2
    assert summary.unique_symbols == 2
    assert repo.stats()["bars"] == 2
    assert repo.stats()["popularity_rows"] == 2


def test_sync_validates_horizon(tmp_path):
    db = Database(tmp_path / "sync.duckdb")
    db.initialize()
    service = HistoricalSignalSyncService(PopularityProvider(), BarProvider(), MarketRepository(db))

    with pytest.raises(ValueError, match="max_horizon"):
        service.sync(date(2026, 9, 1), date(2026, 9, 2), max_rank=20, max_horizon=61)
