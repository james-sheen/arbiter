""" -- a transient state is timed against the model's timeout, or not at all.

`transient:` names states an entity passes through. How long it may take is a
fact about the domain, and until 0.2.22 STABILITY supplied one: five minutes,
whenever the model declared no `timeout:`, measured at the clock. Fed to the Core,
operating-health-audit's case study -- which declares `transient: [restructuring]`
and `transient: [at_risk]` and no timeout -- gained `transient_state_timeout` on
two units the first detection cycle after five minutes had passed: 13 findings
where the engine, judging the capture at its own instant, found 11. The number was
nobody's.

The loader still fills the field with five minutes -- an indicator field's default
is a major release's to change -- so the check reads the keys the author typed
Declined by name where the guess would have been used; timed exactly as
before where the model says how long.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from arbiter_engine import api
from arbiter_engine.interfaces import IndicatorSpec, IndicatorType
from arbiter_engine.ontology.axioms.stability import StabilityChecker
from arbiter_engine.types import Axiom

T0 = datetime(2026, 9, 29, 12, 0)


def _model(timeout=None):
    extra = f", timeout: {timeout}" if timeout else ""
    return f"""
domain:
  id: passing_states
  name: passing states
  entity_types: [Unit]
  relationship_types: []
  indicators:
    Unit:
      - {{name: status, type: STATE, axioms: [STABILITY], window: 7d,
         normal: [steady], transient: [changing], bad: [broken]{extra}}}
"""


def _check(timeout=None, *, since=timedelta(hours=2), state="changing"):
    """A unit that was steady, then entered `state` `since` before T0."""
    session = api.EngineSession()
    session.load_model(_model(timeout))
    session.add_entity("u-1", "Unit", {"status": state})
    start = T0 - since
    readings = [(start - timedelta(hours=2), "steady"), (start - timedelta(hours=1), "steady")]
    # One reading a minute, as the Core records a state each cycle: the old check
    # looked back twice its timeout for where the state began, and a sparse series
    # hid the guess by leaving it nothing to measure.
    readings += [(start + timedelta(minutes=m), state)
                 for m in range(0, int(since.total_seconds() // 60) + 1)]
    session.add_observations("u-1", "status", readings)
    with api.as_of(T0):
        return api.check(session).to_dict()


def _timeouts(result):
    return [f for f in result["findings"] if f["problem_type"].startswith("transient_state_timeout")]


def _declines(result):
    return [d for d in result["not_checked"]
            if d.get("reason") == "missing_config" and d.get("axiom") in ("STABILITY", "stability")]


class TestNoTimeoutDeclared:

    def test_two_hours_in_a_passing_state_is_not_timed_against_a_guess(self):
        result = _check()
        assert _timeouts(result) == []

    def test_the_check_says_so_by_name(self):
        [decline] = _declines(_check())
        assert decline.get("indicator") == "status"
        assert "timeout" in (decline.get("detail") or "")

    def test_a_unit_not_in_a_passing_state_raises_nothing_to_decline(self):
        result = _check(state="steady")
        assert _timeouts(result) == [] and _declines(result) == []


class TestATimeoutDeclared:

    def test_a_state_held_past_the_declared_timeout_is_found(self):
        [finding] = _timeouts(_check("30m", since=timedelta(hours=1)))
        assert finding["entity_id"] == "u-1"

    def test_a_state_within_the_declared_timeout_is_not(self):
        result = _check("30m", since=timedelta(minutes=10))
        assert _timeouts(result) == [] and _declines(result) == []

    def test_the_declared_timeout_is_the_one_used(self):
        """Two hours held: a 3h timeout is not yet reached, a 1h one is."""
        assert _timeouts(_check("3h", since=timedelta(hours=2))) == []
        assert len(_timeouts(_check("1h", since=timedelta(hours=2)))) == 1


class TestASpecBuiltInCode:

    def test_an_explicit_timeout_set_in_code_is_still_timed(self):
        """No keys are typed in code, so the timeout the code set is the declaration."""
        spec = IndicatorSpec(uri="t:status", name="status", indicator_type=IndicatorType.STATE,
                             relevant_axioms=[Axiom.STABILITY], normal_states=["steady"],
                             transient_states=["changing"], transient_timeout=timedelta(minutes=5))
        assert not spec.declared_keys
        assert StabilityChecker._declared_timeout(spec) == timedelta(minutes=5)

    def test_a_typed_spec_without_timeout_reports_none_whatever_the_loader_filled(self):
        spec = IndicatorSpec(uri="t:status", name="status", indicator_type=IndicatorType.STATE,
                             relevant_axioms=[Axiom.STABILITY], transient_states=["changing"],
                             transient_timeout=timedelta(minutes=5),
                             declared_keys=frozenset({"name", "type", "axioms", "transient"}))
        assert StabilityChecker._declared_timeout(spec) is None
