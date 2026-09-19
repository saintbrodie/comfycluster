from pathlib import Path

import pytest

from comfycluster_common.tenancy import GroupRecord, MembershipRecord, UserRecord
from comfycluster_controller.sqlite_store import SQLiteFleetStore


@pytest.mark.asyncio
async def test_tenant_identity_and_token_survive_restart(tmp_path: Path):
    path = tmp_path / "fleet.db"
    first = SQLiteFleetStore(path)
    await first.create_group(GroupRecord(group_id="creative", name="Creative"))
    await first.create_user(UserRecord(user_id="alice", display_name="Alice"))
    await first.add_membership(MembershipRecord(user_id="alice", group_id="creative"))
    issued = await first.issue_token("alice", "workstation")
    first.close()

    second = SQLiteFleetStore(path)
    principal = await second.principal_for_token(issued.token)
    assert principal is not None
    assert principal.user_id == "alice"
    assert principal.group_ids == ["creative"]
    second.close()


@pytest.mark.asyncio
async def test_revoked_token_stays_revoked_after_restart(tmp_path: Path):
    path = tmp_path / "fleet.db"
    first = SQLiteFleetStore(path)
    await first.create_user(UserRecord(user_id="alice", display_name="Alice"))
    issued = await first.issue_token("alice", "workstation")
    assert await first.revoke_token(issued.token_id) is True
    first.close()

    second = SQLiteFleetStore(path)
    assert await second.principal_for_token(issued.token) is None
    second.close()
