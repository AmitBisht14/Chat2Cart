from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

import httpx
import structlog
from pydantic import BaseModel, ValidationError

from chat2cart.secrets import SWIGGY_CLIENT, SWIGGY_TOKENS, SecretStore
from chat2cart.swiggy.errors import AuthError, NeedsLoginError
from chat2cart.swiggy.oauth import (
    TOKEN_URL,
    ClientRegistration,
    TokenResponse,
    parse_json,
    token_json,
    utc_now,
)

REFRESH_MARGIN = timedelta(seconds=60)
LOGIN_HINT = "Run chat2cart login swiggy"
UNAUTHORIZED_STATUS = 401
UNAUTHORIZED_RPC_CODE = -32001
INVALID_GRANT_STATUS = 400
INVALID_GRANT_ERROR = "invalid_grant"


class TokenSet(BaseModel):
    access_token: str
    refresh_token: str
    expires_at: datetime
    needs_login: bool = False


class TokenManager:
    """Keeps the stored Swiggy tokens fresh. Refresh tokens rotate: each refresh replaces both."""

    def __init__(
        self,
        store: SecretStore,
        http: httpx.Client,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._store = store
        self._http = http
        self._clock = clock

    def ensure_fresh(self) -> str:
        tokens = self._load()
        if tokens.expires_at - self._clock() <= REFRESH_MARGIN:
            tokens = self.refresh()
        return tokens.access_token

    def refresh(self) -> TokenSet:
        tokens = self._load()
        response = self._post_refresh(tokens)
        if response.is_error:
            self._raise_refresh_failure(response, tokens)
        refreshed = parse_json(TokenResponse, response.text)
        stored = token_json(refreshed, self._clock())
        self._store.set(SWIGGY_TOKENS, stored)
        new_tokens = TokenSet.model_validate_json(stored)
        structlog.get_logger().info("token_refreshed", expires_at=new_tokens.expires_at.isoformat())
        return new_tokens

    def expires_at(self) -> datetime | None:
        """When the access token expires, or None when there are no usable tokens.

        Only the time is returned, so a status display can show it without touching a secret.
        """
        stored = self._store.get(SWIGGY_TOKENS)
        if stored is None:
            return None
        try:
            return TokenSet.model_validate_json(stored).expires_at
        except ValidationError:
            return None

    def needs_login(self) -> bool:
        stored = self._store.get(SWIGGY_TOKENS)
        if stored is None:
            return True
        try:
            return TokenSet.model_validate_json(stored).needs_login
        except ValidationError:
            return True

    def _load(self) -> TokenSet:
        stored = self._store.get(SWIGGY_TOKENS)
        if stored is None:
            raise NeedsLoginError(LOGIN_HINT)
        try:
            tokens = TokenSet.model_validate_json(stored)
        except ValidationError:
            # Dropped on purpose: pydantic's message would echo the stored tokens.
            raise NeedsLoginError(LOGIN_HINT) from None
        if tokens.needs_login:
            raise NeedsLoginError(LOGIN_HINT)
        return tokens

    def _post_refresh(self, tokens: TokenSet) -> httpx.Response:
        try:
            return self._http.post(
                TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": tokens.refresh_token,
                    "client_id": self._client_id(),
                },
            )
        except httpx.HTTPError as error:
            raise AuthError("Could not reach Swiggy to refresh the session.") from error

    def _client_id(self) -> str:
        stored = self._store.get(SWIGGY_CLIENT)
        if stored is None:
            raise NeedsLoginError(LOGIN_HINT)
        return parse_json(ClientRegistration, stored).client_id

    def _raise_refresh_failure(self, response: httpx.Response, tokens: TokenSet) -> None:
        if (
            response.status_code == INVALID_GRANT_STATUS
            and _error_code(response) == INVALID_GRANT_ERROR
        ):
            flagged = tokens.model_copy(update={"needs_login": True})
            self._store.set(SWIGGY_TOKENS, flagged.model_dump_json())
            raise NeedsLoginError(LOGIN_HINT)
        raise AuthError("Swiggy rejected the token refresh.", status=response.status_code)


async def call_with_auth_retry[ResultT](
    manager: TokenManager, call: Callable[[str], Awaitable[ResultT]]
) -> ResultT:
    """Run call(access_token). After an auth failure, refresh once and call once more."""
    try:
        return await call(manager.ensure_fresh())
    except AuthError as error:
        if not _is_expired_token_error(error):
            raise
    return await call(manager.refresh().access_token)


def _is_expired_token_error(error: AuthError) -> bool:
    return error.status == UNAUTHORIZED_STATUS or error.rpc_code == UNAUTHORIZED_RPC_CODE


def _error_code(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    code = body.get("error") if isinstance(body, dict) else None
    return code if isinstance(code, str) else None
