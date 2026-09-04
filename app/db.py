from __future__ import annotations

import os
from pathlib import Path

import duckdb


class Database:
    def __init__(self, path: str | Path | None = None) -> None:
        default_path = "/tmp/alpha_lab.duckdb" if os.getenv("VERCEL") else "data/alpha_lab.duckdb"
        raw_path = str(path or os.getenv("ALPHALAB_DB_PATH", default_path))
        self.path = raw_path
        if raw_path != ":memory:":
            Path(raw_path).parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(self.path)

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_bars (
                    symbol VARCHAR NOT NULL,
                    trade_date DATE NOT NULL,
                    open DOUBLE NOT NULL,
                    high DOUBLE NOT NULL,
                    low DOUBLE NOT NULL,
                    close DOUBLE NOT NULL,
                    turnover_rate DOUBLE NOT NULL,
                    PRIMARY KEY (symbol, trade_date)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS popularity (
                    symbol VARCHAR NOT NULL,
                    trade_date DATE NOT NULL,
                    popularity_rank INTEGER NOT NULL,
                    popularity_score DOUBLE,
                    PRIMARY KEY (symbol, trade_date)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_daily_bars_date ON daily_bars(trade_date)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_popularity_date ON popularity(trade_date)"
            )
