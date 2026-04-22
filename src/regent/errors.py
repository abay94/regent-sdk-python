from __future__ import annotations

from typing import Any

RegentErrorCode = str  # Literal union kept open for forward compatibility

KNOWN_CODES = frozenset(
    {
        "AGENT_NOT_FOUND",
        "AGENT_ALREADY_REVOKED",
        "EVENT_NOT_FOUND",
        "BATCH_NOT_FOUND",
        "NOT_YET_ANCHORED",
        "SCORE_NOT_FOUND",
        "ALERT_NOT_FOUND",
        "ALERT_NOT_OPEN",
        "MANDATE_NOT_FOUND",
        "MANDATE_ALREADY_INACTIVE",
        "MANDATE_LIMIT_EXCEEDED",
        "NETWORK_ERROR",
        "VALIDATION_ERROR",
        "UNAUTHORIZED",
    }
)


class RegentError(Exception):
    """Base class for all Regent SDK errors.

    All exceptions raised by public SDK methods are instances of
    ``RegentError`` or one of its subclasses.
    """

    def __init__(
        self,
        message: str,
        *,
        code: RegentErrorCode = "NETWORK_ERROR",
        status_code: int | None = None,
        request_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.request_id = request_id
        self.details = details

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"code={self.code!r}, "
            f"message={str(self)!r}, "
            f"status_code={self.status_code!r})"
        )


class RegentAPIError(RegentError):
    """Raised when the API returns a non-2xx HTTP response.

    ``status_code`` is always set to the HTTP status code.
    ``code`` maps to the ``code`` field in the API error body.
    """


class RegentNetworkError(RegentError):
    """Raised when a network-level failure occurs (timeout, DNS, connection refused)."""

    def __init__(self, message: str, *, cause: BaseException | None = None) -> None:
        super().__init__(message, code="NETWORK_ERROR")
        self.__cause__ = cause
