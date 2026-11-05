class SwiggyError(Exception):
    """Base class for every Swiggy-related failure."""


class AuthError(SwiggyError):
    """Login or token handling with Swiggy failed."""
