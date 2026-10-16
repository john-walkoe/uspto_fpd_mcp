"""One end-to-end time budget for a long tool call (ported from PTAB).

Cloudflare cuts a proxied request at about 100 s, and claude.ai then sees an
error the server never hears about. FPD_get_document_content_with_ocr runs a
chain (petition details with documents, falling back to the application file
wrapper, then the PDF download, pypdf, Mistral upload + OCR with retries, and
Docling), and FPD_Get_petition_details(include_documents=True) runs the first
link of it. Each step used to budget itself: three USPTO attempts of 30 s, a
60 s download, 120 s of OCR, 300 s of Docling. One Deadline is created when
the tool starts and every step below takes what is left of it, so retries
and fallbacks stay inside the one budget rather than each getting a fresh
one.

FPD differs from PTAB in one respect: the steps live in three layers
(FPDClient, DocumentExtractionService, the tools), and the USPTO request
path is shared with every search tool. So the running Deadline travels in a
ContextVar (`bind_deadline` / `current_deadline`) rather than as a
parameter: a step outside a bound call sees None and behaves exactly as
before, and a task spawned inside the block inherits it.

Env:
    FPD_CONTENT_DEADLINE_SECONDS    budget per FPD_get_document_content_with_ocr
                                    call and per FPD_Get_petition_details call
                                    with include_documents (default 85, under
                                    the ~100 s cut)
    FPD_STATISTICS_DEADLINE_SECONDS budget per FPD_get_petition_statistics and
                                    FPD_get_dismissal_grounds call (default
                                    60); sections not reached in time are
                                    returned flagged partial
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import os
import time
from typing import Any, Awaitable, Callable, Dict, Iterator, Optional, TypeVar

from ..shared.error_utils import format_error_response
from ..shared.unified_logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")

DEFAULT_CONTENT_DEADLINE_SECONDS = 85.0

#: FPD_get_petition_statistics and FPD_get_dismissal_grounds (2026-10-12
#: audit): a sequence of facet searches, each answered in a second or two,
#: so the budget sits well under the ~100 s cut with room for a retry.
DEFAULT_STATISTICS_DEADLINE_SECONDS = 60.0

#: The `error` text of a spent budget starts with this, so a caller (and a
#: test) can tell it from an upstream failure.
DEADLINE_EXCEEDED = "Deadline exceeded"

#: Below this many seconds left, a USPTO attempt or download is not started:
#: none can finish in less.
MIN_ATTEMPT_SECONDS = 2.0


class DeadlineExceeded(Exception):
    """The call's time budget ran out before the step could finish."""


class Deadline:
    """A monotonic end time. `clock` is injectable so tests can fake time."""

    def __init__(self, seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.seconds = float(seconds)
        self._clock = clock
        self._end = clock() + self.seconds

    def remaining(self) -> float:
        """Seconds left, never negative."""
        return max(0.0, self._end - self._clock())

    def expired(self) -> bool:
        return self.remaining() <= 0.0


def _seconds_from_env(name: str, default: float) -> float:
    """A positive number of seconds from `name`, else `default`."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning(f"Invalid {name}, using default {default:g}")
        return default
    return value if value > 0 else default


def content_deadline_seconds() -> float:
    """FPD_CONTENT_DEADLINE_SECONDS, else 85; non-positive or junk -> 85."""
    return _seconds_from_env("FPD_CONTENT_DEADLINE_SECONDS", DEFAULT_CONTENT_DEADLINE_SECONDS)


def statistics_deadline_seconds() -> float:
    """FPD_STATISTICS_DEADLINE_SECONDS, else 60; non-positive or junk -> 60."""
    return _seconds_from_env(
        "FPD_STATISTICS_DEADLINE_SECONDS", DEFAULT_STATISTICS_DEADLINE_SECONDS
    )


_CURRENT: contextvars.ContextVar[Optional[Deadline]] = contextvars.ContextVar(
    "fpd_call_deadline", default=None
)


@contextlib.contextmanager
def bind_deadline(deadline: Optional[Deadline]) -> Iterator[Optional[Deadline]]:
    """Every step run inside the block shares `deadline` (None: no budget)."""
    token = _CURRENT.set(deadline)
    try:
        yield deadline
    finally:
        _CURRENT.reset(token)


def current_deadline() -> Optional[Deadline]:
    """The running call's Deadline, or None outside a bound call."""
    return _CURRENT.get()


def check_room(minimum: Optional[float] = None) -> Optional[float]:
    """Seconds left in the running call's budget, or None when there is no
    budget. Raises DeadlineExceeded when fewer than `minimum` (default
    MIN_ATTEMPT_SECONDS) are left, so a step is never started that cannot
    finish."""
    deadline = current_deadline()
    if deadline is None:
        return None
    remaining = deadline.remaining()
    if remaining < (MIN_ATTEMPT_SECONDS if minimum is None else minimum):
        raise DeadlineExceeded("no time left for another step")
    return remaining


def room_for(seconds: float, minimum: Optional[float] = None) -> bool:
    """Would waiting `seconds` still leave room for one more step (of at
    least `minimum`, default MIN_ATTEMPT_SECONDS)?"""
    deadline = current_deadline()
    floor = MIN_ATTEMPT_SECONDS if minimum is None else minimum
    return deadline is None or deadline.remaining() >= seconds + floor


async def run_within_deadline(
    make: Callable[[], Awaitable[T]], minimum: Optional[float] = None
) -> T:
    """Run one step on what is left of the running call's budget.

    `make` builds the awaitable only after the room check passes, so a step
    that is refused never leaves an un-awaited coroutine behind. Outside a
    bound call this is exactly `await make()`. A step still running when the
    budget ends is cancelled and DeadlineExceeded raised in its place.
    """
    remaining = check_room(minimum)
    if remaining is None:
        return await make()
    scope = asyncio.timeout(remaining)
    try:
        async with scope:
            return await make()
    except TimeoutError as exc:
        if scope.expired():
            raise DeadlineExceeded("step ran past the deadline") from exc
        raise


def deadline_exceeded_response(request_id: Optional[str] = None) -> Dict[str, Any]:
    """The envelope a spent budget returns (408, like the other time limits).

    Authored text: it carries no upstream detail, so production keeps it."""
    return format_error_response(
        f"{DEADLINE_EXCEEDED}: this call ran out of its time budget before "
        "the USPTO and extraction steps finished. Try the call again; for a "
        "long document, FPD_get_document_download gives the PDF directly.",
        408,
        request_id,
        authored=True,
    )


def is_deadline_exceeded(result: Any) -> bool:
    """True when `result` is the envelope deadline_exceeded_response built."""
    return isinstance(result, dict) and str(result.get("error", "")).startswith(
        DEADLINE_EXCEEDED
    )
