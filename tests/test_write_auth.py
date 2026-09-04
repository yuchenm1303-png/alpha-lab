import pytest
from fastapi import HTTPException

from app.main import require_write_access


def test_write_access_fails_closed_without_server_token(monkeypatch):
    monkeypatch.delenv("ALPHALAB_ADMIN_TOKEN", raising=False)
    with pytest.raises(HTTPException) as exc_info:
        require_write_access("anything")
    assert exc_info.value.status_code == 503


def test_write_access_rejects_missing_or_wrong_token(monkeypatch):
    monkeypatch.setenv("ALPHALAB_ADMIN_TOKEN", "server-secret")
    with pytest.raises(HTTPException) as missing:
        require_write_access(None)
    assert missing.value.status_code == 401

    with pytest.raises(HTTPException) as wrong:
        require_write_access("wrong-secret")
    assert wrong.value.status_code == 401


def test_write_access_accepts_exact_token(monkeypatch):
    monkeypatch.setenv("ALPHALAB_ADMIN_TOKEN", "server-secret")
    assert require_write_access("server-secret") is None
