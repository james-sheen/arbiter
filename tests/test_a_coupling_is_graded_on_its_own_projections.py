"""A coupling's confirm rate is over the projections IT drove, and it says
how many trajectories those came from.

`model_describe` reports, beside every declared coupling, how its own
projections fared -- and it is emphatic in its own docstring about why the
denominator travels with the figure: *a confirm rate over two graded records
is not the same statement as one over two hundred*. Two things made that
denominator the wrong number.

ONE -- IT COUNTED RECORDS THE COUPLING NEVER DROVE. A value prediction is
filed per entity and property; the report resolved the entities of the rule's
TARGET TYPE and matched on the target property alone. Two rules into one
property therefore each claimed ALL of the records. Measured with four
records on `tank1.level_pct`: `Pump-feeds->Tank` reported `graded 4,
falsified 4` and `Heater-warms->Tank` reported `graded 4, falsified 4` -- four
records producing eight attributions, and neither coupling able to say whether
it was responsible. A value driven by BOTH couplings does belong to both; one
driven by neither, or by only one, does not.

TWO -- IT COUNTED ONE TRAJECTORY AS MANY. A rollout files one record per step,
so twelve steps of one trajectory, driven by one declared gain against one
mirror, confirmed or falsified together. Measured: `graded 12, confirmed 0,
confirm_rate 0.0` from a single rollout, with the ledger's own `episodes_n`
correctly reporting 1. The author was told *0 of 12 projections this coupling
drove were confirmed* -- which reads as twelve contradictions of a datasheet
number and is one.

THE FIX IS ATTRIBUTION, not a threshold. A filed value now records which
couplings drove it, taken from the per-source spread breakdown the walk
already computes, and the report counts only its own and says how many
episodes they came from. RECORDS WITH NO ATTRIBUTION ARE COUNTED AND NAMED
rather than silently claimed by everyone -- the same shape
`entity_type_unattributed_n` already uses in this ledger, and for the same
reason: a rate over an unstated subset is worse than no rate.

WHAT DOES NOT CHANGE: the remedy still fires on the rate the author sees, and
the engine still changes nothing. Deciding how much evidence is enough before
doubting a declaration is a domain question, so the engine reports the
evidence and lets the author weigh it.
"""
from __future__ import annotations

import random
import tempfile
from datetime import timedelta
from pathlib import Path

import pytest

from arbiter_engine import api
from arbiter_engine.history.observation import (
    InMemoryObservationHistory)

ONE_COUPLING = """
domain:
  id: graded_one
  name: One coupling whose projections can be graded
  entity_types: [Pump, Tank]
  relationship_types: [feeds]
  indicators:
    Pump:
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9,
         window: 4h, lookback: 24h, dynamics: {model: random_walk}}
    Tank:
      - {name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9,
         window: 4h, lookback: 24h}
  relationship_rules:
    - {type: feeds, source_type: Pump, target_type: Tank,
       temporal: {propagation_delay_s: 0, time_constant_s: 600,
                  response_model: exponential},
       transition: {from: speed_rpm, to: level_pct, gain: 0.02,
                    gain_sigma: 0.002, source: datasheet}}
"""

#: A second rule into the SAME property whose source never moves, so it drives
#: nothing and must claim nothing.
TWO_COUPLINGS = ONE_COUPLING.replace(
    "  entity_types: [Pump, Tank]",
    "  entity_types: [Pump, Heater, Tank]").replace(
    "  relationship_types: [feeds]",
    "  relationship_types: [feeds, warms]").replace(
    """    Tank:
      - {name: level_pct,""",
    """    Heater:
      - {name: duty, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9,
         window: 4h, lookback: 24h}
    Tank:
      - {name: level_pct,""") + """
    - {type: warms, source_type: Heater, target_type: Tank,
       temporal: {propagation_delay_s: 0, time_constant_s: 600,
                  response_model: exponential},
       transition: {from: duty, to: level_pct, gain: 0.5,
                    gain_sigma: 0.05, source: runbook}}
"""

HORIZON_S, STEP_S = 3600.0, 300.0
STEPS = int(HORIZON_S // STEP_S)


def _walk(seed=5, n=200, start=2000.0, sd=25.0):
    rng = random.Random(seed)
    value, out = start, []
    for _ in range(n):
        value += rng.gauss(0.0, sd)
        out.append(value)
    return out


def _session(model_text, heater=False):
    path = Path(tempfile.mkdtemp()) / "graded.yaml"
    path.write_text(model_text)
    session = api.EngineSession()
    session.load_model(str(path))
    values = _walk()
    session.add_entity("pump1", "Pump", {"speed_rpm": values[-1]})
    session.add_entity("tank1", "Tank", {"level_pct": 50.0})
    session.add_relationship("pump1", "feeds", "tank1")
    if heater:
        session.add_entity("heat1", "Heater", {"duty": 10.0})
        session.add_relationship("heat1", "warms", "tank1")
    now = api.now_utc()
    for k, value in enumerate(values):
        session.add_observations(
            "pump1", "speed_rpm",
            [(now - timedelta(seconds=60 * (len(values) - k)), value)])
    return session


def _run_and_grade(session, drift=2.0, rollouts=1):
    for _ in range(rollouts):
        api.rollout(session, actions=[], horizon_s=HORIZON_S, step_s=STEP_S,
                    seed_mode="projected", file_predictions=True)
    now = api.now_utc()
    mirror = InMemoryObservationHistory()
    for step in range(1, STEPS + 1):
        mirror.add("tank1", "level_pct", 50.0 + drift * step,
                   now + timedelta(seconds=STEP_S * step))
    session.ledger.grade_matured(
        [], set(), now=now + timedelta(
            seconds=HORIZON_S + session.ledger.grace_s + 1),
        histories=[mirror])
    return session


def _declared(session):
    payload = api.model_describe(session).to_dict()
    block = payload.get("model") or payload
    for key in ("dynamics", "transitions", "declared"):
        if isinstance(block, dict) and key in block:
            block = block[key]
            break
    return {entry["rule"]: entry for entry in block["declared"]}


class TestACouplingCountsOnlyWhatItDrove:

    def test_a_coupling_that_drove_nothing_claims_nothing(self):
        session = _run_and_grade(_session(TWO_COUPLINGS, heater=True))
        entries = _declared(session)
        assert "Heater-warms->Tank" in entries, "the fixture must declare it"
        heater = entries["Heater-warms->Tank"]["projections"]
        assert heater["graded"] == 0, (
            f"the heater never moved, so it drove none of these projections; "
            f"it claims {heater['graded']}")
        assert "remedy" not in entries["Heater-warms->Tank"], (
            "a coupling that drove nothing must not be told its gain may be "
            "wrong")

    def test_the_coupling_that_did_drive_them_still_counts_them(self):
        session = _run_and_grade(_session(TWO_COUPLINGS, heater=True))
        pump = _declared(session)["Pump-feeds->Tank"]["projections"]
        assert pump["graded"] == STEPS
        assert pump["falsified"] == STEPS

    def test_one_coupling_alone_is_unaffected(self):
        """The floor: attribution must not cost the simple case its rate."""
        session = _run_and_grade(_session(ONE_COUPLING))
        pump = _declared(session)["Pump-feeds->Tank"]["projections"]
        assert pump["graded"] == STEPS
        assert pump["confirm_rate"] == 0.0


class TestTheDenominatorSaysHowManyTrajectories:

    def test_one_rollout_reports_one_episode(self):
        session = _run_and_grade(_session(ONE_COUPLING))
        pump = _declared(session)["Pump-feeds->Tank"]["projections"]
        assert pump["graded"] == STEPS
        assert pump["episodes"] == 1, (
            f"{STEPS} records from one trajectory report "
            f"{pump.get('episodes')} episodes")

    def test_two_rollouts_report_two(self):
        session = _run_and_grade(_session(ONE_COUPLING), rollouts=2)
        assert _declared(session)["Pump-feeds->Tank"][
            "projections"]["episodes"] == 2

    def test_nothing_graded_reports_no_episodes_rather_than_zero(self):
        session = _session(ONE_COUPLING)
        pump = _declared(session)["Pump-feeds->Tank"]["projections"]
        assert pump["graded"] == 0
        assert pump["episodes"] is None
        assert pump["confirm_rate"] is None


class TestTheRemedySaysWhatItRestsOn:

    def test_the_remedy_names_the_trajectory_count(self):
        session = _run_and_grade(_session(ONE_COUPLING))
        remedy = _declared(session)["Pump-feeds->Tank"]["remedy"]
        assert "1 trajectory" in remedy, (
            f"the remedy invites an author to doubt a declared gain and must "
            f"say how much evidence it rests on: {remedy}")

    def test_the_remedy_still_changes_nothing(self):
        remedy = _declared(_run_and_grade(_session(ONE_COUPLING)))[
            "Pump-feeds->Tank"]["remedy"]
        assert "Nothing has been changed" in remedy

    def test_a_coupling_whose_projections_held_gets_no_remedy(self):
        session = _run_and_grade(_session(ONE_COUPLING), drift=0.0)
        entry = _declared(session)["Pump-feeds->Tank"]
        assert entry["projections"]["confirm_rate"] == 1.0
        assert "remedy" not in entry


class TestUnattributedRecordsAreNamedNotClaimed:
    """A record filed by something other than a rollout carries no coupling.
    Claiming it for every coupling is what this file exists to end, and
    dropping it silently would hide it -- so it is counted and named."""

    def test_a_record_with_no_attribution_is_reported_separately(self):
        session = _session(ONE_COUPLING)
        session.ledger.record_value_prediction(
            entity_id="tank1", property_name="level_pct",
            predicted_value=50.0, tolerance=0.1, horizon_s=300.0)
        now = api.now_utc()
        mirror = InMemoryObservationHistory()
        mirror.add("tank1", "level_pct", 99.0,
                   now + timedelta(seconds=300.0))
        session.ledger.grade_matured(
            [], set(), now=now + timedelta(
                seconds=300 + session.ledger.grace_s + 1),
            histories=[mirror])
        pump = _declared(session)["Pump-feeds->Tank"]["projections"]
        assert pump["graded"] == 0, (
            "a record nobody attributed to this coupling is not its evidence")
        assert pump["unattributed"] == 1, (
            "and it must not vanish either")
