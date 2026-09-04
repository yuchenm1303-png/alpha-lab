from __future__ import annotations

from collections.abc import Sequence

from app.db import Database


BarRow = tuple[str, str, float, float, float, float, float]
PopularityRow = tuple[str, str, int, float | None]
FactorRow = tuple[str, str, str, float, str | None]


class MarketRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def upsert_bars(self, rows: Sequence[BarRow]) -> int:
        if not rows:
            return 0
        with self.database.connect() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO daily_bars
                (symbol, trade_date, open, high, low, close, turnover_rate)
                VALUES (?, CAST(? AS DATE), ?, ?, ?, ?, ?)
                """,
                rows,
            )
        return len(rows)

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
