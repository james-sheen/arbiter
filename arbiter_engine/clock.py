"""One clock for the engine, and one answer to what an aware timestamp means.

Before this module the cut read the system clock at 47 independent
sites across 21 files. Thirty-seven were spelled as a call; the other ten were
spelled ``field(default_factory=...)``, which is the same decision written
without parentheses and therefore invisible to a grep written for the first
form. An external report inventoried the call sites and missed all ten, which
is the reason this module exists rather than a tidier sweep of the call sites.

THE CONVENTION, DECIDED ONCE AND STATED HERE

Every timestamp the engine stores or compares is NAIVE and reads as UTC. That
is what this codebase already ruled for its own clock work elsewhere, and it
keeps arithmetic correct against timestamps written by earlier versions. Aware
inputs are not rejected -- they are CONVERTED at the boundary they arrive on,
by ``as_naive_utc``, after which every internal comparison may assume naive-UTC
on both sides without checking.

WHY ``now_utc`` DOES NOT CALL THE DEPRECATED CONSTRUCTOR

Routing 47 sites through a helper that still called it would have centralised
the convention and kept the warning storm: one warning per observation
ingested, which measured 8,342 in a single downstream suite run on 3.12. A
volume at which the next real warning is not read. ``datetime.now(timezone.utc)``
computes the same instant with no deprecation; dropping the tzinfo afterwards
is what makes the result naive-UTC rather than aware-UTC.

WHY THE ORDER INSIDE ``as_naive_utc`` IS LOAD-BEARING

Convert THEN flatten. The three defensive strips this module replaces did only
the flattening, which keeps the local wall-clock reading and discards the zone
that explains it. Measured against one entity created ten minutes ago and past
its 120-second threshold, changing only how the caller spelled the same
instant: naive and ``Z`` both produced a finding at 600s; ``+08:00`` produced a
negative age and NO FINDING AT ALL; ``-05:00`` produced 18,600s, which is past
twice the threshold and so also escalated the severity. One instant, three
verdicts, decided by the reporter's timezone.
"""

import calendar as _calendar
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterator, Union

__all__ = ["as_naive_utc", "now_utc", "as_of", "clock_is_frozen",
           "CalendarSpan", "shift_months", "span_back", "span_forward",
           "span_seconds_back", "span_seconds_forward", "span_times",
           "span_is_positive"]


def _system_now() -> datetime:
    """The wall clock, in the engine's convention. The default provider."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


#: WHY THE PROVIDER IS SWAPPABLE AND ``now_utc`` IS NOT
#:
#: Twenty-five modules do ``from .clock import now_utc``, which binds the
#: function object at import. Rebinding ``clock.now_utc`` afterwards therefore
#: changes nothing for any of them -- they already hold the old one. The only
#: seam that reaches every caller is INSIDE the function, so that is where it
#: is: ``now_utc`` stays the single name everyone imports, and what it reads is
#: what moves.
#:
#: WHY A ContextVar RATHER THAN A MODULE GLOBAL
#:
#: A plain global would make freezing the clock a process-wide act. This engine
#: is imported by a long-lived MCP server whose tools are called independently,
#: so one caller replaying last Tuesday would silently move every concurrent
#: caller's windows, retention cut-offs and grading deadlines to last Tuesday
#: as well -- and the symptom would be a check that declined
#: ``insufficient_samples`` on live data, which reads exactly like a quiet feed.
#:
#: A ContextVar is per-thread and per-task, so the freeze reaches the work
#: inside the ``with`` block and nothing else. The sibling core in this family
#: took the same decision for the same reason when its vocabulary had to be
#: per-call rather than ambient.
#:
#: The consequence worth knowing: a thread started INSIDE ``as_of`` does not
#: inherit the frozen clock, while an asyncio task created inside it DOES,
#: because a task copies the context at creation. Both are correct
#: ContextVar semantics rather than choices made here.
_provider: ContextVar[Callable[[], datetime]] = ContextVar(
    "arbiter_engine_clock_provider", default=_system_now,
)


def now_utc() -> datetime:
    """The current instant, naive, reading as UTC. The engine's only clock.

    Reads the active provider, which is the wall clock unless a caller is
    inside :func:`as_of`.
    """
    return _provider.get()()


def clock_is_frozen() -> bool:
    """True inside :func:`as_of`. For a caller that must report which clock
    produced a result -- a replay record that cannot say whether it was
    replayed is not a replay record."""
    return _provider.get() is not _system_now


@contextmanager
def as_of(at: datetime) -> Iterator[datetime]:
    """Read every clock in the engine as ``at`` for the duration of the block.

    Every window, retention cut-off and grading deadline in the engine is
    anchored at ``now_utc()``, so this is the whole of what a replay or a
    backtest needs: feed history once with real timestamps, then step the
    clock. ``InMemoryObservationHistory.get_values`` reads
    ``cutoff = now_utc() - window`` and bounds the far end at ``now_utc()``
    too, so a step reads the span that ended at the instant asked for and not
    the one running past it into the recorded future.

    The instant is normalised ONCE, here, by :func:`as_naive_utc` -- so an
    aware ``at`` is converted rather than stripped, and the block cannot
    observe a different instant than the caller asked for.

    Nests correctly: the provider is restored to whatever was active on entry,
    not to the wall clock.

    **This moves the clock, not the data.** Threshold axioms read
    ``Entity.properties`` -- the current value -- while the temporal axioms
    read history, and the current value does not follow the clock by itself.
    A replay that only moves the clock is checking today's values against
    last Tuesday's windows.
    """
    fixed = as_naive_utc(at)
    token = _provider.set(lambda: fixed)
    try:
        yield fixed
    finally:
        _provider.reset(token)


def as_naive_utc(value: datetime) -> datetime:
    """Normalise a caller-supplied timestamp to the internal convention.

    Naive values pass through unchanged. They are already read as UTC, and
    guessing that a naive value meant local time would silently move instants
    that are correct today.

    Aware values are converted to UTC first and only then flattened. Doing only
    the second half is the defect this function was written to remove.

    Raises ``TypeError`` for a non-datetime, which is deliberate: the three
    axiom sites that call this sit inside ``except (ValueError, TypeError)``
    blocks, and a property holding an int used to reach an attribute lookup and
    raise ``AttributeError`` past them.
    """
    if not isinstance(value, datetime):
        raise TypeError(
            f"expected a datetime, got {type(value).__name__}"
        )
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# a span that names calendar months.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CalendarSpan:
    """A duration that names calendar months, which no number of seconds is.

    A month has no fixed length, so a span naming one cannot be a `timedelta`:
    it is a count of calendar months and a fixed remainder, applied at the
    instant it is measured from. `n` months from an instant moves its calendar
    month by `n` and keeps the day, clamped to that month's last; the months
    apply first, then the fixed part. A year is twelve months.

    Measured on engine 0.2.33, a month written as 30 days on a monthly series
    read the previous capture when the captures fell at month end and the one
    before it when they fell on the 1st or the 15th -- the same declared number
    right or wrong by the day of the month.

    A duration naming no month stays a `timedelta`, so nothing that was read
    before changes. Every reader applies either through `span_back` and
    `span_forward`.
    """
    months: int
    fixed: timedelta = timedelta(0)
    #: As the author wrote it, for what the engine reports back.
    written: str = ""

    def back_from(self, instant: datetime) -> datetime:
        return shift_months(instant, -self.months) - self.fixed

    def forward_from(self, instant: datetime) -> datetime:
        return shift_months(instant, self.months) + self.fixed

    def __str__(self) -> str:
        return self.written or f"{self.months}mo {self.fixed}"


#: What a duration key holds: a fixed span, or one naming calendar months.
Span = Union[timedelta, CalendarSpan]


def shift_months(instant: datetime, months: int) -> datetime:
    """`instant` moved by whole calendar months, its day clamped to the last of
    the month it lands in: Mar 31 back one month is Feb 28 (29 in a leap year),
    and Jan 31 forward one month is the same."""
    if not months:
        return instant
    index = instant.year * 12 + (instant.month - 1) + months
    year, month0 = divmod(index, 12)
    day = min(instant.day, _calendar.monthrange(year, month0 + 1)[1])
    return instant.replace(year=year, month=month0 + 1, day=day)


def span_back(span: Span, instant: datetime) -> datetime:
    """The instant `span` before `instant`: where a window measured back from
    it starts."""
    if isinstance(span, CalendarSpan):
        return span.back_from(instant)
    return instant - span


def span_forward(span: Span, instant: datetime) -> datetime:
    """The instant `span` after `instant`: where a horizon from it ends."""
    if isinstance(span, CalendarSpan):
        return span.forward_from(instant)
    return instant + span


def span_seconds_back(span: Span, instant: datetime) -> float:
    """How many seconds `span` covers measured back from `instant` -- the one
    length a span naming months has, and only at that instant."""
    return (instant - span_back(span, instant)).total_seconds()


def span_seconds_forward(span: Span, instant: datetime) -> float:
    """How many seconds `span` covers measured forward from `instant`."""
    return (span_forward(span, instant) - instant).total_seconds()


def span_times(span: Span, factor: int) -> Span:
    """`span` taken `factor` times: its months and its fixed part each scaled."""
    if isinstance(span, CalendarSpan):
        return CalendarSpan(span.months * factor, span.fixed * factor,
                            f"{factor} x {span}")
    return span * factor


def span_is_positive(span: Span) -> bool:
    """Whether `span` declares any time at all."""
    if isinstance(span, CalendarSpan):
        return span.months > 0 or span.fixed > timedelta(0)
    return span > timedelta(0)

