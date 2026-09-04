from __future__ import annotations

from app.db import Database
from app.models import (
    EventSample,
    EventSamplePage,
    EventStudyRequest,
    EventStudyResult,
    HorizonStat,
)


class EventStudyEngine:
    """Compute forward close-to-close returns for historical signal observations."""

    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _params(request: EventStudyRequest) -> list[object]:
        return [
            request.start_date,
            request.end_date,
            request.turnover_min,
            request.turnover_max,
            request.popularity_rank_min,
            request.popularity_rank_max,
        ]

    @staticmethod
    def _lead_columns(horizons: list[int]) -> str:
        return ",\n".join(
            f"LEAD(b.close, {h}) OVER (PARTITION BY b.symbol ORDER BY b.trade_date) AS close_{h}d"
            for h in horizons
        )

    @staticmethod
    def _return_columns(horizons: list[int]) -> str:
        return ",\n".join(
            f"CASE WHEN close_{h}d IS NULL OR base_close = 0 THEN NULL "
            f"ELSE (close_{h}d / base_close - 1.0) * 100.0 END AS ret_{h}d"
            for h in horizons
        )

    @staticmethod
    def _count_sql() -> str:
        return """
        WITH prepared AS (
            SELECT
                b.symbol,
                b.trade_date,
                b.turnover_rate,
                p.popularity_rank
            FROM daily_bars b
            LEFT JOIN popularity p
              ON p.symbol = b.symbol AND p.trade_date = b.trade_date
        )
        SELECT COUNT(*)
        FROM prepared
        WHERE trade_date BETWEEN ? AND ?
          AND turnover_rate BETWEEN ? AND ?
          AND popularity_rank BETWEEN ? AND ?
        """

    def run(self, request: EventStudyRequest) -> EventStudyResult:
        horizons = request.horizons
        lead_columns = self._lead_columns(horizons)
        return_columns = self._return_columns(horizons)
        stat_queries = []
        for h in horizons:
            stat_queries.append(
                f"""
                SELECT
                    {h} AS horizon,
                    COUNT(ret_{h}d) AS sample_count,
                    CASE WHEN COUNT(ret_{h}d) = 0 THEN NULL
                         ELSE 100.0 * SUM(CASE WHEN ret_{h}d > 0 THEN 1 ELSE 0 END) / COUNT(ret_{h}d)
                    END AS positive_rate,
                    AVG(ret_{h}d) AS average_return,
                    MEDIAN(ret_{h}d) AS median_return,
                    STDDEV_SAMP(ret_{h}d) AS return_stddev
                FROM returns
                """
            )

        sql = f"""
        WITH prepared AS (
            SELECT
                b.symbol,
                b.trade_date,
                b.close AS base_close,
                b.turnover_rate,
                p.popularity_rank,
                p.popularity_score,
                {lead_columns}
            FROM daily_bars b
            LEFT JOIN popularity p
              ON p.symbol = b.symbol AND p.trade_date = b.trade_date
        ),
        filtered AS (
            SELECT *
            FROM prepared
            WHERE trade_date BETWEEN ? AND ?
              AND turnover_rate BETWEEN ? AND ?
              AND popularity_rank BETWEEN ? AND ?
        ),
        returns AS (
            SELECT
                *,
                {return_columns}
            FROM filtered
        )
        SELECT * FROM (
            {" UNION ALL ".join(stat_queries)}
        )
        ORDER BY horizon
        """
        params = self._params(request)

        with self.database.connect() as conn:
            event_count = int(conn.execute(self._count_sql(), params).fetchone()[0])
            rows = conn.execute(sql, params).fetchall()

        stats = [
            HorizonStat(
                horizon=int(row[0]),
                sample_count=int(row[1]),
                coverage_rate=(100.0 * int(row[1]) / event_count) if event_count else None,
                positive_rate=_float_or_none(row[2]),
                average_return=_float_or_none(row[3]),
                median_return=_float_or_none(row[4]),
                return_stddev=_float_or_none(row[5]),
            )
            for row in rows
        ]
        return EventStudyResult(event_count=event_count, stats=stats)

    def samples(
        self,
        request: EventStudyRequest,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> EventSamplePage:
        if limit < 1 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        if offset < 0:
            raise ValueError("offset must be >= 0")

        horizons = request.horizons
        return_names = [f"ret_{h}d" for h in horizons]
        select_returns = ", ".join(return_names)
        sql = f"""
        WITH prepared AS (
            SELECT
                b.symbol,
                b.trade_date,
                b.close AS base_close,
                b.turnover_rate,
                p.popularity_rank,
                {self._lead_columns(horizons)}
            FROM daily_bars b
            LEFT JOIN popularity p
              ON p.symbol = b.symbol AND p.trade_date = b.trade_date
        ),
        filtered AS (
            SELECT
                *,
                {self._return_columns(horizons)}
            FROM prepared
            WHERE trade_date BETWEEN ? AND ?
              AND turnover_rate BETWEEN ? AND ?
              AND popularity_rank BETWEEN ? AND ?
        )
        SELECT
            symbol,
            trade_date,
            turnover_rate,
            popularity_rank,
            base_close,
            {select_returns}
        FROM filtered
        ORDER BY trade_date DESC, popularity_rank ASC, symbol ASC
        LIMIT ? OFFSET ?
        """
        params = self._params(request)
        with self.database.connect() as conn:
            total_count = int(conn.execute(self._count_sql(), params).fetchone()[0])
            rows = conn.execute(sql, [*params, limit, offset]).fetchall()

        samples = []
        for row in rows:
            returns = {
                f"{h}d": _float_or_none(row[5 + index])
                for index, h in enumerate(horizons)
            }
            samples.append(
                EventSample(
                    symbol=str(row[0]),
                    trade_date=row[1],
                    turnover_rate=float(row[2]),
                    popularity_rank=int(row[3]),
                    close=float(row[4]),
                    forward_returns=returns,
                )
            )
        return EventSamplePage(
            total_count=total_count,
            limit=limit,
            offset=offset,
            samples=samples,
        )


def _float_or_none(value: object) -> float | None:
    return None if value is None else float(value)
