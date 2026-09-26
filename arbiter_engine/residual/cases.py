"""The case book: one problem followed from the finding that opened it.

`Problem` is a finding -- one check's verdict on one entity. A CASE is
what an operator works: it opens on a subject and a declared indicator, the
loop's stages attach to it as they run, and it resolves when checks stop
finding anything on that indicator. Nothing else in the engine carried that,
so a loop that ran every stage left no record that the stages were about the
same thing, and no count of how many problems it had actually closed.

THE BOOK RECORDS; IT DRIVES NOTHING. It calls no stage. `check` records itself
into every open case, because resolution is counted in checks; every other
stage is attached by the vertical that ran it, by reference -- the ranking's
causes, the plan's choice, the execution the act filed, the adoption the
vertical reports. A stage that ran and declined is attached with its decline,
so an absent stage and a refused one never read alike.

RESOLUTION IS THE INDICATOR'S OWN BOUND, not a second tolerance. A case
resolves after `cases.consecutive_checks` checks in a row that LOOKED at its
indicator and found nothing at or above `cases.severity`. Both numbers are
declared in the model and copied onto the case when it opens, so a case says
what it was held to. A check that could not look -- every axiom on the
indicator declined for the entity -- is not a clean check: it restarts the
count, because silence is not evidence of health.

KEPT BESIDE THE LEDGER, and durable when it is: the in-memory ledger holds an
in-memory book, and the SQLite ledger keeps its book in the same file.
"""

from __future__ import annotations

import copy
import json
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

#: The stages a case carries, in the order the loop runs them. `check` is
#: recorded by the book itself; the rest are attached by whoever ran them.
STAGES = ("check", "hypothesize", "plan", "act", "learn")

OPEN, RESOLVED = "open", "resolved"


@dataclass
class Case:
    """One problem, from the finding that opened it to its resolution."""

    case_id: str
    entity_id: str
    indicator: str
    opened_at: str
    basis: str
    #: The declared criterion, copied when the case opened.
    severity: str
    consecutive_checks: int
    status: str = OPEN
    resolved_at: Optional[str] = None
    #: Checks in a row that looked and found nothing at or above `severity`.
    clean_streak: int = 0
    #: stage -> the attachments, oldest first. Every stage is present; an
    #: empty list means nothing has been attached for it.
    stages: Dict[str, List[Dict[str, Any]]] = field(
        default_factory=lambda: {stage: [] for stage in STAGES})

    def to_dict(self) -> Dict[str, Any]:
        return copy.deepcopy(asdict(self))


class CaseBook:
    """The cases a ledger keeps. In memory; `SqliteCaseBook` persists."""

    def __init__(self) -> None:
        self._cases: Dict[str, Case] = {}

    # -- storage -------------------------------------------------------------

    def _store(self, case: Case) -> None:
        """The ONE place a case is written, so a durable book overrides one
        method -- the same rule the ledger's `_append` follows."""
        self._cases[case.case_id] = case

    def cases(self) -> List[Case]:
        return list(self._cases.values())

    def get(self, case_id: str) -> Optional[Case]:
        return self._cases.get(case_id)

    # -- the three things that happen to a case ------------------------------

    def open(self, *, entity_id: str, indicator: str, opened_at: str,
             basis: str, severity: str, consecutive_checks: int) -> Case:
        case = Case(case_id=str(uuid.uuid4()), entity_id=entity_id,
                    indicator=indicator, opened_at=opened_at, basis=basis,
                    severity=severity,
                    consecutive_checks=int(consecutive_checks))
        self._store(case)
        return case

    def attach(self, case: Case, stage: str, entry: Dict[str, Any]) -> Case:
        case.stages.setdefault(stage, []).append(dict(entry))
        self._store(case)
        return case

    def record_check(self, case: Case, entry: Dict[str, Any], *,
                     outcome: str, at: str) -> Case:
        """One check, as the case saw it: `clean`, `found` or `not_looked`.

        Only `clean` extends the run; either of the others restarts it.
        A resolved case records nothing more.
        """
        if case.status != OPEN:
            return case
        case.clean_streak = case.clean_streak + 1 if outcome == "clean" else 0
        case.stages["check"].append(dict(entry, outcome=outcome,
                                         clean_streak=case.clean_streak))
        if case.clean_streak >= case.consecutive_checks:
            case.status, case.resolved_at = RESOLVED, at
        self._store(case)
        return case

    def summary(self) -> Dict[str, Any]:
        """Counts, and every case. The ratio of resolved to opened is left
        for the reader to take, over the denominator printed beside it."""
        cases = self.cases()
        return {
            "opened": len(cases),
            "resolved": sum(1 for c in cases if c.status == RESOLVED),
            "open": sum(1 for c in cases if c.status == OPEN),
            "cases": [c.to_dict() for c in cases],
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    case_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);
"""


class SqliteCaseBook(CaseBook):
    """The book in the SQLite ledger's own file, so it lives as long as the
    predictions it records do."""

    def __init__(self, db: Any) -> None:
        super().__init__()
        self._db = db
        self._db.executescript(_SCHEMA)
        self._db.commit()
        #: Rows this build could not read back, counted rather than dropped.
        self.unreadable_rows = 0
        for (blob,) in self._db.execute("SELECT payload FROM cases").fetchall():
            try:
                case = Case(**json.loads(blob))
            except (TypeError, ValueError):
                self.unreadable_rows += 1
                continue
            self._cases[case.case_id] = case

    def _store(self, case: Case) -> None:
        super()._store(case)
        self._db.execute(
            "INSERT OR REPLACE INTO cases (case_id, payload) VALUES (?, ?)",
            (case.case_id, json.dumps(asdict(case), default=str)))
        self._db.commit()
