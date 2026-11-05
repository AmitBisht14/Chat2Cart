import webbrowser

import httpx
import typer

from chat2cart.config import load_settings
from chat2cart.logging import configure_logging
from chat2cart.secrets import LLM_API_KEY, KeychainSecretStore, SecretStore
from chat2cart.swiggy.errors import AuthError
from chat2cart.swiggy.oauth import login as swiggy_login

SECRET_NAMES = {"llm-api-key": LLM_API_KEY}
UNKNOWN_SECRET_EXIT_CODE = 2
HTTP_TIMEOUT_SECONDS = 30

app = typer.Typer(help="Chat2Cart: turn WhatsApp messages into a Swiggy Instamart cart.")
secrets_app = typer.Typer(help="Store secrets in the macOS Keychain.")
app.add_typer(secrets_app, name="secrets")
login_app = typer.Typer(help="Log in to external services.")
app.add_typer(login_app, name="login")


@app.callback()
def main() -> None:
    """Chat2Cart command line."""
    configure_logging(load_settings())


def build_secret_store() -> SecretStore:
    return KeychainSecretStore()


@secrets_app.command("set")
def set_secret(name: str) -> None:
    """Store a secret. The value is read from a hidden prompt, never from an argument."""
    key = SECRET_NAMES.get(name)
    if key is None:
        # The name is not echoed: someone may have typed the secret value in its place.
        typer.echo(f"Unknown secret name. Supported: {', '.join(SECRET_NAMES)}", err=True)
        raise typer.Exit(UNKNOWN_SECRET_EXIT_CODE)
    value = typer.prompt("Value", hide_input=True)
    build_secret_store().set(key, value)
    typer.echo(f"Saved {name} to the Keychain.")


@login_app.command("swiggy")
def login_swiggy() -> None:
    """Log in to Swiggy in the browser; the phone number and OTP are entered on Swiggy's page."""
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as http:
            swiggy_login(build_secret_store(), http, open_browser=open_authorize_url)
    except AuthError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    typer.echo("Logged in to Swiggy. Tokens saved to the Keychain.")


def open_authorize_url(url: str) -> None:
    typer.echo(f"Opening Swiggy login in your browser. If nothing opens, visit:\n{url}")
    webbrowser.open(url)
