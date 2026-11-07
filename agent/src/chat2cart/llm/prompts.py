def wrap_untrusted(text: str) -> str:
    """Put message text inside <message> tags with markup escaped, so it cannot close the tag.

    Message text is data from outside: prompts tell the model to treat what is inside the tags
    as content to read, never as instructions.
    """
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"<message>{escaped}</message>"
