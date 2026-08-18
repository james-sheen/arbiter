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

from datetime import datetime, timezone

__all__ = ["as_naive_utc", "now_utc"]


def now_utc() -> datetime:
    """The current instant, naive, reading as UTC. The engine's only clock."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


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
