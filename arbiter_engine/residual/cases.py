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

WHAT RESOLVED IT, when a line decided it. -- a bound read off the entity
(`{from_property:...}`) moves when its property does, so a line that moved below
a unit closed its case exactly as a unit that recovered: the FAA case's 59
facilities whose target fell while their controllers did not rise read as
recoveries. A check records the reading and the declared bounds it was judged
against, and a case that resolves says which crossed: the reading crossed the
line, the line crossed the reading, or both.

A LINE WITHDRAWN IS NOT SILENCE. -- a line read off the entity that the
entity stops carrying leaves its check nothing to judge against while the reading
is there: the model has stopped drawing the line, and the unit has not gone quiet.
Counted as silence, it held open for good every case opened on it -- on the
nursing homes case, 232 cases on lines a court had struck down. A check that finds
the reading and no line -- every line the indicator declares read off a property
the entity no longer carries -- is `withdrawn`, extends the run as a clean one
does, and a case that closes on one says the line was withdrawn. A line still
standing, or a property there and unreadable, is not withdrawn.

A RETIRED UNIT TAKES ITS CASES WITH IT. -- a unit that leaves the world
the model describes is retired (`api.retire_entity`), and each case open on it
resolves at that instant and says so, with the caller's basis. Nothing is
recorded as a check, because nothing was checked; what was found while it stood
stays in the case.

KEPT BESIDE THE LEDGER, and durable when it is: the in-memory ledger holds an
in-memory book, and the SQLite ledger keeps its book in the same file.
"""

from __future__ import annotations

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
    #: the reading and declared lines it opened on (`_reading_and_bounds`),
    #: or None where the indicator declares no line.
    opened_with: Optional[Dict[str, Any]] = None
    #: what resolved it, when a declared line decided both the check that
    #: last found it and the one that closed it (`resolution_of`); None otherwise.
    resolved_by: Optional[Dict[str, Any]] = None
    #: Checks in a row that looked and found nothing at or above `severity`, or
    #: found the reading with its line withdrawn.
    clean_streak: int = 0
    #: stage -> the attachments, oldest first. Every stage is present; an
    #: empty list means nothing has been attached for it.
    stages: Dict[str, List[Dict[str, Any]]] = field(
        default_factory=lambda: {stage: [] for stage in STAGES})

    def to_dict(self) -> Dict[str, Any]:
        # `asdict` builds every container anew and deep-copies every leaf, so its answer
        # shares nothing with the case. A deep copy over it copied a case's whole history twice, on
        # every call: 70 percent of a late walk on the unemployment case.
        return asdict(self)


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
             basis: str, severity: str, consecutive_checks: int,
             opened_with: Optional[Dict[str, Any]] = None) -> Case:
        case = Case(case_id=str(uuid.uuid4()), entity_id=entity_id,
                    indicator=indicator, opened_at=opened_at, basis=basis,
                    severity=severity,
                    consecutive_checks=int(consecutive_checks),
                    opened_with=dict(opened_with) if opened_with else None)
        self._store(case)
        return case

    def attach(self, case: Case, stage: str, entry: Dict[str, Any]) -> Case:
        case.stages.setdefault(stage, []).append(dict(entry, seq=_next_seq(case)))
        self._store(case)
        return case

    def record_check(self, case: Case, entry: Dict[str, Any], *,
                     outcome: str, at: str) -> Case:
        """One check, as the case saw it: `clean`, `found`, `not_looked` or
        `withdrawn` -- the reading there and its line not.

        `clean` and `withdrawn` extend the run; either of the others restarts it.
        A resolved case records nothing more.
        """
        if case.status != OPEN:
            return case
        case.clean_streak = case.clean_streak + 1 if outcome in _RUN_EXTENDED_BY else 0
        case.stages["check"].append(dict(entry, outcome=outcome,
                                         clean_streak=case.clean_streak,
                                         seq=_next_seq(case)))
        if case.clean_streak >= case.consecutive_checks:
            case.status, case.resolved_at = RESOLVED, at
            case.resolved_by = resolution_of(case)
        self._store(case)
        return case

    def retire(self, case: Case, *, at: str, basis: str = "") -> Case:
        """ -- the unit `case` is on was retired: the case resolves at `at`
        and says so. A resolved case is left as it was."""
        if case.status != OPEN:
            return case
        case.status, case.resolved_at = RESOLVED, at
        case.resolved_by = {"by": "retired", "basis": basis}
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
            "reopened": reopened(cases),
            # the resolutions a declared line decided, by what crossed it.
            "resolved_by": {by: sum(1 for c in cases if (c.resolved_by or {}).get("by") == by)
                            for by in RESOLVED_BY},
            "confirmed": confirmed_causes(cases),
            "cases": [c.to_dict() for c in cases],
        }


#: what resolved a case: the reading crossed the line, the line crossed
#: the reading, or it took both; -- or the line was withdrawn; -- or
#: the unit was retired.
RESOLVED_BY = ("reading", "bound", "both", "withdrawn", "retired")
#: The check outcomes that extend a case's run toward closing.
_RUN_EXTENDED_BY = ("clean", "withdrawn")
#: The lines a case is held to, by its criterion: a critical case closes inside the
#: critical lines; any other only inside every line declared.
_LINES = {"critical": ("critical", "lower_critical")}
_ALL_LINES = ("warning", "critical", "lower_warning", "lower_critical")


def _inside(reading: float, bounds: Dict[str, Any], lines: tuple) -> Optional[bool]:
    """Whether `reading` is inside every one of `lines` that `bounds` declares, as
    BOUNDEDNESS reads them -- a reading ON a line is across it -- or None when
    `bounds` declares none of them."""
    held = [(line, bounds[line]) for line in lines
            if isinstance(bounds.get(line), (int, float))]
    if not held:
        return None
    return all(reading > bound if line.startswith("lower_") else reading < bound
               for line, bound in held)


def _withdrawn(case: Case, found: Dict[str, Any], closing: Dict[str, Any]) -> Dict[str, Any]:
    """ -- what a case closed on a withdrawn line says: the reading it was last
    found at and the one that closed it, and each line of its criterion it was found
    against, or the closing check lacked, beside the nothing that closed it."""
    lines = _LINES.get(str(case.severity).lower(), _ALL_LINES)
    before = found.get("bounds") or {}
    gone = set(closing.get("withdrawn") or ())

    def number(value: Any) -> Optional[float]:
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    return {"by": "withdrawn", "reading": [number(found.get("reading")), number(closing.get("reading"))],
            "bounds": {line: [before.get(line), None] for line in lines if line in before or line in gone}}


def resolution_of(case: Case) -> Optional[Dict[str, Any]]:
    """ -- what resolved `case`, read off two checks: the last that found it
    (or, where none since it opened did, what it opened on), and the one that
    closed it.

    The reading crossed the line when the closing reading is inside the lines the
    finding was judged against; the line crossed the reading when the finding's
    reading is inside the closing lines; `both` when each would have done it
    alone, or only the two together did. None unless a declared line decided both
    checks -- the finding's reading across a line, the closing one inside every
    line -- because a trend, a statistical baseline or another axiom has no line to
    have crossed. -- a case closed by a check whose line was withdrawn says
    so, with the two readings and the lines it was found against, none after.
    """
    checks = case.stages.get("check") or []
    if not checks:
        return None
    closing = checks[-1]
    # The last check that found it, or, where none since it opened did, what it opened on.
    found = next((c for c in reversed(checks[:-1]) if c.get("outcome") == "found"),
                 case.opened_with)
    if closing.get("outcome") == "withdrawn":
        return _withdrawn(case, found or {}, closing)
    if found is None or not isinstance(found.get("reading"), (int, float)) \
            or not isinstance(closing.get("reading"), (int, float)):
        return None
    lines = _LINES.get(str(case.severity).lower(), _ALL_LINES)
    before, after = found.get("bounds") or {}, closing.get("bounds") or {}
    r0, r1 = float(found["reading"]), float(closing["reading"])
    if _inside(r0, before, lines) is not False or _inside(r1, after, lines) is not True:
        return None
    by_reading, by_line = _inside(r1, before, lines), _inside(r0, after, lines)
    by = ("reading" if by_reading and not by_line
          else "bound" if by_line and not by_reading else "both")
    return {"by": by, "reading": [r0, r1],
            "bounds": {line: [before.get(line), after.get(line)] for line in lines
                       if line in before or line in after}}


def _seq(entry: Dict[str, Any]) -> int:
    """An entry's place in its case's history, or 0 when it was attached before
    entries carried one."""
    value = entry.get("seq")
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _next_seq(case: Case) -> int:
    """ -- the place the next entry takes in its case's history, 1 first,
    across every stage: the order a confirmation is read in, which no stamp can
    give when the stamps come from different clocks."""
    return 1 + max((_seq(entry) for entries in case.stages.values()
                    for entry in entries), default=0)


def reopened(cases: List[Case]) -> int:
    """How many cases opened on an entity and indicator whose earlier case
    there had already resolved. -- a problem that comes back is not a
    new one, and `opened` beside `resolved` counted it as one: two cases, one
    resolved, read as half the work done when the one problem had returned.

    Paired on the entity AND the indicator, so a second case on another of
    the entity's indicators is a new problem. Each case counts once, however
    many resolved before it."""
    resolved_at: Dict[tuple, List[tuple]] = {}
    for case in cases:
        if case.status == RESOLVED and case.resolved_at:
            resolved_at.setdefault((case.entity_id, case.indicator), []).append(
                (str(case.resolved_at), case.case_id))
    return sum(1 for case in cases if any(
        at <= str(case.opened_at) and other != case.case_id
        for at, other in resolved_at.get((case.entity_id, case.indicator), ())))


def confirmed_causes(cases: List[Case]) -> Dict[str, Any]:
    """Where each confirmed cause stood before anyone confirmed it.

    the one number that says whether a ranking is worth reading is
    how often the cause a person later confirms was near its top, and whether
    the reading it named was the one that settled it. Per confirmed case: the
    cause's rank in the LAST `hypothesize` attachment before the confirmation,
    in the order they were attached (`None` when it was not ranked there, or no
    ranking came first), how many it was ranked among, and whether that
    ranking's discriminating reading named the confirmed cause's entity. Counts
    beside the rows, never a rate: a rate carries the denominator it was taken
    over, and here it is small.

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

    A RANK SAYS NOTHING ABOUT THE WALK, and a screened cause
    confirmed read as a success: on a board whose only candidate is a fan,
    the walk read the fan sound and screened it, and the fan confirmed stood
    "rank 1 of 1", counted in `ranked_first`. Each row now says the cause's
    `standing` on that last walk -- its own, or `beyond_bound` when the walk
    counted it among the declared causes past `causal.max_hops`, or
    `not_connected` when it neither ranked nor counted it -- with the walk's
    `walk_state`, the confirmation's own `basis`, and `walks_before`, the
    rankings the case held before it. All of it is read from what the
    attachments kept, so a session holding only the ledger gives the same
    row. `by_standing` counts the rows at each standing, and
    `confirmed_after_screened` the causes the walk had screened -- the walk's
    own surprise. `ranked_first` keeps its meaning: such a cause ranked first
    is still counted there, and the new total says the walk had screened it.

    `confirmed_by`, the reference's `by` as the caller recorded it
    (null when it recorded none), and `confirmed_at`, the confirmation's own
    stamp: a confirmation is a person's judgement, and on a shared book the row
    says whose and when.
    """
    rows: List[Dict[str, Any]] = []
    for case in cases:
        for confirmation in case.stages.get("confirm") or []:
            reference = confirmation.get("reference") or {}
            cause = reference.get("cause")
            at = str(confirmation.get("at") or "")
            # the walks attached before it, in the case's own order.
            # By stamp, two clocks met: a walk is stamped at the instant its data
            # describes, a confirmation when a person makes it, so on data older
            # than now every walk stamped before every confirmation and each was
            # read against the case's last walk. An entry from before `seq`
            # existed reads as earlier than any that has one; a confirmation
            # without one is read by stamp, as it always was.
            position = _seq(confirmation)
            before = [entry for entry in case.stages.get("hypothesize") or []
                      if (_seq(entry) < position if position
                          else str(entry.get("at") or "") <= at)]
            ranking = (before[-1].get("reference") or {}) if before else {}
            ranked_rows = [row for row in ranking.get("causes") or []
                           if isinstance(row, dict)]
            causes = [row.get("cause") for row in ranked_rows]
            discriminating = ranking.get("most_discriminating") or {}
            named = discriminating.get("entity")
            named_reading = _text(discriminating.get("reading"))
            settling = _text(reference.get("reading"))
            rank = causes.index(cause) + 1 if cause in causes else None
            walk = ranking.get("walk")
            rows.append({
                "case_id": case.case_id, "cause": cause,
                "rank": rank,
                "of": len(causes),
                "ranked_by": (_ranked_by(ranked_rows, ranking.get("ranked_by"))
                              if rank is not None else None),
                "standing": _standing(ranking, ranked_rows, cause),
                "walk_state": walk.get("state") if isinstance(walk, dict) else None,
                "basis": _text(reference.get("basis")),
                # who confirmed it, as the caller recorded them, and when: the
                # confirmation's own stamp.
                "confirmed_by": _text(reference.get("by")),
                "confirmed_at": str(confirmation.get("at") or "") or None,
                "walks_before": sum(1 for entry in before
                                    if isinstance(entry.get("reference"), dict)),
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
    by_standing = {standing: sum(1 for row in rows if row["standing"] == standing)
                   for standing in _STANDINGS}
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
        "by_standing": by_standing,
        "confirmed_after_screened": by_standing["screened"],
        "rows": rows,
    }


#: where a confirmed cause can have stood on the last walk before
#: it: the walk's four standings, then declared but past `causal.max_hops`,
#: then neither ranked nor counted.
_STANDINGS = ("frontier", "trail", "open", "screened", "beyond_bound",
             "not_connected")


def _standing(ranking: Dict[str, Any], ranked_rows: List[Dict[str, Any]],
              cause: Any) -> Optional[str]:
    """Where `cause` stood on the walk a ranking kept, read from that record
    alone: no graph, because a vertical confirms on a session holding the
    ledger and nothing else.

    `None` when the ranking kept no walk -- one attached before 0.2.31, a
    stage that could not run, or none at all -- and when `report_above` cut
    the causes and this one is not among those kept: where it stood was not
    kept, which is not the same as not connected."""
    if not isinstance(ranking.get("walk"), dict):
        return None
    for row in ranked_rows:
        if row.get("cause") == cause:
            return row.get("standing")
    if cause in (ranking.get("beyond_bound") or ()):
        return "beyond_bound"
    if ranking.get("reported") is not None:
        return None
    return "not_connected"


def _ranked_by(causes: List[Dict[str, Any]], kept: Any = None) -> Optional[str]:
    """What a ranking's order rested on: every cause's posterior, none (so
    nearest hop first, then entity id), or some of each.

    a ranking from 0.2.27 on keeps the order it was ranked in, and
    without every posterior that order is the standing first, so `standing` is
    read from it; one kept before then is ranked by the rule above, which was
    the order it was in."""
    if not causes:
        return None
    if kept in ("posterior", "standing"):
        return kept
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
