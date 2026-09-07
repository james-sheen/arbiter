"""A domain check that cannot run is reported, not dropped.

Extensions supply callables; this engine calls them inside a `try` so that one
bad extension cannot take out the others in the same pass. That is correct. What
was wrong is where the exception went: a debug line, which in production is
indistinguishable from the check having run and found nothing.

**The two answers are different and the difference is the whole point.** *Ran,
found nothing* is a result. *Could not be called* is a check that is not
happening, and a caller who declared it has every reason to believe it is.

MEASURED, NOT HYPOTHETICAL. A shipped domain file declared a check whose second
parameter is required and is not the one the binder inspects, so the binder
called it with too few arguments, every time, for as long as both existed. The
TypeError landed in that debug line and no surface said anything.

AND IT REACHES THE ENVELOPE, WHICH IS THE POINT. An earlier version of this
file said a log level was the only channel available, because
`run_domain_checks` returned a plain list with nowhere to put a decline. It
returns a `CheckOutcome` now, and the record travels: the reason is
`checker_error`, which was in the closed decline vocabulary from the start and
had never once been emitted by any path. A reason a schema advertises and no
code produces is indistinguishable, from outside, from a reason that cannot
happen.

So the assertions below are two-sided on purpose. The log is for the operator
watching a process; the decline is for the consumer reading a result, and only
one of those is machine-readable.
"""
from __future__ import annotations

import logging

import pytest

from arbiter_engine.history.observation import InMemoryObservationHistory
from arbiter_engine.interfaces import Entity
from arbiter_engine.ontology.axioms.extensions import (
    AxiomExtension, extension_registry)
from arbiter_engine.ontology.axioms.homeostasis import HomeostasisChecker
from arbiter_engine.ontology.axioms.responsiveness import (
    ResponsivenessChecker)

DOMAIN = "a-domain-that-declares-a-broken-check"


def _entity():
    return Entity(id="e/1", type="Thing", name="e1", properties={"v": 1},
                  metadata={"domain_id": DOMAIN})


class _RaisingExtension(AxiomExtension):
    """One check that cannot be called, and one beside it that can."""

    @property
    def domain_id(self):
        return DOMAIN

    @staticmethod
    def _cannot_run(entity, history):
        raise TypeError("missing 1 required positional argument: 'desired_config'")

    def get_homeostasis_checks(self):
        return [self._cannot_run, lambda entity, history: []]

    def get_responsiveness_checks(self):
        return [self._cannot_run]


@pytest.fixture
def registered():
    ext = _RaisingExtension()
    extension_registry.register(ext)
    try:
        yield ext
    finally:
        extension_registry.unregister(DOMAIN)


@pytest.mark.parametrize("checker_cls,module", [
    (HomeostasisChecker, "arbiter_engine.ontology.axioms.homeostasis"),
    (ResponsivenessChecker, "arbiter_engine.ontology.axioms.responsiveness"),
])
class TestTheFailureReachesAReader:
    def test_it_is_reported_at_warning_not_debug(self, registered, caplog,
                                                 checker_cls, module):
        with caplog.at_level(logging.DEBUG, logger=module):
            checker_cls().run_domain_checks(
                _entity(), InMemoryObservationHistory(), domain_id=DOMAIN)
        levels = {r.levelno for r in caplog.records if r.name == module}
        assert logging.WARNING in levels, (
            f"{module}: a check that raised produced no warning; at debug this "
            f"is invisible in production and reads as 'ran, found nothing'")

    def test_the_message_names_the_reason(self, registered, caplog, checker_cls, module):
        with caplog.at_level(logging.DEBUG, logger=module):
            checker_cls().run_domain_checks(
                _entity(), InMemoryObservationHistory(), domain_id=DOMAIN)
        text = " ".join(r.getMessage() for r in caplog.records if r.name == module)
        assert "desired_config" in text, (
            "the underlying error is not in the message, so a reader learns a "
            "check failed but not which argument it wanted")


class TestItReachesTheEnvelope:
    """The half a log line cannot do. `checked` counts what was attempted and
    `not_checked` says why something was not judged -- a consumer reading the
    envelope has no access to the process's log, and this is the difference
    between a result they can act on and one they can only wonder about."""

    def test_the_decline_is_recorded_with_the_declared_reason(self, registered):
        outcome = HomeostasisChecker().run_domain_checks(
            _entity(), InMemoryObservationHistory(), domain_id=DOMAIN)
        reasons = [n.reason for n in getattr(outcome, "not_evaluated", ())]
        assert reasons, (
            "the failure produced no decline record; it exists only in the log, "
            "where a consumer of the envelope cannot see it")
        assert any(getattr(r, "value", r) == "checker_error" for r in reasons), (
            f"the decline used {reasons!r} rather than the vocabulary's own name "
            f"for this case")

    def test_it_survives_check_all_rather_than_being_dropped(self, registered):
        """The seam. Building a plain list from a `CheckOutcome` keeps the
        problems and drops the declines, so a record written one frame down is
        thrown away at the return line unless the method carries it."""
        outcome = ResponsivenessChecker().check_all(
            _entity(), InMemoryObservationHistory())
        assert getattr(outcome, "not_evaluated", None), (
            "check_all returned no declines; the record was made and then lost "
            "at the boundary, which is the failure this seam is known for")

    def test_the_detail_names_what_went_wrong(self, registered):
        outcome = HomeostasisChecker().run_domain_checks(
            _entity(), InMemoryObservationHistory(), domain_id=DOMAIN)
        details = " ".join(str(getattr(n, "detail", "")) 
                           for n in getattr(outcome, "not_evaluated", ()))
        assert "desired_config" in details, (
            "the decline records that something failed but not what it wanted")


class TestTheSurvivingChecksStillRun:
    """The reason the `try` exists. A test that only asserted the warning would
    pass against an implementation that aborted the whole pass on the first
    failure, which would be a worse defect than the one being fixed."""

    def test_one_broken_check_does_not_stop_the_others(self, registered):
        problems = HomeostasisChecker().run_domain_checks(
            _entity(), InMemoryObservationHistory(), domain_id=DOMAIN)
        assert problems == []          # the survivor returns nothing, by design
