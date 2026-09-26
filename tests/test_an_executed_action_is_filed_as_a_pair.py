"""An executed action, filed as two predictions and graded like any other.

`rollout` under actions files nothing, because nothing says the actions were
taken, and grading a world nobody brought about scores the model on outcomes
nobody attempted. `file_action` is the case where somebody DID take one: the
caller records that a declared action took effect at an instant, and the engine
rolls the model forward from there with the action and without it, and files
both. The grader needs no change -- each record is an ordinary value forecast --
and `calibration()` keeps the pair out of the ordinary figures, reporting it
under `executions` instead.

The acceptance is on the shipped pump example: readings that follow the
action confirm the action arm and falsify the other, and readings that follow
no action do the reverse -- on the in-memory ledger and across two sessions on
the durable one.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from arbiter_engine import api
from arbiter_engine.residual.sqlite_ledger import \
    SqlitePredictionLedger
from arbiter_engine.subenvelope import VOCABULARIES
from arbiter_engine.twin.actions import load_templates

import yaml

def _example() -> Path:
    """The shipped example, in whichever tree this file runs in: the package
    keeps it in `examples/`, the repository in `docs/publication`."""
    here = Path(__file__).resolve()
    for candidate in (here.parents[1] / "examples", here.parents[2] / "examples",
                      here.parents[2] / "docs" / "publication" / "engine-example"):
        if (candidate / "pump_tank_planning.yaml").is_file():
            return candidate / "pump_tank_planning.yaml"
    raise AssertionError("no examples directory in this tree carries it")


EXAMPLE = _example()
AT = datetime(2026, 9, 26, 12, 0)
THROTTLE = {"template": "throttle_pump", "entity_id": "pump1",
            "parameters": {"speed_rpm": 1500}}
HORIZON, STEP = 1800.0, 300.0


def _model(tolerance=None):
    """The shipped example, with a `tolerance:` on the pump's parameter when
    a test declares one."""
    model = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    if tolerance is not None:
        template = next(t for t in model["domain"]["action_templates"]
                        if t["name"] == "throttle_pump")
        template["parameters_schema"]["speed_rpm"]["tolerance"] = tolerance
    return model


def _session(ledger=None, tolerance=None):
    session = api.EngineSession(ledger=ledger)
    session.load_model(_model(tolerance))
    session.add_entity("pump1", "Pump", {"speed_rpm": 3000.0})
    session.add_entity("tank1", "Tank", {"level_pct": 50.0})
    session.add_entity("valve1", "Valve", {"open_pct": 0.0})
    session.add_relationship("pump1", "feeds", "tank1")
    session.add_relationship("valve1", "drains", "tank1")
    return session


def _file(session, action=THROTTLE, at=AT, basis="operator log 17", **kwargs):
    with api.as_of(at):
        return api.file_action(session, action, at, basis, horizon_s=HORIZON,
                               step_s=STEP, **kwargs).to_dict()


def _grade(session, follow, prop="level_pct", entity="tank1"):
    """Feed the readings one arm predicted, and let `check` grade the pair."""
    predicted = {r.horizon_s: r.value for r in session.ledger.records()
                 if r.execution and r.execution["arm"] == follow
                 and r.indicator == prop}
    assert predicted, f"nothing was filed for the {follow} arm"
    later = AT + timedelta(seconds=HORIZON + session.ledger.grace_s + 1)
    with api.as_of(later):
        session.add_observations(entity, prop, [
            (AT + timedelta(seconds=h), v) for h, v in sorted(predicted.items())])
        api.check(session)
    return session.ledger.calibration()["executions"]


def _verdicts(executions, arm):
    counts = executions["arms"][arm]
    return counts["confirmed"], counts["falsified"]


class TestTheWorldPicksAnArm:

    def test_readings_that_follow_the_action_confirm_it(self):
        session = _session()
        filed = _file(session)["execution"]["checked"]["pairs_filed"]
        executions = _grade(session, "action")
        assert filed > 0
        assert _verdicts(executions, "action") == (filed, 0)
        assert _verdicts(executions, "no_action") == (0, filed)

    def test_readings_that_follow_no_action_confirm_the_other_arm(self):
        session = _session()
        filed = _file(session)["execution"]["checked"]["pairs_filed"]
        executions = _grade(session, "no_action")
        assert _verdicts(executions, "action") == (0, filed)
        assert _verdicts(executions, "no_action") == (filed, 0)

    def test_the_pair_survives_a_new_session_on_the_durable_ledger(self, tmp_path):
        path = str(tmp_path / "predictions.db")
        first = _session(SqlitePredictionLedger(path))
        envelope = _file(first)["execution"]
        second = _session(SqlitePredictionLedger(path))
        executions = _grade(second, "action")
        row = executions["by_execution"][envelope["id"]]
        filed = envelope["checked"]["pairs_filed"]
        assert row["basis"] == "operator log 17"
        assert row["arms"]["action"]["confirmed"] == filed
        assert row["arms"]["no_action"]["falsified"] == filed


class TestWhatIsFiledAndWhatIsNot:

    def test_a_value_the_action_did_not_move_is_not_filed(self):
        """The valve reads the same in both arms, and a pair that cannot
        disagree cannot say which world happened."""
        session = _session()
        checked = _file(session)["execution"]["checked"]
        assert checked["values_unaffected"] > 0
        assert not [r for r in session.ledger.records() if r.entity_id == "valve1"]

    def test_both_arms_share_one_band_at_each_instant(self):
        session = _session()
        _file(session)
        by_instant = {}
        for record in session.ledger.records():
            by_instant.setdefault((record.indicator, record.horizon_s),
                                  set()).add(record.tolerance)
        assert all(len(bands) == 1 for bands in by_instant.values())

    def test_the_written_value_needs_a_declared_tolerance(self):
        session = _session()
        envelope = _file(session)["execution"]
        assert not [r for r in session.ledger.records() if r.entity_id == "pump1"]
        detail = next(d["detail"] for d in envelope["not_checked"]
                      if d["reason"] == "no_declared_tolerance")
        assert "`tolerance:` on the parameter" in detail

    def test_a_declared_tolerance_files_the_written_value(self):
        session = _session(tolerance=25.0)
        _file(session)
        written = [r for r in session.ledger.records() if r.entity_id == "pump1"]
        assert {r.tolerance for r in written} == {25.0}
        assert {r.execution["arm"]: r.value for r in written
                if r.horizon_s == STEP} == {"action": 1500.0, "no_action": 3000.0}
        executions = _grade(session, "action", prop="speed_rpm", entity="pump1")
        assert executions["arms"]["action"]["confirmed"] >= len(written) // 2

    def test_every_record_names_its_execution(self):
        session = _session()
        envelope = _file(session)["execution"]
        for record in session.ledger.records():
            assert record.execution["id"] == envelope["id"]
            assert record.execution["action"] == "throttle_pump@pump1"
            assert record.execution["executed_at"] == AT.isoformat()


class TestTheOrdinaryFiguresStayOrdinary:

    def test_the_pair_is_counted_and_kept_out_of_them(self):
        session = _session()
        filed = _file(session)["execution"]["checked"]["records_filed"]
        _grade(session, "action")
        calibration = session.ledger.calibration()
        assert calibration["recorded"] == filed
        assert calibration["by_kind"] == {}
        assert calibration["confirm_rate"] is None
        assert calibration["own_projections"]["n"] == 0
        assert calibration["executions"]["recorded"] == filed

    def test_a_rollout_carrying_actions_still_files_nothing(self):
        session = _session()
        with api.as_of(AT):
            payload = api.rollout(session, actions=[THROTTLE], horizon_s=HORIZON,
                                  step_s=STEP, file_predictions=True).to_dict()
        assert payload["simulation"]["checked"]["predictions_filed"] == 0
        assert "counterfactual_not_a_prediction" in {
            d["reason"] for d in payload["simulation"]["not_checked"]}
        assert session.ledger.records() == []


class TestItRefusesByName:

    def _reasons(self, envelope):
        return {d["reason"] for d in envelope["execution"]["not_checked"]}

    @pytest.mark.parametrize("change, reason", [
        ({"at_s": 60.0}, "malformed_action"),
        ({"template": "no_such_template"}, "unknown_action"),
        ({"entity_id": "pump9"}, "missing_entity"),
        ({"entity_id": "tank1"}, "wrong_entity_type"),
        ({"parameters": {"torque": 3}}, "unknown_parameter"),
    ])
    def test_an_action_the_model_cannot_place(self, change, reason):
        session = _session()
        envelope = _file(session, action={**THROTTLE, **change})
        assert reason in self._reasons(envelope)
        assert session.ledger.records() == []

    def test_an_execution_nobody_vouches_for(self):
        envelope = _file(_session(), basis="  ")
        assert "malformed_request" in self._reasons(envelope)

    def test_an_execution_that_has_not_happened_yet(self):
        session = _session()
        with api.as_of(AT):
            envelope = api.file_action(session, THROTTLE, AT + timedelta(hours=1),
                                       "a plan").to_dict()
        assert "malformed_request" in self._reasons(envelope)
        assert session.ledger.records() == []

    def test_a_present_the_action_already_changed(self):
        """Readings after the execution mean the session's state is not the
        state the action met."""
        session = _session()
        with api.as_of(AT + timedelta(minutes=10)):
            session.add_observations("tank1", "level_pct", [
                (AT + timedelta(minutes=5), 47.0)])
            envelope = api.file_action(session, THROTTLE, AT, "log").to_dict()
        leg = envelope["execution"]
        assert "precondition_unmet" in self._reasons(envelope)
        assert next(d for d in leg["not_checked"]
                    if d["reason"] == "precondition_unmet")["evidence"] == {
                        "readings_after": 1}
        assert session.ledger.records() == []

    def test_every_reason_is_one_the_simulation_vocabulary_publishes(self):
        session = _session()
        reasons = set()
        for change in ({"at_s": 1.0}, {"template": "x"}, {"entity_id": "x"}, {}):
            reasons |= self._reasons(_file(session, action={**THROTTLE, **change},
                                           basis="" if not change else "b"))
        assert reasons and reasons <= VOCABULARIES["simulation"]

    @pytest.mark.parametrize("args", [
        (["throttle_pump"], AT, "b"),
        (THROTTLE, 1_695_000_000, "b"),
        (THROTTLE, AT, None),
    ])
    def test_a_wrong_argument_type_is_a_caller_bug(self, args):
        with pytest.raises(TypeError):
            api.file_action(_session(), *args)

    def test_executed_at_may_arrive_as_text(self):
        session = _session()
        with api.as_of(AT):
            envelope = api.file_action(session, THROTTLE, AT.isoformat() + "Z",
                                       "log", horizon_s=HORIZON,
                                       step_s=STEP).to_dict()
        assert envelope["execution"]["executed_at"] == AT.isoformat()
        assert envelope["execution"]["checked"]["pairs_filed"] > 0


class TestTheParameterTolerance:

    def test_it_is_a_key_the_loader_reads(self):
        session = _session(tolerance=25.0)
        assert not [row for row in session.model.unread_fields()
                    if "tolerance" in str(row)]

    @pytest.mark.parametrize("bad", [0, -1.0, "close", True, float("nan")])
    def test_one_nobody_can_read_refuses_the_template(self, bad):
        model = _model()
        template = next(t for t in model["domain"]["action_templates"]
                        if t["name"] == "throttle_pump")
        template["parameters_schema"]["speed_rpm"]["tolerance"] = bad
        session = api.EngineSession()
        session.load_model(model)
        templates, refused = load_templates(session.model)
        assert "throttle_pump" not in templates
        assert [(r.reason, r.location) for r in refused] == [
            ("malformed_action", "throttle_pump")]


def test_the_transport_carries_it():
    from arbiter_engine.mcp.server import TOOL_SPECS, dispatch

    assert "file_action" in {spec["name"] for spec in TOOL_SPECS}
    session = _session()
    with api.as_of(AT):
        payload = dispatch(session, "file_action", {
            "action": copy.deepcopy(THROTTLE), "executed_at": AT.isoformat(),
            "basis": "operator log 17", "horizon_s": HORIZON, "step_s": STEP})
    assert payload["execution"]["checked"]["pairs_filed"] > 0
