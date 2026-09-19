from __future__ import annotations

import hmac

from comfycluster_common.tenancy import Principal

from .store import FleetStore


def _bearer_value(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, separator, value = authorization.partition(" ")
    if not separator or scheme.casefold() != "bearer" or not value:
        return None
    return value.strip()


def agent_authorized(authorization: str | None, expected_token: str | None) -> bool:
    """Validate the agent WebSocket bearer token."""
    if not expected_token:
        return True
    value = _bearer_value(authorization)
    return bool(value and hmac.compare_digest(value, expected_token))


async def authenticate_principal(
    authorization: str | None,
    store: FleetStore,
    admin_token: str | None,
) -> Principal | None:
    """Resolve a human API principal without conflating agent and user credentials.

    With no configured admin token the controller remains in explicit development
    mode so the existing local demo/test flow stays zero-config. Production installs
    generate an admin token and therefore require bearer authentication.
    """
    value = _bearer_value(authorization)
    if not admin_token:
        return Principal(
            user_id="dev-admin",
            display_name="Development Admin",
            platform_admin=True,
            content_auditor=True,
        )
    if not value:
        return None
    if hmac.compare_digest(value, admin_token):
        return Principal(
            user_id="platform-admin",
            display_name="Platform Admin",
            platform_admin=True,
            content_auditor=False,
        )
    return await store.principal_for_token(value)
