from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pytest

from app.db import Database
from app.models import FactorFilter, ResearchEventStudyRequest
from app.repository import MarketRepository
from app.services.market_dump import MarketDumpSyncService
from app.services.research import ResearchEventStudyEngine


def _date_ms(day: date) -> int:
    point = datetime(day.year, day.month, day.day, tzinfo=ZoneInfo("Asia/Shanghai"))
    return int(point.timestamp() * 1000)


def _write_daily_parquet(path: Path, rows: list[tuple[object, ...]]) -> None:
    con = duckdb.connect()
    try:
        con.execute(
            """
            CREATE TABLE daily_dump (
                thscode VARCHAR,
                currency VARCHAR,
                interval VARCHAR,
                adjusted VARCHAR,
                date_ms BIGINT,
                open_price DOUBLE,
                high_price DOUBLE,
                low_price DOUBLE,
                close_price DOUBLE,
                volume DOUBLE,
                turnover DOUBLE
            )
            """
        )
        if rows:
            con.executemany(
                "INSERT INTO daily_dump VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
        escaped = str(path).replace("'", "''")
        con.execute(f"COPY daily_dump TO '{escaped}' (FORMAT PARQUET)")
    finally:
        con.close()


def _write_adjustment_parquet(path: Path, rows: list[tuple[object, ...]]) -> None:
    con = duckdb.connect()
    try:
        con.execute(
            """
            CREATE TABLE adjustment_dump (
                thscode VARCHAR,
                ticker VARCHAR,
                ex_date_ms BIGINT,
                dividend_per_share DOUBLE,
                per_share_bonus DOUBLE,
                allotment_ratio DOUBLE,
                allotment_price DOUBLE,
                currency VARCHAR
            )
            """
        )
        if rows:
            con.executemany(
                "INSERT INTO adjustment_dump VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
        escaped = str(path).replace("'", "''")
        con.execute(f"COPY adjustment_dump TO '{escaped}' (FORMAT PARQUET)")
    finally:
        con.close()


def test_market_dump_builds_qfq_view_and_preserves_baostock_enrichment(tmp_path):
    database = Database(tmp_path / "market.duckdb")
    database.initialize()
    repository = MarketRepository(database)
    repository.upsert_bars(
        [
            ("000001.SZ", "2026-01-05", 9.0, 9.5, 8.8, 9.0, 8.0),
            ("000001.SZ", "2026-01-06", 9.0, 9.3, 8.9, 9.0, 9.0),
            ("000001.SZ", "2026-01-07", 9.8, 10.0, 9.7, 9.9, 10.0),
        ]
    )

    daily = tmp_path / "daily.parquet"
    adjustments = tmp_path / "adjustments.parquet"
    _write_daily_parquet(
        daily,
        [
            ("000001.SZ", "CNY", "1d", "none", _date_ms(date(2026, 1, 5)), 9.8, 10.2, 9.7, 10.0, 1000, 10000),
            ("000001.SZ", "CNY", "1d", "none", _date_ms(date(2026, 1, 6)), 8.8, 9.2, 8.7, 9.0, 1200, 10800),
            ("000001.SZ", "CNY", "1d", "none", _date_ms(date(2026, 1, 7)), 9.7, 10.0, 9.6, 9.9, 1500, 14850),
            ("600000.SH", "CNY", "1d", "none", _date_ms(date(2026, 1, 5)), 19.8, 20.2, 19.7, 20.0, 2000, 40000),
            ("600000.SH", "CNY", "1d", "none", _date_ms(date(2026, 1, 6)), 20.5, 21.2, 20.4, 21.0, 2100, 44100),
        ],
    )
    _write_adjustment_parquet(
        adjustments,
        [
            ("000001.SZ", "000001", _date_ms(date(2026, 1, 6)), 1.0, 0.0, 0.0, 0.0, "CNY"),
        ],
    )

    summary = MarketDumpSyncService(object(), database).import_parquet(
        daily,
        adjustments,
        mode="full",
    )

    assert summary.raw_rows == 5
    assert summary.factor_rows == 5
    assert summary.first_trade_date == date(2026, 1, 5)
    assert summary.last_trade_date == date(2026, 1, 7)

    with database.connect() as conn:
        rows = conn.execute(
            """
            SELECT trade_date, close, turnover_rate
            FROM research_daily_bars
            WHERE symbol = '000001.SZ'
            ORDER BY trade_date
            """
        ).fetchall()
    assert rows[0][1] == pytest.approx(9.0)
    assert rows[1][1] == pytest.approx(9.0)
    assert rows[2][1] == pytest.approx(9.9)
    assert rows[0][2] == pytest.approx(8.0)

    result = ResearchEventStudyEngine(database).run(
        ResearchEventStudyRequest(
            start_date=date(2026, 1, 5),
            end_date=date(2026, 1, 5),
            filters=[
                FactorFilter(
                    factor_id="turnover_rate",
                    min_value=7,
                    max_value=9,
                )
            ],
            horizons=[1],
        )
    )
    assert result.event_count == 1
    assert result.stats[0].sample_count == 1
    assert result.stats[0].average_return == pytest.approx(0.0, abs=1e-10)


def test_incremental_dump_upserts_overlap_without_deleting_history(tmp_path):
    database = Database(tmp_path / "incremental.duckdb")
    database.initialize()

    full_daily = tmp_path / "full.parquet"
    incremental_daily = tmp_path / "incremental.parquet"
    adjustments = tmp_path / "adjustments.parquet"
    _write_daily_parquet(
        full_daily,
        [
            ("600000.SH", "CNY", "1d", "none", _date_ms(date(2026, 1, 5)), 10, 10, 10, 10, 100, 1000),
            ("600000.SH", "CNY", "1d", "none", _date_ms(date(2026, 1, 6)), 11, 11, 11, 11, 110, 1210),
        ],
    )
    _write_adjustment_parquet(adjustments, [])
    service = MarketDumpSyncService(object(), database)
    service.import_parquet(full_daily, adjustments, mode="full")

    _write_daily_parquet(
        incremental_daily,
        [
            ("600000.SH", "CNY", "1d", "none", _date_ms(date(2026, 1, 6)), 11.5, 11.5, 11.5, 11.5, 115, 1322.5),
            ("600000.SH", "CNY", "1d", "none", _date_ms(date(2026, 1, 7)), 12, 12, 12, 12, 120, 1440),
        ],
    )
    summary = service.import_parquet(
        incremental_daily,
        adjustments,
        mode="incremental",
    )

    assert summary.raw_rows == 3
    assert summary.last_trade_date == date(2026, 1, 7)
    with database.connect() as conn:
        rows = conn.execute(
            """
            SELECT trade_date, close
            FROM market_daily_raw
            WHERE symbol = '600000.SH'
            ORDER BY trade_date
            """
        ).fetchall()
    assert [row[1] for row in rows] == pytest.approx([10.0, 11.5, 12.0])
