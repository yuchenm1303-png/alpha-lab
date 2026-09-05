from __future__ import annotations

from app.db import Database
from app.models import (
    HorizonStat,
    ResearchEventSample,
    ResearchEventSamplePage,
    ResearchEventStudyRequest,
    EventStudyResult,
)
from app.research.factors import FactorSpec, get_factor_spec


_DERIVED_FACTOR_EXPRESSIONS = {
    "change_pct": (
        "CASE WHEN LAG(b.close) OVER (PARTITION BY b.symbol ORDER BY b.trade_date) IS NULL "
        "OR LAG(b.close) OVER (PARTITION BY b.symbol ORDER BY b.trade_date) = 0 THEN NULL "
        "ELSE (b.close / LAG(b.close) OVER (PARTITION BY b.symbol ORDER BY b.trade_date) - 1.0) * 100.0 END"
    ),
    "amplitude": (
        "CASE WHEN LAG(b.close) OVER (PARTITION BY b.symbol ORDER BY b.trade_date) IS NULL "
        "OR LAG(b.close) OVER (PARTITION BY b.symbol ORDER BY b.trade_date) = 0 THEN NULL "
        "ELSE (b.high - b.low) / LAG(b.close) OVER (PARTITION BY b.symbol ORDER BY b.trade_date) * 100.0 END"
    ),
    "intraday_return": (
        "CASE WHEN b.open = 0 THEN NULL ELSE (b.close / b.open - 1.0) * 100.0 END"
    ),
    "volume_ratio_5d": (
        "CASE WHEN b.volume IS NULL "
        "OR COUNT(b.volume) OVER (PARTITION BY b.symbol ORDER BY b.trade_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING) < 5 "
        "OR AVG(b.volume) OVER (PARTITION BY b.symbol ORDER BY b.trade_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING) = 0 "
        "THEN NULL ELSE b.volume / AVG(b.volume) OVER (PARTITION BY b.symbol ORDER BY b.trade_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING) END"
    ),
    "float_market_cap_est": (
        "CASE WHEN b.amount IS NULL OR b.turnover_rate IS NULL OR b.turnover_rate <= 0 "
        "THEN NULL ELSE b.amount / (b.turnover_rate / 100.0) / 100000000.0 END"
    ),
    "is_st": (
        "CASE WHEN b.is_st IS NULL THEN NULL WHEN b.is_st THEN 1.0 ELSE 0.0 END"
    ),
    "listing_age_days": (
        "CASE WHEN b.ipo_date IS NULL THEN NULL ELSE DATE_DIFF('day', b.ipo_date, b.trade_date) END"
    ),
}


class ResearchEventStudyEngine:
    def __init__(self, database: Database) -> None:
        self.database = database

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
    def _factor_sql(specs: list[FactorSpec]) -> tuple[list[str], list[str]]:
        joins: list[str] = []
        selects: list[str] = []
        for index, spec in enumerate(specs):
            alias = f"factor_{index}"
            if spec.storage == "bar":
                selects.append(f"b.{spec.column} AS {alias}")
            elif spec.storage == "derived":
                try:
                    expression = _DERIVED_FACTOR_EXPRESSIONS[spec.id]
                except KeyError as exc:
                    raise ValueError(f"derived factor has no SQL expression: {spec.id}") from exc
                selects.append(f"{expression} AS {alias}")
            else:
                join_alias = f"fv_{index}"
                joins.append(
                    f"LEFT JOIN factor_values {join_alias} ON {join_alias}.symbol = b.symbol "
                    f"AND {join_alias}.trade_date = b.trade_date "
                    f"AND {join_alias}.factor_id = '{spec.id}'"
                )
                if spec.missing_value is None:
                    selects.append(f"{join_alias}.value AS {alias}")
                else:
                    selects.append(
                        f"COALESCE({join_alias}.value, {float(spec.missing_value)}) AS {alias}"
                    )
        return joins, selects

    def _query_parts(self, request: ResearchEventStudyRequest) -> tuple[str, list[object], list[FactorSpec]]:
        specs = [get_factor_spec(item.factor_id) for item in request.filters]
        joins, factor_selects = self._factor_sql(specs)
        filters = ["trade_date BETWEEN ? AND ?"]
        params: list[object] = [request.start_date, request.end_date]
        for index, item in enumerate(request.filters):
            if item.min_value is not None:
                filters.append(f"factor_{index} >= ?")
                params.append(item.min_value)
            if item.max_value is not None:
                filters.append(f"factor_{index} <= ?")
                params.append(item.max_value)
        factor_sql = ",\n                ".join(factor_selects)
        if factor_sql:
            factor_sql = ",\n                " + factor_sql
        prepared = f"""
        WITH prepared AS (
            SELECT
                b.symbol,
                b.trade_date,
                b.close AS base_close,
                {self._lead_columns(request.horizons)}
                {factor_sql}
            FROM research_daily_bars b
            {' '.join(joins)}
        ),
        filtered AS (
            SELECT *
            FROM prepared
            WHERE {' AND '.join(filters)}
        ),
        returns AS (
            SELECT
                *,
                {self._return_columns(request.horizons)}
            FROM filtered
        )
        """
        return prepared, params, specs

    def run(self, request: ResearchEventStudyRequest) -> EventStudyResult:
        prepared, params, _ = self._query_parts(request)
        stat_queries = []
        for h in request.horizons:
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
        sql = prepared + f"""
        SELECT * FROM ({' UNION ALL '.join(stat_queries)})
        ORDER BY horizon
        """
        count_sql = prepared + "SELECT COUNT(*) FROM returns"
        with self.database.connect() as conn:
            event_count = int(conn.execute(count_sql, params).fetchone()[0])
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
        request: ResearchEventStudyRequest,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> ResearchEventSamplePage:
        if limit < 1 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        if offset < 0:
            raise ValueError("offset must be >= 0")
        prepared, params, specs = self._query_parts(request)
        factor_names = [f"factor_{index}" for index in range(len(specs))]
        return_names = [f"ret_{h}d" for h in request.horizons]
        extra_columns = factor_names + return_names
        select_extra = ", ".join(extra_columns)
        if select_extra:
            select_extra = ", " + select_extra
        sql = prepared + f"""
        SELECT symbol, trade_date, base_close{select_extra}
        FROM returns
        ORDER BY trade_date DESC, symbol ASC
        LIMIT ? OFFSET ?
        """
        count_sql = prepared + "SELECT COUNT(*) FROM returns"
        with self.database.connect() as conn:
            total_count = int(conn.execute(count_sql, params).fetchone()[0])
            rows = conn.execute(sql, [*params, limit, offset]).fetchall()
        samples: list[ResearchEventSample] = []
        for row in rows:
            factor_values = {
                spec.id: _float_or_none(row[3 + index])
                for index, spec in enumerate(specs)
            }
            return_start = 3 + len(specs)
            forward_returns = {
                f"{h}d": _float_or_none(row[return_start + index])
                for index, h in enumerate(request.horizons)
            }
            samples.append(
                ResearchEventSample(
                    symbol=str(row[0]),
                    trade_date=row[1],
                    close=float(row[2]),
                    factors=factor_values,
                    forward_returns=forward_returns,
                )
            )
        return ResearchEventSamplePage(
            total_count=total_count,
            limit=limit,
            offset=offset,
            samples=samples,
        )


def _float_or_none(value: object) -> float | None:
    return None if value is None else float(value)
