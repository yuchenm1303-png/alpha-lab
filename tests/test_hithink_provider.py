from datetime import date

import pytest

from app.providers.hithink import HiThinkClient, HiThinkError


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params, timeout))
        return self.responses.pop(0)


def test_hithink_hot_rank_normalizes_and_filters():
    session = FakeSession([
        FakeResponse({
            "code": 0,
            "message": "ok",
            "request_id": "req-1",
            "data": {
                "date": "2026-09-01",
                "date_ms": 0,
                "item": [
                    {"thscode": "600519.SH", "rank": 3},
                    {"thscode": "000001.SZ", "rank": 25},
                ],
            },
        })
    ])
    client = HiThinkClient("secret", session=session)
    rows = client.fetch_hot_rank(date(2026, 9, 1), max_rank=10)

    assert rows == [("600519.SH", "2026-09-01", 3, None)]
    assert session.headers["X-api-key"] == "secret"
    assert session.calls[0][1] == {"date": "2026-09-01"}


def test_hithink_requires_code_zero_even_on_http_200():
    session = FakeSession([
        FakeResponse({"code": 1002, "message": "bad date", "request_id": "req-x", "data": None})
    ])
    client = HiThinkClient("secret", session=session)
    with pytest.raises(HiThinkError, match="request_id=req-x"):
        client.fetch_hot_rank(date(2026, 9, 1))


def test_hithink_trading_days_parses_calendar():
    session = FakeSession([
        FakeResponse({
            "code": 0,
            "message": "ok",
            "request_id": "req-2",
            "data": {"timestamp": 0, "item": [{"date": "20260831"}, {"date": "20260901"}]},
        })
    ])
    client = HiThinkClient("secret", session=session)
    assert client.trading_days(date(2026, 9, 1), date(2026, 9, 2)) == [date(2026, 9, 1)]


def test_hithink_limit_up_pool_emits_sparse_factor_rows():
    session = FakeSession([
        FakeResponse({
            "code": 0,
            "message": "ok",
            "request_id": "req-limit",
            "data": {
                "pagination": {"total": 2, "pages": 1, "size": 200, "page": 1},
                "item": [
                    {"thscode": "600519.SH", "continue_day_cnt": 2, "seal_money": 123456.0},
                    {"thscode": "000001.SZ", "continue_day_cnt": 1, "seal_money": 888.0},
                ],
            },
        })
    ])
    client = HiThinkClient("secret", session=session)
    rows = client.fetch_limit_up_pool(date(2026, 9, 1), symbols=["600519.SH"])

    assert rows == [
        ("600519.SH", "2026-09-01", "is_limit_up", 1.0, "hithink_limit_up_pool"),
        ("600519.SH", "2026-09-01", "limit_up_streak", 2.0, "hithink_limit_up_pool"),
        (
            "600519.SH",
            "2026-09-01",
            "limit_up_seal_money",
            123456.0,
            "hithink_limit_up_pool",
        ),
    ]
    params = session.calls[0][1]
    assert params["page"] == 1
    assert params["size"] == 200
    assert isinstance(params["date_ms"], int)
    assert params["date_ms"] > 0
