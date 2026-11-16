"""POST /eval-runs rejects an unknown triggered_by with a clear 422 (not a vague DB 409)."""
import uuid


def test_invalid_triggered_by_is_422(client, make_user):
    user = make_user("developer")
    r = client.post(
        "/eval-runs",
        headers=user.headers,
        json={"agent_version_id": str(uuid.uuid4()), "suite_id": str(uuid.uuid4()), "triggered_by": "verify"},
    )
    assert r.status_code == 422
    assert "triggered_by" in r.json()["error"]["message"]
