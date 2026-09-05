from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal, Protocol

from app.db import Database


MarketDumpMode = Literal["auto", "full", "incremental"]


class MarketDumpError(RuntimeError):
    """Full-market dump download/import error."""


class MarketDumpDownloader(Protocol):
    def download_market_dump(self, kind: str, destination: Path) -> Path:
        ...


@dataclass(frozen=True)
class MarketDumpSyncSummary:
    mode_requested: str
    mode_used: str
    daily_rows: int
    raw_rows: int
    adjustment_events: int
    factor_rows: int
    research_rows: int
    first_trade_date: date | None
    last_trade_date: date | None


_DAILY_REQUIRED_COLUMNS = {
    "thscode",
    "currency",
    "interval",
    "adjusted",
    "date_ms",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "volume",
    "turnover",
}

_ADJUSTMENT_REQUIRED_COLUMNS = {
    "thscode",
    "ticker",
    "ex_date_ms",
    "dividend_per_share",
    "per_share_bonus",
    "allotment_ratio",
    "allotment_price",
    "currency",
}


def _quoted_path(path: Path) -> str:
    return "'" + str(path.resolve()).replace("'", "''") + "'"


def _shanghai_date_expr(column: str) -> str:
    return f"CAST(epoch_ms(CAST({column} AS BIGINT)) + INTERVAL '8 hours' AS DATE)"


class MarketDumpSyncService:
    """Import HiThink whole-market Parquet dumps and rebuild qfq research prices."""

    def __init__(self, downloader: MarketDumpDownloader, database: Database) -> None:
        self.downloader = downloader
        self.database = database

    def _raw_status(self) -> tuple[int, date | None, date | None]:
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*), MIN(trade_date), MAX(trade_date) FROM market_daily_raw"
            ).fetchone()
        return int(row[0]), row[1], row[2]

    @staticmethod
    def _parquet_columns(conn, path: Path) -> set[str]:
        rows = conn.execute(
            f"DESCRIBE SELECT * FROM read_parquet({_quoted_path(path)})"
        ).fetchall()
        return {str(row[0]) for row in rows}

    def _validate_parquet(self, conn, path: Path, required: set[str], label: str) -> None:
        columns = self._parquet_columns(conn, path)
        missing = sorted(required - columns)
        if missing:
            raise MarketDumpError(
                f"{label} parquet is missing required columns: {', '.join(missing)}"
            )

    def _daily_range(self, path: Path) -> tuple[date | None, date | None]:
        with self.database.connect() as conn:
            self._validate_parquet(conn, path, _DAILY_REQUIRED_COLUMNS, "daily-k")
            date_expr = _shanghai_date_expr("date_ms")
            row = conn.execute(
                f"SELECT MIN({date_expr}), MAX({date_expr}) "
                f"FROM read_parquet({_quoted_path(path)})"
            ).fetchone()
        return row[0], row[1]

    def sync(self, mode: MarketDumpMode = "auto") -> MarketDumpSyncSummary:
        if mode not in ("auto", "full", "incremental"):
            raise ValueError("mode must be auto, full or incremental")
        self.database.initialize()
        raw_rows, _, local_last = self._raw_status()

        with TemporaryDirectory(prefix="alpha-lab-market-dump-") as tmp_dir:
            tmp = Path(tmp_dir)
            chosen: Literal["full", "incremental"]
            daily_path: Path

            if mode == "full" or (mode == "auto" and raw_rows == 0):
                chosen = "full"
                daily_path = self.downloader.download_market_dump(
                    "daily-k", tmp / "daily-k.parquet"
                )
            elif mode == "incremental":
                chosen = "incremental"
                daily_path = self.downloader.download_market_dump(
                    "daily-k-10d", tmp / "daily-k-10d.parquet"
                )
            else:
                incremental_path = self.downloader.download_market_dump(
                    "daily-k-10d", tmp / "daily-k-10d.parquet"
                )
                incremental_first, _ = self._daily_range(incremental_path)
                if (
                    local_last is None
                    or incremental_first is None
                    or local_last < incremental_first
                ):
                    chosen = "full"
                    daily_path = self.downloader.download_market_dump(
                        "daily-k", tmp / "daily-k.parquet"
                    )
                else:
                    chosen = "incremental"
                    daily_path = incremental_path

            adjustment_path = self.downloader.download_market_dump(
                "adjustment-factors", tmp / "adjustment-factors.parquet"
            )
            return self.import_parquet(
                daily_path,
                adjustment_path,
                mode=chosen,
                mode_requested=mode,
            )

    def import_parquet(
        self,
        daily_path: str | Path,
        adjustment_path: str | Path,
        *,
        mode: Literal["full", "incremental"] = "full",
        mode_requested: str | None = None,
    ) -> MarketDumpSyncSummary:
        self.database.initialize()
        daily = Path(daily_path)
        adjustments = Path(adjustment_path)
        if not daily.exists():
            raise MarketDumpError(f"daily parquet does not exist: {daily}")
        if not adjustments.exists():
            raise MarketDumpError(f"adjustment parquet does not exist: {adjustments}")
        if mode not in ("full", "incremental"):
            raise ValueError("import mode must be full or incremental")

        with self.database.connect() as conn:
            self._validate_parquet(conn, daily, _DAILY_REQUIRED_COLUMNS, "daily-k")
            self._validate_parquet(
                conn, adjustments, _ADJUSTMENT_REQUIRED_COLUMNS, "adjustment-factors"
            )
            try:
                conn.execute("BEGIN TRANSACTION")
                conn.execute("DROP TABLE IF EXISTS stg_market_daily")
                conn.execute("DROP TABLE IF EXISTS stg_market_adjustments")

                daily_date = _shanghai_date_expr("date_ms")
                conn.execute(
                    f"""
                    CREATE TEMP TABLE stg_market_daily AS
                    SELECT
                        UPPER(CAST(thscode AS VARCHAR)) AS symbol,
                        {daily_date} AS trade_date,
                        CAST(open_price AS DOUBLE) AS open,
                        CAST(high_price AS DOUBLE) AS high,
                        CAST(low_price AS DOUBLE) AS low,
                        CAST(close_price AS DOUBLE) AS close,
                        CAST(volume AS DOUBLE) AS volume,
                        CAST(turnover AS DOUBLE) AS amount,
                        CAST(currency AS VARCHAR) AS currency
                    FROM read_parquet({_quoted_path(daily)})
                    WHERE thscode IS NOT NULL
                      AND date_ms IS NOT NULL
                      AND open_price IS NOT NULL
                      AND high_price IS NOT NULL
                      AND low_price IS NOT NULL
                      AND close_price IS NOT NULL
                      AND (interval IS NULL OR CAST(interval AS VARCHAR) = '1d')
                      AND (adjusted IS NULL OR CAST(adjusted AS VARCHAR) = 'none')
                    """
                )
                daily_rows = int(
                    conn.execute("SELECT COUNT(*) FROM stg_market_daily").fetchone()[0]
                )
                if daily_rows == 0:
                    raise MarketDumpError("daily-k parquet produced zero valid rows")

                if mode == "full":
                    conn.execute("DELETE FROM market_daily_raw")
                    conn.execute(
                        """
                        INSERT INTO market_daily_raw
                            (symbol, trade_date, open, high, low, close, volume, amount,
                             currency, source, updated_at)
                        SELECT symbol, trade_date, open, high, low, close, volume, amount,
                               currency, 'hithink_market_dump', CURRENT_TIMESTAMP
                        FROM stg_market_daily
                        """
                    )
                else:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO market_daily_raw
                            (symbol, trade_date, open, high, low, close, volume, amount,
                             currency, source, updated_at)
                        SELECT symbol, trade_date, open, high, low, close, volume, amount,
                               currency, 'hithink_market_dump', CURRENT_TIMESTAMP
                        FROM stg_market_daily
                        """
                    )

                adjustment_date = _shanghai_date_expr("ex_date_ms")
                conn.execute(
                    f"""
                    CREATE TEMP TABLE stg_market_adjustments AS
                    SELECT
                        UPPER(CAST(thscode AS VARCHAR)) AS symbol,
                        CAST(ticker AS VARCHAR) AS ticker,
                        {adjustment_date} AS ex_date,
                        CAST(dividend_per_share AS DOUBLE) AS dividend_per_share,
                        CAST(per_share_bonus AS DOUBLE) AS per_share_bonus,
                        CAST(allotment_ratio AS DOUBLE) AS allotment_ratio,
                        CAST(allotment_price AS DOUBLE) AS allotment_price,
                        CAST(currency AS VARCHAR) AS currency
                    FROM read_parquet({_quoted_path(adjustments)})
                    WHERE thscode IS NOT NULL AND ex_date_ms IS NOT NULL
                    """
                )
                adjustment_rows = int(
                    conn.execute(
                        "SELECT COUNT(*) FROM stg_market_adjustments"
                    ).fetchone()[0]
                )
                conn.execute("DELETE FROM market_adjustment_events")
                conn.execute(
                    """
                    INSERT INTO market_adjustment_events
                        (symbol, ticker, ex_date, dividend_per_share, per_share_bonus,
                         allotment_ratio, allotment_price, currency)
                    SELECT symbol, ticker, ex_date, dividend_per_share, per_share_bonus,
                           allotment_ratio, allotment_price, currency
                    FROM stg_market_adjustments
                    """
                )

                factor_rows = self._rebuild_adjustment_factors(conn)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

            row = conn.execute(
                """
                SELECT COUNT(*), MIN(trade_date), MAX(trade_date)
                FROM market_daily_raw
                """
            ).fetchone()
            research_rows = int(
                conn.execute("SELECT COUNT(*) FROM research_daily_bars").fetchone()[0]
            )

        return MarketDumpSyncSummary(
            mode_requested=mode_requested or mode,
            mode_used=mode,
            daily_rows=daily_rows,
            raw_rows=int(row[0]),
            adjustment_events=adjustment_rows,
            factor_rows=factor_rows,
            research_rows=research_rows,
            first_trade_date=row[1],
            last_trade_date=row[2],
        )

    @staticmethod
    def _rebuild_adjustment_factors(conn) -> int:
        conn.execute("DELETE FROM market_adjust_factors")
        conn.execute(
            """
            INSERT INTO market_adjust_factors
                (symbol, trade_date, forward_factor, backward_factor, updated_at)
            WITH events AS (
                SELECT
                    symbol,
                    ex_date,
                    COALESCE(dividend_per_share, 0.0) AS d,
                    COALESCE(per_share_bonus, 0.0) AS s,
                    COALESCE(allotment_ratio, 0.0) AS r,
                    COALESCE(allotment_price, 0.0) AS p
                FROM market_adjustment_events
            ),
            effective_event AS (
                SELECT
                    e.symbol,
                    e.d, e.s, e.r, e.p,
                    (
                        SELECT MIN(k.trade_date)
                        FROM market_daily_raw k
                        WHERE k.symbol = e.symbol AND k.trade_date >= e.ex_date
                    ) AS eff_date
                FROM events e
            ),
            kline_with_prev AS (
                SELECT
                    symbol,
                    trade_date,
                    close,
                    LAG(close) OVER (
                        PARTITION BY symbol ORDER BY trade_date
                    ) AS prev_close
                FROM market_daily_raw
            ),
            event_ratios AS (
                SELECT
                    e.symbol,
                    e.eff_date AS trade_date,
                    (kp.prev_close * (1.0 + e.s + e.r))
                        / NULLIF(kp.prev_close - e.d + e.r * e.p, 0) AS ratio
                FROM effective_event e
                JOIN kline_with_prev kp
                  ON kp.symbol = e.symbol AND kp.trade_date = e.eff_date
                WHERE e.eff_date IS NOT NULL
                  AND kp.prev_close IS NOT NULL
            ),
            ratio_per_day AS (
                SELECT
                    symbol,
                    trade_date,
                    EXP(SUM(LN(ratio))) AS day_ratio
                FROM event_ratios
                WHERE ratio IS NOT NULL AND ratio > 0
                GROUP BY symbol, trade_date
            ),
            kline_ratio AS (
                SELECT
                    k.symbol,
                    k.trade_date,
                    COALESCE(rp.day_ratio, 1.0) AS day_ratio
                FROM market_daily_raw k
                LEFT JOIN ratio_per_day rp
                  ON rp.symbol = k.symbol AND rp.trade_date = k.trade_date
            ),
            backward AS (
                SELECT
                    symbol,
                    trade_date,
                    EXP(SUM(LN(day_ratio)) OVER (
                        PARTITION BY symbol
                        ORDER BY trade_date
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    )) AS backward_factor
                FROM kline_ratio
            ),
            normalized AS (
                SELECT
                    symbol,
                    trade_date,
                    backward_factor,
                    LAST_VALUE(backward_factor) OVER (
                        PARTITION BY symbol
                        ORDER BY trade_date
                        ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                    ) AS last_backward
                FROM backward
            )
            SELECT
                symbol,
                trade_date,
                backward_factor / NULLIF(last_backward, 0) AS forward_factor,
                backward_factor,
                CURRENT_TIMESTAMP
            FROM normalized
            """
        )
        return int(
            conn.execute("SELECT COUNT(*) FROM market_adjust_factors").fetchone()[0]
        )
