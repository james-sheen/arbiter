"""`plan` ranked by a forecast and filed nothing, so nothing could grade it.

`plan` states an objective per row -- *throttling to 800 rpm produces
4.33 expected findings, doing nothing produces 0.0* -- and that arithmetic was
the one claim in this engine nothing could ever check. Measured before the fix:
the ledger was EMPTY after a call and the plan leg carried no calibration.

MOST ROWS CANNOT BE GRADED AND MUST NOT BE. A candidate carrying actions
describes a world nobody has brought about; `rollout` already refuses to file
one by name, and grading it against a world where nobody acted would fill the
ledger with falsified records that say nothing about the model.

**`do_nothing` IS NOT A COUNTERFACTUAL.** It is the trajectory that obtains if
nobody acts, and it is the row every other row is measured against -- so it is
the one whose projections are filable. Operator ruled 2026-09-21 that the
objective IS a forecast and this row should be filed and graded.

WHAT THIS FILE PINS
  - default OFF: `plan` writes nothing into a durable ledger unless asked;
  - exactly ONE row files, and it is the no-action row;
  - the rows that do not file say so ONCE, with a count, at plan level --
    not on the per-candidate `declines`, where a by-design exclusion would sit
    beside real faults and make four healthy rows look damaged;
  - one episode reaches the ledger however deep the search goes;
  - what it files is raced like any other forecast;
  - `seed_mode` reaches EVERY candidate or none -- applying it to the filing
    row alone would score one row on a trajectory the others never saw, which
    is the defect that an internal ruling recorded.

AND THE SEED HAS TO BE FITTED. `plan` never did the projector step `rollout`
does, so under `seed_mode='projected'` every candidate declined
`insufficient_samples` and completed zero steps -- a sample shortage reported
for a projection nobody had fitted. Measured: the same model and inputs gave
`steps_requested: 6` through `rollout` and `0` through `plan`.
"""
from __future__ import annotations

import datetime as dt
import random

import pytest

from arbiter_engine import api
from arbiter_engine.projection.projector import BASELINE_MODEL_ID

STEP_S, HORIZON_S = 300.0, 1800.0
STEPS = int(HORIZON_S // STEP_S)

MODEL = """
domain:
  id: plan_filed
  name: A plan whose no-action row is a forecast
  entity_types: [Pump, Tank]
  relationship_types: [feeds]
  indicators:
    Pump:
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9,
         window: 30m, dynamics: {model: local_level}}
    Tank:
      - {name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9,
         window: 30m}
  relationship_rules:
    - {type: feeds, source_type: Pump, target_type: Tank,
       temporal: {propagation_delay_s: 0, time_constant_s: 1,
                  response_model: step},
       transition: {from: speed_rpm, to: level_pct, gain: 0.02,
                    gain_sigma: 0.002, source: datasheet}}
  action_templates:
    - name: throttle_pump
      applies_to: Pump
      parameters_schema:
        speed_rpm: {type: number, entity_property: speed_rpm,
                    candidates: [800, 3000]}
      effect: set
      settle_s: 30
      source: runbook
  planning:
    objective: expected_findings
%(depth)s"""

DEEP = "    max_depth: 2\n"


def _session(tmp_path, name, depth=""):
    path = tmp_path / f"{name}.yaml"
    path.write_text(MODEL % {"depth": depth})
    session = api.EngineSession()
    session.load_model(str(path))
    rng = random.Random(7)
    level, series = 2500.0, []
    for _ in range(60):
        level += rng.gauss(0.0, 8.0)
        series.append(round(level + rng.gauss(0.0, 4.0), 3))
    session.add_entity("pump1", "Pump", {"speed_rpm": series[-1]})
    session.add_entity("tank1", "Tank", {"level_pct": 50.0})
    session.add_relationship("pump1", "feeds", "tank1")
    session.add_observations("pump1", "speed_rpm", series)
    session.add_observations("tank1", "level_pct", [50.0] * 60)
    return session


def _plan(session, **kwargs):
    kwargs.setdefault("seed_mode", "projected")
    return api.plan(session, horizon_s=HORIZON_S, step_s=STEP_S,
                    **kwargs).to_dict()["plan"]


def _own(session):
    return [r for r in session.ledger.records()
            if r.kind == "value" and r.model_id != BASELINE_MODEL_ID]


class TestFilingIsOffUnlessAsked:
    """A verb that reads as a query must not write to a durable ledger."""

    def test_the_default_files_nothing(self, tmp_path):
        session = _session(tmp_path, "default")
        leg = _plan(session)
        assert leg["checked"]["predictions_filed"] == 0
        assert not session.ledger.records()

    def test_the_default_carries_no_race_or_calibration_leg(self, tmp_path):
        leg = _plan(_session(tmp_path, "nolegs"))
        assert "raced" not in leg
        assert "calibration" not in leg

    def test_the_count_is_reported_even_when_nothing_was_filed(self, tmp_path):
        """`0` must mean *nothing was filed*, never *this verb cannot file*."""
        leg = _plan(_session(tmp_path, "zero"))
        assert leg["checked"]["predictions_filed"] == 0
        assert leg["checked"]["counterfactuals_not_filed"] > 0


class TestOnlyTheNoActionRowIsAForecast:

    def test_asking_to_file_files_the_no_action_row(self, tmp_path):
        session = _session(tmp_path, "files")
        leg = _plan(session, file_predictions=True)
        assert leg["checked"]["predictions_filed"] == STEPS
        assert len(_own(session)) == STEPS

    def test_every_acting_candidate_is_counted_as_unfiled(self, tmp_path):
        leg = _plan(_session(tmp_path, "counted"), file_predictions=True)
        acting = [c for c in leg["candidates"] if c["actions"]]
        assert leg["checked"]["counterfactuals_not_filed"] == len(acting) > 0

    def test_the_refusal_is_named_once_at_plan_level(self, tmp_path):
        leg = _plan(_session(tmp_path, "once"), file_predictions=True)
        reasons = [d.get("reason") for d in leg["not_checked"]]
        assert reasons.count("counterfactual_not_a_prediction") == 1

    def test_the_refusal_does_not_land_on_the_candidate_rows(self, tmp_path):
        """A by-design exclusion beside real faults makes healthy rows look
        damaged -- the reader comparing rows is the one it misleads."""
        leg = _plan(_session(tmp_path, "clean"), file_predictions=True)
        for candidate in leg["candidates"]:
            assert "counterfactual_not_a_prediction" not in candidate["declines"]

    def test_nothing_is_refused_when_filing_was_not_asked_for(self, tmp_path):
        leg = _plan(_session(tmp_path, "unasked"))
        reasons = [d.get("reason") for d in leg["not_checked"]]
        assert "counterfactual_not_a_prediction" not in reasons


class TestOneEpisodeHoweverDeepTheSearch:
    """The filable trajectory is rolled once, before the depth loop."""

    @pytest.mark.parametrize("depth", ["", DEEP])
    def test_exactly_one_episode_reaches_the_ledger(self, tmp_path, depth):
        session = _session(tmp_path, f"depth{len(depth)}", depth=depth)
        _plan(session, file_predictions=True)
        assert len({r.traversal_id for r in _own(session)}) == 1

    def test_a_deeper_search_still_files_one_row_of_steps(self, tmp_path):
        session = _session(tmp_path, "deepsteps", depth=DEEP)
        leg = _plan(session, file_predictions=True)
        assert leg["checked"]["predictions_filed"] == STEPS


class TestWhatItFilesIsRaced:
    """ composes: a plan's forecast gets the same yardstick."""

    def test_a_race_row_accompanies_every_filed_prediction(self, tmp_path):
        session = _session(tmp_path, "raced")
        leg = _plan(session, file_predictions=True)
        assert len(leg["raced"]) == leg["checked"]["predictions_filed"]

    def test_the_yardstick_reaches_the_ledger(self, tmp_path):
        session = _session(tmp_path, "yard")
        leg = _plan(session, file_predictions=True)
        filed = [r for r in session.ledger.records()
                 if r.model_id == BASELINE_MODEL_ID]
        assert len(filed) == leg["checked"]["baselines_filed"] > 0

    def test_the_filed_row_grades_and_is_compared(self, tmp_path):
        session = _session(tmp_path, "graded")
        start = api.now_utc()
        _plan(session, file_predictions=True)
        for k in range(1, STEPS + 1):
            with api.as_of(start + dt.timedelta(seconds=STEP_S * k)):
                session.add_observations("tank1", "level_pct", [50.0 + 0.3 * k])
        with api.as_of(start + dt.timedelta(seconds=HORIZON_S + 60)):
            api.check(session)
            own = session.ledger.calibration()["own_projections"]
        assert own["n"] > 0
        assert own["baseline"]["compared_n"] > 0
        assert own["baseline"]["beats_baseline"] in (True, False)


class TestTheSeedReachesEveryCandidateOrNone:

    def test_an_unsupported_seed_mode_is_refused_by_name(self, tmp_path):
        payload = api.plan(_session(tmp_path, "badseed"), horizon_s=HORIZON_S,
                           step_s=STEP_S, seed_mode="wishful").to_dict()
        assert payload["meta"]["source"] == "unavailable"

    def test_the_projected_seed_is_fitted_so_candidates_step(self, tmp_path):
        """The bug this pins: a sample shortage reported for a projection
        nobody had fitted, on every row, with zero steps completed."""
        leg = _plan(_session(tmp_path, "fitted"), file_predictions=True)
        for candidate in leg["candidates"]:
            assert candidate["checked"]["steps_completed"] == STEPS
            assert "insufficient_samples" not in candidate["declines"]

    def test_every_candidate_ran_on_the_same_seed(self, tmp_path):
        """Comparability is what the ranking rests on."""
        leg = _plan(_session(tmp_path, "same"), file_predictions=True)
        requested = {c["checked"]["steps_requested"] for c in leg["candidates"]}
        assert len(requested) == 1
