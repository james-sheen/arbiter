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

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Callable, Iterator

__all__ = ["as_naive_utc", "now_utc", "as_of", "clock_is_frozen"]


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
    clock. ``InMemoryObservationHistory.get_values`` computes
    ``cutoff = now_utc() - window`` and needs no change to follow.

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
