"""Did this engine say it at the time? Scoring a model against real surprises.

WHAT A SURPRISE SET IS

A `surprises:` companion declares events a human confirmed AFTER the fact, and
what a detector would have had to say to have caught each one:

    surprises:
      domain: substation
      entries:
        - id: alpha-13
          description: a gauge reading healthy while the system was blocking
          subject: {entity: panel-a, type: Panel, property: voltage_v}
          window: {start: 2026-06-10T00:00:00, end: 2026-06-11T00:00:00}
          counts_as_detected_when:
            axiom: HOMEOSTASIS
            severity_in: [warning, critical]
          confirmed: true
          anticipated: false
          source: the record this was taken from

It is a COMPANION, not a domain model -- `load_domain` refuses it, and
`is_surprise_set` is the filter for a directory scan, exactly as
`is_domain_model` is for the other direction.

WHY THE SCORE HAS NO SINGLE NUMBER

The project's own record of the only real corpus it has carries the figure in
two senses that must never travel apart: of sixteen observations, SIXTEEN
surprised the operator at first sight and NONE were anticipated by the design
of the probes -- which is favourable, and is a statement about foresight -- and
NONE were surfaced by the detector at the time, with three reached on a later
replay -- which is unfavourable, and is a statement about the detector. Both are
`0 of 16`. They answer different questions, and quoting either bare was ruled a
defect here after it happened.

So `SurpriseScore` has no `rate` attribute to quote. It carries counts, it
names its denominator in a sentence, and `statement()` renders both senses
or neither. A caller who wants one number has to divide two fields itself and will
have to decide which, which is the decision the bare ratio was hiding.

WHY A MISS AND A REFUSAL ARE DIFFERENT

An entry whose window holds no observation of its subject is NOT a miss. The
engine was never shown the data, and scoring it zero would grade a corpus
against a store rather than against a detector -- the same error as reading an
envelope with eight declines and no findings as health. Those entries decline
`not_replayable` and leave the denominator.

The replay instants are the SUBJECT'S OWN observation timestamps inside the
window. A step size would be a number nobody declared, and a benchmark that
invents its own sampling cadence can move its result by changing it.

WHAT THIS DOES NOT MEASURE

Not importance: a hit says a finding matching the declared predicate arrived in
the window, not that anyone would have acted on it.

Not the engine's ceiling: the corpus is written after the fact by someone who
already knows the answer, so a predicate can be drawn tight around whatever the
engine happens to emit. The only defence is that the predicate is declared ONCE
and then left alone. A corpus whose predicates are adjusted until the number
improves measures the adjusting, and the loudest place to say so is here.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import yaml

from .clock import as_naive_utc, as_of
from .subenvelope import Decline
from .types import Severity, read_severity_floor

__all__ = [
    "Surprise", "SurpriseSet", "SurpriseScore", "SurpriseOutcome",
    "load_surprises", "is_surprise_set", "score",
    "DECLINE_REASONS", "SET_KEYS", "ENTRY_KEYS", "SUBJECT_KEYS",
    "WINDOW_KEYS", "PREDICATE_KEYS",
]


class NotASurpriseSetError(ValueError):
    """The source parsed, and is not a surprise set."""


#: The closed refusal vocabulary of this scorer.
#:
#: Deliberately NOT a member of `subenvelope.VOCABULARIES`. That dict holds the
#: disciplines that run inside a verb and attach their refusals to an envelope;
#: this is an offline scorer, and `replay`, which it is built on, is not a verb
#: either and says so in its own first paragraph. Claiming a slot there would
#: assert a surface this does not have.
DECLINE_REASONS = frozenset({
    "no_subject",                # the entry names no entity to look at
    "no_window",                 # no span, so no question about a moment
    "malformed_window",          # a span that is not one: unparseable, or end <= start
    "subject_absent",            # the entity is not in this session
    "empty_predicate",           # nothing declared, so ANY finding would count
    "unknown_key",               # a key nothing here reads
    "unknown_value",             # a declared severity that is not one
    "not_replayable",            # no observation of the subject inside the window
    "instant_budget_exhausted",  # more instants in the window than the budget allows
    "internal_error",            # this scorer itself failed
})

SET_KEYS = frozenset({"domain", "entries"})

#: `confirmed` and `anticipated` are BOTH here because the two senses of the
#: score are two different columns and a set that carries only one of them can
#: report only one. `anticipated` answers *was this in the planned probe
#: surface* -- the foresight question -- and has nothing to do with whether the
#: detector fired.
ENTRY_KEYS = frozenset({
    "id", "description", "subject", "window", "counts_as_detected_when",
    "confirmed", "anticipated", "source",
})

#: `type` is here because a bare observation store does not carry one --
#: `SqliteObservationHistory` reads back `entity_type=""` by construction --
#: and an entity needs one to be checked at all. The corpus already names
#: deployment-specific ids, so naming the type beside them adds no new kind
#: of coupling and removes a second file from the interface.
SUBJECT_KEYS = frozenset({"entity", "type", "property"})
WINDOW_KEYS = frozenset({"start", "end"})

#: What may narrow a hit. Each is OPTIONAL and at least one is REQUIRED: a
#: predicate declaring nothing matches the first finding of any kind on that
#: entity, which would score a detector for noticing something else entirely.
#:
#: `severity_in` is a SET rather than a floor, and reads through
#: `read_severity_floor` -- the one place in this engine that turns a declared
#: list of severity words into severities. A second reader would be a second
#: copy of the valid set, which is the shape this project has watched drift.
PREDICATE_KEYS = frozenset({"problem_type", "axiom", "severity_in"})


@dataclass(frozen=True)
class Surprise:
    """One confirmed observation, and what would have counted as catching it."""

    id: str
    description: str = ""
    entity: str = ""
    entity_type: str = ""
    property_name: str = ""
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    problem_type: str = ""
    axiom: str = ""
    severities: frozenset = frozenset()
    confirmed: bool = True
    #: Was this observation inside the planned probe surface. The FORESIGHT
    #: column. Default False, because a set that does not say is a set whose
    #: author did not make the claim, and the favourable reading is the one
    #: that must be earned.
    anticipated: bool = False
    source: str = ""


@dataclass(frozen=True)
class SurpriseSet:
    """A corpus of surprises, and the domain they were observed in."""

    domain: str = ""
    entries: Tuple[Surprise, ...] = ()


@dataclass(frozen=True)
class SurpriseOutcome:
    """What the replay said about one entry."""

    id: str
    #: `detected`, `missed`, or `declined`. Three states and not two, because
    #: the third is the one a bare ratio destroys.
    verdict: str
    instants: int = 0
    matched: Tuple[str, ...] = ()
    decline: Optional[Decline] = None


@dataclass
class SurpriseScore:
    """Counts, their denominators, and no ratio.

    There is no `rate` here on purpose. See this module's docstring: the only
    real corpus this project holds carries its figure in two senses that answer
    different questions, and a single attribute is how they got separated.
    """

    domain: str = ""
    entries: int = 0
    #: Entries excluded from the detector denominator because the record does
    #: not claim they were confirmed. Not a miss and not a hit.
    unconfirmed: int = 0
    detected: int = 0
    missed: int = 0
    declined: int = 0
    #: The FORESIGHT numerator: confirmed entries the design did not anticipate.
    unanticipated: int = 0
    instants: int = 0
    outcomes: List[SurpriseOutcome] = field(default_factory=list)
    declines: List[Decline] = field(default_factory=list)

    @property
    def replayable(self) -> int:
        """The detector denominator: confirmed entries that could be replayed.

        A property rather than a stored field so it cannot disagree with the
        counts it is derived from -- a number written twice will drift, and
        this one is the denominator of the only figure anybody will quote.
        """
        return self.detected + self.missed

    def statement(self) -> str:
        """Both senses, in one sentence, with every denominator named."""
        confirmed = self.entries - self.unconfirmed
        return (
            f"detector performance: {self.detected} of {self.replayable} "
            f"replayable confirmed surprise(s) were surfaced by this model "
            f"({confirmed} confirmed, {self.declined} not replayable, "
            f"{self.unconfirmed} unconfirmed); "
            f"design foresight: {self.unanticipated} of {confirmed} confirmed "
            f"surprise(s) were outside the declared probe surface"
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "checked": {
                "entries": self.entries,
                "confirmed": self.entries - self.unconfirmed,
                "replayable": self.replayable,
                "instants": self.instants,
            },
            "detector": {
                "detected": self.detected,
                "missed": self.missed,
                "not_replayable": self.declined,
            },
            "foresight": {
                "unanticipated": self.unanticipated,
                "anticipated": (self.entries - self.unconfirmed
                                - self.unanticipated),
            },
            "statement": self.statement(),
            "outcomes": [
                {"id": o.id, "verdict": o.verdict, "instants": o.instants,
                 **({"matched": list(o.matched)} if o.matched else {}),
                 **({"decline": o.decline.to_dict()} if o.decline else {})}
                for o in self.outcomes
            ],
            "not_checked": [d.to_dict() for d in self.declines],
        }


def _did_you_mean(word: Any, valid: Sequence[str]) -> Optional[str]:
    """Nearest member of a closed set, matched without case.

    The same shape as the domain loader's, and for the same reason: `difflib`
    is case-sensitive and these vocabularies are not, so a suggestion appeared
    or vanished depending on how the author happened to type it.
    """
    if not isinstance(word, str):
        return None
    lowered = {member.casefold(): member for member in valid}
    near = difflib.get_close_matches(word.casefold(), list(lowered), 1, 0.8)
    return lowered[near[0]] if near else None


def _unknown_keys(block: Any, known: frozenset, where: str,
                  out: List[Decline]) -> None:
    """Name every key nothing reads, with the nearest one that is read."""
    if not isinstance(block, dict):
        return
    for key in sorted(set(block) - known):
        near = _did_you_mean(key, sorted(known))
        detail = (f"`{where}.{key}` is not a key this scorer reads, so "
                  f"nothing will ever consume it")
        if near:
            detail += f" — did you mean `{near}`?"
        out.append(Decline("unknown_key", {"field": f"{where}.{key}"},
                           detail, {"did_you_mean": near} if near else {}))


def _as_instant(value: Any) -> Optional[datetime]:
    """A declared moment, or None. Accepts what YAML already parsed."""
    if isinstance(value, datetime):
        return as_naive_utc(value)
    if isinstance(value, str):
        try:
            return as_naive_utc(datetime.fromisoformat(value))
        except ValueError:
            return None
    return None


def load_surprises(source: Union[str, Path, Dict[str, Any]]
                   ) -> Tuple[SurpriseSet, List[Decline]]:
    """Parse a surprise set, and report everything that will not be read.

    Returns the set AND the refusals rather than raising on them, because a
    corpus with one malformed entry is still a corpus: refusing the file would
    turn one author's typo into a benchmark that reports nothing, which reads
    exactly like a clean run of an empty set.

    Raises only when the source is not a surprise set at all, so a directory
    scan can filter with `is_surprise_set` instead of catching.
    """
    if isinstance(source, dict):
        data: Any = source
    else:
        text = str(source)
        # Same convention as `load_domain`: a newline-free string is a path.
        if isinstance(source, Path) or "\n" not in text:
            data = yaml.safe_load(Path(text).read_text(encoding="utf-8"))
        else:
            data = yaml.safe_load(text)

    if not isinstance(data, dict):
        raise NotASurpriseSetError(
            f"a surprise set must parse to a mapping, got "
            f"{type(data).__name__}")
    block = data.get("surprises", data)
    if not isinstance(block, dict) or "entries" not in block:
        raise NotASurpriseSetError(
            "no `surprises:` block with `entries:` — this looks like a domain "
            "model or another companion. Use is_surprise_set() to filter these "
            "when scanning a directory.")

    declines: List[Decline] = []
    _unknown_keys(block, SET_KEYS, "surprises", declines)

    raw = block.get("entries")
    if not isinstance(raw, (list, tuple)):
        raise NotASurpriseSetError(
            f"`surprises.entries` is {type(raw).__name__}, not a list")

    entries: List[Surprise] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            declines.append(Decline(
                "unknown_value", {"entry": index},
                f"entry {index} is {type(item).__name__}, not a mapping"))
            continue
        identifier = str(item.get("id") or f"entry-{index}")
        where = f"entries[{identifier}]"
        _unknown_keys(item, ENTRY_KEYS, where, declines)

        subject = item.get("subject") or {}
        _unknown_keys(subject, SUBJECT_KEYS, f"{where}.subject", declines)
        window = item.get("window") or {}
        _unknown_keys(window, WINDOW_KEYS, f"{where}.window", declines)
        predicate = item.get("counts_as_detected_when") or {}
        _unknown_keys(predicate, PREDICATE_KEYS,
                      f"{where}.counts_as_detected_when", declines)

        floor = read_severity_floor(predicate, key="severity_in")
        if floor.problem is not None:
            # UNUSABLE IS NOT PARTIAL, which is `read_severity_floor`'s own
            # rule and the reason it is the single reader. `[warning, critcal]`
            # yields an empty set and names the word to fix, rather than a
            # predicate quietly narrowed to one severity the author did not
            # choose.
            declines.append(Decline(
                "unknown_value",
                {"entry": identifier,
                 "field": f"{where}.counts_as_detected_when.severity_in"},
                f"`severity_in` is unusable ({floor.problem})"
                + (f": {', '.join(floor.rejected)} "
                   f"{'is' if len(floor.rejected) == 1 else 'are'} not a "
                   f"severity" if floor.rejected else ""),
                {"rejected": list(floor.rejected),
                 "known": sorted(m.value for m in Severity)}))

        entries.append(Surprise(
            id=identifier,
            description=str(item.get("description") or ""),
            entity=str(subject.get("entity") or ""),
            entity_type=str(subject.get("type") or ""),
            property_name=str(subject.get("property") or ""),
            start=_as_instant(window.get("start")),
            end=_as_instant(window.get("end")),
            problem_type=str(predicate.get("problem_type") or ""),
            axiom=str(predicate.get("axiom") or ""),
            severities=floor.floor,
            # ABSENT MEANS CONFIRMED, and absent means NOT anticipated. Both
            # defaults put the burden on the claim that flatters somebody: a
            # set that does not say `confirmed: false` is making the ordinary
            # claim, and one that does not say `anticipated: true` is not
            # claiming the design saw it coming.
            confirmed=bool(item.get("confirmed", True)),
            anticipated=bool(item.get("anticipated", False)),
            source=str(item.get("source") or ""),
        ))

    return SurpriseSet(domain=str(block.get("domain") or ""),
                       entries=tuple(entries)), declines


def is_surprise_set(source: Union[str, Path, Dict[str, Any]]) -> bool:
    """True if `load_surprises` would accept this source.

    The mirror of `is_domain_model`, and for the same reason: a directory scan
    should not need exceptions for control flow.
    """
    try:
        load_surprises(source)
        return True
    except (NotASurpriseSetError, ValueError, OSError, yaml.YAMLError):
        return False


def _matches(finding: Any, entry: Surprise) -> bool:
    """Does this finding satisfy the entry's declared predicate.

    Every declared clause must hold; an undeclared clause constrains nothing.
    The caller has already refused a predicate that declares NOTHING, so this
    can never return True for the first finding of any kind.
    """
    if getattr(finding, "entity_id", "") != entry.entity:
        return False
    if entry.problem_type and \
            getattr(finding, "problem_type", "") != entry.problem_type:
        return False
    if entry.axiom:
        axiom = getattr(finding, "axiom", None)
        name = getattr(axiom, "value", None) or getattr(axiom, "name", None)
        if str(name or "").upper() != entry.axiom.upper():
            return False
    if entry.severities:
        severity = getattr(finding, "severity", None)
        value = getattr(severity, "value", severity)
        if str(value or "").upper() not in entry.severities:
            return False
    return True


def _instants(session: Any, entry: Surprise) -> List[datetime]:
    """The subject's own observation timestamps inside the window.

    Not a grid. A step size is a number nobody declared, and a benchmark that
    picks its own can move its score by picking a different one. The readings
    the store actually holds are the moments the engine could have spoken at,
    which is exactly the question.
    """
    observations = session.history.get_observations(
        entry.entity, entry.start, entry.end)
    stamps = {
        as_naive_utc(observation.timestamp)
        for observation in observations
        if not entry.property_name
        or observation.property_name == entry.property_name
    }
    return sorted(stamps)


def score(session: Any, surprises: SurpriseSet, *,
          max_instants: int = 500,
          lookback_days: int = 30) -> SurpriseScore:
    """Replay the model across each entry's window and report both senses.

    `session` must already hold the model, the entities and the history. This
    does not feed anything: a scorer that built its own inputs would be scoring
    a corpus it wrote, which is the one way a benchmark can never fail.
    """
    from datetime import timedelta

    from .api import check
    from .replay import sync_current_from_history

    result = SurpriseScore(domain=surprises.domain,
                           entries=len(surprises.entries))
    lookback = timedelta(days=lookback_days)

    for entry in surprises.entries:
        if not entry.confirmed:
            # Outside both denominators. The record does not claim this
            # happened, so neither a hit nor a miss is available to report.
            result.unconfirmed += 1
            continue
        if not entry.anticipated:
            result.unanticipated += 1

        decline = _refuse(session, entry)
        if decline is not None:
            result.declined += 1
            result.declines.append(decline)
            result.outcomes.append(
                SurpriseOutcome(entry.id, "declined", decline=decline))
            continue

        stamps = _instants(session, entry)
        if not stamps:
            decline = Decline(
                "not_replayable", {"entry": entry.id, "entity": entry.entity},
                f"no observation of {entry.entity}"
                + (f".{entry.property_name}" if entry.property_name else "")
                + " inside the declared window, so this model was never shown "
                  "the data this entry is about — a miss here would grade the "
                  "store rather than the detector",
                {"window_start": entry.start.isoformat(),
                 "window_end": entry.end.isoformat()})
            result.declined += 1
            result.declines.append(decline)
            result.outcomes.append(
                SurpriseOutcome(entry.id, "declined", decline=decline))
            continue
        if len(stamps) > max_instants:
            decline = Decline(
                "instant_budget_exhausted",
                {"entry": entry.id, "entity": entry.entity},
                f"the window holds {len(stamps)} readings and the budget is "
                f"{max_instants}; sub-sampling could step over the instant the "
                f"engine spoke at, and reporting a miss it did not earn is "
                f"worse than reporting nothing",
                {"instants": len(stamps), "budget": max_instants})
            result.declined += 1
            result.declines.append(decline)
            result.outcomes.append(
                SurpriseOutcome(entry.id, "declined", decline=decline))
            continue

        matched: List[str] = []
        for instant in stamps:
            result.instants += 1
            with as_of(instant) as frozen:
                sync_current_from_history(session, frozen, lookback)
                envelope = check(session)
            hits = [f for f in envelope.findings if _matches(f, entry)]
            if hits:
                matched = sorted({f.problem_type for f in hits})
                break
        if matched:
            result.detected += 1
            result.outcomes.append(SurpriseOutcome(
                entry.id, "detected", len(stamps), tuple(matched)))
        else:
            result.missed += 1
            result.outcomes.append(
                SurpriseOutcome(entry.id, "missed", len(stamps)))

    return result


def _refuse(session: Any, entry: Surprise) -> Optional[Decline]:
    """The refusals that can be made before any replay runs."""
    if not entry.entity:
        return Decline(
            "no_subject", {"entry": entry.id},
            "no `subject.entity`, so there is nothing to ask the model about")
    if entry.start is None or entry.end is None:
        return Decline(
            "no_window", {"entry": entry.id},
            "a surprise is a claim about a span of time, and this entry "
            "declares none — `window.start` and `window.end` are both needed")
    if entry.end <= entry.start:
        return Decline(
            "malformed_window", {"entry": entry.id},
            f"`window.end` ({entry.end.isoformat()}) is not after "
            f"`window.start` ({entry.start.isoformat()})")
    if not (entry.problem_type or entry.axiom or entry.severities):
        return Decline(
            "empty_predicate", {"entry": entry.id},
            "`counts_as_detected_when` declares nothing, so the first finding "
            "of any kind on this entity would count as catching this one. "
            f"Declare at least one of {sorted(PREDICATE_KEYS)}")
    if entry.entity not in getattr(session, "entities", {}):
        return Decline(
            "subject_absent", {"entry": entry.id, "entity": entry.entity},
            f"{entry.entity!r} is not an entity in this session, so no finding "
            f"could ever carry its id")
    return None
