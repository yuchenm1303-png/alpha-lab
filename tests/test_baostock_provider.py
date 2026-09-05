from datetime import date

from app.providers.baostock import BaoStockClient


class Result:
    error_code = "0"
    error_msg = ""

    def __init__(self, fields=None, rows=None):
        self.fields = fields or []
        self._rows = list(rows or [])
        self._index = -1

    def next(self):
        self._index += 1
        return self._index < len(self._rows)

    def get_row_data(self):
        return self._rows[self._index]


class FakeBaoStock:
    def __init__(self):
        self.login_count = 0
        self.logout_count = 0
        self.calls = []

    def login(self):
        self.login_count += 1
        return Result()

    def logout(self):
        self.logout_count += 1
        return Result()

    def query_stock_basic(self, code):
        return Result(
            ["code", "code_name", "ipoDate", "outDate", "type", "status"],
            [[code, "Test", "2001-08-27", "", "1", "1"]],
        )

    def query_history_k_data_plus(self, code, fields, **kwargs):
        self.calls.append((code, fields, kwargs))
        names = fields.split(",")
        rows = [
            [
                "2026-09-01", code, "10", "11", "9.8", "10.5",
                "1000000", "10500000", "8.25", "1", "1",
            ],
            [
                "2026-09-02", code, "10.5", "10.6", "10", "10.2",
                "0", "0", "9.10", "0", "1",
            ],
        ]
        return Result(names, rows)


def test_baostock_uses_forward_adjustment_and_skips_suspension():
    fake = FakeBaoStock()
    client = BaoStockClient(fake)
    rows, unsupported = client.fetch_many_bars(
        ["600519.SH", "920001.BJ"], date(2026, 9, 1), date(2026, 9, 2)
    )

    assert unsupported == ["920001.BJ"]
    assert rows == [
        (
            "600519.SH",
            "2026-09-01",
            10.0,
            11.0,
            9.8,
            10.5,
            8.25,
            1000000.0,
            10500000.0,
            True,
            "2001-08-27",
        )
    ]
    assert fake.login_count == 1
    assert fake.logout_count == 1
    assert fake.calls[0][0] == "sh.600519"
    assert fake.calls[0][2]["adjustflag"] == "2"
    assert fake.calls[0][2]["frequency"] == "d"
