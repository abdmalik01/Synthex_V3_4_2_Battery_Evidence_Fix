"""Public-safe UI error messages for Synthex.

Technical exception details belong in backend logs. Public notices intentionally
avoid echoing provider payloads, stack traces, credentials, model names, or
validation internals.
"""

from __future__ import annotations

from dataclasses import dataclass


_SERVER_BUSY_TOKENS = (
    "resource_exhausted",
    "quota",
    "429",
    "503",
    "unavailable",
    "high demand",
    "deadline_exceeded",
    "timeout",
    "timed out",
    "connection",
    "permission_denied",
    "permission denied",
    "denied access",
    "all configured gemini models",
    "all approved gemini models",
    "models unavailable",
)


@dataclass(frozen=True)
class PublicErrorNotice:
    title: str
    message: str
    status: str


def is_server_busy_error(exc: Exception) -> bool:
    """Return True for provider failures that should be hidden behind Server Busy."""
    text = f"{type(exc).__name__}: {exc}".casefold()
    return any(token in text for token in _SERVER_BUSY_TOKENS)


def public_error_notice(
    exc: Exception | None = None,
    *,
    context: str = "request",
    force_server_busy: bool = False,
) -> PublicErrorNotice:
    """Return a user-safe notice without exposing the underlying exception text."""
    if force_server_busy or (exc is not None and is_server_busy_error(exc)):
        return PublicErrorNotice(
            title="Server Busy",
            message="Our processing service is temporarily busy. Please try again shortly.",
            status="server_busy",
        )

    messages = {
        "discovery": "Paper search is temporarily unavailable. Please try again shortly.",
        "extraction_validation": (
            "We couldn't finish processing this paper on this attempt. Please try again; "
            "a cleaner or text-readable PDF may also help."
        ),
        "batch_selection": "That selection can't be processed as one batch. Please adjust the number of PDFs and try again.",
        "calibration": "We couldn't apply that calibration. Please review the entered points and try again.",
    }
    return PublicErrorNotice(
        title="Request Not Completed",
        message=messages.get(context, "Something interrupted this request. Please try again."),
        status="could_not_complete",
    )
