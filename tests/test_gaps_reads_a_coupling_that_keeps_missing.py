"""`gaps` locates a coupling that keeps missing, with nobody acting.

the dynamics arm read one input: the pairs `file_action` files for
an EXECUTED action. The plan that built it named a second, a coupling's own
forecasts, and it was never built, so a model that only watches -- a coupling
filing what it predicts for the property it drives, nobody acting -- could
never be told its dynamics had stopped explaining what happened.

A graded forecast outside its declared spread is falsified. COUNTED IN
ROLLOUTS, as the pairs are counted in executions: every step of one rollout
comes from one declared gain, so its steps are one occasion. A
rollout missed when its furthest graded forecast missed. The last
`gaps.min_cycles` rollouts all missing, none with an action inside its window,
is located as an `unexplained_change`; the count is the model's to declare.

The world here is a tank a pump feeds, forecast through the declared gain,
while an inflow nobody declared lifts it a little more every minute.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from arbiter_engine import api
from arbiter_engine.subenvelope import VOCABULARIES

T0 = datetime(2026, 9, 29, 0, 0)
STEP_S, HORIZON_S = 60.0, 600.0
SPACING = timedelta(minutes=20)
COUPLING = "feeds:speed_rpm->level_pct"
THROTTLE = {"template": "throttle_pump", "entity_id": "pump1",
            "parameters": {"speed_rpm": 1500}}


def _model(cycles=3, *, vents=False, actions=False):
    domain = {
        "id": "keeps_missing", "name": "a coupling that keeps missing",
        "entity_types": ["Pump", "Tank", "Valve"],
        "relationship_types": ["feeds"] + (["vents"] if vents else []),
        "indicators": {
            "Pump": [{"name": "speed_rpm", "type": "NUMERIC",
                      "axioms": ["BOUNDEDNESS"], "critical": 9e9,
                      "dynamics": {"model": "trend"}}],
            "Tank": [{"name": "level_pct", "type": "NUMERIC",
                      "axioms": ["BOUNDEDNESS"], "critical": 9e9}],
            "Valve": [{"name": "open_pct", "type": "NUMERIC",
                       "axioms": ["BOUNDEDNESS"], "critical": 9e9}],
        },
        "relationship_rules": [
            {"type": "feeds", "source_type": "Pump", "target_type": "Tank",
             "temporal": {"propagation_delay_s": 0, "time_constant_s": 1,
                          "response_model": "step"},
             "transition": {"from": "speed_rpm", "to": "level_pct",
                            "gain": 0.02, "gain_sigma": 0.002,
                            "source": "datasheet"}},
        ],
    }
    if vents:
        domain["relationship_rules"].append(
            {"type": "vents", "source_type": "Valve", "target_type": "Tank"})
    if actions:
        domain["action_templates"] = [{
            "name": "throttle_pump", "applies_to": "Pump",
            "description": "Set the pump to a specific speed.",
            "parameters_schema": {"speed_rpm": {
                "type": "number", "entity_property": "speed_rpm",
                "candidates": [1500, 3000], "tolerance": 50.0}},
            "effect": "set", "settle_s": 30, "source": "runbook"}]
    if cycles is not None:
        domain["gaps"] = {"min_cycles": cycles}
    return {"domain": domain}


def _world(drifts, *, cycles=3, vents=False, act=False):
    """One rollout per entry in `drifts`, twenty minutes apart. Each is filed,
    then the tank is fed what the rollout forecast plus `drift` more for every
    minute ahead -- the inflow nobody declared -- and graded."""
    session = api.EngineSession()
    session.load_model(_model(cycles, vents=vents, actions=act))
    session.add_entity("pump1", "Pump", {"speed_rpm": 2000.0})
    session.add_entity("tank1", "Tank", {"level_pct": 50.0})
    session.add_relationship("pump1", "feeds", "tank1")
    if vents:
        session.add_entity("valve1", "Valve", {"open_pct": 10.0})
        session.add_relationship("valve1", "vents", "tank1")
    fed_until = T0 - timedelta(minutes=30)
    # Scattered, because a trend fitted through a perfect line reports no
    # uncertainty and a rollout declines `covariance_unbounded` on it.
    rng = random.Random(7)
    for k, drift in enumerate(drifts):
        at = T0 + SPACING * k
        # The driver's own history up to this rollout, rising steadily, so a
        # projection moves it and the coupling carries that to the tank.
        speeds = []
        while fed_until <= at:
            minutes = (fed_until - T0).total_seconds() / 60.0
            speeds.append((fed_until,
                           2000.0 + 5.0 * minutes + rng.gauss(0.0, 8.0)))
            fed_until += timedelta(seconds=STEP_S)
        session.add_observations("pump1", "speed_rpm", speeds)
        with api.as_of(at):
            simulation = api.rollout(
                session, horizon_s=HORIZON_S, step_s=STEP_S,
                seed_mode="projected", file_predictions=True
            ).to_dict()["simulation"]
        if act:
            # Filed once it has happened: an execution after the engine's
            # clock is refused.
            acted = at + timedelta(minutes=2)
            with api.as_of(acted):
                filed = api.file_action(session, THROTTLE, acted,
                                        "operator log", horizon_s=HORIZON_S,
                                        step_s=STEP_S).to_dict()["execution"]
            assert not filed["not_checked"], filed["not_checked"]
        projected = [step["values"]["tank1"]["level_pct"]
                     for step in simulation["per_step"]]
        session.add_observations("tank1", "level_pct", [
            (at + timedelta(seconds=STEP_S * i), value + drift * i)
            for i, value in enumerate(projected, start=1)])
        with api.as_of(at + timedelta(seconds=HORIZON_S
                                      + session.ledger.grace_s + 1)):
            api.check(session)
    return session


def _residuals(session):
    with api.as_of(T0 + timedelta(days=1)):
        return api.gaps(session).to_dict()["residuals"]


def _located(residuals):
    return [h for h in residuals["hypotheses"]
            if h["basis"] == "coupling forecasts"]


def _declined(residuals):
    return {(d["reason"], d.get("location")) for d in residuals["not_checked"]}


class TestACouplingThatKeepsMissing:

    def test_three_missed_rollouts_are_an_unexplained_change(self):
        residuals = _residuals(_world([3.0, 3.0, 3.0]))
        assert _located(residuals) == [{
            "kind": "unexplained_change", "on": "tank1.level_pct",
            "basis": "coupling forecasts", "couplings": [COUPLING],
            "rollouts": 3, "candidates": [], "evidence_needed": None,
            "reason": "every declared relation into it already drives this "
                      "property, so the change arrives by a relation nobody "
                      "declared"}]
        assert residuals["checked"]["forecasts_read"] == 30

    def test_an_undeclared_channel_is_named_with_a_reading_to_take(self):
        [row] = _located(_residuals(_world([3.0] * 3, vents=True)))
        assert row["candidates"] == ["vents"]
        assert row["evidence_needed"] == "valve1.open_pct"

    def test_a_world_that_follows_the_coupling_locates_nothing(self):
        """The negative control: every forecast graded, every one held."""
        residuals = _residuals(_world([0.0, 0.0, 0.0]))
        assert residuals["checked"]["forecasts_read"] == 30
        assert _located(residuals) == []
        assert ("insufficient_samples", "forecasts") not in _declined(residuals)

    def test_a_run_that_has_ended_is_not_located(self):
        """Three misses and then a rollout that held: whatever pushed the tank
        has stopped, and the last word is the coupling's."""
        assert _located(_residuals(_world([3.0, 3.0, 3.0, 0.0]))) == []

    def test_the_steps_of_one_rollout_are_one_occasion(self):
        """Ten falsified forecasts from ONE rollout are one miss, not ten: one
        declared gain drove every step."""
        residuals = _residuals(_world([3.0], cycles=2))
        assert residuals["checked"]["forecasts_read"] == 10
        assert _located(residuals) == []
        [row] = [d for d in residuals["not_checked"]
                 if d["reason"] == "insufficient_samples"]
        assert row["evidence"] == {"graded_rollouts": 1, "min_cycles": 2}

    def test_fewer_rollouts_than_declared_is_insufficient_samples(self):
        residuals = _residuals(_world([3.0, 3.0], cycles=3))
        assert _located(residuals) == []
        assert ("insufficient_samples", "forecasts") in _declined(residuals)

    def test_without_a_declared_count_no_count_is_chosen(self):
        residuals = _residuals(_world([3.0] * 3, cycles=None))
        assert _located(residuals) == [], "a pattern was called on a count " \
                                          "nobody declared"
        assert ("missing_config", "gaps.min_cycles") in _declined(residuals)

    def test_an_action_inside_the_window_takes_the_miss(self):
        """The operator throttled the pump two minutes into every rollout.
        Those misses belong to the pairs the action filed, not the coupling."""
        residuals = _residuals(_world([3.0] * 3, act=True))
        assert _located(residuals) == []


class TestItRefusesByName:

    def test_every_reason_is_a_discovery_name(self):
        for session in (_world([3.0], cycles=2), _world([3.0], cycles=None)):
            reasons = {d["reason"] for d in _residuals(session)["not_checked"]}
            assert reasons <= VOCABULARIES["discovery"], reasons

    def test_one_missing_count_is_declined_once(self):
        """A model with actions AND a coupling, and no count: the two inputs
        miss the same declaration, and it is named once."""
        residuals = _residuals(_world([3.0] * 3, cycles=None, act=True))
        missing = [d for d in residuals["not_checked"]
                   if (d["reason"], d.get("location"))
                   == ("missing_config", "gaps.min_cycles")]
        assert len(missing) == 1

    def test_a_model_with_no_coupling_forecasts_reads_none(self):
        session = api.EngineSession()
        session.load_model(_model())
        session.add_entity("tank1", "Tank", {"level_pct": 50.0})
        api.check(session)
        residuals = _residuals(session)
        assert residuals["checked"]["forecasts_read"] == 0
        assert not {r for r, loc in _declined(residuals) if loc == "forecasts"}
