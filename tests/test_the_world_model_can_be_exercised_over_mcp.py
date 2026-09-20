"""The whole world model, driven through `dispatch` and nothing else.

`TOOL_SPECS` is hand-maintained against `api`, and two of the verbs
the world model needs fell through the gap between them:

  - no tool reached `EngineSession.add_relationship`, which is the ONLY path
    by which a session acquires an edge. Without an edge there is no
    instantiated coupling, so `rollout` and `plan` run over a graph with
    nothing in it;
  - `rollout`'s `inputSchema` exposed `actions, horizon_s, max_transitions,
    seed_mode, step_s` and not `file_predictions`, so the closed loop --
    file, mirror, grade -- could not be started over this transport at all.

Measured over `dispatch` on the shipped example before this file, with the
model loaded and both entities added because that is as far as the transport
went:

    rollout(throttle to 1500) -> transitions_applied 0, tank flat at its
                                 baseline, not_checked [], assumptions
                                 ['exogenous_inputs_held']
    plan -> ranked true, every candidate scoring the
                                 same, do_nothing first by tie-break

which is the 0.2.3 shape the changelog describes -- *the planner recommended
inaction because the dynamics had never run* -- reached this time through a
missing tool rather than a frozen transient.

WHY THIS TEST AND NOT ANOTHER WRAPPER CHECK. There is already a test that
every declared tool has a handler. It passed throughout: nothing was declared
without a handler, the verbs were simply never declared. The thing that
catches an ABSENCE is a test that has to get a job done -- load, entities,
edge, rollout, check, describe -- and can only use what the transport
offers.
"""
from __future__ import annotations

import pathlib
from datetime import datetime, timedelta

import numpy as np
import pytest

from arbiter_engine.mcp import server
from arbiter_engine.api import EngineSession
from arbiter_engine.clock import as_of

#: Held, so which readings fall inside the projector's lookback is a fact
#: about this test rather than about the minute it ran in.
T0 = datetime(2026, 9, 10, 12, 0, 0)


def _examples_dir() -> pathlib.Path:
    """Whichever copy this tree has; never an absolute path into the private
    tree, which the build refuses and rightly -- this file ships."""
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / "examples",
                      here.parents[2] / "docs" / "publication"
                      / "engine-example"):
        if candidate.is_dir() and list(candidate.glob("*.yaml")):
            return candidate
    raise AssertionError("no examples directory found in this tree")


EXAMPLE = str(_examples_dir() / "pump_tank_dynamics.yaml")


def _spec(name):
    for spec in server.TOOL_SPECS:
        if spec["name"] == name:
            return spec
    raise AssertionError(
        f"{name} is not declared; declared are "
        f"{sorted(s['name'] for s in server.TOOL_SPECS)}")


class TestTheTransportDeclaresWhatTheWorldModelNeeds:

    def test_an_edge_can_be_instantiated(self):
        assert _spec("add_relationship")

    def test_a_rollout_can_be_asked_to_file(self):
        assert "file_predictions" in _spec("rollout")["inputSchema"][
            "properties"]


class TestTheLoopClosesOverDispatchAlone:
    """Every call below goes through `dispatch`. Nothing touches the session
    directly, because a client cannot."""

    @pytest.fixture
    def session(self):
        return EngineSession()

    def test_load_entities_edge_rollout_check_describe(self, session):
        server.dispatch(session, "load_model", {"path": EXAMPLE})
        server.dispatch(session, "add_entity", {
            "entity_id": "pump1", "entity_type": "Pump",
            "properties": {"speed_rpm": 1000.0}})
        server.dispatch(session, "add_entity", {
            "entity_id": "tank1", "entity_type": "Tank",
            "properties": {"level_pct": 50.0}})
        server.dispatch(session, "add_relationship", {
            "source_id": "pump1", "relation_type": "feeds",
            "target_id": "tank1"})

        rolled = server.dispatch(session, "rollout", {
            "actions": [{"template": "throttle_pump", "entity_id": "pump1",
                         "parameters": {"speed_rpm": 1500.0}, "at_s": 0.0}],
            "horizon_s": 3600.0, "step_s": 300.0})
        simulation = rolled["simulation"]
        assert simulation["checked"]["transitions_applied"] > 0, (
            "the declared coupling never ran: the transport could not "
            "instantiate the edge it needs")
        last = simulation["per_step"][-1]["values"]["tank1"]["level_pct"]
        assert last != pytest.approx(50.0), (
            f"the tank sat at its baseline {last} while the pump was "
            f"throttled by 500 rpm through a declared gain")

    def test_a_rollout_can_file_and_the_ledger_receives_it(self, session):
        """The closed loop is the headline of this surface and it was
        unreachable here.

        THE CLOCK IS HELD AND THE READINGS CARRY THEIR OWN TIMESTAMPS. Bare
        readings are laid down as a ladder ending at *now*, so which of them
        fall inside the projector's lookback depends on the wall clock: the
        first version of this test passed and failed on alternate runs, the
        projector declining `model_inconsistent` on the runs where the window
        cut the series somewhere it could not separate the two variances.
        A test that is sometimes green is not evidence about the transport.
        """
        server.dispatch(session, "load_model", {"path": EXAMPLE})
        server.dispatch(session, "add_entity", {
            "entity_id": "pump1", "entity_type": "Pump",
            "properties": {"speed_rpm": 1000.0}})
        server.dispatch(session, "add_entity", {
            "entity_id": "tank1", "entity_type": "Tank",
            "properties": {"level_pct": 50.0}})
        server.dispatch(session, "add_relationship", {
            "source_id": "pump1", "relation_type": "feeds",
            "target_id": "tank1"})
        # A WANDER, not a ramp: `local_level` separates the level's own
        # variance from measurement noise, and a straight line gives it
        # nothing to separate. Seeded, so the series is the same every run.
        rng = np.random.default_rng(17)
        series = 1000.0 + np.cumsum(rng.normal(0, 8, 200))
        with as_of(T0):
            for index, value in enumerate(series):
                server.dispatch(session, "add_observations", {
                    "entity_id": "pump1", "property_name": "speed_rpm",
                    # A POSIX number, which is what JSON can carry: the
                    # session takes a pair whose head is a datetime or a
                    # timestamp, and an ISO string is neither -- deliberately,
                    # so that a two-character reading cannot unpack as a pair.
                    "values": [[
                        (T0 - timedelta(
                            seconds=(len(series) - 1 - index) * 60)
                         ).timestamp(), float(value)]]})
            rolled = server.dispatch(session, "rollout", {
                "horizon_s": 1800.0, "step_s": 300.0,
                "seed_mode": "projected", "file_predictions": True})
        assert rolled["simulation"]["checked"]["predictions_filed"] > 0, (
            f"nothing was filed, so `check` has nothing to grade and the "
            f"loop this surface exists to close does not close; the rollout "
            f"declined "
            f"{sorted(d['reason'] for d in rolled['simulation']['not_checked'])}")


class TestADeclaredCouplingWithNoInstanceIsReported:
    """The engine half of the same absence. Every simulation verb ran happily
    over a graph with declared rules and zero instances -- for an engine whose
    one-line description is *it reports what it did not check*, a coupling
    with nowhere to run is a reportable absence."""

    @pytest.fixture
    def without_an_edge(self):
        session = EngineSession()
        server.dispatch(session, "load_model", {"path": EXAMPLE})
        server.dispatch(session, "add_entity", {
            "entity_id": "pump1", "entity_type": "Pump",
            "properties": {"speed_rpm": 1000.0}})
        server.dispatch(session, "add_entity", {
            "entity_id": "tank1", "entity_type": "Tank",
            "properties": {"level_pct": 92.0}})
        return session

    def test_a_rollout_says_the_coupling_had_nowhere_to_run(
            self, without_an_edge):
        rolled = server.dispatch(without_an_edge, "rollout", {
            "actions": [{"template": "throttle_pump", "entity_id": "pump1",
                         "parameters": {"speed_rpm": 1500.0}, "at_s": 0.0}],
            "horizon_s": 3600.0, "step_s": 300.0})
        reasons = {d["reason"] for d in rolled["simulation"]["not_checked"]}
        assert "coupling_uninstantiated" in reasons, (
            f"the model declares Pump-feeds->Tank, the session holds a Pump "
            f"and a Tank, and no `feeds` edge joins them; the rollout "
            f"declined {sorted(reasons)}")

    def test_and_says_how_many_of_them_there_were(self, without_an_edge):
        rolled = server.dispatch(without_an_edge, "rollout", {
            "horizon_s": 3600.0, "step_s": 300.0})
        checked = rolled["simulation"]["checked"]
        assert checked.get("couplings_instantiated") == 0
        assert checked.get("couplings_declared") == 1

    def test_a_plan_says_it_too(self, without_an_edge):
        planned = server.dispatch(without_an_edge, "plan", {
            "horizon_s": 3600.0, "step_s": 300.0})
        reasons = {d["reason"] for d in planned["plan"]["not_checked"]}
        assert "coupling_uninstantiated" in reasons, (
            f"every candidate was ranked over a topology in which no declared "
            f"coupling could run; declined {sorted(reasons)}")


class TestAnInstantiatedCouplingSaysNothingOfTheKind:
    """The floor. A decline that fired whenever a coupling existed would be
    noise, and noise in a decline vocabulary is how a closed enum stops being
    evidence about anything."""

    def test_the_ordinary_case_is_silent(self):
        session = EngineSession()
        server.dispatch(session, "load_model", {"path": EXAMPLE})
        server.dispatch(session, "add_entity", {
            "entity_id": "pump1", "entity_type": "Pump",
            "properties": {"speed_rpm": 1000.0}})
        server.dispatch(session, "add_entity", {
            "entity_id": "tank1", "entity_type": "Tank",
            "properties": {"level_pct": 50.0}})
        server.dispatch(session, "add_relationship", {
            "source_id": "pump1", "relation_type": "feeds",
            "target_id": "tank1"})
        rolled = server.dispatch(session, "rollout", {
            "horizon_s": 3600.0, "step_s": 300.0})
        reasons = {d["reason"]
                   for d in rolled["simulation"]["not_checked"]}
        assert "coupling_uninstantiated" not in reasons
        assert rolled["simulation"]["checked"][
            "couplings_instantiated"] == 1
