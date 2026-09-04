import pytest

from app.providers.symbols import UnsupportedSymbolError, baostock_code, normalize_thscode


def test_normalize_common_symbol_forms():
    assert normalize_thscode("600519") == "600519.SH"
    assert normalize_thscode("SH600519") == "600519.SH"
    assert normalize_thscode("sh.600519") == "600519.SH"
    assert normalize_thscode("000001.SZ") == "000001.SZ"
    assert normalize_thscode("920001") == "920001.BJ"


def test_baostock_rejects_beijing_exchange():
    assert baostock_code("600519.SH") == "sh.600519"
    assert baostock_code("000001") == "sz.000001"
    with pytest.raises(UnsupportedSymbolError):
        baostock_code("920001.BJ")
