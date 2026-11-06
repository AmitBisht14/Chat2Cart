class SwiggyError(Exception):
    """Base class for every Swiggy-related failure."""


class AuthError(SwiggyError):
    """Login or token handling with Swiggy failed."""

    def __init__(
        self, message: str, *, status: int | None = None, rpc_code: int | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.rpc_code = rpc_code


class NeedsLoginError(AuthError):
    """The Swiggy session has ended; the user must log in again."""
