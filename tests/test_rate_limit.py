from fastapi.testclient import TestClient

from comfycluster_controller.app import create_app
from comfycluster_controller.rate_limit import SlidingWindowRateLimiter


ADMIN = {"Authorization": "Bearer admin-secret"}


def test_sliding_window_limiter_expires_old_events():
    limiter = SlidingWindowRateLimiter(window_seconds=60)
    assert limiter.allow("alice", 2, now=0)[0] is True
    assert limiter.allow("alice", 2, now=1)[0] is True
    blocked = limiter.allow("alice", 2, now=2)
    assert blocked[0] is False
    assert blocked[1] == 2
    assert limiter.allow("alice", 2, now=61)[0] is True


def test_job_submission_rate_limit_is_enforced():
    client = TestClient(create_app(admin_token="admin-secret"))
    assert client.post(
        "/api/v1/admin/groups",
        headers=ADMIN,
        json={"group_id": "creative", "name": "Creative"},
    ).status_code == 200
    assert client.post(
        "/api/v1/admin/users",
        headers=ADMIN,
        json={
            "user_id": "alice",
            "display_name": "Alice",
            "max_queued_jobs": 10,
            "max_running_jobs": 2,
            "max_submissions_per_minute": 1,
        },
    ).status_code == 200
    assert client.post(
        "/api/v1/admin/memberships",
        headers=ADMIN,
        json={"user_id": "alice", "group_id": "creative"},
    ).status_code == 200
    issued = client.post("/api/v1/admin/users/alice/tokens", headers=ADMIN, json={})
    alice = {"Authorization": f"Bearer {issued.json()['token']}"}

    first = client.post(
        "/api/v1/jobs", headers=alice, json={"group_id": "creative", "workflow": {}}
    )
    second = client.post(
        "/api/v1/jobs", headers=alice, json={"group_id": "creative", "workflow": {}}
    )

    assert first.status_code == 202
    assert second.status_code == 429
    detail = second.json()["detail"]
    assert detail["error"] == "submission_rate_limit_reached"
    assert detail["limit"] == 1
    assert second.headers["retry-after"]


def test_disabled_group_cannot_accept_new_jobs():
    client = TestClient(create_app(admin_token="admin-secret"))
    assert client.post(
        "/api/v1/admin/groups",
        headers=ADMIN,
        json={"group_id": "paused", "name": "Paused", "active": False},
    ).status_code == 200
    assert client.post(
        "/api/v1/admin/users",
        headers=ADMIN,
        json={"user_id": "alice", "display_name": "Alice"},
    ).status_code == 200
    assert client.post(
        "/api/v1/admin/memberships",
        headers=ADMIN,
        json={"user_id": "alice", "group_id": "paused"},
    ).status_code == 200
    issued = client.post("/api/v1/admin/users/alice/tokens", headers=ADMIN, json={})
    alice = {"Authorization": f"Bearer {issued.json()['token']}"}

    response = client.post(
        "/api/v1/jobs", headers=alice, json={"group_id": "paused", "workflow": {}}
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "group is disabled"
