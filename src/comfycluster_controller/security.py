from __future__ import annotations

import hmac
from typing import Protocol

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


class HumanAuthProvider(Protocol):
    """Pluggable human identity boundary for built-in tokens or future OIDC/SSO."""

    async def authenticate(self, authorization: str | None) -> Principal | None: ...


class BuiltinTokenAuthProvider:
    """Current local token provider.

    Keeping this behind HumanAuthProvider means Entra ID, generic OIDC, or another
    enterprise identity provider can replace token resolution without changing every
    controller endpoint or the tenancy/authorization rules that consume Principal.
    """

    def __init__(self, store: FleetStore, admin_token: str | None) -> None:
        self.store = store
        self.admin_token = admin_token

    async def authenticate(self, authorization: str | None) -> Principal | None:
        value = _bearer_value(authorization)
        if not self.admin_token:
            return Principal(
                user_id="dev-admin",
                display_name="Development Admin",
                platform_admin=True,
                content_auditor=True,
            )
        if not value:
            return None
        if hmac.compare_digest(value, self.admin_token):
            return Principal(
                user_id="platform-admin",
                display_name="Platform Admin",
                platform_admin=True,
                content_auditor=False,
            )
        return await self.store.principal_for_token(value)


async def authenticate_principal(
    authorization: str | None,
    store: FleetStore,
    admin_token: str | None,
) -> Principal | None:
    """Compatibility entrypoint for the controller's human authentication boundary."""
    provider: HumanAuthProvider = BuiltinTokenAuthProvider(store, admin_token)
    return await provider.authenticate(authorization)
