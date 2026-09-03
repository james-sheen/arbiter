"""MONOTONICITY's positive path, and the tolerance that used to hide it.

**No shipped test asserted this axiom FIRING.** Its declines were covered — the
sample floor, the missing config — and the detection half was folklore. That
asymmetry was reported from outside, and characterizing it is what found the
defect below rather than confirming the capability.

THE DEFECT. A single rollback of a cumulative counter produced no
finding AND no decline. `_check_reversals` fires at `reversal_count >=
reversal_threshold`, the threshold was a global engine default of 3, and below
it the function returns an empty list that reaches nothing. Measured on 0.1.7:
one reversal 0/0, two reversals 0/0, three reversals 1/0 — identical under both
`allow_reset` settings, so the reset arm was not what suppressed it.

**The threshold is not the defect; its invisibility was.** BOUNDEDNESS is
correctly quiet at 84 against a declared `warning: 85`, and nobody calls that a
bug, because somebody declared the 85. This number was one no model could
state, no document named, and no envelope mentioned — the single exception in a
format where every other tolerance is per-indicator. It is declarable now, and
the default is unchanged, so nothing written before this behaves differently.

WHY THE DEFAULT DID NOT MOVE TO 1. Lowering it would make every model that
relies on the old behaviour start firing on ordinary counter noise, which is a
change nobody asked for smuggled in behind a fix somebody did. A consumer who
wants one-rollback detection writes `reversal_tolerance: 1`; a consumer who
wants what they had writes nothing.
"""

from __future__ import annotations

import sys

import pytest

from arbiter_engine.api import EngineSession, check


WINDOW = "24h"


def _model(**mono) -> dict:
    """One entity type, one indicator, MONOTONICITY and nothing else.

    The config block is spread in by the caller so each test names only what it
    is varying — a fixture that carried `reversal_tolerance` for every case
    would make the default-behaviour tests silently depend on it.
    """
    block = {"expected_direction": "increasing", "allow_reset": False}
    block.update(mono)
    return {
        "domain": {
            "id": "monotonicity-positive",
            "name": "Counter integrity",
            "entity_types": ["Unit"],
            "relationship_types": [],
            "indicators": {
                "Unit": [{
                    "name": "run_hours_total",
                    "type": "NUMERIC",
                    "axioms": ["MONOTONICITY"],
                    "window": WINDOW,
                    "monotonicity": block,
                }],
            },
        }
    }


def _run(series, **mono):
    session = EngineSession()
    session.load_model(_model(**mono))
    session.add_entity("unit/1", "Unit", {"run_hours_total": float(series[-1])})
    session.add_observations("unit/1", "run_hours_total",
                             [float(v) for v in series], interval_seconds=60)
    payload = check(session).to_dict()
    findings = [f for f in payload["findings"]
                if str(f.get("axiom", "")).upper() == "MONOTONICITY"]
    declines = [d for d in payload["not_checked"]
                if str(d.get("axiom", "")).upper() == "MONOTONICITY"]
    return findings, declines


#: One backward move. The canonical violation of a forward-only counter, and
#: the series the outside report named.
ROLLBACK = [10, 11, 12, 13, 9]
#: The control. Same length, same window, same config, no backward move.
CLEAN = [10, 11, 12, 13, 14]
#: Three backward moves — enough for the shipped default.
THREE_REVERSALS = [10, 9, 11, 8, 12, 7]


def _reversal_declines(declines):
    """Every decline EXCEPT the rate arm's.

    An internal ruling made the rate arm decline `no_threshold` when no rate is declared,
    and none of the models in this file declares one -- so every case here now
    carries exactly that decline beside whatever it was written to check.

    The blanket `declines == []` these assertions used to make was always wider
    than their subject: this file is about the reversal arm and the sample
    floor. Narrowed rather than deleted, and narrowed by NAMING the reason
    excluded, so that a second unexpected decline still fails.
    """
    return [d for d in declines if d["reason"] != "no_threshold"]


class TestThePositivePathExists:
    """The half that was never demonstrated."""

    def test_it_fires_on_a_series_that_reverses(self):
        findings, _ = _run(THREE_REVERSALS)
        assert len(findings) == 1, (
            "MONOTONICITY did not fire on a series with three backward moves; "
            "before this file, nothing asserted it could fire at all")

    def test_the_control_stays_clean(self):
        """Without this the test above passes on an axiom that fires on
        everything, which is not the capability anyone wants."""
        findings, declines = _run(CLEAN)
        assert findings == []
        assert _reversal_declines(declines) == []
        assert [d["reason"] for d in declines] == ["no_threshold"], (
            "the clean control should carry the rate arm's decline and nothing "
            "else; this model declares no rate")

    def test_the_finding_is_attributed_to_the_axiom_and_the_property(self):
        """The SHIPPED envelope carries no `evidence` — `check()` strips it, so
        `reversal_count` and the tolerance the count was judged against are not
        on this surface. Asserting them here would pin a field the published
        artifact does not have. What a consumer of the envelope gets is the
        attribution, and that is what this asserts.

        `reason` is deliberately not matched on. COMPATIBILITY.md says finding
        text is for humans and logs and that matching it is unsupported — a
        suite that pinned the sentence would break on a rewording the contract
        explicitly permits."""
        finding, = _run(THREE_REVERSALS)[0]
        assert finding["axiom"] == "MONOTONICITY"
        assert finding["problem_type"].endswith(":run_hours_total")
        assert finding["entity_id"] == "unit/1"
        assert "evidence" not in finding


class TestTheToleranceIsDeclarable:
    def test_one_rollback_is_silent_at_the_default(self):
        """The defect, pinned rather than fixed by moving the default.
        This is the behaviour every model written before 0.1.8 has, and the
        pin is what makes a future change to it deliberate."""
        findings, declines = _run(ROLLBACK)
        assert findings == [] and _reversal_declines(declines) == []

    def test_declaring_a_tolerance_of_one_catches_it(self):
        findings, _ = _run(ROLLBACK, reversal_tolerance=1)
        assert len(findings) == 1
        assert findings[0]["axiom"] == "MONOTONICITY"

    def test_a_declared_tolerance_of_two_still_permits_one(self):
        """Non-vacuity for the declaration: if the field were ignored, the test
        above could pass because the default had simply been lowered."""
        assert _run(ROLLBACK, reversal_tolerance=2)[0] == []

    def test_the_control_stays_clean_at_the_strictest_setting(self):
        assert _run(CLEAN, reversal_tolerance=1)[0] == []

    @pytest.mark.parametrize("bad", [0, -1, "1", 1.5, True])
    def test_an_unusable_tolerance_falls_back_rather_than_coercing(self, bad):
        """`0` reads as *no reversals allowed* and would fire on every clean
        series forever, since the comparison is `count >= tolerance`. A string
        or a float is an author writing something they thought meant a number.
        All of them take the default and warn, which is the loader's own
        convention for a value it cannot use."""
        assert _run(ROLLBACK, reversal_tolerance=bad)[0] == []
        assert _run(THREE_REVERSALS, reversal_tolerance=bad)[0] != []


class TestTheResetArmGotTheSameTreatment:
    """ added the reset-storm arm on the SAME global default, so it
    carried the identical defect one arm over. Fixing only the reversal side
    would have been fixing the instance and leaving the class."""

    #: Two drops to near zero, which `allow_reset` excuses individually.
    TWO_RESETS = [100, 1, 200, 1, 300]

    def test_two_resets_are_silent_at_the_default(self):
        findings, _ = _run(self.TWO_RESETS, allow_reset=True)
        assert [f for f in findings if "reset" in f["problem_type"]] == []

    def test_declaring_a_reset_tolerance_catches_them(self):
        findings, _ = _run(self.TWO_RESETS, allow_reset=True, reset_tolerance=2)
        storms = [f for f in findings if "reset" in f["problem_type"]]
        assert len(storms) == 1

    def test_the_two_tolerances_are_independent(self):
        """One number governing both was the state that hid the reset side.
        Declaring the reversal tolerance must not move the reset one."""
        findings, _ = _run(self.TWO_RESETS, allow_reset=True,
                           reversal_tolerance=1)
        assert [f for f in findings if "reset" in f["problem_type"]] == []


class TestTheSampleFloorIsUnchanged:
    """The decline half was already covered; this pins that an internal ruling did not
    disturb it, because a tolerance change that also moved the floor would be
    two behaviour changes reported as one."""

    def test_below_the_floor_it_declines_rather_than_passing(self):
        findings, declines = _run([10, 9])
        assert findings == []
        assert len(declines) == 1
        assert declines[0]["reason"] == "insufficient_samples"

    def test_at_the_floor_it_evaluates(self):
        _, declines = _run([10, 11, 9])
        assert [d for d in declines
                if d["reason"] == "insufficient_samples"] == [], (
            "three points is the fewest that can exhibit a reversal and is the "
            "declared floor; declining here would re-impose the over-gate")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
