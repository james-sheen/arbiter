"""HOMEOSTASIS against a declared setpoint, and what the learned baseline cannot do.

**No shipped test asserted this axiom FIRING.** Its declines were covered; the
detection half was folklore. Characterizing it found the defect below rather
than confirming the capability — which is the second time that happened in one
review, MONOTONICITY being the first.

THE DEFECT. The baseline is a mean and standard deviation over a
window that CONTAINS the deviation, so a persisting fault walks the mean toward
itself and inflates the spread. The score decays on both terms at once and the
axiom falls silent on a fault that is still running. Measured on 0.1.7 through
this same public surface: a tank 30 points off its baseline fired at 5.4 sigma
after two samples, 2.4 after ten, and nothing at all from about fifteen.

THE RULING was a declared setpoint — see
the internal notes. A number the
operator wrote cannot walk. The rolling baseline stays the default because it is
what the axiom means and because a genuinely drifting quantity must not be
accused forever.

WHY THE ABSORPTION IS PINNED HERE RATHER THAN TREATED AS A BUG TO FIX LATER.
It is a documented property of the default, and a reader of this suite should be
able to see the limit and the remedy in one place. A test asserting only that
the setpoint arm works would leave the reason it exists undiscoverable.
"""

from __future__ import annotations

import math
import sys

import pytest

from arbiter_engine.api import EngineSession, check


BASELINE = [40.0 + math.sin(i / 3) for i in range(60)]


def _model(**homeostasis) -> dict:
    indicator = {
        "name": "level_pct",
        "type": "NUMERIC",
        "axioms": ["HOMEOSTASIS"],
        "window": "1h",
    }
    if homeostasis:
        indicator["homeostasis"] = dict(homeostasis)
    return {
        "domain": {
            "id": "homeostasis-setpoint",
            "name": "Held quantity",
            "entity_types": ["Tank"],
            "relationship_types": [],
            "indicators": {"Tank": [indicator]},
        }
    }


def _run(model, held, value=10.0):
    """A tank at ~40 that moves to `value` and stays there for `held` samples."""
    session = EngineSession()
    session.load_model(model)
    session.add_entity("tank/1", "Tank", {"level_pct": value})
    session.add_observations("tank/1", "level_pct", BASELINE + [value] * held,
                             interval_seconds=60)
    payload = check(session).to_dict()
    return (
        [f for f in payload["findings"] if f.get("axiom") == "HOMEOSTASIS"],
        [d for d in payload["not_checked"] if d.get("axiom") == "HOMEOSTASIS"],
    )


class TestThePositivePathExists:
    """The half that was never demonstrated, on the default path."""

    def test_a_fresh_deviation_fires(self):
        findings, _ = _run(_model(), 2)
        assert len(findings) == 1
        assert findings[0]["severity"] in ("warning", "critical")

    def test_a_quantity_at_its_normal_stays_clean(self):
        """Without this the test above passes on an axiom that fires on
        everything."""
        findings, declines = _run(_model(), 2, value=40.0)
        assert findings == [] and declines == []


class TestTheLearnedBaselineAbsorbsAPersistentDeviation:
    """The limit, pinned so it is visible rather than discovered."""

    def test_the_score_decays_as_the_fault_persists(self):
        assert _run(_model(), 2)[0], "fresh deviation does not fire"
        assert _run(_model(), 10)[0], "ten-sample deviation does not fire"

    def test_and_eventually_says_nothing_at_all(self):
        findings, declines = _run(_model(), 60)
        assert findings == [], (
            "the default no longer absorbs a persistent deviation; if that is "
            "deliberate, 's premise has moved and its ruling needs "
            "re-reading")
        assert declines == [], (
            "absorption now DECLINES rather than going silent — a different "
            "and better defect, and one this pin should be rewritten for")


class TestADeclaredSetpointCannotBeAbsorbed:
    SETPOINT = {"setpoint": 40, "tolerance": 5}

    @pytest.mark.parametrize("held", [2, 16, 60, 240])
    def test_it_holds_at_every_duration(self, held):
        findings, _ = _run(_model(**self.SETPOINT), held)
        assert len(findings) == 1, (
            f"the declared setpoint stopped firing after {held} held samples; "
            f"a reference that decays is not a reference")

    def test_it_is_quiet_at_the_setpoint(self):
        assert _run(_model(**self.SETPOINT), 240, value=40.0)[0] == []

    def test_it_is_quiet_inside_the_tolerance(self):
        """Non-vacuity for the band. An arm that fired on any difference would
        pass every test above."""
        assert _run(_model(**self.SETPOINT), 60, value=43.0)[0] == []

    def test_it_fires_outside_the_tolerance(self):
        findings, _ = _run(_model(**self.SETPOINT), 60, value=47.0)
        assert len(findings) == 1
        assert findings[0]["severity"] == "warning"

    def test_critical_defaults_to_twice_the_tolerance(self):
        findings, _ = _run(_model(**self.SETPOINT), 60, value=55.0)
        assert findings[0]["severity"] == "critical"

    def test_and_the_critical_band_is_declarable(self):
        model = _model(setpoint=40, tolerance=5, tolerance_critical=20)
        findings, _ = _run(model, 60, value=55.0)
        assert findings[0]["severity"] == "warning", (
            "tolerance_critical was ignored; the default is a default, not a "
            "rule")

    def test_it_needs_no_history_at_all(self):
        """The side effect worth the ruling on its own: the statistical path
        needs 30 samples across a 7-day window, so anything sampled less often
        than every 5.6 hours could never reach it. A model that knows its own
        target no longer waits for a baseline it could have declared."""
        session = EngineSession()
        session.load_model(_model(**self.SETPOINT))
        session.add_entity("tank/1", "Tank", {"level_pct": 99.0})
        payload = check(session).to_dict()
        findings = [f for f in payload["findings"]
                    if f.get("axiom") == "HOMEOSTASIS"]
        assert len(findings) == 1, (
            "a declared setpoint still waits for history it does not need")


class TestASetpointWithoutATolerance:
    def test_falls_back_rather_than_inventing_a_band(self):
        """The engine has no basis for guessing how far is too far. Guessing
        would be it deciding a domain question, which is the class and each removed from a different axiom."""
        findings, _ = _run(_model(setpoint=40), 60)
        assert findings == [], "a band was invented for an undeclared tolerance"

    def test_and_the_fallback_is_the_learned_baseline_not_silence(self):
        """It must fall back to the statistical path, not disable the axiom."""
        assert _run(_model(setpoint=40), 2)[0], (
            "declaring a setpoint without a tolerance turned the axiom off "
            "entirely rather than falling back")


class TestUndeclaredMeansUnchanged:
    """The compatibility claim the patch release rests on. A fix that changed
    the default would pass every test about the reported case and be a
    different engine for everybody else."""

    @pytest.mark.parametrize("held,value,fires", [
        (2, 10.0, True), (60, 10.0, False), (2, 40.0, False),
    ])
    def test_the_default_path_behaves_exactly_as_before(self, held, value, fires):
        findings, _ = _run(_model(), held, value=value)
        assert bool(findings) is fires


class TestZeroSpreadDeclines:
    def test_a_motionless_baseline_is_not_a_clean_pass(self):
        """Fixed in passing while implementing a bare return that
        the envelope reported as clean. Third instance of that shape."""
        session = EngineSession()
        session.load_model(_model())
        session.add_entity("tank/1", "Tank", {"level_pct": 40.0})
        session.add_observations("tank/1", "level_pct", [40.0] * 60,
                                 interval_seconds=60)
        payload = check(session).to_dict()
        declines = [d for d in payload["not_checked"]
                    if d.get("axiom") == "HOMEOSTASIS"]
        assert len(declines) == 1
        assert declines[0]["reason"] == "not_applicable"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
