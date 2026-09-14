"""Two axioms read the same field names and compared them differently.

Reported from outside, from a bridge transcribing published limits. `warning:`
and `critical:` are read by BOUNDEDNESS and by RESPONSIVENESS; all four of
BOUNDEDNESS's bounds fired AT the declared number and RESPONSIVENESS fired only
past it. So `critical: 600` meant *600 is already critical* on one axiom and
*600 is still fine* on the other, and an author had no way to know which rule
applied to the number they were writing down.

Either comparator is defensible alone; the two disagreeing silently is not.
They agree now, inclusively -- the direction four of the six already used, and
the one where a finding APPEARS at the bound rather than disappearing there.

The second half of this file is the same shape one layer down: a decline code
covering two dispositions, where only the prose told them apart.
"""
from __future__ import annotations

import contextlib
import io

import pytest

from arbiter_engine.api import EngineSession, check


HEAD = ("\ndomain:\n  id: bound-probe\n  name: Bound probe\n"
        "  entity_types: [Thing]\n  indicators:\n    Thing:\n")


def _envelope(indicator_yaml: str, properties: dict, series=None) -> dict:
    session = EngineSession()
    with contextlib.redirect_stderr(io.StringIO()):
        session.load_model(HEAD + indicator_yaml)
        session.add_entity("t1", "Thing", properties=properties)
        for name, values in (series or {}).items():
            session.add_observations("t1", name, values)
        return check(session).to_dict()


def _fired(envelope: dict) -> list[str]:
    return [f.get("problem_type") for f in envelope.get("findings") or []]


def _declines(envelope: dict) -> list[dict]:
    return list(envelope.get("not_checked") or [])


BOUNDED = """      - name: v
        type: NUMERIC
        role: percentage
        axioms: [BOUNDEDNESS]
        {keys}
"""
LATENCY = """      - name: response_time_ms
        type: NUMERIC
        role: latency
        axioms: [RESPONSIVENESS]
        warning: 120
        critical: 600
"""


class TestResponsivenessFiresAtTheNumber:
    """The half that moved."""

    @pytest.mark.parametrize("value,expected", [
        (119.999, None),
        (120.0, "response_time_warning:response_time_ms"),
        (599.999, "response_time_warning:response_time_ms"),
        (600.0, "response_time_critical:response_time_ms"),
    ])
    def test_each_bound_is_reached_at_its_own_value(self, value, expected):
        fired = _fired(_envelope(LATENCY, {"response_time_ms": value}))
        assert fired == ([expected] if expected else []), (value, fired)

    def test_the_wording_no_longer_says_exceeds_at_the_bound(self):
        """A sentence saying a value exceeds a number it is equal to is a
        sentence a reader will not believe twice."""
        envelope = _envelope(LATENCY, {"response_time_ms": 600.0})
        said = " ".join(str(f.get("reason", "")) for f in envelope["findings"])
        assert "exceeds" not in said, said


class TestBoundednessIsUnchanged:
    """The control. Every assertion above would also hold if BOUNDEDNESS had
    been moved to meet RESPONSIVENESS, which is the direction that makes a
    finding disappear at the bound."""

    @pytest.mark.parametrize("keys,value,expected", [
        ("warning: 50", 50.0, "threshold_warning:v"),
        ("critical: 40", 40.0, "threshold_exceeded:v"),
        ("lower_warning: 72\n        warning: 95", 72.0, "below_warning_threshold:v"),
        ("lower_critical: 24\n        critical: 95", 24.0, "below_critical_threshold:v"),
    ])
    def test_every_bound_still_fires_at_its_declared_value(self, keys, value, expected):
        assert _fired(_envelope(BOUNDED.format(keys=keys), {"v": value})) == [expected]

    def test_just_inside_a_ceiling_is_still_quiet(self):
        assert _fired(_envelope(BOUNDED.format(keys="warning: 50"), {"v": 49.999})) == []


class TestTheTwoAxiomsAgree:
    """The claim the issue actually made: not that either rule is right, but
    that one engine must not hold both."""

    def test_an_upper_bound_means_the_same_thing_on_both(self):
        upper = _fired(_envelope(BOUNDED.format(keys="warning: 120"), {"v": 120.0}))
        latency = _fired(_envelope(LATENCY, {"response_time_ms": 120.0}))
        assert bool(upper) == bool(latency), (upper, latency)


MONOTONIC = """      - name: v
        type: NUMERIC
        axioms: [MONOTONICITY]
        monotonicity:
          expected_direction: increasing
          allow_reset: false
          reversal_tolerance: 1
"""


class TestOneArmRanAndTheOtherHadNothingToJudge:
    """`no_threshold` covered an indicator with nothing to judge against AND a
    two-armed axiom whose other arm found a real violation."""

    @pytest.fixture
    def envelope(self):
        return _envelope(MONOTONIC, {"v": 50},
                         series={"v": [100.0, 90.0, 80.0, 70.0, 60.0, 50.0]})

    def test_the_reversal_arm_still_reports_what_it_found(self, envelope):
        assert "monotonicity_reversal:v" in _fired(envelope)

    def test_the_decline_no_longer_shares_a_code_with_a_model_defect(self, envelope):
        reasons = [d["reason"] for d in _declines(envelope)]
        assert reasons == ["partially_checked"], reasons

    def test_the_decline_names_the_arm_that_ran(self, envelope):
        assert _declines(envelope)[0].get("arms_checked") == ["reversal"], (
            "a floor keyed on this has to read the prose detail otherwise, "
            "which is what a closed decline vocabulary exists to avoid")

    def test_an_axiom_with_nothing_to_judge_still_says_no_threshold(self):
        """N=2, and the point of the split. Without this the new code could
        simply have replaced the old one everywhere and proved nothing."""
        nothing = """      - name: v
        type: NUMERIC
        role: latency
        axioms: [RESPONSIVENESS]
"""
        reasons = [d["reason"] for d in _declines(_envelope(nothing, {"v": 5.0}))]
        assert reasons == ["no_threshold"], reasons
