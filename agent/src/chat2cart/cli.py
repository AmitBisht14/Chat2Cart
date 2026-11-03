import typer

app = typer.Typer(help="Chat2Cart: turn WhatsApp messages into a Swiggy Instamart cart.")


@app.callback()
def main() -> None:
    """Chat2Cart command line."""
