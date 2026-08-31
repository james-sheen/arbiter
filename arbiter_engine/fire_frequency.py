"""FireFrequencyTracker — dedicated rolling-window fire counter.

The earlier FireCounterMixin (date-bucket Counter shape) was the
v1 instrumentation; this module lands the dedicated v2 tracker with:

- Per-(axiom, domain, indicator) granularity (the earlier mixin
  tracked (domain) only; this tracker adds the axiom + indicator
  dimensions the reflection-layer spec called for).
- Deque-based exact rolling-window counting (no day-bucket
  approximation; sliding window of arbitrary length).
- The cadence WARN on suspiciously high fire rates.

An internal ruling landed that migration: the mixin is gone, and the reasoner records
every axiom's fires into the shared tracker at its dispatch boundary. This
module moved from ``reflection/`` to ``detection/`` at the same time, so the
eight checkers can be counted without ``detection`` importing ``reflection`` —
the two packages are otherwise decoupled, and ``detection`` is what becomes
the extracted engine.

API contract:

- ``record_fire(axiom, domain, indicator=None, timestamp=None)``
- ``get_fire_rate(axiom, domain, indicator=None, window=24h) -> int``
- ``get_fires_by_axiom_domain(window=24h) -> Dict[axiom, Dict[domain, int]]``
- ``get_fires_by_indicator(window=24h) -> Dict[(axiom, domain, indicator), int]``
- ``prune(now=None)`` — evict entries older than retention
- ``count()`` / ``clear()`` ops helpers

Per read-only-by-design + hook-not-replicate principles:
axiom checkers + reflection-side consumers both read this tracker;
no shadow storage.
"""

import logging
from collections import Counter, defaultdict, deque
from datetime import datetime, timedelta
from .clock import as_naive_utc, now_utc

from typing import Counter as TypedCounter
from typing import DefaultDict, Deque, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


# Default retention window — entries older than this are evicted
# on prune. Generous default so the 24h get_fire_rate query never
# misses entries due to clock skew.
_DEFAULT_RETENTION = timedelta(days=2)


class FireFrequencyTracker:
    """per-(axiom, domain, indicator) rolling fire counter.

    Args:
        retention: keep entries this long; older entries evicted on
            ``prune`` or ``record_fire``. Default 2 days.
        warn_rate_per_hour: if a single (axiom, domain) bucket
            exceeds this rate in the past 1h, emit a WARN cadence
            (sibling to heartbeat WARN). Default 100/hr.
        warn_repeat_every: every Nth warn triggers (first-
            occurrence + every-Nth cadence). Default 10.
    """

    def __init__(
        self,
        retention: timedelta = _DEFAULT_RETENTION,
        warn_rate_per_hour: int = 100,
        warn_repeat_every: int = 10,
    ):
        self.retention = retention
        self.warn_rate_per_hour = int(warn_rate_per_hour)
        self.warn_repeat_every = int(warn_repeat_every)
        # (axiom, domain, indicator) -> deque[datetime]
        # indicator can be None — represented as "" in the key for
        # hashability + deterministic comparison.
        self._fires: DefaultDict[Tuple[str, str, str], Deque[datetime]] = (
            defaultdict(deque)
        )
        # WARN cadence tracking — count (date_iso, axiom, domain) bucket.
        self._warn_counts: TypedCounter = Counter()

    @staticmethod
    def _key(axiom: str, domain: Optional[str], indicator: Optional[str]) -> Tuple[str, str, str]:
        return (str(axiom), str(domain or "unknown"), str(indicator or ""))

    def record_fire(
        self,
        axiom: str,
        domain: Optional[str] = None,
        indicator: Optional[str] = None,
        timestamp: Optional[datetime] = None,
    ) -> None:
        """Record one fire event.

        Args:
            axiom: Axiom name (e.g. ``"BOUNDEDNESS"``).
            domain: Optional domain ID; None → "unknown" bucket.
            indicator: Optional indicator name; None → empty bucket
                (axiom-level total).
            timestamp: Override clock for testing.
        """
        now = as_naive_utc(timestamp) if timestamp else now_utc()
        key = self._key(axiom, domain, indicator)
        self._fires[key].append(now)
        self._prune_one(key, now)
        # Cadence WARN if 1h rate exceeds threshold.
        recent_1h = self._count_in_window(key, now - timedelta(hours=1), now)
        if recent_1h >= self.warn_rate_per_hour:
            self._maybe_warn(axiom, domain or "unknown", recent_1h, now)

    def _prune_one(self, key: Tuple[str, str, str], now: datetime) -> None:
        """Drop entries older than retention from one deque."""
        cutoff = now - self.retention
        dq = self._fires[key]
        while dq and dq[0] < cutoff:
            dq.popleft()
        if not dq:
            del self._fires[key]

    def prune(self, now: Optional[datetime] = None) -> int:
        """Evict every entry older than retention. Returns count removed."""
        now = as_naive_utc(now) if now else now_utc()
        cutoff = now - self.retention
        removed = 0
        for key in list(self._fires.keys()):
            dq = self._fires[key]
            while dq and dq[0] < cutoff:
                dq.popleft()
                removed += 1
            if not dq:
                del self._fires[key]
        return removed

    def _count_in_window(
        self,
        key: Tuple[str, str, str],
        cutoff: datetime,
        now: datetime,
    ) -> int:
        """Count entries in `[cutoff, now]` for one key."""
        dq = self._fires.get(key, deque())
        # deque is sorted by insertion time (timestamps monotonic per
        # _key); count entries >= cutoff.
        return sum(1 for ts in dq if ts >= cutoff)

    def get_fire_rate(
        self,
        axiom: str,
        domain: Optional[str] = None,
        indicator: Optional[str] = None,
        window: timedelta = timedelta(hours=24),
        now: Optional[datetime] = None,
    ) -> int:
        """Return fire count for ``(axiom, domain, indicator)`` over ``window``."""
        now = as_naive_utc(now) if now else now_utc()
        cutoff = now - window
        key = self._key(axiom, domain, indicator)
        return self._count_in_window(key, cutoff, now)

    def get_fires_by_axiom_domain(
        self,
        window: timedelta = timedelta(hours=24),
        now: Optional[datetime] = None,
    ) -> Dict[str, Dict[str, int]]:
        """Return ``{axiom: {domain: total_count}}`` aggregated over indicators.

        Sibling to ``FireCounterMixin.get_fire_counts_by_domain``;
        provides the same surface so the reflection layer can swap to
        this tracker without changing the API contract.
        """
        now = as_naive_utc(now) if now else now_utc()
        cutoff = now - window
        out: DefaultDict[str, Counter] = defaultdict(Counter)
        for (axiom, domain, _indicator), dq in self._fires.items():
            count = sum(1 for ts in dq if ts >= cutoff)
            if count > 0:
                out[axiom][domain] += count
        return {a: dict(c) for a, c in out.items()}

    def get_fires_by_indicator(
        self,
        window: timedelta = timedelta(hours=24),
        now: Optional[datetime] = None,
    ) -> Dict[Tuple[str, str, str], int]:
        """Return ``{(axiom, domain, indicator): count}`` over ``window``."""
        now = as_naive_utc(now) if now else now_utc()
        cutoff = now - window
        out: Dict[Tuple[str, str, str], int] = {}
        for key, dq in self._fires.items():
            count = sum(1 for ts in dq if ts >= cutoff)
            if count > 0:
                out[key] = count
        return out

    def count(self) -> int:
        """Total retained events across all buckets."""
        return sum(len(dq) for dq in self._fires.values())

    def clear(self) -> int:
        """Drop everything; returns count removed."""
        n = self.count()
        self._fires.clear()
        self._warn_counts.clear()
        return n

    def _maybe_warn(
        self,
        axiom: str,
        domain: str,
        rate_1h: int,
        now: datetime,
    ) -> None:
        """ first-occurrence + every-Nth WARN cadence."""
        date_iso = now.date().isoformat()
        warn_key = (date_iso, axiom, domain)
        n = self._warn_counts[warn_key]
        self._warn_counts[warn_key] += 1
        if n == 0 or (self.warn_repeat_every > 0 and n % self.warn_repeat_every == 0):
            logger.warning(
                f"FireFrequencyTracker: high fire rate for "
                f"({axiom}, {domain}) — {rate_1h} fires in past hour "
                f"≥ warn_rate_per_hour={self.warn_rate_per_hour} "
                f"(attempt #{n + 1} today)"
            )


# ---------------------------------------------------------------------------
# the shared tracker every axiom checker records into.
#
# A module-level instance rather than a constructor argument, deliberately.
# The eight checkers are built inside `UnifiedAxiomReasoner.__init__` with no
# tracker in scope, and threading one through would mean changing that
# signature plus every construction site — a wide change to a kernel class for
# a metric nothing gates on. The mixin this replaces held per-checker state
# and was read globally, so a shared instance is the same reachability with
# one counter instead of eight.
#
# The tracker keys on (axiom, domain, indicator), so one instance holds every
# axiom without collision. That is why v2 can be shared where v1 could not.
_SHARED_TRACKER: Optional["FireFrequencyTracker"] = None


def get_shared_tracker() -> "FireFrequencyTracker":
    """The process-wide fire counter. Created on first use."""
    global _SHARED_TRACKER
    if _SHARED_TRACKER is None:
        _SHARED_TRACKER = FireFrequencyTracker()
    return _SHARED_TRACKER


def reset_shared_tracker() -> None:
    """Drop the shared tracker. For tests that need isolation between cases."""
    global _SHARED_TRACKER
    _SHARED_TRACKER = None
