"""The MONOTONICITY rate arm declines rather than answering from a default.

closing the ruling. Measured from outside on released 0.1.10 by
an independent bridge built to BRIDGES.md: with no rate declared, this arm fired
`warning` at 0.1/s and `critical` at 0.5/s. Every PLC heartbeat crosses that.
Every fast production counter crosses it. The finding named an entity whose model
never asked the question, against a number nobody in the domain chose.

IT WAS THE ONLY ARM IN THE FORMAT THAT DID THIS. The reversal tolerance beside
it became declarable in 0.1.8 on the same argument -- an allowance no model could
state, no document named, and no envelope mentioned. The rate arm was left on the
old footing: the instance fixed and the class left, one arm over.

WHAT THIS IS ALLOWED TO BREAK, AND WHAT IT IS NOT. COMPATIBILITY.md permits a
patch release to *make a check DECLINE where it previously answered from a
guess*. It forbids going quiet: a check withdrawn without a decline is
indistinguishable from one that passed. So the cell still counts in
`checked.invariants`, the decline names the declaration to write, and -- the part
that is easy to get wrong -- **the reversal arm beside it still runs and its
findings still report**. Returning early would have withdrawn a working check in
order to report a missing one.
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import io

import pytest

from arbiter_engine.api import EngineSession, check

NOW = _dt.datetime.now(_dt.timezone.utc)

MODEL = """
domain:
  id: rate-arm-probe
  name: Rate arm probe
  entity_types: [Controller]
  indicators:
    Controller:
      - name: heartbeat
        type: NUMERIC
        role: count
        axioms: [MONOTONICITY]
        monotonicity:
          expected_direction: increasing
{block}"""


def _stamped(values, cadence=60.0):
    n = len(values)
    return [(NOW - _dt.timedelta(seconds=cadence * (n - 1 - i)), v)
            for i, v in enumerate(values)]


def _ramp(per_second, n=30, cadence=60.0):
    return [float(i * per_second * cadence) for i in range(n)]


def _with_reversals(count, n=30, step=5.0):
    """A rising series with `count` recent backward steps, inside the window."""
    values, current = [], 0.0
    down = {n - 1 - 2 * i for i in range(count)}
    for i in range(n):
        current += -step if i in down else step
        values.append(current)
    return values


def _run(block: str, values) -> dict:
    session = EngineSession()
    with contextlib.redirect_stderr(io.StringIO()):
        session.load_model(MODEL.format(block=block))
        session.add_entity("plc1", "Controller",
                           properties={"heartbeat": values[-1]})
        session.add_observations("plc1", "heartbeat", _stamped(values))
        return check(session).to_dict()


def _declines(envelope):
    return [row for row in envelope["not_checked"]
            if row.get("axiom") == "MONOTONICITY"]


def _kinds(envelope):
    return [f["problem_type"] for f in envelope["findings"]]


RATES = "          rate_warning: 60\n          rate_critical: 120\n"


class TestUndeclaredIsDeclinedNotGuessed:
    @pytest.mark.parametrize("per_second", [0.01, 0.09, 0.1, 0.5, 50.0, 200.0])
    def test_no_rate_declared_declines_at_every_speed(self, per_second):
        """At 0.1/s and above this used to produce a finding, and below it a
        silent pass. Both were answers to a question nobody asked."""
        envelope = _run("", _ramp(per_second))
        assert [row["reason"] for row in _declines(envelope)] == ["no_threshold"]
        assert "monotonicity_rate:heartbeat" not in _kinds(envelope)

    def test_the_cell_is_still_counted(self):
        """COMPATIBILITY.md: a patch release may not go quiet. A withdrawn
        check that leaves the denominator is indistinguishable from one that
        passed."""
        envelope = _run("", _ramp(50.0))
        assert envelope["checked"]["invariants"] == 1

    def test_the_decline_names_the_declaration_to_write(self):
        detail = _declines(_run("", _ramp(50.0)))[0]["detail"]
        assert "rate_warning" in detail and "rate_critical" in detail
        assert "basis" in detail

    def test_the_decline_says_the_other_arm_ran(self):
        """Otherwise a reader takes `no_threshold` to mean MONOTONICITY was not
        checked at all, and retires a reversal check that is running."""
        assert "reversal arm ran" in _declines(_run("", _ramp(50.0)))[0]["detail"]


class TestTheReversalArmIsUntouched:
    """The part that would have been quietly lost. The two arms share one axiom
    and one indicator, so a decline that returned early would take the reversal
    finding with it."""

    def test_a_reversal_still_fires_while_the_rate_declines(self):
        envelope = _run("", _with_reversals(3))
        assert "monotonicity_reversal:heartbeat" in _kinds(envelope)
        assert [row["reason"] for row in _declines(envelope)] == ["no_threshold"]

    def test_a_clean_counter_reports_neither_finding(self):
        """The control. Without it the test above passes against a checker that
        had started firing reversals on everything."""
        envelope = _run("", _ramp(0.01))
        assert _kinds(envelope) == []

    def test_the_declared_reversal_tolerance_still_reaches_the_comparison(self):
        block = "          reversal_tolerance: 1\n"
        assert "monotonicity_reversal:heartbeat" in _kinds(
            _run(block, _with_reversals(1)))


class TestDeclaredRatesAreJudged:
    def test_a_declared_pair_that_is_crossed_fires_critical(self):
        envelope = _run(RATES, _ramp(200.0))
        assert _declines(envelope) == []
        assert [(f["problem_type"], f["severity"]) for f in envelope["findings"]] == [
            ("monotonicity_rate:heartbeat", "critical")]

    def test_a_declared_pair_that_is_not_crossed_is_quiet(self):
        """50/s under a declared 60/120 -- the case a real PLC heartbeat is in
        once somebody writes the number down."""
        envelope = _run(RATES, _ramp(50.0))
        assert _declines(envelope) == [] and _kinds(envelope) == []

    def test_declaring_only_critical_is_enough_and_leaves_warning_silent(self):
        """`critical:` without `warning:` already behaves this way under
        BOUNDEDNESS and RESPONSIVENESS; the rate arm now matches."""
        envelope = _run("          rate_critical: 120\n", _ramp(50.0))
        assert _declines(envelope) == [] and _kinds(envelope) == []
        crossed = _run("          rate_critical: 120\n", _ramp(200.0))
        assert [f["severity"] for f in crossed["findings"]] == ["critical"]

    def test_declaring_only_warning_is_enough(self):
        envelope = _run("          rate_warning: 60\n", _ramp(200.0))
        assert [f["severity"] for f in envelope["findings"]] == ["warning"]


class TestTheOldNumbersAreGone:
    """The engine's own 0.1 and 0.5 must not survive anywhere as a judging
    fallback. A default that still fires from one code path is the defect."""

    @pytest.mark.parametrize("per_second", [0.1, 0.11, 0.5, 0.51])
    def test_the_old_firing_points_no_longer_fire(self, per_second):
        assert _kinds(_run("", _ramp(per_second))) == []

    def test_a_caller_who_sets_the_params_is_still_honoured(self):
        """`AxiomParameters(...)` is the unsupported deep path, and a caller who
        reaches it and states a number HAS declared one. Only the untouched
        dataclass default reads as the engine's guess."""
        from arbiter_engine.ontology.axioms.monotonicity import (
            MonotonicityChecker)
        from arbiter_engine.types import AxiomParameters
        checker = MonotonicityChecker(params=AxiomParameters(
            monotonicity_rate_warning=1000.0,
            monotonicity_rate_critical=2000.0))
        assert checker.params.monotonicity_rate_warning == 1000.0
