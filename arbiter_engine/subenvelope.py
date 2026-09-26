"""The four-leg envelope, one level down: a discipline reporting its own work.

The top-level :class:`~.envelope.Envelope` answers for the eight axioms. A
discipline -- entailment, projection, inference, discovery -- does work of a
different KIND, with its own denominator and its own reasons for refusing, and
the envelope's contract is deliberately unable to carry it:

``not_checked[].axiom`` is a closed enum of eight and every decline record
requires one. A projection that cannot fit a model has no axiom to name. Given
that record shape, a discipline could only report a refusal by inventing an
axiom for it, which is precisely the name-derived judgement this engine has
been removing.

So a discipline reports in a sub-envelope of the same SHAPE -- checked,
findings, not_checked, questions -- riding as a payload key alongside the
legs rather than inside them. The schema already permits that and documents
why: additive keys are how this envelope grows, and a tool-specific payload is
not a change to the contract every tool satisfies identically.

**Two denominators are never summed.** The top-level ``checked.invariants``
counts axiom evaluations attempted and nothing else. A sub-envelope's
``checked`` counts what that discipline attempted, in units that discipline
owns -- rules, series, queries, pairs. Adding them would produce a number that
is true of no process.

WHY THE VOCABULARY IS CHECKED HERE AND NOT AT THE EDGE

A decline whose reason is outside the vocabulary is the failure this engine
keeps paying for in other forms: a refusal that reads as a judgement, or a
category nobody can count because it is spelled three ways. The check is in
``__post_init__`` rather than in a serialiser because a sub-envelope that
cannot be built is a bug the author sees, while one that serialises to
something a consumer cannot classify is a bug the consumer sees.

Each discipline owns its own closed set. They are separate because the reasons
genuinely do not overlap: ``cpt_missing`` means nothing to a projector and
``filter_not_converged`` means nothing to a query planner. A single merged
vocabulary would let either accept the other's refusals, which is how a closed
enum stops being evidence about anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .envelope import (
    SOURCE_LIVE,
    SOURCE_UNAVAILABLE,
    SOURCE_WARMING_UP,
    _problem_to_dict,
    _question_to_dict,
)
from .interfaces import Problem
from .types import NotEvaluatedReason

__all__ = ["VOCABULARIES", "Decline", "SubEnvelope"]


#: The closed decline vocabulary of each discipline.
#:
#: These are the refusals each discipline can make and no others. A member is
#: added by a patch release -- COMPATIBILITY.md permits growing a decline set,
#: because a reader that switches on a reason it knows is unaffected by a
#: reason it has never seen; what it forbids is changing what an existing
#: member MEANS.
#:
#: ``internal_error`` is in all four deliberately. A discipline that raises
#: where it could have declined turns one unanswerable cell into an
#: unanswerable pass, and the envelope's whole claim is that it reports what it
#: could not do rather than failing to return.
#: The shadow discipline's vocabulary is DERIVED, and it is the only one that
#: is. Every other discipline owns its refusals; this one runs the eight axioms
#: over forecast values and passes their declines through unchanged, so its
#: vocabulary is theirs plus the two refusals it makes on its own account --
#: a forecast with no median, and a subject this session cannot place.
#:
#: Written as a union rather than a list because a list would be a second copy
#: of `NotEvaluatedReason`, and this file's own comment on the discovery
#: vocabulary says what happens to those: it goes stale the first time a member
#: is added, which has happened to a decline vocabulary here before.
_SHADOW_VOCABULARY = frozenset({
    "missing_property",            # a forecast with no median to shadow with
    "precondition_unmet",          # a subject this session cannot place
    "no_report_probability",       # results, and no declared line for them
    "tail_not_declared",           # the line falls outside the sent quantiles
    # Records that name a `source` are not a producer's submission,
    # so the axioms do not run over them. Counted and named in one decline
    # rather than dropped: the path used to be the only silent skip in
    # `shadow_entities`, and a batch that was entirely stamped produced a zero
    # denominator with nothing beside it to say why.
    "not_a_producers_submission",
    # Every discipline carries this and a standing test says so. The axioms'
    # own enum has `checker_error`, which is a different statement -- that one
    # names a checker that raised, and this one is the discipline itself
    # failing. Inheriting the union alone left this the only discipline that
    # could not say it had broken.
    "internal_error",
}) | {reason.value for reason in NotEvaluatedReason}

#:. Hoisted out of `VOCABULARIES` so the simulation set can
#: fold it in. `seed_mode="projected"` runs the declared projector, so a
#: simulation carries whatever that projector declined with -- and a
#: second copy of a closed set is how two vocabularies drift apart.
_PROJECTION_VOCABULARY = frozenset({
    "model_missing",               # no dynamics declared; a default would decide it
        "insufficient_samples",
        "unidentifiable_parameter",    # q and r not separable from this series
        "model_inconsistent",          # innovations outside the declared band
        "covariance_unbounded",
        "no_threshold",                # nothing to compute a breach probability against
        "no_report_probability",       # a breach probability, and no declared line for it
        "no_lookback",                 # no declared span of history to fit on
        "internal_error",
        # WITHDRAWN 0.1.18, four at once, for the reason this file already
        # gives twice: a member no input can reach makes the set a worse
        # instrument. All four named a state THIS filter does not compute.
        #
        # `unobservable_state` and `filter_not_converged` belong to a filter
        # that reports its own observability and convergence. The local-level
        # model ships closed-form: it has one state, which is observed by
        # construction, and no iteration to fail to converge. The member that
        # DOES fire where they would have is `unidentifiable_parameter`.
        #
        # `stale_observation` and `horizon_exceeds_validity` each need a number
        # nobody declared -- how old is too old, and how far out this model
        # stays valid. Inventing either is the thing this project refuses: a
        # floor is a specification, not a guess. A series whose readings all
        # fall outside the declared `lookback` already declines
        # `insufficient_samples` with `n: 0`, truthfully. They return with a
        # `validity:` or a staleness line in the declaration, which would be
        # the specification these two are currently missing.
    })

VOCABULARIES: Dict[str, frozenset] = {
    "shadow": _SHADOW_VOCABULARY,
    "simulation": frozenset({
        # What a traversal asked for a VALUE and would not produce.
        "missing_dynamics",      # the edge declares no transition
        "missing_declaration",   # a `transition:` block missing a required key
        "missing_property",      # the driving property is absent or not a number
        "cycle_unsupported",     # a feedback path needs iteration, not one pass
        # `reconvergence_unsupported` WAS HERE AND IS GONE, which
        # is the intended end of a decline rather than a rollback.
        # added it to name a real limitation: a node reached by two acyclic
        # paths of unequal length ended correct while anything downstream of
        # it stayed short, and saying so was better than the `cycle` this used
        # to claim. Ordering the value pass by dependency removed the
        # limitation, so the reason had nothing left to report -- and a member
        # nobody can construct an input for is the dead-vocabulary shape
        # exists to catch. It never shipped; it was added and retired
        # inside one unreleased section.
        "budget_exhausted",      # max_transitions reached; the count is carried
        "internal_error",
        # the rollout's own. A rollout can refuse for reasons a
        # single what-if cannot have: a malformed request, an actuator slower
        # than the step, and an axiom the reasoner declined over the imagined
        # state -- the last carrying whatever `NotEvaluatedReason` it gave,
        # which is why the axiom vocabulary is folded in below rather than
        # re-listed and left to drift.
        "malformed_request",
        "settle_exceeds_step",
        "unknown_action",
        "unknown_parameter",
        "wrong_entity_type",
        "missing_entity",
        "malformed_action",
        "precondition_unmet",
        "insufficient_samples",
        # the planner's two. Both are the same refusal in different
        # places: a choice the model did not supply. `plan` evaluates its
        # candidates either way and reports what each does; what it will not
        # do is rank them against an objective nobody declared, or invent the
        # values to try.
        "no_objective",
        "no_candidates",
        # the pair is declared, the magnitude is not yet.
        "gain_not_adopted",
        # no `dynamics:` on an indicator a caller asked to project.
        # The same refusal `run_projection` makes, now reachable from the
        # simulation side too: the engine does not choose a model for you, and
        # it used to on this one path while declining on the other.
        "model_missing",
        # the closed loop's two refusals to FILE a prediction.
        #
        # A rollout under actions is a COUNTERFACTUAL, not a forecast. This
        # engine never dispatches -- a rollout carrying actions reports
        # `tier: 3` and stops -- so it cannot know the actions were taken, and
        # grading *what would have happened if* against what did would score
        # the model on outcomes nobody attempted. The ledger would fill with
        # falsified records that say nothing about the model.
        "counterfactual_not_a_prediction",
        # A point prediction is not falsifiable without a resolution, and the
        # ledger requires one for exactly that reason. The engine will not
        # invent it: how close counts as right is a domain fact, the same
        # class as the floor refuses to guess. A declared
        # `gain_sigma:` IS that statement, so a value carrying one can be
        # filed and a value without one is declined here by name.
        "no_declared_tolerance",
        # two NON-ADDITIVE effects on one property at one instant.
        # Only `add` superposes. Two `set` deltas measured from the same
        # pre-step reading and summed give `A + B - base`, which is a value
        # neither action asked for: measured, 1500 and 2000 on a pump at 1000
        # put it at 2500. `at_s` is the only ordering here and they share it,
        # so there is nothing to break the tie with except list position,
        # which is an accident of how the caller built the sequence.
        # Scalings are NOT refused -- multiplication is commutative, so they
        # compose without an ordering.
        "contradictory_actions",
        # a declared coupling with NO INSTANCE to run on. A
        # `transition:` block lives on a relationship RULE, and the rule has
        # nothing to move until an edge of that type joins two entities of
        # the right types. A session that holds a Pump and a Tank and no
        # `feeds` edge between them ran every simulation verb happily: the
        # rollout reported `transitions_applied: 0`, the tank sat at its
        # baseline while the pump was throttled by 500 rpm, `plan` ranked
        # five candidates that all did the same nothing, and NOTHING in any
        # of those envelopes said the declared coupling had nowhere to run.
        # For an engine whose product is *did you look*, that is a reportable
        # absence -- and it is the state every client of a transport with no
        # way to build an edge is permanently in.
        "coupling_uninstantiated",
    }) | {reason.value for reason in NotEvaluatedReason}
      # AND THE PROJECTION VOCABULARY, folded in rather than
      # re-listed. `seed_mode="projected"` runs the declared projector, so a
      # simulation can now carry whatever that projector declined with --
      # `unidentifiable_parameter` when two variance terms do not separate
      # from a series, `no_lookback` when nothing says how far back to fit.
      # Re-listing them here would be a second copy of one closed set, which
      # is how two vocabularies drift; the rollout already folds in the
      # axioms' enum for exactly this reason.
      | _PROJECTION_VOCABULARY,
    "forecasts": frozenset({
        "forecast_missing",     # declared expected, and nothing arrived
        "stale_forecast",       # older than the declared `max_age`
        "model_unknown",        # a model_id the declaration does not list
        "ungradeable",          # matured with no mirror observation to score on
        "internal_error",
        # WITHDRAWN 0.1.18, on this file's own rule. `no_tolerance` named a
        # point prediction with no declared tolerance, and no such record can
        # reach this vocabulary: `contract.py` takes three shapes, all of which
        # become quantiles, and a `mean` without a finite `sigma` is REJECTED
        # there as `malformed_forecast` -- "a mean on its own states no
        # interval". A rejection at the contract is reported in `rejected`,
        # which is the ingest report's vocabulary and not this one, so the
        # decline had no path to exist.
        #
        # The same argument the entries below already make, applied to itself:
        # a member no input can reach makes the set a worse instrument. It
        # returns if a point-forecast shape ever lands.
    }),
    "entailment": frozenset({
        "rule_unreachable",            # a body predicate is not declared
        "open_world_undecidable",      # absence of a fact is not evidence of absence
        "depth_exceeded",              # body longer than the atom limit
        "recursion_unsupported",       # head predicate appears in its own body
        "malformed_rule",              # the head or a body atom did not parse
        "binding_budget_exhausted",    # polynomial is not the same as affordable
        "internal_error",
        # -- RETURNED with the loader change that produces it, as the
        # note below promised. A subtype that `extends:` a parent and changes
        # part of an inherited band into a contradiction neither declaration
        # had alone; the pair is named here and in `unreachable_declarations`.
        "inheritance_conflict",
        # WITHDRAWN BEFORE THEY EVER FIRED, and recorded rather than deleted
        # silently. The design named two more. `inheritance_conflict` was the
        # first, and came back above when `extends:` landed.
        #
        # `unit_mismatch` has no producer that could ever exist here: this
        # engine has no unit system at all, so nothing can declare two
        # operands in incompatible units. A member no input can reach makes the
        # set a worse instrument -- a reader counting refusal kinds counts one
        # that cannot happen, and the enum stops being evidence about the
        # engine. Both come back with the machinery that emits them.
    }),
    "projection": _PROJECTION_VOCABULARY,
    "inference": frozenset({
        "not_identifiable",            # an open backdoor through a declared latent
        "cpt_missing",                 # a weight on an active path is a default
        "cycle_unsupported",
        "evidence_conflict",           # the model gives this evidence probability zero
        "treewidth_exceeded",          # exact elimination would build a factor too wide
        "no_report_probability",       # a posterior, and no declared line for it
        "internal_error",
        # WITHDRAWN until the method that produces them lands, like the two in
        # `entailment`. `approximation_not_converged` and `sample_floor` belong
        # to the Monte Carlo fallback for graphs exact elimination cannot take;
        # this discipline ships exact-only, and refuses by `treewidth_exceeded`
        # where the fallback would have been. Naming a convergence failure that
        # nothing can converge is a member a reader would count and never see.
    }),
    "discovery": frozenset({
        "orientation_undetermined",    # both directions significant
        "nonstationary_series",        # the tests are invalid as-is
        "untested_pair",               # the budget ran out; this is discovery's denominator
        "latent_confounding_possible",
        "faithfulness_unverifiable",   # assumed; not testable from observational data
        "insufficient_samples",
        "no_significance_level",       # results, and no declared line for them
        "internal_error",
    }),
}

#: Keys a :class:`Decline` writes itself when it serialises. A ``scope`` key
#: with one of these names would overwrite the record's own field and produce a
#: decline whose stated reason is not the reason it was declined for -- silently,
#: because a dict update is not an error. The names are refused at construction.
_RESERVED_SCOPE_KEYS = frozenset({"reason", "detail", "evidence"})

_SOURCES = frozenset({SOURCE_LIVE, SOURCE_WARMING_UP, SOURCE_UNAVAILABLE})


@dataclass(frozen=True)
class Decline:
    """One thing a discipline did not do, and why.

    ``scope`` says WHAT was not done, in the units of the discipline: a
    projection names ``{"entity_id", "property"}``, entailment names
    ``{"rule"}``, discovery names ``{"pair"}``, inference names ``{"query"}``.
    It is deliberately not a closed shape -- the disciplines do not share one --
    while ``reason`` is, because that is the field a consumer counts.

    ``evidence`` carries the numbers behind the refusal, and the refusals worth
    having all have some: how many samples arrived against how many were
    needed, which p-values disagreed, which edges were defaults.
    """

    reason: str
    scope: Dict[str, Any] = field(default_factory=dict)
    detail: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.scope, Mapping):
            raise TypeError(
                f"decline scope must be a mapping, got {type(self.scope).__name__}")
        clash = _RESERVED_SCOPE_KEYS & set(self.scope)
        if clash:
            raise ValueError(
                f"decline scope may not use {sorted(clash)}: the record writes "
                f"those keys itself and a scope entry would overwrite them"
            )

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"reason": self.reason}
        out.update(self.scope)
        if self.detail:
            out["detail"] = self.detail
        if self.evidence:
            out["evidence"] = dict(self.evidence)
        return out


@dataclass(frozen=True)
class SubEnvelope:
    """What one discipline checked, what it found, what it declined, what it asks.

    ``checked`` is the discipline's own denominator, in its own units, reported
    by the routine that attempted the work. The keys are the discipline's to
    choose; what is enforced here is that there IS one and that at least one
    entry counts something. A sub-envelope with an empty ``checked`` is the
    "8 declined out of ?" shape the top-level denominator exists to prevent,
    one level down.

    Non-count entries are allowed alongside the counts -- inference reports
    which method answered, and that is not a number -- but they cannot be the
    whole of it.
    """

    kind: str
    checked: Dict[str, Any]
    findings: List[Problem] = field(default_factory=list)
    not_checked: List[Decline] = field(default_factory=list)
    questions: List[Any] = field(default_factory=list)
    source: str = SOURCE_LIVE
    reason: Optional[str] = None
    #: the approximations this leg's numbers rest on, by stamp. The
    #: simulation and plan payloads have carried one for releases; a discipline
    #: built through this type had nowhere to put one, so `infer` disclosed a
    #: default it was making on every call by not mentioning it. Emitted only
    #: when non-empty, so no existing payload gains a key.
    assumptions: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in VOCABULARIES:
            raise ValueError(
                f"unknown discipline {self.kind!r}; "
                f"known: {sorted(VOCABULARIES)}"
            )
        if not isinstance(self.checked, Mapping) or not self.checked:
            raise ValueError(
                f"{self.kind}: `checked` is the denominator and cannot be empty -- "
                f"declines are uninterpretable without it"
            )
        if not any(isinstance(v, int) and not isinstance(v, bool)
                   for v in self.checked.values()):
            raise ValueError(
                f"{self.kind}: `checked` counts nothing; at least one entry must "
                f"be an integer count. Got {dict(self.checked)!r}"
            )
        vocabulary = VOCABULARIES[self.kind]
        outside = sorted({d.reason for d in self.not_checked
                          if d.reason not in vocabulary})
        if outside:
            raise ValueError(
                f"{self.kind}: reason(s) outside the vocabulary: {outside}. "
                f"Known: {sorted(vocabulary)}"
            )
        if self.source not in _SOURCES:
            raise ValueError(
                f"{self.kind}: source must be one of {sorted(_SOURCES)}, "
                f"got {self.source!r}"
            )
        # The envelope's own rule, applied one level down: `reason` is
        # populated whenever `source` is not `live`. A sub-envelope that says
        # `unavailable` and does not say why is the silence this shape exists
        # to make impossible.
        if self.source != SOURCE_LIVE and not self.reason:
            raise ValueError(
                f"{self.kind}: source is {self.source!r} and carries no reason"
            )

    @property
    def is_fully_evaluated(self) -> bool:
        """True when the discipline declined nothing. Named after the
        envelope's property of the same name, and meaning the same thing:
        not health, just an absence of refusals."""
        return not self.not_checked

    def to_dict(self) -> Dict[str, Any]:
        meta: Dict[str, Any] = {"source": self.source}
        if self.reason is not None:
            meta["reason"] = self.reason
        return {
            "checked": dict(self.checked),
            # Findings carry their evidence here, where top-level findings do
            # not. A discipline's finding is a claim built from a computation
            # the reader did not watch -- a posterior, a breach probability, a
            # lead-lag -- and the numbers behind it are the only way to tell a
            # measurement from an assertion.
            "findings": [
                dict(_problem_to_dict(p),
                     evidence=dict(getattr(p, "evidence", {}) or {}))
                for p in self.findings
            ],
            "not_checked": [d.to_dict() for d in self.not_checked],
            "questions": [_question_to_dict(q) for q in self.questions],
            "meta": meta,
            **({"assumptions": list(self.assumptions)} if self.assumptions else {}),
        }
