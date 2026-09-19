from comfycluster_controller.security import agent_authorized


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
