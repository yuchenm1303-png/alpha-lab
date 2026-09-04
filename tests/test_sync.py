from datetime import date

from app.db import Database
from app.repository import MarketRepository
from app.services.sync import HistoricalSignalSyncService


class PopularityProvider:
    def fetch_popularity(self, start_date, end_date, *, max_rank=None):
        assert max_rank == 20
        return [
            ("000001.SZ", "2026-09-01", 5, None),
            ("600519.SH", "2026-09-01", 10, None),
        ]


class BarProvider:
    def fetch_many_bars(self, symbols, start_date, end_date):
        assert symbols == ["000001.SZ", "600519.SH"]
        return [
            ("000001.SZ", "2026-09-01", 10.0, 11.0, 9.5, 10.5, 8.0),
            ("600519.SH", "2026-09-01", 100.0, 102.0, 99.0, 101.0, 1.5),
        ], []


def test_sync_joins_independent_sources_into_repository(tmp_path):
    db = Database(tmp_path / "sync.duckdb")
    db.initialize()
    repo = MarketRepository(db)
    service = HistoricalSignalSyncService(PopularityProvider(), BarProvider(), repo)

    summary = service.sync(date(2026, 9, 1), date(2026, 9, 2), max_rank=20)

    assert summary.popularity_rows == 2
    assert summary.bar_rows == 2
    assert summary.unique_symbols == 2
    assert repo.stats()["bars"] == 2
    assert repo.stats()["popularity_rows"] == 2
