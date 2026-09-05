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
                    volume DOUBLE,
                    amount DOUBLE,
                    is_st BOOLEAN,
                    ipo_date DATE,
                    PRIMARY KEY (symbol, trade_date)
                )
                """
            )
            existing_columns = {
                row[1] for row in conn.execute("PRAGMA table_info('daily_bars')").fetchall()
            }
            for column_name, column_type in (
                ("volume", "DOUBLE"),
                ("amount", "DOUBLE"),
                ("is_st", "BOOLEAN"),
                ("ipo_date", "DATE"),
            ):
                if column_name not in existing_columns:
                    conn.execute(
                        f"ALTER TABLE daily_bars ADD COLUMN {column_name} {column_type}"
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
                """
                CREATE TABLE IF NOT EXISTS factor_values (
                    symbol VARCHAR NOT NULL,
                    trade_date DATE NOT NULL,
                    factor_id VARCHAR NOT NULL,
                    value DOUBLE NOT NULL,
                    source VARCHAR,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (symbol, trade_date, factor_id)
                )
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS market_daily_raw (
                    symbol VARCHAR NOT NULL,
                    trade_date DATE NOT NULL,
                    open DOUBLE NOT NULL,
                    high DOUBLE NOT NULL,
                    low DOUBLE NOT NULL,
                    close DOUBLE NOT NULL,
                    volume DOUBLE,
                    amount DOUBLE,
                    currency VARCHAR,
                    source VARCHAR NOT NULL DEFAULT 'hithink_market_dump',
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (symbol, trade_date)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS market_adjustment_events (
                    symbol VARCHAR NOT NULL,
                    ticker VARCHAR,
                    ex_date DATE NOT NULL,
                    dividend_per_share DOUBLE,
                    per_share_bonus DOUBLE,
                    allotment_ratio DOUBLE,
                    allotment_price DOUBLE,
                    currency VARCHAR
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS market_adjust_factors (
                    symbol VARCHAR NOT NULL,
                    trade_date DATE NOT NULL,
                    forward_factor DOUBLE NOT NULL,
                    backward_factor DOUBLE NOT NULL,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
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
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_factor_values_factor_date "
                "ON factor_values(factor_id, trade_date)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_market_daily_raw_date "
                "ON market_daily_raw(trade_date)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_market_adjustment_events_date "
                "ON market_adjustment_events(ex_date)"
            )

            conn.execute(
                """
                INSERT OR REPLACE INTO factor_values
                    (symbol, trade_date, factor_id, value, source, updated_at)
                SELECT symbol, trade_date, 'popularity_rank', CAST(popularity_rank AS DOUBLE),
                       'legacy_popularity', CURRENT_TIMESTAMP
                FROM popularity
                """
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO factor_values
                    (symbol, trade_date, factor_id, value, source, updated_at)
                SELECT symbol, trade_date, 'popularity_score', popularity_score,
                       'legacy_popularity', CURRENT_TIMESTAMP
                FROM popularity
                WHERE popularity_score IS NOT NULL
                """
            )

            conn.execute(
                """
                CREATE OR REPLACE VIEW research_daily_bars AS
                SELECT
                    r.symbol,
                    r.trade_date,
                    r.open * f.forward_factor AS open,
                    r.high * f.forward_factor AS high,
                    r.low * f.forward_factor AS low,
                    r.close * f.forward_factor AS close,
                    d.turnover_rate,
                    r.volume,
                    r.amount,
                    d.is_st,
                    d.ipo_date
                FROM market_daily_raw r
                JOIN market_adjust_factors f
                  ON f.symbol = r.symbol AND f.trade_date = r.trade_date
                LEFT JOIN daily_bars d
                  ON d.symbol = r.symbol AND d.trade_date = r.trade_date

                UNION ALL

                SELECT
                    d.symbol,
                    d.trade_date,
                    d.open,
                    d.high,
                    d.low,
                    d.close,
                    d.turnover_rate,
                    d.volume,
                    d.amount,
                    d.is_st,
                    d.ipo_date
                FROM daily_bars d
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM market_daily_raw r
                    JOIN market_adjust_factors f
                      ON f.symbol = r.symbol AND f.trade_date = r.trade_date
                    WHERE r.symbol = d.symbol AND r.trade_date = d.trade_date
                )
                """
            )
