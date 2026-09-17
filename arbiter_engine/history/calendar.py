"""Windows measured in OPEN time rather than wall-clock time.

THE FAILURE THIS FIXES

Monday at the open, a one-hour window spans the weekend. Every temporal axiom
then answers about a span in which nothing could have been observed: a series
sampled once a minute during the session looks like a series sampled once every
three days, `floor_unreachable_at_this_rate` fires on data that is arriving
perfectly well, and a freeze check calls a shut-down line frozen.

WHY `SessionCalendar` AND NOT `TradingCalendar`

The same shape is a factory's shifts, a clinic's opening hours, a settlement
window and a market's session. Naming it for one of them would put a domain
into the engine, which this package does not carry -- the sessions are declared
in YAML like everything else, and a domain that is open around the clock simply
declares none and is unaffected.

WHAT IS WRAPPED AND WHAT IS NOT

`CalendarHistory` wraps any `ObservationHistory` and translates the WINDOW
before delegating. The eight checkers are untouched, and so is the store: the
only thing that changes is what *one hour ago* means.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:                                        # stdlib since 3.9
    from zoneinfo import ZoneInfo
except ImportError:                         # pragma: no cover - 3.8 and older
    ZoneInfo = None                         # type: ignore

from ..clock import as_naive_utc, now_utc
from ..interfaces import Observation, ObservationHistory

__all__ = ["Session", "SessionCalendar", "CalendarHistory"]

_WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4,
             "sat": 5, "sun": 6}

#: How far back `shift_back` will walk looking for open time before giving up.
#: A window that cannot be satisfied inside this many days is a declaration
#: problem -- a calendar with no sessions at all, most likely -- and returning
#: the boundary is better than looping.
_MAX_LOOKBACK_DAYS = 3650


@dataclass(frozen=True)
class Session:
    days: Tuple[int, ...]
    open: time
    close: time
    tz: Optional[str] = None

    def bounds_on(self, day: date) -> Optional[Tuple[datetime, datetime]]:
        """The session's open and close on `day`, as naive UTC, or None when it
        does not run that day."""
        if day.weekday() not in self.days:
            return None
        start_local = datetime.combine(day, self.open)
        end_local = datetime.combine(day, self.close)
        if end_local <= start_local:
            return None
        return (_to_utc(start_local, self.tz), _to_utc(end_local, self.tz))


def _to_utc(local: datetime, tz: Optional[str]) -> datetime:
    if not tz or ZoneInfo is None:
        return local
    aware = local.replace(tzinfo=ZoneInfo(tz))
    return as_naive_utc(aware)


@dataclass
class SessionCalendar:
    """When the world this model describes is OPEN.

    A calendar with no sessions is *always open*, and every method below then
    reduces to wall-clock arithmetic. That is the default on purpose: a domain
    that declares nothing must behave exactly as it did before this existed.
    """

    sessions: Tuple[Session, ...] = ()
    holidays: frozenset = frozenset()

    @classmethod
    def from_declaration(cls, declaration: Optional[Dict[str, Any]]) -> "SessionCalendar":
        if not declaration:
            return cls()
        sessions = []
        for entry in declaration.get("sessions") or ():
            days = tuple(sorted(
                _WEEKDAYS[str(d).strip().lower()[:3]]
                for d in (entry.get("days") or ())
                if str(d).strip().lower()[:3] in _WEEKDAYS))
            if not days:
                continue
            sessions.append(Session(
                days=days,
                open=_parse_time(entry.get("open")),
                close=_parse_time(entry.get("close")),
                tz=entry.get("tz")))
        holidays = frozenset(
            _parse_date(d) for d in (declaration.get("holidays") or ())
            if _parse_date(d) is not None)
        return cls(sessions=tuple(sessions), holidays=holidays)

    @property
    def always_open(self) -> bool:
        return not self.sessions

    def _spans_on(self, day: date) -> List[Tuple[datetime, datetime]]:
        if day in self.holidays:
            return []
        spans = [s.bounds_on(day) for s in self.sessions]
        return sorted(s for s in spans if s is not None)

    def open_seconds_between(self, start: datetime, end: datetime) -> float:
        """Open seconds in `[start, end]`. Wall-clock seconds when always open."""
        start, end = as_naive_utc(start), as_naive_utc(end)
        if end <= start:
            return 0.0
        if self.always_open:
            return (end - start).total_seconds()
        total = 0.0
        day = start.date() - timedelta(days=1)
        while day <= end.date() + timedelta(days=1):
            for span_start, span_end in self._spans_on(day):
                overlap = (min(end, span_end) - max(start, span_start)).total_seconds()
                if overlap > 0:
                    total += overlap
            day += timedelta(days=1)
        return total

    def shift_back(self, end: datetime, seconds: float) -> datetime:
        """The instant `seconds` of OPEN time before `end`.

        This is what a window becomes under a calendar: a one-hour window at
        Monday's open reaches back into Friday's session, not into Sunday.
        """
        end = as_naive_utc(end)
        if self.always_open or seconds <= 0:
            return end - timedelta(seconds=max(seconds, 0.0))
        remaining = float(seconds)
        day = end.date()
        cursor = end
        for _ in range(_MAX_LOOKBACK_DAYS):
            for span_start, span_end in reversed(self._spans_on(day)):
                usable_end = min(cursor, span_end)
                if usable_end <= span_start:
                    continue
                available = (usable_end - span_start).total_seconds()
                if available >= remaining:
                    return usable_end - timedelta(seconds=remaining)
                remaining -= available
            # STEP TO THE PREVIOUS DAY. An earlier version moved the cursor to
            # midnight of the SAME day and re-read it, which consumed nothing
            # and walked the loop to its limit before returning that midnight --
            # a window that silently became *the start of today* for every
            # calendar with a session.
            day -= timedelta(days=1)
            cursor = datetime.combine(day, time.max)
        return cursor


def _parse_time(raw: Any) -> time:
    text = str(raw or "00:00").strip()
    parts = text.split(":")
    try:
        return time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0,
                    int(parts[2]) if len(parts) > 2 else 0)
    except (ValueError, IndexError):
        return time(0, 0)


def _parse_date(raw: Any) -> Optional[date]:
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if isinstance(raw, datetime):
        return raw.date()
    try:
        return datetime.strptime(str(raw).strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


class CalendarHistory(ObservationHistory):
    """An `ObservationHistory` whose windows are open time.

    Delegates everything; the only thing it changes is the span a window
    covers. `get_observations` takes explicit instants rather than a window and
    is therefore passed straight through -- a caller who named two instants
    meant those two instants.
    """

    def __init__(self, inner: ObservationHistory, calendar: SessionCalendar) -> None:
        self.inner = inner
        self.calendar = calendar

    def _wall_window(self, window: timedelta) -> timedelta:
        end = now_utc()
        start = self.calendar.shift_back(end, window.total_seconds())
        return end - start

    def add(self, entity_id: str, property_name: str, value: Any,
            timestamp: Optional[datetime] = None) -> None:
        self.inner.add(entity_id, property_name, value, timestamp)

    def get_values(self, entity_id: str, property_name: str,
                   window: timedelta) -> List[Tuple[datetime, float]]:
        return self.inner.get_values(entity_id, property_name,
                                     self._wall_window(window))

    def get_states(self, entity_id: str, property_name: str,
                   window: timedelta) -> List[Tuple[datetime, str]]:
        return self.inner.get_states(entity_id, property_name,
                                     self._wall_window(window))

    def get_observations(self, entity_id: str, start: datetime,
                         end: datetime) -> List[Observation]:
        return self.inner.get_observations(entity_id, start, end)

    def get_observation_count(self, entity_id: str, property_name: str) -> int:
        return self.inner.get_observation_count(entity_id, property_name)
