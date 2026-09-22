"""The live fire counter counts live fires.

`reasoner._record_fires` counts every finding at the dispatch
boundary into `fire_frequency.get_shared_tracker()`, a process-wide
singleton. A rollout evaluates the same eight axioms over an IMAGINED state,
through the same dispatcher, so every breach the simulator invented landed in
the same buckets as the ones somebody actually has.

Measured on the shipped example at a tank level of 92 %:

    one `check` -> +2 fires
    one `plan` (5 rollouts x 60 steps) -> +600 fires
                    (BOUNDEDNESS: 301, HOMEOSTASIS: 301)

and the second of those trips the tracker's own high-fire-rate WARN cadence
on stderr. Nothing in this package reads the counts back today, so no verdict
moved -- which is exactly why it could sit there. It stops being harmless the
day something does, and the rollout's own rule, stated at the top of its
module, is that the imagined world never writes into the live one.

WHY A CONTEXT RATHER THAN A FLAG IN THE REASONER. The dispatcher lives in
`ontology/`, is shared by every domain and every verb, and has no business
knowing that one caller is simulating -- the same reason it counts at the
boundary instead of inside eight checkers. The rollout already owns the line
between imagined and real: it clones the history, it prefixes the findings.
Owning the counter for the duration of its own evaluation is the same line,
drawn in the same place.
"""
from __future__ import annotations

import pathlib

import pytest

from arbiter_engine import api, fire_frequency
from arbiter_engine.twin.actions import ActionInstance


def _examples_dir() -> pathlib.Path:
    """Whichever copy this tree has; never an absolute path -- one names a
    directory that exists only where this file was written, and this file ships."""
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / "examples",
                      here.parents[2] / "docs" / "publication"
                      / "engine-example"):
        if candidate.is_dir() and list(candidate.glob("*.yaml")):
            return candidate
    raise AssertionError("no examples directory found in this tree")


EXAMPLE = str(_examples_dir() / "pump_tank_dynamics.yaml")


@pytest.fixture(autouse=True)
def _fresh_tracker():
    """The tracker is process-wide, so a test that counts it has to own it."""
    fire_frequency.reset_shared_tracker()
    yield
    fire_frequency.reset_shared_tracker()


def _count() -> int:
    return fire_frequency.get_shared_tracker().count()


def _session(level=92.0):
    session = api.EngineSession()
    session.load_model(EXAMPLE)
    session.add_entity("pump1", "Pump", {"speed_rpm": 1000.0})
    session.add_entity("tank1", "Tank", {"level_pct": level})
    session.add_relationship("pump1", "feeds", "tank1")
    return session


class TestALiveCheckStillCounts:
    """The floor. A guard that silenced the real ones would be worse than
    the defect it closes."""

    def test_a_breach_somebody_actually_has_is_counted(self):
        before = _count()
        result = api.check(_session()).to_dict()
        assert result["findings"], "the premise: 92 % breaches a declared line"
        assert _count() > before


class TestAnImaginedBreachIsNot:

    def test_a_rollout_adds_nothing(self):
        api.check(_session())          # one live check, so the tracker is warm
        before = _count()
        simulation = api.rollout(
            _session(), actions=[ActionInstance(
                "throttle_pump", "pump1", {"speed_rpm": 800.0}, 0.0)],
            horizon_s=1800.0, step_s=300.0).to_dict()["simulation"]
        assert any(step["findings"] for step in simulation["per_step"]), (
            "the premise: this rollout imagines breaches")
        assert _count() == before

    def test_a_plan_adds_nothing(self):
        before = _count()
        plan = api.plan(_session(), horizon_s=1800.0,
                        step_s=300.0).to_dict()["plan"]
        assert plan["candidates"], "the premise: this plan rolls something"
        assert _count() == before

    def test_and_a_live_check_after_one_still_counts(self):
        """The context is restored. A rollout that left the simulator's
        tracker installed would silence every later live check in the
        process, which is the same defect pointing the other way."""
        api.plan(_session(), horizon_s=1800.0, step_s=300.0)
        before = _count()
        api.check(_session())
        assert _count() > before
