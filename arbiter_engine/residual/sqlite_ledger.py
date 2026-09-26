"""A prediction ledger that outlives the process that made the predictions.

`README.md` names this as a boundary rather than an oversight, and
says what the boundary costs:

    `grade_matured` scores a record when its horizon has passed AND the record
    is still in the live session's ledger, so *did it beat a random walk* is
    answerable only by a process that outlives the horizon. [...] treat
    calibration as out of reach until the ledger is persistent.

So a one-shot command that loads a model, ingests forecasts and exits can
never learn whether any of them were right. Every prediction it filed is
discarded at exit, and the next process starts with an empty ledger and a
calibration rate of null -- which reads as *no data* rather than as *this
tool cannot answer that question*.

WHAT THIS IS NOT. It is not a different ledger. It subclasses
`PredictionLedger` and changes exactly one thing: where records live between
processes. Every grading rule, the grace period, the ring cap, the
ungradeable verdict and the eviction counter are the base class's and are
untouched -- a second implementation of the grading rules is how two ledgers
come to disagree about what CONFIRMED means.

THE RING CAP STILL APPLIES, and that is deliberate. A durable store could
keep everything, and then `records()` would return a different population
before and after a restart, which makes the calibration denominator depend on
when the process happened to start. The file holds what the ring holds.
`evicted_pending` is persisted with it, because a still-pending record dropped
at the cap is an ungraded prediction and the count of those is the one number
that says how much the ledger is NOT telling you.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from ..clock import as_naive_utc
from .cases import SqliteCaseBook
from .predict_vs_mirror import (PredictionLedger, PredictionRecord,
                                PredictionResidualProblem)

__all__ = ["SqlitePredictionLedger"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions (
    prediction_id TEXT PRIMARY KEY,
    filed_at      REAL NOT NULL,
    payload       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS predictions_filed ON predictions (filed_at);
CREATE TABLE IF NOT EXISTS ledger_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

#: Naive UTC throughout, the same convention `history/sqlite_store.py` states:
#: storing an aware value would put the writer's zone into the file and make
#: one row mean two instants.
_EPOCH = datetime(1970, 1, 1)

#: Fields that are datetimes and must round-trip as seconds rather than as
#: whatever `str()` produced.
_TIME_FIELDS = ("predicted_at", "graded_at")


def _to_seconds(when: datetime) -> float:
    return (as_naive_utc(when) - _EPOCH).total_seconds()


def _from_seconds(seconds: float) -> datetime:
    return _EPOCH + timedelta(seconds=float(seconds))


def _encode(record: PredictionRecord) -> str:
    payload: Dict[str, Any] = {}
    for field_name, value in vars(record).items():
        if field_name in _TIME_FIELDS:
            payload[field_name] = (_to_seconds(value)
                                   if isinstance(value, datetime) else None)
        elif isinstance(value, (list, tuple)):
            payload[field_name] = list(value)
        elif isinstance(value, dict):
            payload[field_name] = dict(value)
        else:
            payload[field_name] = value
    return json.dumps(payload, default=str)


def _decode(blob: str) -> Optional[PredictionRecord]:
    try:
        payload = json.loads(blob)
    except (TypeError, ValueError):
        return None
    for field_name in _TIME_FIELDS:
        seconds = payload.get(field_name)
        payload[field_name] = (_from_seconds(seconds)
                               if isinstance(seconds, (int, float)) else None)
    try:
        return PredictionRecord(**payload)
    except TypeError:
        # A file written by a build that carried a field this one does not, or
        # the other way round. Skipped rather than raised: a ledger that will
        # not open because one row is from a neighbouring version is worse
        # than one that opens and says how many rows it could not read.
        return None


class SqlitePredictionLedger(PredictionLedger):
    """`PredictionLedger`, with the records held in a file."""

    def __init__(self, path: str = "predictions.db",
                 ring_cap: Optional[int] = None,
                 grace_s: float = 60.0) -> None:
        super().__init__(ring_cap=ring_cap, grace_s=grace_s)
        self.path = path
        self._db = sqlite3.connect(path)
        self._db.executescript(_SCHEMA)
        self._db.commit()
        #: Rows on disk this build could not read back. Reported rather than
        #: silently skipped -- a calibration figure computed over a population
        #: that quietly shrank is the shape this whole module exists to stop.
        self.unreadable_rows = 0
        self._load()
        #: -- the case book in the same file, so a case outlives the
        #: process exactly as the predictions it records do.
        self.case_book = SqliteCaseBook(self._db)

    # -- persistence ---------------------------------------------------------

    def _load(self) -> None:
        """Restore the most recent `ring_cap` records, oldest first."""
        cap = self._records.maxlen or 1
        rows = self._db.execute(
            "SELECT payload FROM predictions ORDER BY filed_at DESC, "
            "rowid DESC LIMIT ?", (cap,)).fetchall()
        restored: List[PredictionRecord] = []
        for (blob,) in rows:
            record = _decode(blob)
            if record is None:
                self.unreadable_rows += 1
                continue
            restored.append(record)
        for record in reversed(restored):
            self._records.append(record)
        row = self._db.execute(
            "SELECT value FROM ledger_meta WHERE key = 'evicted_pending'"
        ).fetchone()
        if row:
            try:
                self.evicted_pending = int(row[0])
            except (TypeError, ValueError):
                self.evicted_pending = 0

    def _append(self, record: PredictionRecord) -> None:
        """The base class's one entry point, with a write behind it."""
        super()._append(record)
        self._persist(record)
        self._trim()

    def _persist(self, record: PredictionRecord) -> None:
        when = getattr(record, "predicted_at", None)
        self._db.execute(
            "INSERT OR REPLACE INTO predictions (prediction_id, filed_at, "
            "payload) VALUES (?, ?, ?)",
            (record.prediction_id,
             _to_seconds(when) if isinstance(when, datetime) else 0.0,
             _encode(record)))
        self._db.commit()

    def _trim(self) -> None:
        """Keep the file to the ring's population, not to everything ever."""
        cap = self._records.maxlen
        if cap is None:
            return
        self._db.execute(
            "DELETE FROM predictions WHERE prediction_id NOT IN ("
            "SELECT prediction_id FROM predictions "
            "ORDER BY filed_at DESC, rowid DESC LIMIT ?)", (cap,))
        self._db.execute(
            "INSERT OR REPLACE INTO ledger_meta (key, value) VALUES "
            "('evicted_pending', ?)", (str(self.evicted_pending),))
        self._db.commit()

    # -- grading -------------------------------------------------------------

    def grade_matured(self, problems: Sequence[Any],
                      observed_entity_ids: Set[str],
                      now: Optional[datetime] = None,
                      histories: Optional[Iterable[Any]] = None
                      ) -> List[PredictionResidualProblem]:
        """The base class's grading, with the verdicts written down.

        Overridden for persistence ONLY. Reimplementing the rules here would
        be a second answer to *what does CONFIRMED mean*, and the two would
        disagree the first time one changed.
        """
        emitted = super().grade_matured(
            problems, observed_entity_ids, now=now, histories=histories)
        for record in self._records:
            if record.verdict is not None:
                self._persist(record)
        self._trim()
        return emitted

    def close(self) -> None:
        self._db.close()
