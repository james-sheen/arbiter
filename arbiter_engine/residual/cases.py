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
#: `gaps` (what the declaration could not explain) and `confirm` (a
#: person naming the cause that settled the case) come last, so every stage
#: an older book recorded keeps its place.
STAGES = ("check", "hypothesize", "plan", "act", "learn", "gaps", "confirm")

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
            "confirmed": confirmed_causes(cases),
            "cases": [c.to_dict() for c in cases],
        }


def confirmed_causes(cases: List[Case]) -> Dict[str, Any]:
    """Where each confirmed cause stood before anyone confirmed it.

    the one number that says whether a ranking is worth reading is
    how often the cause a person later confirms was near its top, and whether
    the reading it named was the one that settled it. Per confirmed case: the
    cause's rank in the LAST `hypothesize` attachment before the confirmation
    (`None` when it was not ranked there, or no ranking came first), how many
    it was ranked among, and whether that ranking's discriminating reading
    named the confirmed cause's entity. Counts beside the rows, never a rate:
    a rate carries the denominator it was taken over, and here it is small.

    THAT LAST FIELD IS NOT WHETHER THE READING SETTLED ANYTHING,
    and it keeps its published name and meaning because a patch release may
    not change what a field means. It asks whether the named reading sat on
    the cause itself, and the reading a ranking names is chosen to SEPARATE
    the candidates, so it usually sits somewhere else: a person who confirms
    the pump after the tank's reading turned the ranking round was told the
    tank settled nothing. The confirmation has always carried the answer --
    `reading`, the one that settled it -- and nothing read it.
    `settling_reading_was_named` compares that reading with the one the
    ranking named, and is `None` when the person gave none or the ranking
    named none: an unasked question is not a no.

    A RANK IS ONLY AS GOOD AS WHAT IT RESTED ON, and the row did not
    say. With no strength declared every posterior is null and the order is
    nearest hop first, then entity id: on a consulting model a confirmed
    executive stood "rank 1 of 2" by spelling. `ranked_by` says which --
    `posterior` when every cause in that ranking had one, `hops` when none did,
    `mixed` otherwise -- and `ranked_first_by_posterior` counts only the first
    places a posterior decided. `named_by` is the `basis` of the reading the
    ranking named. And that reading is the type's first declared value, so a
    person who settles the same entity on another of its readings was counted
    as not named; `settling_entity_was_named` asks whether the settling reading
    is on the entity the ranking pointed at, which is the question the count is
    for. All three are additive: every field above keeps its meaning.
    """
    rows: List[Dict[str, Any]] = []
    for case in cases:
        for confirmation in case.stages.get("confirm") or []:
            reference = confirmation.get("reference") or {}
            cause = reference.get("cause")
            at = str(confirmation.get("at") or "")
            before = [entry for entry in case.stages.get("hypothesize") or []
                      if str(entry.get("at") or "") <= at]
            ranking = (before[-1].get("reference") or {}) if before else {}
            ranked_rows = [row for row in ranking.get("causes") or []
                           if isinstance(row, dict)]
            causes = [row.get("cause") for row in ranked_rows]
            discriminating = ranking.get("most_discriminating") or {}
            named = discriminating.get("entity")
            named_reading = _text(discriminating.get("reading"))
            settling = _text(reference.get("reading"))
            rank = causes.index(cause) + 1 if cause in causes else None
            rows.append({
                "case_id": case.case_id, "cause": cause,
                "rank": rank,
                "of": len(causes),
                "ranked_by": _ranked_by(ranked_rows) if rank is not None else None,
                "named_by": _text(discriminating.get("basis")),
                "named_reading_settled_it": bool(named) and named == cause,
                "named_reading": named_reading,
                "settling_reading": settling,
                "settling_reading_was_named": (
                    settling == named_reading if settling and named_reading
                    else None),
                "settling_entity_was_named": (
                    settling == named or settling.startswith(f"{named}.")
                    if settling and isinstance(named, str) and named
                    else None),
            })
    ranked = [row for row in rows if row["rank"] is not None]
    by_posterior = [row for row in ranked if row["ranked_by"] == "posterior"]
    return {
        "confirmations": len(rows),
        "ranked_first": sum(1 for row in ranked if row["rank"] == 1),
        "ranked": len(ranked),
        "not_ranked": len(rows) - len(ranked),
        "ranked_by_posterior": len(by_posterior),
        "ranked_first_by_posterior": sum(1 for row in by_posterior
                                         if row["rank"] == 1),
        "named_reading_settled_it": sum(1 for row in rows
                                        if row["named_reading_settled_it"]),
        "settling_reading_given": sum(1 for row in rows
                                      if row["settling_reading"]),
        "settling_reading_was_named": sum(
            1 for row in rows if row["settling_reading_was_named"]),
        "settling_entity_was_named": sum(
            1 for row in rows if row["settling_entity_was_named"]),
        "rows": rows,
    }


def _ranked_by(causes: List[Dict[str, Any]]) -> Optional[str]:
    """What a ranking's order rested on: every cause's posterior, none (so
    nearest hop first, then entity id), or some of each."""
    if not causes:
        return None
    with_posterior = sum(1 for row in causes if row.get("posterior") is not None)
    if with_posterior == len(causes):
        return "posterior"
    return "hops" if with_posterior == 0 else "mixed"


def _text(value: Any) -> Optional[str]:
    """A reading as given, or `None` for anything that is not one."""
    return value.strip() if isinstance(value, str) and value.strip() else None


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
