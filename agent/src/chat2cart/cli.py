import asyncio
import webbrowser
from collections.abc import Callable, Coroutine
from typing import Annotated

import httpx
import typer

from chat2cart.config import DEFAULT_ADDRESS_ENV, ENV_FILE, load_settings, save_env_value
from chat2cart.logging import configure_logging
from chat2cart.secrets import LLM_API_KEY, KeychainSecretStore, SecretStore
from chat2cart.swiggy.addresses import Address, list_addresses
from chat2cart.swiggy.cart import Cart, CartItem, read_cart, write_cart
from chat2cart.swiggy.client import SwiggyClient
from chat2cart.swiggy.errors import AuthError, NeedsLoginError, SwiggyError
from chat2cart.swiggy.oauth import login as swiggy_login
from chat2cart.swiggy.products import Product, Variant, search
from chat2cart.swiggy.tokens import TokenManager

SECRET_NAMES = {"llm-api-key": LLM_API_KEY}
UNKNOWN_SECRET_EXIT_CODE = 2
HTTP_TIMEOUT_SECONDS = 30

app = typer.Typer(help="Chat2Cart: turn WhatsApp messages into a Swiggy Instamart cart.")
secrets_app = typer.Typer(help="Store secrets in the macOS Keychain.")
app.add_typer(secrets_app, name="secrets")
login_app = typer.Typer(help="Log in to external services.")
app.add_typer(login_app, name="login")
swiggy_app = typer.Typer(help="Work with your Swiggy account.")
app.add_typer(swiggy_app, name="swiggy")


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


def build_swiggy_client(http: httpx.Client) -> SwiggyClient:
    return SwiggyClient(TokenManager(build_secret_store(), http))


@swiggy_app.command("address")
def choose_address() -> None:
    """Choose the delivery address used for carts and save it in .env."""
    addresses = fetch_addresses()
    if not addresses:
        typer.echo(
            "No saved addresses found. Add a delivery address in the Swiggy app, "
            "then run chat2cart swiggy address again.",
            err=True,
        )
        raise typer.Exit(1)
    for number, address in enumerate(addresses, start=1):
        typer.echo(f"{number}. {address.description}")
    chosen = ask_for_address(addresses)
    save_env_value(ENV_FILE, DEFAULT_ADDRESS_ENV, chosen.id)
    typer.echo(f"Saved your delivery address as {DEFAULT_ADDRESS_ENV} in {ENV_FILE.name}.")


def fetch_addresses() -> list[Address]:
    return run_swiggy(list_addresses)


def run_swiggy[ResultT](
    step: Callable[[SwiggyClient], Coroutine[object, object, ResultT]],
) -> ResultT:
    """Run one Swiggy step; a Swiggy failure becomes a one-line message and exit code 1."""
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as http:
            return asyncio.run(step(build_swiggy_client(http)))
    except NeedsLoginError as error:
        typer.echo("Run chat2cart login swiggy", err=True)
        raise typer.Exit(1) from error
    except SwiggyError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error


def ask_for_address(addresses: list[Address]) -> Address:
    while True:
        number: int = typer.prompt("Choose an address number", type=int)
        if 1 <= number <= len(addresses):
            return addresses[number - 1]
        typer.echo(f"Enter a number from 1 to {len(addresses)}.")


@app.command("prototype")
def prototype(
    item: Annotated[str, typer.Argument(help="The item to look for, for example: milk.")],
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Only search; do not touch the cart.")
    ] = False,
) -> None:
    """Milestone 0: search an item, add the chosen variant to your real cart, read the cart back.

    Never checks out or pays: review the cart and pay in the Swiggy app yourself.
    """
    address_id = require_default_address()
    variants = search_variants(item, address_id)
    for number, (product, variant) in enumerate(variants, start=1):
        stock = "in stock" if variant.in_stock else "OUT OF STOCK"
        typer.echo(f"{number}. {product.name} | {variant.pack_size} | Rs {variant.price} | {stock}")
    if dry_run:
        typer.echo("Dry run: cart not changed")
        return
    chosen = ask_for_variant(variants)
    cart = run_swiggy(read_cart)
    lines = add_one(cart.items, chosen)
    run_swiggy(lambda client: write_cart(client, lines, address_id))
    print_cart(run_swiggy(read_cart))


def require_default_address() -> str:
    address_id = load_settings(ENV_FILE).default_address_id
    if address_id is None:
        typer.echo("Run `chat2cart swiggy address` first", err=True)
        raise typer.Exit(2)
    return address_id


def search_variants(item: str, address_id: str) -> list[tuple[Product, Variant]]:
    products = run_swiggy(lambda client: search(client, item, address_id))
    variants = [(product, variant) for product in products for variant in product.variants]
    if not variants:
        typer.echo("No products found for that item.", err=True)
        raise typer.Exit(1)
    return variants


def ask_for_variant(variants: list[tuple[Product, Variant]]) -> Variant:
    if not any(variant.in_stock for _, variant in variants):
        typer.echo("None of these variants is in stock.", err=True)
        raise typer.Exit(1)
    while True:
        number: int = typer.prompt("Choose a variant number", type=int)
        if not 1 <= number <= len(variants):
            typer.echo(f"Enter a number from 1 to {len(variants)}.")
        elif not variants[number - 1][1].in_stock:
            typer.echo("That variant is out of stock. Choose another one.")
        else:
            return variants[number - 1][1]


def add_one(items: list[CartItem], variant: Variant) -> list[CartItem]:
    """The whole cart to write: every existing line, with one more of the chosen variant."""
    if any(item.spin_id == variant.spin_id for item in items):
        return [
            item.model_copy(update={"quantity": item.quantity + 1})
            if item.spin_id == variant.spin_id
            else item
            for item in items
        ]
    new_line = CartItem.model_validate(
        {
            "spin_id": variant.spin_id,
            "sku_id": variant.sku_id,
            "itemName": variant.name,
            "quantity": 1,
        }
    )
    return [*items, new_line]


def print_cart(cart: Cart) -> None:
    typer.echo("Your cart now:")
    for item in cart.items:
        typer.echo(f"- {item.name} x {item.quantity}")
    typer.echo(f"Total: Rs {cart.bill_total}")
    typer.echo("Review the cart and pay in the Swiggy app. This tool never checks out.")
