from __future__ import annotations

import hmac


def agent_authorized(authorization: str | None, expected_token: str | None) -> bool:
    """Validate the agent WebSocket bearer token.

    Authentication is opt-in for local development: if the controller has no
    token configured, existing unauthenticated agents continue to work. Real
    deployments should always configure a token and WSS/TLS.
    """
    if not expected_token:
        return True
    if not authorization:
        return False
    scheme, separator, value = authorization.partition(" ")
    if not separator or scheme.casefold() != "bearer" or not value:
        return False
    return hmac.compare_digest(value.strip(), expected_token)
