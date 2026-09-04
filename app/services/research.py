from __future__ import annotations

from dataclasses import dataclass

from app.db import Database
from app.models import (
    EventStudyResult,
    HorizonStat,
    ResearchEventSample,
    ResearchEventSamplePage,
    ResearchEventStudyRequest,
)
from app.research.factors import FactorSpec, get_factor_spec


@dataclass(frozen=True)
class _PreparedFactor:
    factor_id: str
    column_alias: str
    spec: FactorSpec
    join_alias: str | None


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
}


class ResearchEventStudyEngine:
    """Generic point-in-time factor filters followed by forward-return statistics."""

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
    def _prepare_factors(request: ResearchEventStudyRequest) -> list[_PreparedFactor]:
        prepared: list[_PreparedFactor] = []
        for index, item in enumerate(request.filters):
            spec = get_factor_spec(item.factor_id)
            prepared.append(
                _PreparedFactor(
                    factor_id=item.factor_id,
                    column_alias=f"factor_{index}",
                    spec=spec,
                    join_alias=f"fv_{index}" if spec.storage == "timeseries" else None,
                )
            )
        return prepared

    @staticmethod
    def _prepared_parts(factors: list[_PreparedFactor]) -> tuple[str, str]:
        selects: list[str] = []
        joins: list[str] = []
        for factor in factors:
            if factor.spec.storage == "bar":
                if not factor.spec.column:
                    raise ValueError(f"bar factor {factor.factor_id} has no source column")
                selects.append(f"b.{factor.spec.column} AS {factor.column_alias}")
                continue
            if factor.spec.storage == "derived":
                expression = _DERIVED_FACTOR_EXPRESSIONS.get(factor.factor_id)
                if expression is None:
                    raise ValueError(f"derived factor {factor.factor_id} has no expression")
                selects.append(f"{expression} AS {factor.column_alias}")
                continue
            assert factor.join_alias is not None
            safe_factor_id = factor.spec.id.replace("'", "''")
            joins.append(
                f"LEFT JOIN factor_values {factor.join_alias} "
                f"ON {factor.join_alias}.symbol = b.symbol "
                f"AND {factor.join_alias}.trade_date = b.trade_date "
                f"AND {factor.join_alias}.factor_id = '{safe_factor_id}'"
            )
            selects.append(f"{factor.join_alias}.value AS {factor.column_alias}")
        return (",\n                ".join(selects), "\n            ".join(joins))

    @staticmethod
    def _filter_parts(
        request: ResearchEventStudyRequest,
        factors: list[_PreparedFactor],
    ) -> tuple[list[str], list[object]]:
        clauses = ["trade_date BETWEEN ? AND ?"]
        params: list[object] = [request.start_date, request.end_date]
        for item, factor in zip(request.filters, factors, strict=True):
            if item.min_value is not None:
                clauses.append(f"{factor.column_alias} >= ?")
                params.append(item.min_value)
            if item.max_value is not None:
                clauses.append(f"{factor.column_alias} <= ?")
                params.append(item.max_value)
        return clauses, params

    def _base_ctes(
        self,
        request: ResearchEventStudyRequest,
    ) -> tuple[str, list[object], list[_PreparedFactor]]:
        factors = self._prepare_factors(request)
        factor_selects, joins = self._prepared_parts(factors)
        clauses, params = self._filter_parts(request, factors)
        optional_factor_selects = f",\n                {factor_selects}" if factor_selects else ""
        optional_joins = f"\n            {joins}" if joins else ""
        where_sql = "\n              AND ".join(clauses)
        ctes = f"""
        WITH prepared AS (
            SELECT
                b.symbol,
                b.trade_date,
                b.close AS base_close{optional_factor_selects},
                {self._lead_columns(request.horizons)}
            FROM daily_bars b{optional_joins}
        ),
        filtered AS (
            SELECT *
            FROM prepared
            WHERE {where_sql}
        ),
        returns AS (
            SELECT
                *,
                {self._return_columns(request.horizons)}
            FROM filtered
        )
        """
        return ctes, params, factors

    def run(self, request: ResearchEventStudyRequest) -> EventStudyResult:
        ctes, params, _ = self._base_ctes(request)
        stat_queries: list[str] = []
        for horizon in request.horizons:
            stat_queries.append(
                f"""
                SELECT
                    {horizon} AS horizon,
                    COUNT(ret_{horizon}d) AS sample_count,
                    CASE WHEN COUNT(ret_{horizon}d) = 0 THEN NULL
                         ELSE 100.0 * SUM(CASE WHEN ret_{horizon}d > 0 THEN 1 ELSE 0 END)
                              / COUNT(ret_{horizon}d)
                    END AS positive_rate,
                    AVG(ret_{horizon}d) AS average_return,
                    MEDIAN(ret_{horizon}d) AS median_return,
                    STDDEV_SAMP(ret_{horizon}d) AS return_stddev
                FROM returns
                """
            )
        count_sql = ctes + "SELECT COUNT(*) FROM filtered"
        stats_sql = ctes + f"""
        SELECT * FROM (
            {" UNION ALL ".join(stat_queries)}
        )
        ORDER BY horizon
        """
        with self.database.connect() as conn:
            event_count = int(conn.execute(count_sql, params).fetchone()[0])
            rows = conn.execute(stats_sql, params).fetchall()
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

        ctes, params, factors = self._base_ctes(request)
        factor_columns = [factor.column_alias for factor in factors]
        return_columns = [f"ret_{horizon}d" for horizon in request.horizons]
        selected = ["symbol", "trade_date", "base_close", *factor_columns, *return_columns]
        count_sql = ctes + "SELECT COUNT(*) FROM filtered"
        sample_sql = ctes + f"""
        SELECT {", ".join(selected)}
        FROM returns
        ORDER BY trade_date DESC, symbol ASC
        LIMIT ? OFFSET ?
        """
        with self.database.connect() as conn:
            total_count = int(conn.execute(count_sql, params).fetchone()[0])
            rows = conn.execute(sample_sql, [*params, limit, offset]).fetchall()

        samples: list[ResearchEventSample] = []
        factor_count = len(factors)
        for row in rows:
            factor_values = {
                factor.factor_id: _float_or_none(row[3 + index])
                for index, factor in enumerate(factors)
            }
            return_start = 3 + factor_count
            forward_returns = {
                f"{horizon}d": _float_or_none(row[return_start + index])
                for index, horizon in enumerate(request.horizons)
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
