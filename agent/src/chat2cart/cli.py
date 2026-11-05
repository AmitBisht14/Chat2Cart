import typer

from chat2cart.config import load_settings
from chat2cart.secrets import LLM_API_KEY, KeychainSecretStore, SecretStore

SECRET_NAMES = {"llm-api-key": LLM_API_KEY}
UNKNOWN_SECRET_EXIT_CODE = 2

app = typer.Typer(help="Chat2Cart: turn WhatsApp messages into a Swiggy Instamart cart.")
secrets_app = typer.Typer(help="Store secrets in the macOS Keychain.")
app.add_typer(secrets_app, name="secrets")


@app.callback()
def main() -> None:
    """Chat2Cart command line."""
    load_settings()


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
