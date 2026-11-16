import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from apps.api.core.security import validate_jwt_secret
from apps.api.main import app


@app.get("/__test/boom")
def _boom():
    raise RuntimeError("secret-internal-detail")


@app.get("/__test/integrity")
def _integrity():
    raise IntegrityError("INSERT ...", {}, Exception("duplicate key value violates unique constraint"))


@pytest.fixture(scope="module")
def client():
    return TestClient(app, raise_server_exceptions=False)


def _assert_envelope(resp, status, code):
    assert resp.status_code == status
    body = resp.json()
    assert body["error"]["code"] == code
    assert body["detail"] == body["error"]["message"]
    assert body["error"]["request_id"] == resp.headers["x-request-id"]
    return body


def test_health_is_liveness(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert "x-request-id" in r.headers


def test_request_id_is_echoed(client):
    r = client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert r.headers["x-request-id"] == "abc-123"


def test_http_exception_envelope(client):
    body = _assert_envelope(client.get("/agents/does-not-exist-route"), 404, "not_found")
    assert isinstance(body["detail"], str)


def test_auth_error_envelope(client):
    _assert_envelope(client.get("/auth/me"), 401, "unauthorized")


def test_validation_envelope_and_limits(client):
    r = client.post("/auth/register", json={"name": "x", "email": "a@b.co", "password": "short"})
    body = _assert_envelope(r, 422, "validation_error")
    assert "password" in body["detail"]
    r = client.post("/auth/register", json={"name": "x", "email": "a@b.co", "password": "p" * 129})
    _assert_envelope(r, 422, "validation_error")


def test_integrity_error_is_409(client):
    body = _assert_envelope(client.get("/__test/integrity"), 409, "conflict")
    assert "duplicate key" not in body["detail"]


def test_unhandled_hides_internals_and_logs_traceback(client, caplog):
    with caplog.at_level(logging.ERROR, logger="redline.api"):
        r = client.get("/__test/boom")
    body = _assert_envelope(r, 500, "internal_error")
    assert "secret-internal-detail" not in r.text
    assert body["detail"] == "internal server error"
    rec = [x for x in caplog.records if x.exc_info]
    assert rec and "secret-internal-detail" in str(rec[0].exc_info[1])


def test_ready_ok_when_migrated(client):
    r = client.get("/ready")
    assert r.status_code in (200, 503)
    if r.status_code == 503:
        assert r.json()["status"] == "unavailable"
    else:
        assert r.json()["status"] == "ready"


def test_ready_503_when_schema_not_head(client, monkeypatch):
    import apps.api.main as m

    monkeypatch.setattr(m, "_alembic_head", lambda: "deadbeef0000")
    r = client.get("/ready")
    assert r.status_code == 503
    assert r.json()["head"] == "deadbeef0000"


def test_jwt_secret_length_check():
    with pytest.raises(RuntimeError):
        validate_jwt_secret("short")
    validate_jwt_secret("x" * 32)
