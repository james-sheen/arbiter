"""A declared floor is judged wherever a declared ceiling is judged.

`lower_warning:` / `lower_critical:` are schema, not decoration: an internal ruling rules
that a floor is a SPECIFICATION -- declared only when a datasheet, a contract
or a physical limit gave you the number. `water_tank.yaml` declares both on the
pump's `speed_rpm`, with a comment explaining that a pump has a band because it
must neither run away nor stall.

`UnifiedAxiomReasoner` read the floor. The traversal kernel did not. One
declaration therefore had two answers depending on which verb a caller reached
for, and the quiet one was the traversal: `check` on a stalled pump reported
`below_critical_threshold`, `traverse` on the same entity reported nothing --
while its `checked.invariants` said two invariants had been evaluated.

THE DENOMINATOR IS WHY THIS IS NOT MERELY A GAP. A caller looking for the
blind spot would consult exactly that count, and the count asserted the check
had happened. That is the failure mode the engine's own denominators exist to
prevent, pointing inward.

The floors were dropped in TWO places and this file pins both: the builder did
not READ them off the indicator, so they never reached `AxiomState.evidence`,
and the traverser did not COMPARE against them. Fixing either alone leaves the
traversal silent, so each half gets a test that fails without it.
"""
from __future__ import annotations

import pathlib

import pytest

from arbiter_engine import api

def _examples_dir() -> pathlib.Path:
    """Whichever copy this tree has: the built package ships `examples/` at its
    root, the source tree keeps them under the publication docs.

    - this was a hard-coded path into a directory that does not exist
    in the published package, so the shipped copy of this test could only ever
    fail at import on a reader's machine. It was written where it happened to
    resolve and nothing between there and the wheel disagreed.

    The resolver here is the one `test_every_shipped_example_actually_runs.py`
    already uses; copying its shape rather than inventing a second one is the
    point, since two resolvers for one fact are what drift.
    """
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / "examples",
                      here.parents[2] / "docs" / "publication"
                      / "engine-example"):
        if candidate.is_dir() and list(candidate.glob("*.yaml")):
            return candidate
    raise AssertionError("no examples directory found in this tree")


WATER_TANK = _examples_dir() / "water_tank.yaml"

STALL_FLOOR = 900.0      # lower_critical on Pump.speed_rpm
WARN_FLOOR = 1200.0      # lower_warning on Pump.speed_rpm
CEILING = 3200.0         # critical on Pump.speed_rpm


def _session(speed_rpm: float) -> api.EngineSession:
    session = api.EngineSession()
    session.load_model(str(WATER_TANK))
    session.add_entity("pump1", "Pump",
                       {"speed_rpm": speed_rpm, "run_hours_total": 10.0})
    session.add_entity("tank1", "Tank",
                       {"level_pct": 50.0, "inflow_lps": 5.0,
                        "outflow_lps": 5.0})
    session.add_relationship("pump1", "feeds", "tank1")
    return session


def _types(envelope) -> list:
    return [f.get("problem_type") for f in envelope.to_dict().get("findings", [])]


def _severities(envelope) -> list:
    return [f.get("severity") for f in envelope.to_dict().get("findings", [])]


class TestTheFloorIsDeclaredInTheShippedExample:
    """If this fixture stops declaring a floor the rest of the file is vacuous."""

    def test_the_pump_declares_both_a_floor_and_a_ceiling(self):
        text = WATER_TANK.read_text()
        assert "lower_critical: 900" in text
        assert "lower_warning: 1200" in text
        assert "critical: 3200" in text


class TestTraversalJudgesTheFloor:

    def test_a_stalled_pump_is_a_finding_on_the_traversal_path(self):
        envelope = api.traverse(_session(0.0), ["pump1"], value_mode="current")
        assert any("speed_rpm" in t for t in _types(envelope)), (
            "a reading below `lower_critical` produced no traversal finding; "
            "the floor half of BOUNDEDNESS is unreachable again")
        assert "critical" in _severities(envelope)

    def test_the_warning_floor_fires_at_warning_severity(self):
        envelope = api.traverse(_session(1000.0), ["pump1"],
                                value_mode="current")
        assert _severities(envelope) == ["warning"], (
            "1000 rpm sits between lower_warning=1200 and lower_critical=900, "
            "so exactly one WARNING is the right answer")

    def test_a_reading_inside_the_band_is_silent(self):
        envelope = api.traverse(_session(2000.0), ["pump1"],
                                value_mode="current")
        assert _types(envelope) == [], (
            "2000 rpm is inside the declared band; a finding here would mean "
            "the floor comparison is inverted")

    def test_the_ceiling_still_fires(self):
        envelope = api.traverse(_session(3500.0), ["pump1"],
                                value_mode="current")
        assert _severities(envelope) == ["critical"]


class TestTheTwoVerbsAgree:
    """The defect was disagreement, so the pin is on agreement, not on a type."""

    @pytest.mark.parametrize("speed,expect_finding", [
        (0.0, True),        # below the stall floor
        (1000.0, True),     # below the warning floor
        (2000.0, False),    # inside the band
        (3500.0, True),     # above the ceiling
    ])
    def test_check_and_traverse_agree_on_whether_the_pump_is_in_band(
            self, speed, expect_finding):
        checked = [t for t in _types(api.check(_session(speed)))
                   if "speed_rpm" in t]
        walked = [t for t in _types(
            api.traverse(_session(speed), ["pump1"], value_mode="current"))
            if "speed_rpm" in t]
        assert bool(checked) is expect_finding
        assert bool(walked) is expect_finding, (
            f"at {speed} rpm `check` says {checked} and `traverse` says "
            f"{walked}; one declaration must not have two answers")


class TestTheFloorSurvivesToTheEvidence:
    """The builder half. A traverser fix alone leaves nothing to compare to."""

    def test_the_builder_carries_declared_floors_onto_the_node(self):
        session = _session(2000.0)
        topology = api._build_topology(session)
        node = topology.get_node("pump1")
        state = node.axiom_states.get("BOUNDEDNESS:speed_rpm")
        assert state is not None, "the pump declares BOUNDEDNESS on speed_rpm"
        assert state.evidence.get("lower_critical") == STALL_FLOOR, (
            "the declared floor never reached AxiomState.evidence, so the "
            "traverser had nothing to compare against")
        assert state.evidence.get("lower_warning") == WARN_FLOOR
        assert state.evidence.get("critical") == CEILING

    def test_an_undeclared_bound_is_absent_rather_than_none(self):
        """Absent, not a None sitting where a number belongs.

        The tank declares a ceiling and no floor deliberately -- an empty
        supply tank is a fact about the process. A `None` under the key would
        read as a declaration whose value went missing.
        """
        session = _session(2000.0)
        topology = api._build_topology(session)
        state = topology.get_node("tank1").axiom_states.get(
            "BOUNDEDNESS:level_pct")
        assert state is not None
        assert "critical" in state.evidence
        assert "lower_critical" not in state.evidence
        assert "lower_warning" not in state.evidence


class TestTheHypotheticalPathJudgesTheFloorToo:
    """The reason this blocks a world model: imagined states are judged here.

    A what-if that drives a property through a declared floor is exactly the
    question a simulation is asked, and it was the silent case.
    """

    def test_a_what_if_that_stalls_the_pump_reports_it(self):
        envelope = api.traverse(
            _session(2000.0), ["pump1"], value_mode="hypothetical",
            overrides={"pump1": {"speed_rpm": 0.0}})
        assert any("speed_rpm" in t for t in _types(envelope)), (
            "the override drove the pump below its stall floor and the "
            "traversal said nothing")
