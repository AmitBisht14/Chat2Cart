import hashlib
import hmac
import json
from base64 import urlsafe_b64encode
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from secrets import token_urlsafe
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import structlog
from pydantic import BaseModel, ConfigDict, ValidationError

from chat2cart.secrets import SWIGGY_CLIENT, SWIGGY_TOKENS, SecretStore
from chat2cart.swiggy.errors import AuthError

SWIGGY_AUTH_URL = "https://mcp.swiggy.com/auth"
REGISTER_URL = f"{SWIGGY_AUTH_URL}/register"
AUTHORIZE_URL = f"{SWIGGY_AUTH_URL}/authorize"
TOKEN_URL = f"{SWIGGY_AUTH_URL}/token"
REDIRECT_URI = "http://localhost/callback"
# macOS lets unprivileged processes bind port 80 only on the wildcard address, not on 127.0.0.1.
CALLBACK_HOST = "0.0.0.0"  # noqa: S104
CALLBACK_PORT = 80
CALLBACK_TIMEOUT_SECONDS = 300
CLIENT_NAME = "Chat2Cart"
REDIRECT_HELP = (
    f"Swiggy only accepts {REDIRECT_URI} as the redirect address. "
    "Free port 80 and run the login again, or record the problem in P14."
)


@dataclass(frozen=True)
class Pkce:
    verifier: str
    challenge: str


class ClientRegistration(BaseModel):
    model_config = ConfigDict(extra="allow")

    client_id: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int


def utc_now() -> datetime:
    return datetime.now(UTC)


def login(
    store: SecretStore,
    http: httpx.Client,
    *,
    open_browser: Callable[[str], object],
    callback_port: int = CALLBACK_PORT,
    now: Callable[[], datetime] = utc_now,
) -> None:
    """Log in to Swiggy with OAuth 2.1 + PKCE and save the tokens in the secret store."""
    client_id = register_client(store, http)
    pkce = generate_pkce()
    state = token_urlsafe(32)
    authorize_url = build_authorize_url(client_id, pkce.challenge, state)
    params = receive_callback(open_browser, authorize_url, callback_port)
    code = authorization_code(params, state)
    tokens = exchange_code(http, client_id, code, pkce.verifier)
    save_tokens(store, tokens, now())


def generate_pkce() -> Pkce:
    verifier = token_urlsafe(64)
    return Pkce(verifier=verifier, challenge=challenge_for(verifier))


def challenge_for(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def register_client(store: SecretStore, http: httpx.Client) -> str:
    stored = store.get(SWIGGY_CLIENT)
    if stored is not None:
        return parse_json(ClientRegistration, stored).client_id
    response = _post(
        http,
        REGISTER_URL,
        f"Swiggy rejected the client registration. {REDIRECT_HELP}",
        json={
            "client_name": CLIENT_NAME,
            "redirect_uris": [REDIRECT_URI],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        },
    )
    registration = parse_json(ClientRegistration, response.text)
    store.set(SWIGGY_CLIENT, registration.model_dump_json())
    return registration.client_id


def build_authorize_url(client_id: str, challenge: str, state: str) -> str:
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


def receive_callback(
    open_browser: Callable[[str], object], authorize_url: str, port: int
) -> dict[str, str]:
    received: dict[str, str] = {}
    try:
        server = HTTPServer((CALLBACK_HOST, port), _callback_handler(received))
    except OSError as error:
        raise AuthError(f"Could not listen on {CALLBACK_HOST}:{port}. {REDIRECT_HELP}") from error
    server.timeout = CALLBACK_TIMEOUT_SECONDS
    try:
        open_browser(authorize_url)
        server.handle_request()
    finally:
        server.server_close()
    if not received:
        raise AuthError("Timed out waiting for the Swiggy login. Run the login again.")
    return received


def authorization_code(params: dict[str, str], expected_state: str) -> str:
    if "error" in params:
        raise AuthError(f"Swiggy rejected the login ({params['error']}). {REDIRECT_HELP}")
    if not hmac.compare_digest(params.get("state", ""), expected_state):
        raise AuthError("The login response did not match this login attempt (state mismatch).")
    code = params.get("code")
    if not code:
        raise AuthError("Swiggy did not return an authorization code.")
    return code


def exchange_code(http: httpx.Client, client_id: str, code: str, verifier: str) -> TokenResponse:
    response = _post(
        http,
        TOKEN_URL,
        "Swiggy rejected the token request.",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
        },
    )
    return parse_json(TokenResponse, response.text)


def save_tokens(store: SecretStore, tokens: TokenResponse, now: datetime) -> None:
    stored = token_json(tokens, now)
    store.set(SWIGGY_TOKENS, stored)
    structlog.get_logger().info("oauth_tokens_saved", expires_at=json.loads(stored)["expires_at"])


def token_json(tokens: TokenResponse, now: datetime) -> str:
    """The JSON kept under swiggy.tokens: both tokens and the absolute expiry time."""
    return json.dumps(
        {
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "expires_at": (now + timedelta(seconds=tokens.expires_in)).isoformat(),
        }
    )


def _callback_handler(received: dict[str, str]) -> type[BaseHTTPRequestHandler]:
    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            query = parse_qs(urlparse(self.path).query)
            received.update({name: values[0] for name, values in query.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Login finished. You can close this tab and return to the terminal.")

        def log_message(self, format: str, *args: object) -> None:
            # The default access log would write the authorization code to stderr.
            return

    return CallbackHandler


def _post(
    http: httpx.Client,
    url: str,
    failure_message: str,
    *,
    json: dict[str, object] | None = None,
    data: dict[str, str] | None = None,
) -> httpx.Response:
    try:
        response = http.post(url, json=json, data=data)
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise AuthError(failure_message) from error
    return response


def parse_json[ModelT: BaseModel](model: type[ModelT], text: str) -> ModelT:
    try:
        return model.model_validate_json(text)
    except ValidationError:
        # Dropped on purpose: pydantic's message would echo the response body, which holds tokens.
        raise AuthError("Swiggy returned an unexpected response.") from None
