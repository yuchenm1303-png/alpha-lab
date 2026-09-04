from datetime import date

import pytest

from app.db import Database
from app.models import EventStudyRequest
from app.repository import MarketRepository
from app.services.event_study import EventStudyEngine


def test_event_study_filters_and_forward_returns(tmp_path):
    db = Database(tmp_path / "test.duckdb")
    db.initialize()
    repo = MarketRepository(db)
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

    result = EventStudyEngine(db).run(
        EventStudyRequest(
            start_date=date(2026, 1, 5),
            end_date=date(2026, 1, 9),
            turnover_min=5,
            turnover_max=10,
            popularity_rank_min=1,
            popularity_rank_max=20,
            horizons=[1, 3],
        )
    )

    assert result.event_count == 2
    one_day = result.stats[0]
    assert one_day.horizon == 1
    assert one_day.sample_count == 2
    assert one_day.positive_rate == pytest.approx(50.0)
    assert one_day.average_return == pytest.approx(-4.090909, abs=1e-5)

    three_day = result.stats[1]
    assert three_day.horizon == 3
    assert three_day.sample_count == 2
    assert three_day.positive_rate == pytest.approx(100.0)
    assert three_day.average_return == pytest.approx(19.090909, abs=1e-5)
