"""An ObservationHistory that outlives the process, over the standard library.

WHY THIS EXISTS

The shipped history is a seven-day ring in memory. That is the right default
for a long-running collector and the wrong one for the question this engine is
increasingly asked: *what would you have said last Tuesday?* A replay feeds
years of timestamped observations once and then steps the clock, and a ring
that evicts them is not a store you can ask twice.

NO NEW DEPENDENCY. `sqlite3` is in the standard library, which keeps the
distribution's promise of numpy and pyyaml and nothing else. The schema is one
table and one index; the point is durability and a range scan, not a database.

WHAT IT DOES NOT DO

Evict. The in-memory store has a retention period and a cap because it must;
this one is a file, and silently dropping the oldest rows out of a file a
caller chose for durability would be the surprising behaviour. A caller who
wants a bound sets one themselves.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Any, List, Optional, Tuple

from ..clock import as_naive_utc, now_utc
from ..interfaces import Observation, ObservationHistory

__all__ = ["SqliteObservationHistory"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS obs (
    entity_id TEXT NOT NULL,
    property   TEXT NOT NULL,
    ts         REAL NOT NULL,
    value_num  REAL,
    value_str  TEXT
);
CREATE INDEX IF NOT EXISTS obs_key ON obs (entity_id, property, ts);
"""

#: The epoch every timestamp is stored against. Naive UTC throughout, which is
#: this engine's one convention -- storing an aware value would put the
#: reader's zone into the file and make the same row mean two instants.
_EPOCH = datetime(1970, 1, 1)


def _to_seconds(when: datetime) -> float:
    return (as_naive_utc(when) - _EPOCH).total_seconds()


def _from_seconds(seconds: float) -> datetime:
    return _EPOCH + timedelta(seconds=float(seconds))


class SqliteObservationHistory(ObservationHistory):
    """The five methods of the ABC, over one table.

    `path` may be `":memory:"`, which is useful in a test and useless for the
    durability this class exists for; the default is a file.
    """

    def __init__(self, path: str = "observations.db") -> None:
        self.path = str(path)
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.executescript(_SCHEMA)
        self._connection.commit()

    # -- writing -------------------------------------------------------------

    def add(self, entity_id: str, property_name: str, value: Any,
            timestamp: Optional[datetime] = None) -> None:
        """One observation. `value` is stored as a number when it is one and as
        text otherwise, in two columns rather than one -- a numeric series read
        back out of a TEXT column sorts and compares as text, which is how a
        threshold of 9 comes to exceed 10."""
        when = _to_seconds(timestamp) if timestamp is not None else _to_seconds(now_utc())
        numeric: Optional[float] = None
        text: Optional[str] = None
        if isinstance(value, bool):
            text = str(value)
        elif isinstance(value, (int, float)):
            numeric = float(value)
        else:
            text = str(value)
        with self._lock:
            self._connection.execute(
                "INSERT INTO obs (entity_id, property, ts, value_num, value_str)"
                " VALUES (?, ?, ?, ?, ?)",
                (str(entity_id), str(property_name), when, numeric, text))
            self._connection.commit()

    # -- reading -------------------------------------------------------------

    def get_values(self, entity_id: str, property_name: str,
                   window: timedelta) -> List[Tuple[datetime, float]]:
        """Numeric observations inside `window`, ending NOW.

        `now_utc()` is read here rather than passed in, which is what makes the
        clock's `as_of` reach this store: freeze the clock and the same call
        answers about that instant, with no argument threaded through the eight
        checkers that make it.

        ENDING NOW IS ENFORCED, not only documented. This docstring said
        "ending NOW" while the query bounded only the far end, so a store
        holding real timestamps and read under a frozen clock served rows from
        after the instant -- the replay recipe's own shape, leaking the future
        into every step of a backtest.
        """
        present = _to_seconds(now_utc())
        cutoff = _to_seconds(now_utc() - window)
        with self._lock:
            rows = self._connection.execute(
                "SELECT ts, value_num FROM obs WHERE entity_id = ? AND property = ?"
                " AND ts > ? AND ts <= ? AND value_num IS NOT NULL ORDER BY ts",
                (str(entity_id), str(property_name), cutoff, present)).fetchall()
        return [(_from_seconds(ts), float(value)) for ts, value in rows]

    def get_states(self, entity_id: str, property_name: str,
                   window: timedelta) -> List[Tuple[datetime, str]]:
        """State observations inside `window`, ending NOW -- see `get_values`
        for why the upper bound is there."""
        present = _to_seconds(now_utc())
        cutoff = _to_seconds(now_utc() - window)
        with self._lock:
            rows = self._connection.execute(
                "SELECT ts, value_num, value_str FROM obs WHERE entity_id = ?"
                " AND property = ? AND ts > ? AND ts <= ? ORDER BY ts",
                (str(entity_id), str(property_name), cutoff, present)).fetchall()
        return [(_from_seconds(ts), text if text is not None else str(number))
                for ts, number, text in rows]

    def series_keys(self) -> List[Tuple[str, str]]:
        """Every ``(entity_id, property_name)`` this store holds a series for.

        Not one of the ABC's five, and the in-memory store had it
        from on -- so every reader that enumerates a history was
        written against the default and this class was never asked. Two of
        them crashed on it: `model_describe` and `gaps` raised AttributeError
        for any session built over this store, and `rollout` ran with no
        imagined past behind it, declining `precondition_unmet`. Nothing
        downstream had constructed one until a vertical kept its readings
        across runs, which is the one use this class exists for.
        """
        with self._lock:
            rows = self._connection.execute(
                "SELECT DISTINCT entity_id, property FROM obs"
                " ORDER BY entity_id, property").fetchall()
        return [(str(entity_id), str(prop)) for entity_id, prop in rows]

    def get_observations(self, entity_id: str, start: datetime,
                         end: datetime) -> List[Observation]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT property, ts, value_num, value_str FROM obs"
                " WHERE entity_id = ? AND ts >= ? AND ts <= ? ORDER BY ts",
                (str(entity_id), _to_seconds(start), _to_seconds(end))).fetchall()
        return [
            Observation(entity_id=str(entity_id), entity_type="",
                        property_name=prop, property_type="",
                        value=number if number is not None else text,
                        timestamp=_from_seconds(ts))
            for prop, ts, number, text in rows
        ]

    def get_observation_count(self, entity_id: str, property_name: str) -> int:
        with self._lock:
            row = self._connection.execute(
                "SELECT COUNT(*) FROM obs WHERE entity_id = ? AND property = ?",
                (str(entity_id), str(property_name))).fetchone()
        return int(row[0]) if row else 0

    # -- lifecycle -----------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            self._connection.close()
