"""A latency indicator with no threshold declines rather than holding.

`role: latency`, `axioms: [RESPONSIVENESS]`, and no `critical:` or
`warning:`, with the value present: no finding, no decline, and
`checked.invariants` counting the cell as attempted. An envelope reporting a
question as covered that it could not ask -- which is the shape the decline
vocabulary exists to prevent, arriving through the one axiom that had no arm
for it.

THE FOURTH REPAIR OF ONE CLASS, AND THE MECHANISM IS NAMED IN THE FILE.
`_check_latency_threshold` returns a plain list and `check` extends it, so a
`not_evaluated` record written in the helper is dropped at that line. The
`no_current_value` decline was hoisted into the caller for exactly that reason;
the no-threshold case was left behind, inside the helper, where the guard is
simply skipped and an empty list comes back.

It is the case a bridge meets first, because a latency with no published limit
is the normal state of a latency. Measured from outside on released 0.1.10 by an
independent bridge built to BRIDGES.md, against a latency of ten million.
"""
from __future__ import annotations

import contextlib
import io

import pytest

from arbiter_engine.api import EngineSession, check

MODEL = """
domain:
  id: latency-threshold-probe
  name: Latency threshold probe
  entity_types: [Controller]
  indicators:
    Controller:
      - name: scan_time_ms
        type: NUMERIC
        role: latency
        axioms: [RESPONSIVENESS]
{thresholds}
"""


#: The two controls, at module level so their embedded YAML sits at column 0
#: without a docstring's indentation around it. The scrub's dedented-docstring
#: check reads a line that starts at column 0 inside an INDENTED string as an
#: identifier removal that took the indent with it, and it is right to: that is
#: exactly what a stripped citation looks like. Keeping domain YAML out of
#: indented strings is the cheaper side of that trade.
NO_ROLE = """
domain:
  id: latency-no-role
  name: Latency with no role
  entity_types: [Controller]
  indicators:
    Controller:
      - name: scan_ms
        type: NUMERIC
        axioms: [RESPONSIVENESS]
        critical: 30
"""

BOUNDEDNESS_CONTROL = """
domain:
  id: boundedness-control
  name: Boundedness control
  entity_types: [A]
  indicators:
    A:
      - name: p
        type: NUMERIC
        axioms: [BOUNDEDNESS]
"""


def _check(thresholds: str = "", value=10_000_000) -> dict:
    session = EngineSession()
    with contextlib.redirect_stderr(io.StringIO()):
        session.load_model(MODEL.format(thresholds=thresholds))
        session.add_entity("plc1", "Controller",
                           properties={"scan_time_ms": value})
        return check(session).to_dict()


def _declines(envelope, axiom="RESPONSIVENESS"):
    return [row for row in envelope["not_checked"] if row.get("axiom") == axiom]


class TestTheSilentCell:
    def test_no_threshold_declared_now_declines(self):
        declines = _declines(_check())
        assert [row["reason"] for row in declines] == ["no_threshold"]

    def test_it_used_to_hold_silently(self):
        """The defect, restored as an assertion: neither leg carried anything,
        and the denominator counted the cell anyway."""
        envelope = _check()
        assert envelope["findings"] == []
        assert envelope["checked"]["invariants"] == 1, (
            "the cell must still be COUNTED -- a decline is a statement about "
            "an attempted invariant, and dropping it from the denominator "
            "would hide the question rather than report it")
        assert _declines(envelope), (
            "attempted 1, no finding, no decline: the envelope says a question "
            "was covered that it could not ask")

    def test_the_decline_names_the_remedy_not_the_rule(self):
        detail = _declines(_check())[0]["detail"]
        assert "critical:" in detail and "warning:" in detail
        assert "scan_time_ms" in detail

    def test_only_a_warning_is_enough_to_judge(self):
        envelope = _check("        warning: 20\n")
        assert _declines(envelope) == []
        assert [f["problem_type"] for f in envelope["findings"]] == [
            "response_time_warning:scan_time_ms"]

    def test_only_a_critical_is_enough_to_judge(self):
        envelope = _check("        critical: 40\n")
        assert _declines(envelope) == []
        assert [f["problem_type"] for f in envelope["findings"]] == [
            "response_time_critical:scan_time_ms"]


class TestZeroIsADeclaredThreshold:
    """`if indicator.critical_threshold and...` is falsy at zero, so a bound
    the model states was skipped without a word. Zero is legitimate for a
    latency that must be immediate."""

    def test_a_critical_of_zero_is_compared_not_skipped(self):
        envelope = _check("        critical: 0\n", value=5)
        assert _declines(envelope) == []
        assert [f["problem_type"] for f in envelope["findings"]] == [
            "response_time_critical:scan_time_ms"]

    def test_a_warning_of_zero_is_compared_not_skipped(self):
        envelope = _check("        warning: 0\n", value=5)
        assert [f["problem_type"] for f in envelope["findings"]] == [
            "response_time_warning:scan_time_ms"]

    def test_a_value_inside_a_zero_bound_still_holds(self):
        """The control. Without it the two above would pass against a checker
        that had started firing on everything."""
        envelope = _check("        critical: 0\n", value=-1)
        assert envelope["findings"] == []
        assert _declines(envelope) == []


class TestTheNeighbouringArmsAreUnchanged:
    def test_a_missing_role_still_declines_missing_role(self):
        session = EngineSession()
        with contextlib.redirect_stderr(io.StringIO()):
            session.load_model(NO_ROLE)
            session.add_entity("plc1", "Controller", properties={"scan_ms": 99})
            envelope = check(session).to_dict()
        assert [row["reason"] for row in _declines(envelope)] == ["missing_role"]

    def test_an_absent_value_still_declines_for_its_own_reason(self):
        """`no_current_value` / `missing_property` is raised before the new
        arm, and must stay first: a cell with no value has a more specific
        answer than *nobody declared a threshold*."""
        session = EngineSession()
        with contextlib.redirect_stderr(io.StringIO()):
            session.load_model(MODEL.format(thresholds=""))
            session.add_entity("plc1", "Controller", properties={})
            envelope = check(session).to_dict()
        reasons = [row["reason"] for row in _declines(envelope)]
        assert reasons and reasons[0] != "no_threshold", reasons

    def test_boundedness_in_the_same_position_is_unchanged(self):
        """The control this restores parity with."""
        session = EngineSession()
        with contextlib.redirect_stderr(io.StringIO()):
            session.load_model(BOUNDEDNESS_CONTROL)
            session.add_entity("a1", "A", properties={"p": 99})
            envelope = check(session).to_dict()
        assert [row["reason"] for row in _declines(envelope, "BOUNDEDNESS")] == [
            "no_threshold"]
