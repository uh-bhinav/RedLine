"""Auth: register / login / me, JWT validation, and API-key lifecycle."""
import base64
import json
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from sqlalchemy import text

from apps.api.core.config import get_settings
from apps.api.core.db import SessionLocal

PW = "correct-horse-battery"


def _register(client, email="Ada@Example.com", name="Ada", password=PW):
    return client.post("/auth/register", json={"name": name, "email": email, "password": password})


def _claims(user_id, tenant_id, role="admin", delta=timedelta(minutes=5)):
    now = datetime.now(timezone.utc)
    return {"sub": str(user_id), "tid": str(tenant_id), "role": role, "iat": now, "exp": now + delta}


def _encode(claims, secret=None):
    s = get_settings()
    return jwt.encode(claims, secret or s.jwt_secret_key, algorithm=s.jwt_algorithm)


# ---------------- register / login / me ----------------
def test_register_creates_admin_with_token_and_lowercased_email(client):
    r = _register(client)
    assert r.status_code == 201
    body = r.json()
    assert body["token_type"] == "bearer" and body["access_token"]
    assert body["user"]["email"] == "ada@example.com"
    assert body["user"]["role"] == "admin"
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json() == body["user"]


def test_register_never_returns_password_material(client):
    r = _register(client)
    assert "password" not in r.text.lower().replace("passwordless", "")


def test_register_gives_each_user_own_tenant(client):
    a = _register(client, email="a@example.com").json()["user"]
    b = _register(client, email="b@example.com").json()["user"]
    assert a["tenant_id"] != b["tenant_id"]


def test_duplicate_email_is_409_case_insensitively(client):
    assert _register(client, email="dup@example.com").status_code == 201
    r = _register(client, email="DUP@example.com")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "conflict"


def test_register_rejects_invalid_email(client):
    assert _register(client, email="not-an-email").status_code == 422


def test_login_ok(client):
    _register(client, email="login@example.com")
    r = client.post("/auth/login", json={"email": "LOGIN@example.com", "password": PW})
    assert r.status_code == 200
    assert r.json()["user"]["email"] == "login@example.com"
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).status_code == 200


def test_login_bad_password_and_unknown_user_are_indistinguishable(client):
    _register(client, email="who@example.com")
    bad = client.post("/auth/login", json={"email": "who@example.com", "password": "wrong-password"})
    unknown = client.post("/auth/login", json={"email": "nobody@example.com", "password": PW})
    assert bad.status_code == unknown.status_code == 401
    assert bad.json()["detail"] == unknown.json()["detail"]


def test_me_requires_auth(client):
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Token abc"}).status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Bearer "}).status_code == 401


def test_me_with_api_key_is_400(client, api_key):
    assert client.get("/auth/me", headers=api_key.headers).status_code == 400


# ---------------- JWT validation ----------------
def test_expired_jwt_is_401(client, make_user):
    u = make_user()
    token = _encode(_claims(u.id, u.tenant_id, delta=timedelta(seconds=-10)))
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    assert "expired" in r.json()["detail"]


def test_jwt_signed_with_wrong_secret_is_401(client, make_user):
    u = make_user()
    token = _encode(_claims(u.id, u.tenant_id), secret="x" * 48)
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_tampered_jwt_payload_is_401(client, make_user):
    u = make_user(role="viewer")
    header, payload, sig = u.token.split(".")
    padded = payload + "=" * (-len(payload) % 4)
    data = json.loads(base64.urlsafe_b64decode(padded))
    data["role"] = "admin"
    forged = base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {header}.{forged}.{sig}"})
    assert r.status_code == 401


def test_jwt_with_alg_none_is_401(client, make_user):
    u = make_user()
    token = jwt.encode(_claims(u.id, u.tenant_id), key=None, algorithm="none")
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_garbage_token_is_401(client):
    assert client.get("/auth/me", headers={"Authorization": "Bearer not.a.jwt"}).status_code == 401


def test_valid_jwt_for_deleted_user_is_401(client, make_user):
    u = make_user()
    with SessionLocal() as s:
        s.execute(text("DELETE FROM users WHERE id = :i"), {"i": str(u.id)})
        s.commit()
    assert client.get("/auth/me", headers=u.headers).status_code == 401


# ---------------- API keys ----------------
def test_api_key_create_use_revoke_lifecycle(client, make_user):
    admin = make_user("admin")
    created = client.post("/auth/api-keys", headers=admin.headers)
    assert created.status_code == 201
    body = created.json()
    raw = body["key"]
    assert raw.startswith("rl_") and len(raw) > 20

    key_headers = {"Authorization": f"Bearer {raw}"}
    assert client.get("/dashboard/summary", headers=key_headers).status_code == 200

    assert client.delete(f"/auth/api-keys/{body['id']}", headers=admin.headers).status_code == 204
    revoked = client.get("/dashboard/summary", headers=key_headers)
    assert revoked.status_code == 401 and "revoked" in revoked.json()["detail"]
    # revoking again is idempotent
    assert client.delete(f"/auth/api-keys/{body['id']}", headers=admin.headers).status_code == 204


def test_unknown_api_key_is_401(client):
    r = client.get("/dashboard/summary", headers={"Authorization": "Bearer rl_doesnotexist"})
    assert r.status_code == 401


def test_api_key_list_is_masked_and_flags_revoked(client, make_user):
    admin = make_user("admin")
    k1 = client.post("/auth/api-keys", headers=admin.headers).json()
    k2 = client.post("/auth/api-keys", headers=admin.headers).json()
    client.delete(f"/auth/api-keys/{k1['id']}", headers=admin.headers)

    r = client.get("/auth/api-keys", headers=admin.headers)
    assert r.status_code == 200
    rows = {row["id"]: row for row in r.json()}
    assert set(rows) == {k1["id"], k2["id"]}
    assert rows[k1["id"]]["revoked"] is True and rows[k2["id"]]["revoked"] is False
    for raw, row in ((k1["key"], rows[k1["id"]]), (k2["key"], rows[k2["id"]])):
        assert raw not in r.text
        assert row["masked_key"].endswith(raw[-4:])
        assert raw[3:-4] not in row["masked_key"]
        assert row["masked_key"].startswith("rl_")


def test_api_key_endpoints_require_admin(client, make_user):
    for role in ("viewer", "developer"):
        u = make_user(role)
        assert client.post("/auth/api-keys", headers=u.headers).status_code == 403
        assert client.get("/auth/api-keys", headers=u.headers).status_code == 403
        assert client.delete(f"/auth/api-keys/{uuid.uuid4()}", headers=u.headers).status_code == 403
    assert client.post("/auth/api-keys").status_code == 401


def test_api_key_list_and_revoke_are_tenant_scoped(client, make_user):
    a, b = make_user("admin"), make_user("admin")
    key = client.post("/auth/api-keys", headers=a.headers).json()
    assert client.get("/auth/api-keys", headers=b.headers).json() == []
    assert client.delete(f"/auth/api-keys/{key['id']}", headers=b.headers).status_code == 404
    # still usable by its owner
    assert client.get("/dashboard/summary", headers={"Authorization": f"Bearer {key['key']}"}).status_code == 200


def test_revoke_unknown_key_is_404(client, make_user):
    admin = make_user("admin")
    assert client.delete(f"/auth/api-keys/{uuid.uuid4()}", headers=admin.headers).status_code == 404


def test_api_key_role_is_enforced(client, api_key):
    viewer = api_key.make(role="viewer")
    assert client.get("/dashboard/summary", headers=viewer.headers).status_code == 200
    assert client.post("/agents", json={"name": "x"}, headers=viewer.headers).status_code == 403
    dev = api_key.make(role="developer")
    assert client.post("/agents", json={"name": "x"}, headers=dev.headers).status_code == 201
    assert client.post("/auth/api-keys", headers=dev.headers).status_code == 403
