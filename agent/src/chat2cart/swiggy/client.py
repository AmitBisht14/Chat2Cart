import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx2
import structlog
from mcp import ClientSession, MCPError, types
from mcp.client.streamable_http import streamable_http_client
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from chat2cart.swiggy.allowlist import ALLOWED_TOOLS
from chat2cart.swiggy.errors import (
    AuthError,
    BadInputError,
    BlockedToolError,
    DomainError,
    SwiggyError,
    UpstreamError,
)
from chat2cart.swiggy.tokens import TokenManager, call_with_auth_retry

SWIGGY_MCP_URL = "https://mcp.swiggy.com/im"
HTTP_TIMEOUT_SECONDS = 30.0
MAX_ATTEMPTS = 5
BACKOFF_INITIAL_SECONDS = 0.5
BACKOFF_MAX_SECONDS = 8.0
RPC_UNAUTHORIZED = -32001
RPC_INVALID_PARAMS = -32602

Transport = Callable[[str, str, dict[str, object]], Awaitable[dict[str, object]]]
Sleep = Callable[[float], Awaitable[None]]


class SwiggyClient:
    """The only way to call Swiggy. Swiggy tools are called from code, never bound to the LLM."""

    def __init__(
        self,
        tokens: TokenManager,
        transport: Transport | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._tokens = tokens
        self._transport = transport or McpTransport()
        self._sleep = sleep

    async def call_tool(
        self, name: str, arguments: dict[str, object] | None = None
    ) -> dict[str, object]:
        require_allowed_tool(name)
        call_arguments = arguments or {}
        log = structlog.get_logger()
        log.info("swiggy_call", tool=name, argument_keys=sorted(call_arguments))
        started = time.monotonic()
        succeeded = False
        try:
            payload = await call_with_auth_retry(
                self._tokens, lambda token: self._send(token, name, call_arguments)
            )
            raise_if_domain_failure(payload)
            succeeded = True
            return payload
        finally:
            duration = round(time.monotonic() - started, 3)
            log.info("swiggy_result", tool=name, ok=succeeded, duration_seconds=duration)

    async def _send(self, token: str, name: str, arguments: dict[str, object]) -> dict[str, object]:
        retrying = AsyncRetrying(
            retry=retry_if_exception_type(UpstreamError),
            stop=stop_after_attempt(MAX_ATTEMPTS),
            wait=_seconds_to_wait,
            sleep=self._sleep,
            reraise=True,
        )
        return await retrying(self._transport, token, name, arguments)


def require_allowed_tool(name: str) -> None:
    """Reject any tool outside ALLOWED_TOOLS before a token is read or a request is made."""
    if name in ALLOWED_TOOLS:
        return
    structlog.get_logger().warning("security_blocked_tool", tool=name)
    raise BlockedToolError(f"Swiggy tool '{name}' is not allowed.")


def raise_if_domain_failure(payload: dict[str, object]) -> None:
    if payload.get("success") is not False:
        return
    code, message = payload.get("code"), payload.get("message")
    raise DomainError(
        code=code if isinstance(code, str) else None,
        message=message if isinstance(message, str) else "Swiggy reported a failure.",
        payload=payload,
    )


def _seconds_to_wait(state: RetryCallState) -> float:
    error = state.outcome.exception() if state.outcome else None
    if isinstance(error, UpstreamError) and error.retry_after is not None:
        return error.retry_after
    backoff = wait_exponential_jitter(multiplier=BACKOFF_INITIAL_SECONDS, max=BACKOFF_MAX_SECONDS)
    return backoff(state)


@dataclass(frozen=True)
class HttpFailure:
    status: int
    retry_after: float | None


class _HttpFailures:
    """Remembers the latest failed POST. The SDK hides HTTP statuses behind a generic error."""

    def __init__(self) -> None:
        self.latest: HttpFailure | None = None

    async def record(self, response: httpx2.Response) -> None:
        # The standalone GET stream may answer 405 on servers without one; that is not a failure.
        if response.request.method == "POST" and response.status_code >= 400:
            retry_after = _retry_after_seconds(response.headers.get("retry-after"))
            self.latest = HttpFailure(response.status_code, retry_after)


@dataclass(frozen=True)
class McpTransport:
    """Calls one tool over the MCP SDK's streamable HTTP client with a bearer token."""

    url: str = SWIGGY_MCP_URL
    timeout_seconds: float = HTTP_TIMEOUT_SECONDS

    async def __call__(
        self, token: str, name: str, arguments: dict[str, object]
    ) -> dict[str, object]:
        require_allowed_tool(name)
        failures = _HttpFailures()
        try:
            # No SDK read timeout on purpose: its own timeout would use -32001, which Swiggy
            # uses for an expired token.
            async with httpx2.AsyncClient(
                headers={"Authorization": f"Bearer {token}"},
                timeout=self.timeout_seconds,
                event_hooks={"response": [failures.record]},
            ) as http:
                result = await _call_tool(self.url, http, name, arguments)
        except (MCPError, httpx2.HTTPError, ExceptionGroup) as error:
            raise failure_for(error, failures.latest) from error
        return parse_tool_result(result)


class _Session(ClientSession):
    async def validate_tool_result(self, name: str, result: types.CallToolResult) -> None:
        # The SDK would fetch tools/list to check output schemas: an extra round trip per call.
        # Results are validated by the caller's own models instead.
        return


async def _call_tool(
    url: str, http: httpx2.AsyncClient, name: str, arguments: dict[str, object]
) -> object:
    async with streamable_http_client(url, http_client=http) as (read, write):
        async with _Session(read, write) as session:
            await session.initialize()
            return await session.call_tool(name, arguments)


def failure_for(error: BaseException, http_failure: HttpFailure | None) -> SwiggyError:
    cause = _innermost(error)
    if isinstance(cause, MCPError):
        return classify_failure(cause, http_failure)
    if isinstance(cause, httpx2.HTTPError):
        return UpstreamError("Could not reach Swiggy in time.")
    return SwiggyError("Swiggy request failed unexpectedly.")


def _innermost(error: BaseException) -> BaseException:
    # The SDK runs its streams in a task group, which wraps a single failure in an ExceptionGroup.
    while isinstance(error, BaseExceptionGroup) and len(error.exceptions) == 1:
        error = error.exceptions[0]
    return error


def classify_failure(error: MCPError, http_failure: HttpFailure | None) -> SwiggyError:
    status = http_failure.status if http_failure else None
    if status == 401:
        return AuthError("Swiggy rejected the access token.", status=status)
    if http_failure is not None and status == 429:
        return UpstreamError(
            "Swiggy is rate limiting requests.", retry_after=http_failure.retry_after
        )
    if status is not None and status >= 500:
        return UpstreamError(f"Swiggy answered with HTTP {status}.")
    if status == 400 or error.code == RPC_INVALID_PARAMS:
        return BadInputError(error.message)
    if error.code == RPC_UNAUTHORIZED:
        return AuthError(error.message, rpc_code=error.code)
    return SwiggyError(f"Swiggy request failed (code {error.code}).")


def parse_tool_result(result: object) -> dict[str, object]:
    if not isinstance(result, types.CallToolResult):
        raise SwiggyError("Swiggy returned an unexpected kind of result.")
    # Swiggy's text content is a human-readable summary; the data is in structured content.
    if result.structured_content is not None:
        return dict(result.structured_content)
    texts = [item.text for item in result.content if isinstance(item, types.TextContent)]
    try:
        payload = json.loads(texts[0]) if texts else None
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        raise SwiggyError("Swiggy returned a result that is not a JSON object.")
    return payload


def _retry_after_seconds(header: str | None) -> float | None:
    try:
        return float(header) if header is not None else None
    except ValueError:
        return None  # An HTTP-date form is not worth parsing; the backoff covers it.
