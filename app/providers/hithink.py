from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any

import requests

from app.repository import PopularityRow
from app.providers.symbols import normalize_thscode


DEFAULT_BASE_URL = "https://fuyao.aicubes.cn"


class HiThinkError(RuntimeError):
    """HiThink Financial-API transport or business-contract error."""


class HiThinkClient:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout: float = 20.0,
        session: Any | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("HITHINK_API_KEY")
        if not self.api_key:
            raise HiThinkError("HITHINK_API_KEY is required")
        self.base_url = (base_url or os.getenv("HITHINK_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()
        if hasattr(self.session, "headers"):
            self.session.headers.update({"X-api-key": self.api_key})

    def _get(self, path: str, *, params: dict[str, object] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise HiThinkError(f"HiThink request failed: {exc}") from exc

        if response.status_code != 200:
            raise HiThinkError(f"HiThink HTTP {response.status_code} for {path}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise HiThinkError("HiThink returned invalid JSON") from exc

        if not isinstance(payload, dict):
            raise HiThinkError("HiThink returned an invalid response envelope")
        if payload.get("code") != 0:
            request_id = payload.get("request_id") or "unknown"
            message = payload.get("message") or "unknown error"
            raise HiThinkError(f"HiThink code={payload.get('code')} request_id={request_id}: {message}")
        return payload.get("data")

    def trading_days(self, start_date: date | None = None, end_date: date | None = None) -> list[date]:
        data = self._get("/api/a-share/calendar/trading-days")
        items = data.get("item", []) if isinstance(data, dict) else []
        days: list[date] = []
        for item in items:
            raw = str(item.get("date", ""))
            try:
                day = datetime.strptime(raw, "%Y%m%d").date()
            except (TypeError, ValueError):
                continue
            if start_date is not None and day < start_date:
                continue
            if end_date is not None and day > end_date:
                continue
            days.append(day)
        return days

    def fetch_hot_rank(self, day: date, *, max_rank: int | None = None) -> list[PopularityRow]:
        data = self._get(
            "/api/a-share/special-data/hot-stock-list-history",
            params={"date": day.isoformat()},
        )
        if not isinstance(data, dict):
            raise HiThinkError("HiThink historical hot-list payload is missing")
        response_date = data.get("date")
        if response_date and str(response_date) != day.isoformat():
            raise HiThinkError(
                f"HiThink historical hot-list date mismatch: requested {day}, got {response_date}"
            )

        rows: list[PopularityRow] = []
        for item in data.get("item", []):
            try:
                rank = int(item["rank"])
                symbol = normalize_thscode(str(item["thscode"]))
            except (KeyError, TypeError, ValueError):
                continue
            if max_rank is not None and rank > max_rank:
                continue
            rows.append((symbol, day.isoformat(), rank, None))
        return rows

    def fetch_popularity(
        self,
        start_date: date,
        end_date: date,
        *,
        max_rank: int | None = None,
    ) -> list[PopularityRow]:
        if start_date > end_date:
            raise ValueError("start_date must be on or before end_date")
        all_days = self.trading_days()
        if not all_days:
            raise HiThinkError("HiThink trading calendar returned no dates")
        if start_date < all_days[0]:
            raise HiThinkError(
                f"start_date {start_date} predates HiThink calendar window beginning {all_days[0]}"
            )
        requested_days = [day for day in all_days if start_date <= day <= end_date]
        rows: list[PopularityRow] = []
        for day in requested_days:
            rows.extend(self.fetch_hot_rank(day, max_rank=max_rank))
        return rows
