from __future__ import annotations

from app.db import Database
from app.models import EventStudyRequest, EventStudyResult, HorizonStat


class EventStudyEngine:
    """Compute forward close-to-close returns for historical signal observations."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def run(self, request: EventStudyRequest) -> EventStudyResult:
        horizons = request.horizons
        lead_columns = ",\n".join(
            f"LEAD(b.close, {h}) OVER (PARTITION BY b.symbol ORDER BY b.trade_date) AS close_{h}d"
            for h in horizons
        )
        return_columns = ",\n".join(
            f"CASE WHEN close_{h}d IS NULL OR base_close = 0 THEN NULL "
            f"ELSE (close_{h}d / base_close - 1.0) * 100.0 END AS ret_{h}d"
            for h in horizons
        )
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
        params = [
            request.start_date,
            request.end_date,
            request.turnover_min,
            request.turnover_max,
            request.popularity_rank_min,
            request.popularity_rank_max,
        ]

        count_sql = """
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

        with self.database.connect() as conn:
            event_count = int(conn.execute(count_sql, params).fetchone()[0])
            rows = conn.execute(sql, params).fetchall()

        stats = [
            HorizonStat(
                horizon=int(row[0]),
                sample_count=int(row[1]),
                positive_rate=_float_or_none(row[2]),
                average_return=_float_or_none(row[3]),
                median_return=_float_or_none(row[4]),
                return_stddev=_float_or_none(row[5]),
            )
            for row in rows
        ]
        return EventStudyResult(event_count=event_count, stats=stats)


def _float_or_none(value: object) -> float | None:
    return None if value is None else float(value)
