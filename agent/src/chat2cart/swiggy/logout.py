from typing import Literal

import httpx
import structlog
from pydantic import ValidationError

from chat2cart.secrets import SWIGGY_TOKENS, SecretStore
from chat2cart.swiggy.oauth import LOGOUT_URL
from chat2cart.swiggy.tokens import TokenSet

UNAUTHORIZED_STATUS = 401
SUCCESS_STATUSES = range(200, 400)

LogoutOutcome = Literal["revoked", "not_revoked", "not_logged_in"]


def logout_swiggy(store: SecretStore, http: httpx.Client) -> LogoutOutcome:
    """Revoke the Swiggy session and delete the stored tokens.

    The tokens are deleted even when Swiggy could not be reached, so the Mac no longer holds them;
    the outcome says whether Swiggy confirmed the logout. A 401 means the session had already
    ended, which counts as logged out.
    """
    stored = store.get(SWIGGY_TOKENS)
    if stored is None:
        return "not_logged_in"
    revoked = _revoke(http, _access_token(stored))
    store.delete(SWIGGY_TOKENS)
    return "revoked" if revoked else "not_revoked"


def _access_token(stored: str) -> str | None:
    try:
        return TokenSet.model_validate_json(stored).access_token
    except ValidationError:
        # Dropped on purpose: pydantic's message would echo the stored tokens.
        return None


def _revoke(http: httpx.Client, access_token: str | None) -> bool:
    if access_token is None:
        return False
    try:
        response = http.post(LOGOUT_URL, headers={"Authorization": f"Bearer {access_token}"})
    except httpx.HTTPError as error:
        structlog.get_logger().warning("swiggy_logout_unreachable", error_type=type(error).__name__)
        return False
    return response.status_code in SUCCESS_STATUSES or response.status_code == UNAUTHORIZED_STATUS
