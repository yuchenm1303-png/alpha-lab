from __future__ import annotations

import csv
import io
from collections.abc import Iterable

from app.repository import BarRow, PopularityRow


BAR_COLUMNS = {
    "symbol",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "turnover_rate",
}
POPULARITY_COLUMNS = {
    "symbol",
    "trade_date",
    "popularity_rank",
}


def _reader(content: bytes) -> csv.DictReader:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV must be UTF-8 encoded") from exc
    return csv.DictReader(io.StringIO(text))


def _require_columns(reader: csv.DictReader, required: set[str]) -> None:
    actual = set(reader.fieldnames or [])
    missing = sorted(required - actual)
    if missing:
        raise ValueError(f"missing CSV columns: {', '.join(missing)}")


def parse_bars_csv(content: bytes) -> list[BarRow]:
    reader = _reader(content)
    _require_columns(reader, BAR_COLUMNS)
    rows: list[BarRow] = []
    for line_no, row in enumerate(reader, start=2):
        try:
            rows.append(
                (
                    row["symbol"].strip(),
                    row["trade_date"].strip(),
                    float(row["open"]),
                    float(row["high"]),
                    float(row["low"]),
                    float(row["close"]),
                    float(row["turnover_rate"]),
                )
            )
        except (TypeError, ValueError, KeyError) as exc:
            raise ValueError(f"invalid bars CSV value at line {line_no}") from exc
        if not rows[-1][0]:
            raise ValueError(f"empty symbol at line {line_no}")
    return rows


def parse_popularity_csv(content: bytes) -> list[PopularityRow]:
    reader = _reader(content)
    _require_columns(reader, POPULARITY_COLUMNS)
    rows: list[PopularityRow] = []
    for line_no, row in enumerate(reader, start=2):
        try:
            score_raw = (row.get("popularity_score") or "").strip()
            rows.append(
                (
                    row["symbol"].strip(),
                    row["trade_date"].strip(),
                    int(row["popularity_rank"]),
                    float(score_raw) if score_raw else None,
                )
            )
        except (TypeError, ValueError, KeyError) as exc:
            raise ValueError(f"invalid popularity CSV value at line {line_no}") from exc
        if not rows[-1][0]:
            raise ValueError(f"empty symbol at line {line_no}")
    return rows
