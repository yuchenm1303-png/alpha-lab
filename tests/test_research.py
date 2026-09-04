from datetime import date

import pytest

from app.db import Database
from app.models import FactorFilter, ResearchEventStudyRequest
from app.repository import MarketRepository
from app.research.factors import get_factor_spec, list_factor_specs
from app.services.research import ResearchEventStudyEngine


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


def test_factor_registry_exposes_first_class_popularity_and_derived_factors():
    ids = {spec.id for spec in list_factor_specs()}
    assert {
        "turnover_rate",
        "change_pct",
        "amplitude",
        "intraday_return",
        "popularity_rank",
        "popularity_score",
    } <= ids
    assert get_factor_spec("popularity_rank").storage == "timeseries"
    assert get_factor_spec("change_pct").storage == "derived"
    with pytest.raises(ValueError, match="unsupported factor"):
        get_factor_spec("future_magic")


def test_popularity_upsert_mirrors_into_factor_values(tmp_path):
    db = Database(tmp_path / "factors.duckdb")
    db.initialize()
    repo = MarketRepository(db)
    repo.upsert_popularity([("600519.SH", "2026-09-01", 3, 9123.0)])

    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT factor_id, value
            FROM factor_values
            WHERE symbol = '600519.SH' AND trade_date = DATE '2026-09-01'
            ORDER BY factor_id
            """
        ).fetchall()

    assert rows == [("popularity_rank", 3.0), ("popularity_score", 9123.0)]


def test_generic_event_study_filters_bar_and_timeseries_factors(tmp_path):
    db = Database(tmp_path / "research.duckdb")
    db.initialize()
    repo = MarketRepository(db)
    _seed(repo)
    request = ResearchEventStudyRequest(
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 9),
        filters=[
            FactorFilter(factor_id="turnover_rate", min_value=5, max_value=10),
            FactorFilter(factor_id="popularity_score", min_value=8000),
        ],
        horizons=[1, 3],
    )

    engine = ResearchEventStudyEngine(db)
    result = engine.run(request)
    page = engine.samples(request, limit=10)

    assert result.event_count == 2
    assert result.stats[0].sample_count == 2
    assert result.stats[0].positive_rate == pytest.approx(50.0)
    assert page.total_count == 2
    assert page.samples[0].factors["turnover_rate"] == pytest.approx(8.0)
    assert page.samples[0].factors["popularity_score"] == pytest.approx(8500.0)


def test_generic_event_study_can_filter_derived_daily_change(tmp_path):
    db = Database(tmp_path / "derived.duckdb")
    db.initialize()
    repo = MarketRepository(db)
    _seed(repo)
    request = ResearchEventStudyRequest(
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 9),
        filters=[
            FactorFilter(factor_id="turnover_rate", min_value=5, max_value=10),
            FactorFilter(factor_id="change_pct", min_value=9, max_value=11),
        ],
        horizons=[1],
    )

    engine = ResearchEventStudyEngine(db)
    result = engine.run(request)
    page = engine.samples(request, limit=10)

    assert result.event_count == 1
    assert page.samples[0].trade_date == date(2026, 1, 6)
    assert page.samples[0].factors["change_pct"] == pytest.approx(10.0)
    assert page.samples[0].forward_returns["1d"] == pytest.approx(-18.181818, abs=1e-5)


def test_generic_event_study_rejects_unregistered_factor(tmp_path):
    db = Database(tmp_path / "unknown.duckdb")
    db.initialize()
    request = ResearchEventStudyRequest(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 2),
        filters=[FactorFilter(factor_id="unknown_factor", min_value=1)],
        horizons=[1],
    )
    with pytest.raises(ValueError, match="unsupported factor"):
        ResearchEventStudyEngine(db).run(request)
