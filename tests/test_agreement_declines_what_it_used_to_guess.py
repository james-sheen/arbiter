"""The CONSISTENCY agreement arm declines rather than answering from a default.

`consistency: {agrees_with: [...]}` used to fall back to a global 5% relative
tolerance when the model declared none, and answer. Five percent is a wide
silence wherever the two numbers are money, counts of record, or a measurement
and its check -- **measured on a blind draw, two statements of one contract total
1.9% apart, ninety thousand on four point eight million, and this arm answered
*they agree*** with no finding and no decline to read.

THE FORMAT ALREADY REFUSED THIS MOVE ONE AXIOM OVER. A HOMEOSTASIS setpoint
without a tolerance does not get a guessed one; it abandons the setpoint path and
logs that it did. The agreement arm was left on the old footing -- the instance
fixed and the class left, one axiom over, which is the same shape the rate arm
was found in.

WHAT THIS IS ALLOWED TO BREAK, AND WHAT IT IS NOT. COMPATIBILITY.md permits a
patch release to *make a check DECLINE where it previously answered from a
guess*. It forbids going quiet. So the cell still counts in `checked.invariants`,
the decline names the declaration to write, and -- the part the rate-arm ruling
says is easy to get wrong -- **the role rules beside it still run and their
findings still report**. Withdrawing a working check in order to report a missing
one would be a worse trade than the guess was.
"""
from __future__ import annotations

import pytest

yaml = pytest.importorskip("yaml")

from arbiter_engine.api import EngineSession, check  # noqa: E402


def _envelope(consistency, values, role="percentage"):
    session = EngineSession()
    session.load_model(yaml.safe_dump({"domain": {
        "id": "agree", "name": "agree", "entity_types": ["T"],
        "relationship_types": ["r"],
        "indicators": {"T": [
            {"name": "a", "type": "NUMERIC", "role": role,
             "axioms": ["CONSISTENCY"], "consistency": consistency},
            {"name": "b", "type": "NUMERIC", "role": "count"}]}}}))
    session.add_entity("t", "T", values, "t")
    return check(session).to_dict()


def _reasons(envelope):
    return {d.get("reason") for d in envelope["not_checked"]}


def _types(envelope):
    return {f["problem_type"] for f in envelope["findings"]}


class TestAnUndeclaredToleranceIsNotGuessed:
    def test_it_declines_and_names_the_block_to_write(self):
        envelope = _envelope({"agrees_with": ["b"]}, {"a": 100.0, "b": 103.0})
        assert "missing_config" in _reasons(envelope)
        detail = next(d["detail"] for d in envelope["not_checked"]
                      if d.get("reason") == "missing_config")
        assert "tolerance:" in detail and "tolerance_absolute:" in detail

    def test_the_cell_still_counts(self):
        """A withdrawn check that stops counting is indistinguishable from one
        that passed, which is what the decline exists to prevent."""
        assert _envelope({"agrees_with": ["b"]},
                         {"a": 100.0, "b": 103.0})["checked"]["invariants"] == 1

    def test_the_gap_that_motivated_this_no_longer_passes_silently(self):
        """1.9% apart -- inside the old 5% default. It answered *they agree*."""
        envelope = _envelope({"agrees_with": ["b"]},
                             {"a": 4_820_000.0, "b": 4_910_000.0}, role="count")
        assert _types(envelope) == set()
        assert "missing_config" in _reasons(envelope)


class TestADeclaredToleranceStillDecides:
    @pytest.mark.parametrize("block", [{"tolerance": 0.01},
                                       {"tolerance_absolute": 0}])
    def test_a_disagreement_outside_it_fires(self, block):
        envelope = _envelope({"agrees_with": ["b"], **block},
                             {"a": 100.0, "b": 103.0})
        assert "redundant_disagreement:a" in _types(envelope)
        assert "missing_config" not in _reasons(envelope)

    def test_a_disagreement_inside_it_does_not(self):
        """The control. Without it a checker that flagged every pair would pass
        the test above."""
        envelope = _envelope({"agrees_with": ["b"], "tolerance": 0.10},
                             {"a": 100.0, "b": 103.0})
        assert "redundant_disagreement:a" not in _types(envelope)


class TestTheOtherRulesAreNotWithdrawn:
    def test_a_role_finding_still_reports_beside_the_decline(self):
        """The part the rate-arm ruling calls easy to get wrong. 150 is not a
        percentage whatever the agreement arm could not judge."""
        envelope = _envelope({"agrees_with": ["b"]}, {"a": 150.0, "b": 150.0})
        assert "impossible_value" in _types(envelope)
        assert "missing_config" in _reasons(envelope)

    def test_a_missing_peer_still_reports_its_own_reason(self):
        """The arm had one way to decline before this change and the reason was
        hardcoded at the call site. A second way arrived; a hardcoded reason
        would have named the wrong remedy with full confidence."""
        envelope = _envelope({"agrees_with": ["absent"], "tolerance": 0.01},
                             {"a": 50.0})
        assert "missing_property" in _reasons(envelope)
        assert "missing_config" not in _reasons(envelope)


class TestTheGlobalDefaultIsGone:
    def test_the_parameter_no_longer_exists(self):
        """It had exactly one reader, and that reader was the guess. Left in
        place it would have been accepted, carried and read by nothing -- the
        shape this engine spent the week removing elsewhere."""
        from arbiter_engine.types import AxiomParameters
        assert not hasattr(AxiomParameters(), "consistency_agreement_tolerance")
