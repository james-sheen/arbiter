"""The three-part response envelope.

Every other agent tool in the ecosystem returns findings and stops. This one
returns what it checked, what it could not see, and what it needs to know
next. That sentence is the whole differentiator, and this module is it made
mechanical rather than aspirational.

Three legs, each with a distinct source:

``checked``
    How many (axiom, entity, indicator) evaluations the pass attempted, and
    over how many entities. Comes from ``DetectionResult.evaluations_attempted``
which had to be added — findings and declines were countable,
    but their sum is *not* the total, because an evaluation that ran and found
    nothing appears in neither.

``not_checked``
    What was declined and why, from the ``NotEvaluated`` records. Empty
    is a real answer: it means every declared axiom was actually evaluated.

``questions``
    What the model is missing, from the DISCOVER-mode gap surface. Optional —
    a caller with no topology supplies none, and the leg is then empty rather
    than absent, because "no questions" and "questions not gathered" are
    different and the ``meta.source`` field says which.

**Envelope vocabulary is inherited, not invented.** ``source`` takes the same
three values the established pattern established across ~50 endpoint modules —
``live`` / ``warming_up`` / ``unavailable`` — with ``reason`` populated
whenever it is not ``live``. Diverging here would be the vocabulary-drift
that an internal ruling decided against, in the newest public surface.

**What this module does NOT do**: it does not decide whether a finding is
important, rank findings, or summarise them in prose. It reports what the
engine did.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .interfaces import DetectionResult, Problem
from .types import NotEvaluated

#: the established pattern envelope vocabulary, reused verbatim.
SOURCE_LIVE = "live"
SOURCE_WARMING_UP = "warming_up"
SOURCE_UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class CheckedSummary:
    """The denominator. ``invariants`` counts evaluations **attempted**, which
    is the only figure that makes ``not_checked`` interpretable — 8 declined
    out of 47 attempted is a different statement from 8 out of 9.

    that sentence was true of one of the five construction sites.
    The others reported, under the same name: the count of *declared* axioms
    (``model_describe``), the number of traversal *steps* (``traverse``), and
    the number of *matched findings* from a lookup (``attest``). So a
    traversal that evaluated nothing answered "checked 3 invariants", and
    ``model_describe`` answered with declarations — the exact
    declared-versus-evaluated conflation raised to P1, in the one
    field whose entire job is to be an honest denominator.

    ``invariants`` now means evaluations attempted, everywhere, and nothing
    else. Work that is not an evaluation reports itself in its own field:
    ``steps`` for traversal, ``declared_invariants`` for what a model
    declares. Both are omitted from the payload when zero, matching the
    existing convention that an absent number is not invited to be read as a
    measured zero.
    """

    invariants: int = 0
    entities: int = 0
    steps: int = 0
    declared_invariants: int = 0

    def to_dict(self) -> Dict[str, int]:
        out = {"invariants": self.invariants, "entities": self.entities}
        if self.steps:
            out["steps"] = self.steps
        if self.declared_invariants:
            out["declared_invariants"] = self.declared_invariants
        return out


@dataclass(frozen=True)
class Envelope:
    """A tool response: what was checked, what was not, what is unknown."""

    checked: CheckedSummary
    findings: List[Problem] = field(default_factory=list)
    not_checked: List[NotEvaluated] = field(default_factory=list)
    questions: List[Dict[str, Any]] = field(default_factory=list)
    source: str = SOURCE_LIVE
    reason: Optional[str] = None

    @property
    def is_fully_evaluated(self) -> bool:
        """True when nothing was declined. Deliberately not called
        ``is_healthy`` — an envelope with no findings and eight declines is
        not health, it is silence, and the two must not share a name."""
        return not self.not_checked

    def to_dict(self) -> Dict[str, Any]:
        meta: Dict[str, Any] = {"source": self.source}
        if self.reason is not None:
            meta["reason"] = self.reason
        return {
            "checked": self.checked.to_dict(),
            "findings": [_problem_to_dict(p) for p in self.findings],
            "not_checked": [_not_evaluated_to_dict(n) for n in self.not_checked],
            "questions": list(self.questions),
            "meta": meta,
        }


def _problem_to_dict(problem: Problem) -> Dict[str, Any]:
    axiom = getattr(problem, "axiom", None)
    severity = getattr(problem, "severity", None)
    return {
        "entity_id": getattr(problem, "entity_id", ""),
        "problem_type": getattr(problem, "problem_type", ""),
        "axiom": getattr(axiom, "value", None) if axiom is not None else None,
        "severity": getattr(severity, "value", None) if severity is not None else None,
        "reason": getattr(problem, "reason", ""),
    }


def _not_evaluated_to_dict(record: NotEvaluated) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "entity_id": record.entity_id,
        "entity_type": record.entity_type,
        "indicator": record.indicator,
        "axiom": record.axiom.value,
        "reason": record.reason.value,
    }
    if record.detail:
        out["detail"] = record.detail
    # Only present for sample-floor declines; omitted rather than null so a
    # reader is not invited to interpret a missing count as zero.
    if record.observations_count is not None:
        out["observations"] = record.observations_count
    if record.required_count is not None:
        out["required"] = record.required_count
    # `observations` is a count INSIDE the window and `required` is
    # a global floor. Emitting the pair without the window invites "collect
    # more data", which is false whenever the rate cannot span the floor. The
    # window and the measured interval make the ratio interpretable; the
    # `remedy` line states the conclusion, because an agent reading this will
    # act on it and should not have to do the arithmetic.
    if record.window_seconds is not None:
        out["window_seconds"] = record.window_seconds
    if record.total_observations is not None:
        out["total_observations"] = record.total_observations
    if record.sampling_interval_seconds is not None:
        out["sampling_interval_seconds"] = record.sampling_interval_seconds
    if record.floor_unreachable_at_this_rate:
        out["floor_unreachable_at_this_rate"] = True
        out["remedy"] = (
            f"sample more often than every "
            f"{record.sampling_interval_seconds:.0f}s, or widen the window: "
            f"{record.required_count} samples cannot fit in "
            f"{record.window_seconds:.0f}s at the observed rate. Collecting "
            f"for longer will not help."
        )
    return out


def _question_to_dict(question: Any) -> Dict[str, Any]:
    """Normalise a DISCOVER-mode question.

    Accepts the engine's own ``TopologyQuestion`` and plain dicts, because the
    gap surface is optional and a caller may supply its own.

     corrected the field names here. The first version read
    ``question`` and ``gap_type`` off the object; ``TopologyQuestion`` actually
    carries ``question_text`` and a nested ``gap`` whose ``gap_type`` is the
    enum. Both lookups fell through to ``getattr`` defaults, so a real
    question serialised as its dataclass repr — a bug that could only surface
    on wiring the thing to an actual traversal, which is what an internal ruling did.
    """
    if isinstance(question, dict):
        return dict(question)

    text = getattr(question, "question_text", None)
    if text is None:
        text = getattr(question, "question", None)
    gap = getattr(question, "gap", None)
    gap_type = getattr(gap, "gap_type", None) if gap is not None else None
    location = getattr(gap, "location", None) if gap is not None else None

    out: Dict[str, Any] = {
        "question": text if text is not None else str(question),
        "gap_type": getattr(gap_type, "value", str(gap_type)) if gap_type else None,
        "location": location,
    }
    priority = getattr(question, "priority", None)
    if priority is not None:
        out["priority"] = priority
    context = getattr(question, "context_path", None)
    if context:
        out["context_path"] = list(context)
    return out


def build_envelope(
    result: DetectionResult,
    questions: Optional[Sequence[Any]] = None,
    source: str = SOURCE_LIVE,
    reason: Optional[str] = None,
) -> Envelope:
    """Assemble an envelope from a detection pass.

    ``findings`` merges ``problems`` and ``warnings`` deliberately. The
    reasoner splits them by severity, which is a presentation choice; a caller
    asking what was found wants both, and dropping warnings is how
    BOUNDEDNESS's warning-threshold breach goes missing from a response that
    claims to report findings.

    ``questions`` is a sequence rather than derived here, because gathering
    them requires a topology this module deliberately does not depend on.
    """
    ordered = sorted(
        list(questions or []),
        key=lambda q: getattr(q, "priority", 0.0) or 0.0,
        reverse=True,
    )
    return Envelope(
        checked=CheckedSummary(
            invariants=getattr(result, "evaluations_attempted", 0),
            entities=result.entities_checked,
        ),
        findings=list(result.problems) + list(result.warnings),
        not_checked=list(result.not_evaluated),
        questions=[_question_to_dict(q) for q in ordered],
        source=source,
        reason=reason,
    )


def unavailable_envelope(reason: str) -> Envelope:
    """The established pattern's bootstrap-aware fallback: a tool whose substrate is not
    up answers with an envelope naming the reason, never an error and never a
    misleading empty success."""
    return Envelope(
        checked=CheckedSummary(),
        source=SOURCE_UNAVAILABLE,
        reason=reason,
    )


def summarise(envelope: Envelope) -> str:
    """One-line human form, the shape the CD body sketched.

    Used in tool descriptions and the demo transcript; the machine
    contract is ``to_dict``.
    """
    parts = [
        f"checked {envelope.checked.invariants} invariants "
        f"across {envelope.checked.entities} entities",
        f"findings {len(envelope.findings)}",
        f"not_checked {len(envelope.not_checked)}",
        f"questions {len(envelope.questions)}",
    ]
    if envelope.source != SOURCE_LIVE:
        parts.append(f"source {envelope.source} ({envelope.reason})")
    return "; ".join(parts)
