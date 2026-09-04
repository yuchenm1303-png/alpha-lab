from datetime import date

import pytest

from app.db import Database
from app.models import EventStudyRequest
from app.repository import MarketRepository
from app.services.event_study import EventStudyEngine


def _seed(repo: MarketRepository) -> None:
    repo.upsert_bars(
        [
            ("000001.SZ", "2026-01-05", 9.8, 10.2, 9.7, 10.0, 8.0),
            ("000001.SZ", "2026-01-06", 10.1, 11.2, 10.0, 11.0, 8.0),
            ("000001.SZ", "2026-01-07", 10.8, 11.0, 8.8, 9.0, 20.0),
            ("000001.SZ", "2026-01-08", 9.2, 12.1, 9.1, 12.0, 8.0),
            ("000001.SZ", "2026-01-09", 12.0, 13.2, 11.9, 13.0, 8.0),
        ]
    )
    repo.upsert_popularity(
        [
            ("000001.SZ", "2026-01-05", 10, 9000.0),
            ("000001.SZ", "2026-01-06", 15, 8500.0),
            ("000001.SZ", "2026-01-07", 5, 9500.0),
            ("000001.SZ", "2026-01-08", 50, 6000.0),
            ("000001.SZ", "2026-01-09", 50, 5900.0),
        ]
    )


def _request() -> EventStudyRequest:
    return EventStudyRequest(
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 9),
        turnover_min=5,
        turnover_max=10,
        popularity_rank_min=1,
        popularity_rank_max=20,
        horizons=[1, 3, 4],
    )


def test_event_study_filters_forward_returns_and_coverage(tmp_path):
    db = Database(tmp_path / "test.duckdb")
    db.initialize()
    repo = MarketRepository(db)
    _seed(repo)

    result = EventStudyEngine(db).run(_request())

    assert result.event_count == 2
    one_day = result.stats[0]
    assert one_day.horizon == 1
    assert one_day.sample_count == 2
    assert one_day.coverage_rate == pytest.approx(100.0)
    assert one_day.positive_rate == pytest.approx(50.0)
    assert one_day.average_return == pytest.approx(-4.090909, abs=1e-5)

    three_day = result.stats[1]
    assert three_day.horizon == 3
    assert three_day.sample_count == 2
    assert three_day.coverage_rate == pytest.approx(100.0)
    assert three_day.positive_rate == pytest.approx(100.0)
    assert three_day.average_return == pytest.approx(19.090909, abs=1e-5)

    four_day = result.stats[2]
    assert four_day.horizon == 4
    assert four_day.sample_count == 1
    assert four_day.coverage_rate == pytest.approx(50.0)
    assert four_day.positive_rate == pytest.approx(100.0)
    assert four_day.average_return == pytest.approx(30.0)


def test_event_sample_page_exposes_underlying_observations(tmp_path):
    db = Database(tmp_path / "samples.duckdb")
    db.initialize()
    repo = MarketRepository(db)
    _seed(repo)

    page = EventStudyEngine(db).samples(_request(), limit=10)

    assert page.total_count == 2
    assert len(page.samples) == 2
    latest = page.samples[0]
    assert latest.trade_date == date(2026, 1, 6)
    assert latest.symbol == "000001.SZ"
    assert latest.turnover_rate == pytest.approx(8.0)
    assert latest.popularity_rank == 15
    assert latest.forward_returns["1d"] == pytest.approx(-18.181818, abs=1e-5)
    assert latest.forward_returns["4d"] is None

    earliest = page.samples[1]
    assert earliest.trade_date == date(2026, 1, 5)
    assert earliest.forward_returns["4d"] == pytest.approx(30.0)
