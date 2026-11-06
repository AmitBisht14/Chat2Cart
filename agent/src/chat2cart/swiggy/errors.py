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


class BadInputError(SwiggyError):
    """Swiggy rejected the request arguments. Retrying the same call cannot help."""


class UpstreamError(SwiggyError):
    """Swiggy is slow, unreachable, failing or rate limiting. The call may be retried."""

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class DomainError(SwiggyError):
    """Swiggy understood the call but reported `success: false`. Never retried."""

    def __init__(self, code: str | None, message: str, payload: dict[str, object]) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.payload = payload
