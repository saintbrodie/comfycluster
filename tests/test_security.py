import asyncio

from comfycluster_common.tenancy import UserRecord
from comfycluster_controller.security import BuiltinTokenAuthProvider, agent_authorized
from comfycluster_controller.store import FleetStore


def test_agent_auth_is_optional_for_local_development():
    assert agent_authorized(None, None) is True


def test_agent_auth_accepts_matching_bearer_token():
    assert agent_authorized("Bearer correct-horse", "correct-horse") is True
    assert agent_authorized("bearer correct-horse", "correct-horse") is True


def test_agent_auth_rejects_missing_malformed_or_wrong_token():
    assert agent_authorized(None, "secret") is False
    assert agent_authorized("secret", "secret") is False
    assert agent_authorized("Basic secret", "secret") is False
    assert agent_authorized("Bearer wrong", "secret") is False


def test_builtin_human_auth_provider_keeps_development_mode_explicit():
    provider = BuiltinTokenAuthProvider(FleetStore(), None)
    principal = asyncio.run(provider.authenticate(None))
    assert principal is not None
    assert principal.user_id == "dev-admin"
    assert principal.platform_admin is True
    assert principal.content_auditor is True


def test_builtin_human_auth_provider_separates_platform_admin_from_content_auditor():
    provider = BuiltinTokenAuthProvider(FleetStore(), "admin-secret")
    principal = asyncio.run(provider.authenticate("Bearer admin-secret"))
    assert principal is not None
    assert principal.user_id == "platform-admin"
    assert principal.platform_admin is True
    assert principal.content_auditor is False


def test_builtin_human_auth_provider_resolves_user_tokens_through_store():
    store = FleetStore()
    asyncio.run(store.create_user(UserRecord(user_id="alice", display_name="Alice")))
    issued = asyncio.run(store.issue_token("alice", "desktop"))
    provider = BuiltinTokenAuthProvider(store, "admin-secret")

    principal = asyncio.run(provider.authenticate(f"Bearer {issued.token}"))

    assert principal is not None
    assert principal.user_id == "alice"
    assert principal.display_name == "Alice"
    assert principal.platform_admin is False
    assert principal.content_auditor is False
