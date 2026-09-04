from __future__ import annotations

import re


class UnsupportedSymbolError(ValueError):
    """Raised when an upstream provider does not support a normalized symbol."""


_THSCODE_RE = re.compile(r"^(\d{6})\.(SH|SZ|BJ)$", re.IGNORECASE)
_PREFIX_RE = re.compile(r"^(SH|SZ|BJ)(\d{6})$", re.IGNORECASE)
_BAOSTOCK_RE = re.compile(r"^(sh|sz)\.(\d{6})$", re.IGNORECASE)


def _infer_exchange(ticker: str) -> str:
    if ticker.startswith(("60", "68", "90")):
        return "SH"
    if ticker.startswith(("00", "30", "20")):
        return "SZ"
    if ticker.startswith(("4", "8", "92")):
        return "BJ"
    raise ValueError(f"cannot infer A-share exchange for ticker: {ticker}")


def normalize_thscode(value: str) -> str:
    """Normalize common A-share code forms to ``000001.SZ`` style."""

    raw = str(value).strip()
    if not raw:
        raise ValueError("empty stock symbol")

    match = _THSCODE_RE.fullmatch(raw)
    if match:
        return f"{match.group(1)}.{match.group(2).upper()}"

    match = _PREFIX_RE.fullmatch(raw)
    if match:
        return f"{match.group(2)}.{match.group(1).upper()}"

    match = _BAOSTOCK_RE.fullmatch(raw)
    if match:
        return f"{match.group(2)}.{match.group(1).upper()}"

    if raw.isdigit() and len(raw) == 6:
        return f"{raw}.{_infer_exchange(raw)}"

    raise ValueError(f"unsupported stock symbol format: {value}")


def ticker_from_thscode(value: str) -> str:
    return normalize_thscode(value).split(".", 1)[0]


def baostock_code(value: str) -> str:
    thscode = normalize_thscode(value)
    ticker, exchange = thscode.split(".", 1)
    if exchange == "BJ":
        raise UnsupportedSymbolError(f"BaoStock does not support Beijing Stock Exchange: {thscode}")
    return f"{exchange.lower()}.{ticker}"
