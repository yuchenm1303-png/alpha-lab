from __future__ import annotations

from collections.abc import Sequence

from app.db import Database


BarRow = tuple[
    str,
    str,
    float,
    float,
    float,
    float,
    float,
    float | None,
    float | None,
    bool | None,
    str | None,
]
PopularityRow = tuple[str, str, int, float | None]
FactorRow = tuple[str, str, str, float, str | None]


def _normalize_bar_row(row: Sequence[object]) -> tuple[object, ...]:
    if len(row) == 7:
        return (*row, None, None, None, None)
    if len(row) == 11:
        return tuple(row)
    raise ValueError("bar row must contain 7 legacy fields or 11 normalized fields")


class MarketRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def upsert_bars(self, rows: Sequence[Sequence[object]]) -> int:
        if not rows:
            return 0
        normalized = [_normalize_bar_row(row) for row in rows]
        with self.database.connect() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO daily_bars
                (symbol, trade_date, open, high, low, close, turnover_rate,
                 volume, amount, is_st, ipo_date)
                VALUES (?, CAST(? AS DATE), ?, ?, ?, ?, ?, ?, ?, ?, CAST(? AS DATE))
                """,
                normalized,
            )
        return len(normalized)

    def upsert_factor_values(self, rows: Sequence[FactorRow]) -> int:
        if not rows:
            return 0
        with self.database.connect() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO factor_values
                (symbol, trade_date, factor_id, value, source, updated_at)
                VALUES (?, CAST(? AS DATE), ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                rows,
            )
        return len(rows)

    def upsert_popularity(self, rows: Sequence[PopularityRow]) -> int:
        if not rows:
            return 0
        with self.database.connect() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO popularity
                (symbol, trade_date, popularity_rank, popularity_score)
                VALUES (?, CAST(? AS DATE), ?, ?)
                """,
                rows,
            )
            factor_rows: list[FactorRow] = []
            for symbol, trade_date, rank, score in rows:
                factor_rows.append(
                    (symbol, trade_date, "popularity_rank", float(rank), "popularity")
                )
                if score is not None:
                    factor_rows.append(
                        (symbol, trade_date, "popularity_score", float(score), "popularity")
                    )
            conn.executemany(
                """
                INSERT OR REPLACE INTO factor_values
                (symbol, trade_date, factor_id, value, source, updated_at)
                VALUES (?, CAST(? AS DATE), ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                factor_rows,
            )
        return len(rows)

    def stats(self) -> dict[str, object]:
        with self.database.connect() as conn:
            bars, first_date, last_date = conn.execute(
                "SELECT COUNT(*), MIN(trade_date), MAX(trade_date) FROM daily_bars"
            ).fetchone()
            popularity_rows = conn.execute("SELECT COUNT(*) FROM popularity").fetchone()[0]
        return {
            "bars": int(bars),
            "popularity_rows": int(popularity_rows),
            "first_trade_date": first_date,
            "last_trade_date": last_date,
        }
