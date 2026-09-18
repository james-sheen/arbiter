"""A rollout runs the model forward under actions and judges each state.

An internal ruling completes ``p(s_{t+1} | s_t, a_t)``: Stage 1 gave the state half, this
gives the action half and iterates it. What makes it a WORLD model rather than
a calculator is that every imagined state is judged by the same eight axioms
that judge a real one, over an imagined history the rollout writes as it goes.

THREE THINGS THIS FILE PINS THAT ONLY RUNNING FOUND.

An action at ``at_s=0`` -- *do this now*, the most natural thing a caller
writes -- fired in NO step. The window was half-open on both sides, so step
one asked ``0 < 0`` and got False. The envelope reported
``actions_scheduled: 1``, ``actions_refused: 0`` and a flat trajectory: an
action accepted, never applied, and nothing said. The boundary cases are
parametrised here because that is the only way this class of error shows up.

An action scheduled PAST the horizon, or at a negative time, was accepted and
dropped the same silent way. Both are refused now, by name.

The history clone called ``get_observations(entity, property)`` when that
method takes ``(entity, start, end)``. It never raised in any test that had no
observations to copy -- which is every test written before the one that fed
some. A crash reachable only with real data is the shape a fixture hides.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from arbiter_engine import api
from arbiter_engine.twin.actions import ActionInstance
from arbiter_engine.twin.traverser import IMAGINED_PREFIX

MODEL = """
domain:
  id: rollout
  name: Pump and tank with an action
  entity_types: [Pump, Tank]
  relationship_types: [feeds]
  indicators:
    Pump:
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS],
         lower_critical: 100, critical: 4000}
    Tank:
      - name: level_pct
        type: NUMERIC
        role: percentage
        axioms: [BOUNDEDNESS, HOMEOSTASIS]
        warning: 85
        critical: 95
        window: 30m
        homeostasis: {setpoint: 50, tolerance: 10}
  relationship_rules:
    - type: feeds
      source_type: Pump
      target_type: Tank
      temporal: {propagation_delay_s: 0, time_constant_s: 1, response_model: step}
      transition: {from: speed_rpm, to: level_pct, gain: 0.02, source: datasheet}
  action_templates:
    - name: throttle_pump
      applies_to: Pump
      parameters_schema:
        speed_rpm: {type: number, entity_property: speed_rpm}
      effect: set
      settle_s: 0
      source: runbook
    - name: nudge_pump
      applies_to: Pump
      parameters_schema:
        speed_rpm: {type: number, entity_property: speed_rpm}
      effect: add
      source: runbook
"""


@pytest.fixture
def session(tmp_path):
    path = tmp_path / "rollout.yaml"
    path.write_text(MODEL)
    s = api.EngineSession()
    s.load_model(str(path))
    s.add_entity("pump1", "Pump", {"speed_rpm": 1000.0})
    s.add_entity("tank1", "Tank", {"level_pct": 50.0})
    s.add_relationship("pump1", "feeds", "tank1")
    return s


def _throttle(at_s=0.0, rpm=4000.0):
    return ActionInstance("throttle_pump", "pump1", {"speed_rpm": rpm}, at_s)


def _sim(session, **kw):
    kw.setdefault("horizon_s", 300.0)
    kw.setdefault("step_s", 60.0)
    return api.rollout(session, **kw).to_dict()["simulation"]


class TestAnActionEntersAtItsTimeAndNotBefore:

    @pytest.mark.parametrize("at_s,expected_step", [
        (0.0, 1),      # `do this now` -- the case that fired in no step at all
        (1.0, 1),
        (60.0, 1),     # exactly on the first boundary
        (60.5, 2),
        (120.0, 2),
        (300.0, 5),    # exactly on the last step
    ])
    def test_the_action_fires_in_the_step_containing_its_time(
            self, session, at_s, expected_step):
        simulation = _sim(session, actions=[_throttle(at_s)])
        fired = [s["step"] for s in simulation["per_step"]
                 if s["actions_applied"]]
        assert fired == [expected_step]

    def test_nothing_moves_before_the_action(self, session):
        simulation = _sim(session, actions=[_throttle(180.0)])
        early = [s for s in simulation["per_step"] if s["step"] < 3]
        assert all(s["values"]["tank1"]["level_pct"] == 50.0 for s in early)

    def test_the_value_has_moved_after_the_action(self, session):
        simulation = _sim(session, actions=[_throttle(180.0)])
        late = [s for s in simulation["per_step"] if s["step"] >= 3]
        assert all(s["values"]["tank1"]["level_pct"] == pytest.approx(110.0)
                   for s in late)


class TestAnActionThatCannotFireIsRefused:

    @pytest.mark.parametrize("at_s", [900.0, -5.0])
    def test_it_is_refused_rather_than_dropped(self, session, at_s):
        simulation = _sim(session, actions=[_throttle(at_s)])
        assert simulation["checked"]["actions_refused"] == 1
        assert any(d["reason"] == "malformed_action"
                   for d in simulation["not_checked"])

    def test_an_unknown_template_is_named(self, session):
        simulation = _sim(session, actions=[
            ActionInstance("no_such_action", "pump1", {"x": 1.0}, 0.0)])
        reasons = [d["reason"] for d in simulation["not_checked"]]
        assert "unknown_action" in reasons

    def test_an_action_on_the_wrong_type_is_refused(self, session):
        simulation = _sim(session, actions=[
            ActionInstance("throttle_pump", "tank1", {"speed_rpm": 1.0}, 0.0)])
        assert "wrong_entity_type" in [d["reason"]
                                       for d in simulation["not_checked"]]

    def test_an_undeclared_parameter_is_refused(self, session):
        simulation = _sim(session, actions=[
            ActionInstance("throttle_pump", "pump1", {"nonsense": 1.0}, 0.0)])
        assert "unknown_parameter" in [d["reason"]
                                       for d in simulation["not_checked"]]

    def test_an_action_on_a_missing_entity_is_refused(self, session):
        simulation = _sim(session, actions=[
            ActionInstance("throttle_pump", "ghost", {"speed_rpm": 1.0}, 0.0)])
        assert "missing_entity" in [d["reason"]
                                    for d in simulation["not_checked"]]


class TestTheEffectVerbsMeanDifferentThings:

    def test_set_moves_to_the_value(self, session):
        simulation = _sim(session, actions=[_throttle(0.0, 3000.0)])
        assert simulation["per_step"][0]["values"]["pump1"]["speed_rpm"] == (
            pytest.approx(3000.0))

    def test_add_moves_by_the_value(self, session):
        simulation = _sim(session, actions=[
            ActionInstance("nudge_pump", "pump1", {"speed_rpm": 500.0}, 0.0)])
        assert simulation["per_step"][0]["values"]["pump1"]["speed_rpm"] == (
            pytest.approx(1500.0))


class TestTheImaginedTimelineIsPrivate:

    def test_a_rollout_writes_no_imagined_observation_into_the_live_history(
            self, session):
        now = api.now_utc()
        for k in range(20):
            session.add_observations(
                "tank1", "level_pct",
                [(now - timedelta(minutes=20 - k), 50.0)])

        def snapshot():
            history = session.reading_history()
            return {key: len(history.get_values(
                key[0], key[1], timedelta(days=3650)))
                for key in history.series_keys()}

        before = snapshot()
        api.rollout(session, actions=[_throttle(0.0)],
                    horizon_s=300.0, step_s=60.0)
        assert snapshot() == before, (
            "an imagined observation reached the live history; every "
            "subsequent check would judge a future somebody asked about as "
            "though it had happened")

    def test_the_real_past_is_carried_into_the_imagined_timeline(
            self, session):
        """The TypeError that no empty-history test could reach.

        `steps_completed` is NOT the observable: a rollout seeded from nothing
        completes its steps perfectly well, which is why the broken reader
        survived a green suite. The seeded COUNT is the observable, and it is
        reported for exactly this reason -- a windowed axiom over an imagined
        series answers a different question depending on whether the real past
        came with it, and nothing in the findings says which happened.
        """
        now = api.now_utc()
        for k in range(30):
            session.add_observations(
                "tank1", "level_pct",
                [(now - timedelta(minutes=30 - k), 50.0 + k * 0.1)])
        simulation = _sim(session, actions=[_throttle(0.0)])
        assert simulation["checked"]["steps_completed"] == 5
        assert simulation["checked"]["history_seeded"] == 30, (
            "the imagined timeline was seeded from an empty clone while the "
            "session held thirty readings")

    def test_a_session_with_no_history_seeds_nothing_and_says_so(
            self, session):
        assert _sim(session, actions=[_throttle(0.0)])[
            "checked"]["history_seeded"] == 0


class TestEveryImaginedFindingIsPrefixed:

    def test_no_rollout_finding_is_unprefixed(self, session):
        payload = api.rollout(session, actions=[_throttle(0.0)],
                              horizon_s=300.0, step_s=60.0).to_dict()
        assert payload["findings"], "guard: no findings makes this vacuous"
        assert all(f["problem_type"].startswith(IMAGINED_PREFIX)
                   for f in payload["findings"])

    def test_a_temporal_axiom_is_evaluated_over_the_imagined_series(
            self, session):
        """HOMEOSTASIS reads a history. A rollout writes one."""
        types = {f["problem_type"] for f in api.rollout(
            session, actions=[_throttle(0.0)], horizon_s=300.0,
            step_s=60.0).to_dict()["findings"]}
        assert any("homeostasis" in t for t in types), (
            "the imagined level sits 60 points off a declared setpoint of 50 "
            "with a tolerance of 10, and no temporal axiom said so")


class TestTheRolloutReportsItsOwnAccounting:

    def test_steps_requested_and_completed_are_both_reported(self, session):
        checked = _sim(session, actions=[_throttle(0.0)])["checked"]
        assert checked["steps_requested"] == 5
        assert checked["steps_completed"] == 5

    def test_a_step_longer_than_the_horizon_is_refused_with_a_reason(
            self, session):
        simulation = _sim(session, actions=[_throttle(0.0)],
                          horizon_s=30.0, step_s=60.0)
        assert simulation["checked"]["steps_completed"] == 0
        assert "malformed_request" in [d["reason"]
                                       for d in simulation["not_checked"]]

    @pytest.mark.parametrize("step_s", [0.0, -1.0])
    def test_a_non_positive_step_is_refused_not_defaulted(
            self, session, step_s):
        simulation = _sim(session, actions=[_throttle(0.0)], step_s=step_s)
        assert "malformed_request" in [d["reason"]
                                       for d in simulation["not_checked"]]

    def test_actions_carry_tier_three(self, session):
        """The same classification `traverse` gives overrides."""
        assert _sim(session, actions=[_throttle(0.0)])["tier"] == 3

    def test_a_rollout_without_actions_is_not_tier_three(self, session):
        assert _sim(session)["tier"] == 1

    def test_the_exogenous_hold_is_stamped_once(self, session):
        assumptions = _sim(session, actions=[_throttle(0.0)])["assumptions"]
        assert assumptions.count("exogenous_inputs_held") == 1, (
            "a stamp repeated reads as two assumptions rather than one")


class TestARolloutNeverDispatches:

    def test_the_live_entity_properties_are_unchanged(self, session):
        before = dict(session.entities["pump1"].properties)
        api.rollout(session, actions=[_throttle(0.0)],
                    horizon_s=300.0, step_s=60.0)
        assert session.entities["pump1"].properties == before, (
            "the engine proposes and never dispatches; a rollout that "
            "mutated the session would have executed the action")
