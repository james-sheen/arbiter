"""A decline recorded by an extension check survives to `check_all`.

`run_domain_checks` guarded its collection with `if result:`. A `CheckOutcome`
carrying only declines is falsy — it is a list subclass holding zero problems —
so the guard skipped the whole result and the record with it.

Assertions are OUTCOMES: the record arrives. A test asserting the guard was
deleted would pass the day somebody writes the same skip a different way.

The last test is the mirror: the `CHECKER_ERROR` path was already working before
this fix, and a repair that trades one decline channel for another is not one.
"""

from __future__ import annotations

import pytest

from arbiter_engine.history.observation import InMemoryObservationHistory
from arbiter_engine.interfaces import CheckOutcome, Entity
from arbiter_engine.ontology.axioms.extensions import (
    AxiomExtension,
    extension_registry,
)
from arbiter_engine.ontology.axioms.homeostasis import HomeostasisChecker
from arbiter_engine.ontology.axioms.responsiveness import ResponsivenessChecker
from arbiter_engine.types import Axiom, NotEvaluatedReason

DOMAIN = "a-domain-that-declines"


@pytest.fixture
def entity():
    return Entity(id="e1", type="Thing", name="e1",
                  metadata={"domain_id": DOMAIN}, properties={})


@pytest.fixture
def history():
    return InMemoryObservationHistory()


def _registered(homeostasis=(), responsiveness=()):
    class DecliningExtension(AxiomExtension):
        @property
        def domain_id(self):
            return DOMAIN

        def get_homeostasis_checks(self):
            return list(homeostasis)

        def get_responsiveness_checks(self):
            return list(responsiveness)

    saved = dict(extension_registry._extensions)
    extension_registry.register(DecliningExtension())
    return saved


@pytest.fixture(autouse=True)
def _restore_registry():
    saved = dict(extension_registry._extensions)
    yield
    extension_registry._extensions.clear()
    extension_registry._extensions.update(saved)


def _declines(axiom, reason=NotEvaluatedReason.MISSING_CONFIG):
    def check(entity, history):
        return CheckOutcome().declined(
            axiom, entity, "a_declared_check", reason,
            detail="the check ran and could not judge")
    return check


def _finds_and_declines(axiom, checker_entity):
    """One outcome carrying BOTH, which is the case a naive fix loses."""
    def check(entity, history):
        from arbiter_engine.interfaces import Problem
        from arbiter_engine.types import Severity, DetectionLayer
        out = CheckOutcome([Problem.from_entity(
            entity=entity, problem_type="a_finding", severity=Severity.WARNING,
            reason="something", axiom=axiom, source_layer=DetectionLayer.ONTOLOGY,
            evidence={}, confidence=0.5)])
        return out.declined(axiom, entity, "another_check",
                            NotEvaluatedReason.MISSING_CONFIG, detail="and this")
    return check


def test_a_declining_outcome_is_falsy_which_is_why_this_was_lost(entity, history):
    """The mechanism, pinned once so the rest of the file reads as intended.

    Not the assertion the fix is judged on -- that is the outcome below -- but
    without it a reader cannot tell why an ordinary-looking guard dropped data.
    """
    outcome = CheckOutcome().declined(
        Axiom.HOMEOSTASIS, entity, "c", NotEvaluatedReason.MISSING_CONFIG)
    assert len(outcome.not_evaluated) == 1
    assert not outcome, "a CheckOutcome holding only declines must still be falsy"


def test_a_homeostasis_extension_decline_reaches_run_domain_checks(entity, history):
    _registered(homeostasis=[_declines(Axiom.HOMEOSTASIS)])
    outcome = HomeostasisChecker().run_domain_checks(entity, history, domain_id=DOMAIN)
    assert len(outcome.not_evaluated) == 1, (
        "the check recorded a decline and run_domain_checks returned none")


def test_a_homeostasis_extension_decline_reaches_check_all(entity, history):
    _registered(homeostasis=[_declines(Axiom.HOMEOSTASIS)])
    outcome = HomeostasisChecker().check_all(entity, history)
    reasons = [r.reason for r in outcome.not_evaluated]
    assert NotEvaluatedReason.MISSING_CONFIG in reasons, (
        f"check_all lost the decline; got {reasons}")


def test_a_responsiveness_extension_decline_reaches_check_all(entity, history):
    _registered(responsiveness=[_declines(Axiom.RESPONSIVENESS)])
    outcome = ResponsivenessChecker().check_all(entity, history)
    reasons = [r.reason for r in outcome.not_evaluated]
    assert NotEvaluatedReason.MISSING_CONFIG in reasons, (
        f"check_all lost the decline; got {reasons}")


def test_an_outcome_carrying_both_keeps_both(entity, history):
    """The truthy case. It would have survived the old guard as PROBLEMS and
    still lost its records at `extend`, so passing the guard was never enough."""
    _registered(homeostasis=[_finds_and_declines(Axiom.HOMEOSTASIS, entity)])
    outcome = HomeostasisChecker().check_all(entity, history)
    assert [p.problem_type for p in outcome] == ["a_finding"], "the problem was lost"
    assert len(outcome.not_evaluated) == 1, "the decline beside it was lost"


def test_a_check_that_finds_nothing_and_declines_nothing_adds_nothing(entity, history):
    """The other direction. Removing the guard must not invent a record."""
    _registered(homeostasis=[lambda e, h: []])
    outcome = HomeostasisChecker().check_all(entity, history)
    assert list(outcome) == [] and outcome.not_evaluated == [], (
        "a clean check produced something")


def test_the_raising_path_still_records_checker_error(entity, history):
    """The mirror. This decline channel worked before and the fix must
    not have been a trade."""
    def raises(entity, history):
        raise RuntimeError("boom")
    _registered(homeostasis=[raises])
    outcome = HomeostasisChecker().check_all(entity, history)
    reasons = [r.reason for r in outcome.not_evaluated]
    assert NotEvaluatedReason.CHECKER_ERROR in reasons, (
        f"the pre-existing raising path stopped recording; got {reasons}")
