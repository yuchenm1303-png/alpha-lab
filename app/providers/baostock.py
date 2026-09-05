from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterator, Sequence

from app.repository import BarRow
from app.providers.symbols import UnsupportedSymbolError, baostock_code, normalize_thscode


class BaoStockError(RuntimeError):
    """BaoStock login/query/data-contract error."""


@dataclass(frozen=True)
class BaoStockBatch:
    rows: list[BarRow]
    unsupported_symbols: list[str]


def _load_baostock() -> Any:
    try:
        import baostock as bs
    except ImportError as exc:
        raise BaoStockError('BaoStock is not installed; run: pip install -e ".[data]"') from exc
    return bs


def _optional_float(value: object) -> float | None:
    raw = str(value or "").strip()
    return float(raw) if raw else None


def _optional_bool(value: object) -> bool | None:
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    if raw in {"1", "true", "yes"}:
        return True
    if raw in {"0", "false", "no"}:
        return False
    return None


class BaoStockClient:
    FIELDS = "date,code,open,high,low,close,volume,amount,turn,tradestatus,isST"

    def __init__(self, module: Any | None = None, *, adjustflag: str = "2") -> None:
        self.bs = module or _load_baostock()
        self.adjustflag = adjustflag

    @contextmanager
    def _session(self) -> Iterator[None]:
        login = self.bs.login()
        if getattr(login, "error_code", None) != "0":
            raise BaoStockError(
                f"BaoStock login failed: {getattr(login, 'error_code', '?')} "
                f"{getattr(login, 'error_msg', '')}"
            )
        try:
            yield
        finally:
            self.bs.logout()

    @staticmethod
    def _rows(result: Any) -> Iterator[dict[str, str]]:
        if getattr(result, "error_code", None) != "0":
            raise BaoStockError(
                f"BaoStock query failed: {getattr(result, 'error_code', '?')} "
                f"{getattr(result, 'error_msg', '')}"
            )
        fields = list(getattr(result, "fields", []))
        while result.next():
            values = result.get_row_data()
            yield dict(zip(fields, values, strict=False))

    def _stock_ipo_date(self, code: str) -> str | None:
        query = getattr(self.bs, "query_stock_basic", None)
        if not callable(query):
            return None
        try:
            result = query(code=code)
            for item in self._rows(result):
                raw = (item.get("ipoDate") or "").strip()
                if raw:
                    date.fromisoformat(raw)
                    return raw
        except (BaoStockError, TypeError, ValueError):
            return None
        return None

    def _query_symbol(self, symbol: str, start_date: date, end_date: date) -> list[BarRow]:
        code = baostock_code(symbol)
        ipo_date = self._stock_ipo_date(code)
        result = self.bs.query_history_k_data_plus(
            code,
            self.FIELDS,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            frequency="d",
            adjustflag=self.adjustflag,
        )
        rows: list[BarRow] = []
        for item in self._rows(result):
            if item.get("tradestatus") != "1":
                continue
            try:
                normalized = normalize_thscode(item.get("code") or code)
                turnover = float(item["turn"])
                open_price = float(item["open"])
                high = float(item["high"])
                low = float(item["low"])
                close = float(item["close"])
                trade_date = item["date"]
                volume = _optional_float(item.get("volume"))
                amount = _optional_float(item.get("amount"))
                is_st = _optional_bool(item.get("isST"))
            except (KeyError, TypeError, ValueError):
                continue
            rows.append(
                (
                    normalized,
                    trade_date,
                    open_price,
                    high,
                    low,
                    close,
                    turnover,
                    volume,
                    amount,
                    is_st,
                    ipo_date,
                )
            )
        return rows

    def fetch_many_bars(
        self,
        symbols: Sequence[str],
        start_date: date,
        end_date: date,
    ) -> tuple[list[BarRow], list[str]]:
        if start_date > end_date:
            raise ValueError("start_date must be on or before end_date")
        rows: list[BarRow] = []
        unsupported: list[str] = []
        normalized_symbols = list(dict.fromkeys(normalize_thscode(s) for s in symbols))
        if not normalized_symbols:
            return rows, unsupported

        with self._session():
            for symbol in normalized_symbols:
                try:
                    rows.extend(self._query_symbol(symbol, start_date, end_date))
                except UnsupportedSymbolError:
                    unsupported.append(symbol)
        return rows, unsupported
