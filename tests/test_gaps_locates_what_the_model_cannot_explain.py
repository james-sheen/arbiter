"""`gaps` locates where what was observed is not explained by the model.

`gaps` reported what the MODEL lacks, read off the declaration alone:
thresholds nobody set, properties nobody reads, couplings with no transition.
Nothing read the other way, from what was observed back to where the
declaration fails to explain it, although three things already say so:

- a CONNECTIVITY finding says a required relation is missing, or that one
  points at an entity nobody declared;
- a CONSERVATION finding says a declared balance does not close, and by how much;
- a pair `file_action` filed says, once graded, whether the world followed the
  action, followed no action, or followed neither.

`residuals` locates each one as a hypothesis carrying the reading that would
confirm or dissolve it, and proposes nothing into the graph. How many
executions make a pattern is the model's to declare, as `gaps: {min_cycles:
N}`; an arm the model declares nothing for is refused by name.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml

from arbiter_engine import api
from arbiter_engine.ontology.domain_loader import load_domain
from arbiter_engine.subenvelope import VOCABULARIES


def _examples() -> Path:
    """The shipped examples, in whichever tree this file runs in."""
    here = Path(__file__).resolve()
    for candidate in (here.parents[1] / "examples", here.parents[2] / "examples",
                      here.parents[2] / "docs" / "publication" / "engine-example"):
        if (candidate / "pump_tank_planning.yaml").is_file():
            return candidate
    raise AssertionError("no examples directory in this tree carries them")


EXAMPLES = _examples()


def _units(outputs=("outflow", "overflow")):
    """Units that must feed a sink and must balance what flows through them."""
    return {"domain": {
        "id": "residuals", "name": "residuals",
        "entity_types": ["Unit", "Sink"], "relationship_types": ["feeds"],
        "indicators": {
            "Unit": [
                {"name": "inflow", "type": "NUMERIC", "axioms": ["CONSERVATION"],
                 "conservation": {"input_property": "inflow",
                                  "output_properties": list(outputs)}},
                {"name": "outflow", "type": "NUMERIC", "axioms": []},
                {"name": "overflow", "type": "NUMERIC", "axioms": []},
                {"name": "feeds_a_sink", "type": "RELATIONSHIP",
                 "axioms": ["CONNECTIVITY"], "target_type": "Sink",
                 "relation_type": "feeds", "min_cardinality": 1},
            ],
            "Sink": [{"name": "level", "type": "NUMERIC",
                      "axioms": ["BOUNDEDNESS"], "critical": 100}],
        },
        "relationship_rules": [
            {"type": "feeds", "source_type": "Unit", "target_type": "Sink"}],
    }}


def _plant(units=None, *, checked=True, outputs=("outflow", "overflow")):
    """`units` maps an id to (readings, sinks it feeds)."""
    units = units if units is not None else {
        "u-1": ({"inflow": 50.0, "outflow": 10.0}, ()),
        "u-2": ({"inflow": 50.0, "outflow": 50.0}, ("k-1", "k-ghost")),
    }
    session = api.EngineSession()
    session.load_model(_units(outputs))
    session.add_entity("k-1", "Sink", {"level": 1.0})
    for unit, (readings, sinks) in units.items():
        session.add_entity(unit, "Unit", dict(readings))
        for sink in sinks:
            session.add_relationship(unit, "feeds", sink)
        for prop, value in readings.items():
            session.add_observations(unit, prop, [value] * 40, interval_seconds=10)
    if checked:
        api.check(session)
    return session


def _residuals(session):
    return api.gaps(session).to_dict()["residuals"]


def _located(session, kind=None):
    return [h for h in _residuals(session)["hypotheses"]
            if kind is None or h["kind"] == kind]


def _declined(residuals):
    return {(d["reason"], d["location"]) for d in residuals["not_checked"]}


class TestPresence:

    def test_a_missing_relation_is_located_at_the_entity_that_lacks_it(self):
        rows = [h for h in _located(_plant(), "absent_or_detached") if h["at"] == "u-1"]
        assert rows == [{
            "kind": "absent_or_detached", "at": "u-1", "basis": "CONNECTIVITY",
            "declared_by": "feeds_a_sink", "relation": "feeds",
            "expected_min": 1, "actual": 0, "evidence_needed": "u-1.feeds"}]

    def test_a_reference_to_an_undeclared_entity_is_located_at_that_entity(self):
        rows = [h for h in _located(_plant(), "absent_or_detached")
                if h.get("referenced_by")]
        assert rows == [{
            "kind": "absent_or_detached", "at": "k-ghost", "basis": "CONNECTIVITY",
            "declared_by": "feeds_a_sink", "relation": "feeds",
            "referenced_by": "u-2", "evidence_needed": "u-2.feeds"}]

    def test_a_connected_plant_locates_nothing(self):
        session = _plant({"u-1": ({"inflow": 50.0, "outflow": 50.0}, ("k-1",))})
        assert _located(session, "absent_or_detached") == []


class TestConservation:

    def test_an_imbalance_is_located_between_the_declared_properties(self):
        session = _plant()
        finding = next(p for p in session._last_result.problems
                       if p.problem_type == "conservation_violation:inflow")
        [row] = _located(session, "unaccounted_flow")
        assert row["at"] == "u-1" and row["declared_by"] == "inflow"
        assert row["between"] == ["inflow", "outflow", "overflow"]
        assert row["magnitude"] == finding.evidence["deficit"]
        assert row["ratio"] == pytest.approx(0.8)

    def test_the_reading_needed_is_the_declared_output_nobody_read(self):
        [row] = _located(_plant(), "unaccounted_flow")
        assert row["evidence_needed"] == "u-1.overflow"
        assert "reason" not in row

    def test_with_every_output_read_it_names_no_reading_and_says_why(self):
        [row] = _located(_plant(outputs=("outflow",)), "unaccounted_flow")
        assert row["evidence_needed"] is None
        assert "a path nobody declared" in row["reason"]

    def test_a_balanced_unit_locates_nothing(self):
        session = _plant({"u-1": ({"inflow": 50.0, "outflow": 50.0}, ("k-1",))},
                         outputs=("outflow",))
        assert _located(session, "unaccounted_flow") == []


# -- dynamics: the shipped pump example, its action executed and graded -----

AT = datetime(2026, 9, 28, 6, 0)
THROTTLE = {"template": "throttle_pump", "entity_id": "pump1",
            "parameters": {"speed_rpm": 1500}}
HORIZON, STEP = 1800.0, 300.0


def _pump_model(cycles=2, extra_rule=None):
    model = yaml.safe_load((EXAMPLES / "pump_tank_planning.yaml").read_text())
    if cycles is not None:
        model["domain"]["gaps"] = {"min_cycles": cycles}
    if extra_rule is not None:
        model["domain"]["relationship_rules"].append(extra_rule)
        model["domain"]["relationship_types"] = sorted(
            set(model["domain"].get("relationship_types") or ())
            | {extra_rule["type"]})
    return model


def _executed(world, *, executions=2, cycles=2, extra_rule=None):
    """Execute the throttle `executions` times, three hours apart, and feed
    readings that follow `world`: the action arm, the no-action arm, or
    neither (the no-action arm moved well away from both)."""
    session = api.EngineSession()
    session.load_model(_pump_model(cycles, extra_rule))
    session.add_entity("pump1", "Pump", {"speed_rpm": 3000.0})
    session.add_entity("tank1", "Tank", {"level_pct": 50.0})
    session.add_entity("valve1", "Valve", {"open_pct": 0.0})
    session.add_relationship("pump1", "feeds", "tank1")
    session.add_relationship("valve1", "drains", "tank1")
    if extra_rule is not None:
        session.add_relationship("valve1", extra_rule["type"], "tank1")
    for k in range(executions):
        at = AT + timedelta(hours=3 * k)
        with api.as_of(at):
            api.file_action(session, THROTTLE, at, "operator log",
                            horizon_s=HORIZON, step_s=STEP)
        arm = "action" if world == "action" else "no_action"
        offset = 40.0 if world == "neither" else 0.0
        followed = {r.horizon_s: r.value for r in session.ledger.records()
                    if r.execution and r.execution["executed_at"] == at.isoformat()
                    and r.execution["arm"] == arm and r.indicator == "level_pct"}
        with api.as_of(at + timedelta(seconds=HORIZON + session.ledger.grace_s + 1)):
            session.add_observations("tank1", "level_pct", [
                (at + timedelta(seconds=h), v + offset)
                for h, v in sorted(followed.items())])
            api.check(session)
    return session


def _dynamics(session):
    with api.as_of(AT + timedelta(days=1)):
        residuals = _residuals(session)
    return residuals, [h for h in residuals["hypotheses"]
                       if h["basis"] == "file_action pairs"]


class TestDynamics:

    def test_a_world_that_followed_no_action_is_an_effect_not_observed(self):
        residuals, rows = _dynamics(_executed("no_action"))
        assert rows == [{
            "kind": "effect_not_observed", "on": "tank1.level_pct",
            "basis": "file_action pairs", "executions": 2,
            "action": "throttle_pump@pump1",
            # What the action was declared to write: reading it says whether
            # the action took hold at all.
            "evidence_needed": "pump1.speed_rpm"}]
        assert residuals["checked"]["pairs_read"] > 0

    def test_a_world_that_followed_neither_is_an_unexplained_change(self):
        _, rows = _dynamics(_executed("neither"))
        [row] = rows
        assert row["kind"] == "unexplained_change" and row["on"] == "tank1.level_pct"
        # Both relations into a tank already drive its level, so there is no
        # undeclared channel to name, and it says so rather than guessing one.
        assert row["candidates"] == [] and row["evidence_needed"] is None
        assert "a relation nobody declared" in row["reason"]

    def test_an_undeclared_channel_is_named_with_a_reading_to_take(self):
        vents = {"type": "vents", "source_type": "Valve", "target_type": "Tank"}
        _, rows = _dynamics(_executed("neither", extra_rule=vents))
        [row] = rows
        assert row["candidates"] == ["vents"]
        assert row["evidence_needed"] == "valve1.open_pct"

    def test_a_world_that_followed_the_action_locates_nothing(self):
        """The negative control: a falsified arm is not a gap when the arm
        that was taken is the one the world followed."""
        residuals, rows = _dynamics(_executed("action"))
        assert rows == []
        assert not {r for r, _ in _declined(residuals)} & {"insufficient_samples"}

    def test_fewer_executions_than_declared_is_insufficient_samples(self):
        residuals, rows = _dynamics(_executed("no_action", cycles=3))
        assert rows == []
        [row] = [d for d in residuals["not_checked"]
                 if d["reason"] == "insufficient_samples"]
        assert row["evidence"] == {"graded_executions": 2, "min_cycles": 3}

    def test_one_execution_short_of_the_pattern_is_not_one(self):
        _, rows = _dynamics(_executed("no_action", executions=1, cycles=1))
        assert [row["executions"] for row in rows] == [1]
        _, rows = _dynamics(_executed("no_action", executions=1, cycles=2))
        assert rows == []

    def test_without_a_declared_number_no_number_is_chosen(self):
        residuals, rows = _dynamics(_executed("no_action", cycles=None))
        assert rows == [], "a pattern was called on a count nobody declared"
        assert ("missing_config", "gaps.min_cycles") in _declined(residuals)


class TestTheArmsRefuseByName:

    def test_before_any_check_the_finding_arms_are_precondition_unmet(self):
        declined = _declined(_residuals(_plant(checked=False)))
        assert {("precondition_unmet", "presence"),
                ("precondition_unmet", "conservation")} <= declined

    def test_an_arm_the_model_declares_nothing_for_is_missing_config(self):
        session = api.EngineSession()
        session.load_model({"domain": {
            "id": "bare", "name": "bare", "entity_types": ["Unit"],
            "indicators": {"Unit": [{"name": "load", "type": "NUMERIC",
                                     "axioms": ["BOUNDEDNESS"], "critical": 95}]}}})
        session.add_entity("u-1", "Unit", {"load": 99.0})
        api.check(session)
        residuals = _residuals(session)
        assert residuals["hypotheses"] == []
        assert _declined(residuals) == {("missing_config", "presence"),
                                        ("missing_config", "conservation"),
                                        ("missing_config", "dynamics")}

    def test_every_reason_is_a_discovery_name(self):
        for session in (_plant(checked=False), _plant(),
                        _executed("no_action", cycles=None)):
            reasons = {d["reason"] for d in _residuals(session)["not_checked"]}
            assert reasons <= VOCABULARIES["discovery"], reasons

    def test_a_raise_inside_is_an_internal_error_not_a_crash(self, monkeypatch):
        def boom(session):
            raise RuntimeError("synthetic")
        monkeypatch.setattr(api, "_located_residuals", boom)
        residuals = _residuals(_plant())
        assert residuals["meta"]["source"] == "unavailable"
        assert residuals["hypotheses"] == []


class TestItProposesNothing:

    def test_the_graph_and_the_models_own_report_are_as_they_were(self):
        session = _plant()
        before_entities = {k: dict(e.properties) for k, e in session.entities.items()}
        before_edges = {k: list(v) for k, v in session.graph.edges.items()}
        report = {k: v for k, v in api.gaps(session).to_dict().items()
                  if k != "residuals"}
        again = {k: v for k, v in api.gaps(session).to_dict().items()
                 if k != "residuals"}
        assert again == report
        assert {k: dict(e.properties) for k, e in session.entities.items()} == before_entities
        assert {k: list(v) for k, v in session.graph.edges.items()} == before_edges


class TestMinCyclesIsRead:

    def _unread(self, block):
        model = _pump_model(cycles=None)
        model["domain"]["gaps"] = block
        return [r for r in load_domain(yaml.safe_dump(model)).unread_fields()
                if r["field"].startswith("gaps")]

    @pytest.mark.parametrize("written", [0, True, "3", 2.5, None])
    def test_a_value_that_is_not_a_whole_number_of_at_least_one_is_refused(
            self, written):
        rows = self._unread({"min_cycles": written})
        assert rows and rows[0]["reason"] == "malformed_value", rows

    def test_a_misspelt_key_is_named(self):
        rows = self._unread({"min_cyles": 2})
        assert [r["reason"] for r in rows] == ["unknown_key"]

    def test_a_whole_number_is_read(self):
        assert self._unread({"min_cycles": 2}) == []
