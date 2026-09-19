import pytest
from fastapi.testclient import TestClient

from comfycluster_common.models import JobRecord, JobState, JobSubmitRequest
from comfycluster_common.tenancy import GroupPolicy, GroupRecord, MembershipRecord, UserRecord
from comfycluster_controller.app import create_app
from comfycluster_controller.scheduler import Scheduler
from comfycluster_controller.store import FleetStore


ADMIN = {"Authorization": "Bearer admin-secret"}


def _provision_user(client: TestClient, user_id: str, group_id: str, *, display_name: str | None = None):
    created = client.post(
        "/api/v1/admin/users",
        headers=ADMIN,
        json={"user_id": user_id, "display_name": display_name or user_id},
    )
    assert created.status_code == 200
    membership = client.post(
        "/api/v1/admin/memberships",
        headers=ADMIN,
        json={"user_id": user_id, "group_id": group_id},
    )
    assert membership.status_code == 200
    issued = client.post(
        f"/api/v1/admin/users/{user_id}/tokens",
        headers=ADMIN,
        json={"label": "test"},
    )
    assert issued.status_code == 200
    return {"Authorization": f"Bearer {issued.json()['token']}"}


def test_private_groups_isolate_job_content_and_admin_only_gets_summaries():
    client = TestClient(create_app(admin_token="admin-secret"))
    for group_id, name in (("alpha", "Alpha"), ("beta", "Beta")):
        response = client.post(
            "/api/v1/admin/groups",
            headers=ADMIN,
            json={"group_id": group_id, "name": name},
        )
        assert response.status_code == 200

    alice = _provision_user(client, "alice", "alpha")
    charlie = _provision_user(client, "charlie", "alpha")
    bob = _provision_user(client, "bob", "beta")

    submitted = client.post(
        "/api/v1/jobs",
        headers=alice,
        json={"group_id": "alpha", "workflow": {"1": {"class_type": "KSampler", "inputs": {}}}},
    )
    assert submitted.status_code == 202
    job_id = submitted.json()["job_id"]

    same_group = client.get(f"/api/v1/jobs/{job_id}", headers=charlie)
    assert same_group.status_code == 200
    assert same_group.json()["request"]["workflow"]["1"]["class_type"] == "KSampler"

    other_group = client.get(f"/api/v1/jobs/{job_id}", headers=bob)
    assert other_group.status_code == 404
    assert client.get("/api/v1/jobs", headers=bob).json() == []

    # Platform administrators operate the queue without receiving content visibility.
    assert client.get("/api/v1/jobs", headers=ADMIN).json() == []
    summaries = client.get("/api/v1/admin/jobs", headers=ADMIN)
    assert summaries.status_code == 200
    assert summaries.json()[0]["job_id"] == job_id
    assert "request" not in summaries.json()[0]
    assert "outputs" not in summaries.json()[0]


def test_user_queue_limit_rejects_excess_jobs():
    client = TestClient(create_app(admin_token="admin-secret"))
    assert client.post(
        "/api/v1/admin/groups",
        headers=ADMIN,
        json={
            "group_id": "creative",
            "name": "Creative",
            "policy": {"max_queued_jobs": 50, "max_running_jobs": 2, "weight": 1},
        },
    ).status_code == 200
    assert client.post(
        "/api/v1/admin/users",
        headers=ADMIN,
        json={
            "user_id": "alice",
            "display_name": "Alice",
            "max_queued_jobs": 1,
            "max_running_jobs": 1,
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
    assert second.json()["detail"] == {
        "error": "queue_limit_reached",
        "scope": "user",
        "limit": 1,
        "current": 1,
    }


def test_agent_token_does_not_authenticate_human_api():
    client = TestClient(create_app(agent_token="machine-secret", admin_token="admin-secret"))
    response = client.get("/api/v1/hosts", headers={"Authorization": "Bearer machine-secret"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_running_limits_are_enforced_before_dispatch():
    store = FleetStore()
    await store.create_group(
        GroupRecord(
            group_id="creative",
            name="Creative",
            policy=GroupPolicy(max_queued_jobs=20, max_running_jobs=1, weight=1),
        )
    )
    await store.create_user(UserRecord(user_id="alice", display_name="Alice", max_running_jobs=1))
    await store.add_membership(MembershipRecord(user_id="alice", group_id="creative"))
    running = JobRecord(
        request=JobSubmitRequest(workflow={}, group_id="creative"),
        owner_user_id="alice",
        group_id="creative",
        state=JobState.RUNNING,
    )
    waiting = JobRecord(
        request=JobSubmitRequest(workflow={}, group_id="creative"),
        owner_user_id="alice",
        group_id="creative",
    )
    await store.create_job(running)
    await store.create_job(waiting)

    allowed, reasons = await store.can_dispatch(waiting)
    assert allowed is False
    assert set(reasons) == {"user_running_limit", "group_running_limit"}


def test_weighted_fair_scheduler_advances_virtual_runtime():
    scheduler = Scheduler()
    groups = [
        GroupRecord(group_id="a", name="A", policy=GroupPolicy(weight=1)),
        GroupRecord(group_id="b", name="B", policy=GroupPolicy(weight=2)),
    ]
    jobs = [
        JobRecord(request=JobSubmitRequest(workflow={}, group_id="a"), group_id="a"),
        JobRecord(request=JobSubmitRequest(workflow={}, group_id="b"), group_id="b"),
    ]

    scheduler.note_dispatch("a", groups)
    scheduler.note_dispatch("b", groups)
    assert scheduler.fair_group_order(jobs, groups)[0] == "b"

    scheduler.note_dispatch("b", groups)
    assert scheduler.fair_group_order(jobs, groups)[0] == "a"
