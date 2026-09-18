"""A fitted gain is a proposal. The engine never edits the model.

`causal/discovery.py` sets the governance precedent and states it
plainly: it proposes edges, reports what it could not test, declines
`faithfulness_unverifiable` on every run, and nothing it produces enters the
model without an author. A fitted gain follows it.

THE PAIR IS ALWAYS DECLARED; ONLY THE NUMBER IS EVER LEARNED. Searching for
couplings -- pairing every numeric property on one entity with every numeric
property on another and keeping what correlates -- is the inference this
package removed from `role:`, from flow direction and from `agrees_with:`. It
would find a gain between a pump's lifetime run-hours counter and a tank's
level, because over any window where the pump ran, both rise. So an author
writes `gain: estimate` to say *these two are coupled and I do not know by how
much*, and that is the only way a learned gain comes to exist.

TWO REFUSALS THAT LOOK ALIKE AND ARE NOT. Too few samples is answered by
feeding more data. A declared delay that does not land on the sampling grid is
NOT -- `align` intersects on exact timestamps, so a 90-second delay against a
60-second series pairs nothing however long the series runs. Reporting that as
a sample shortage would send the author to collect data that cannot help, and
a decline whose remedy does not work is worse than no decline.
"""
from __future__ import annotations

import random
from datetime import timedelta

import pytest

from arbiter_engine import api
from arbiter_engine.twin.transition_learner import (
    MINIMUM_PAIRED_SAMPLES)

MODEL = """
domain:
  id: learn
  name: One declared coupling
  entity_types: [Pump, Tank]
  relationship_types: [feeds]
  indicators:
    Pump: [{{name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}}]
    Tank: [{{name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}}]
  relationship_rules:
    - type: feeds
      source_type: Pump
      target_type: Tank
      temporal:
        propagation_delay_s: {delay}
        time_constant_s: 1
        response_model: step
      transition:
        from: speed_rpm
        to: level_pct
        gain: {gain}
        source: {source}
"""


def _session(tmp_path, *, gain="0.02", source="datasheet", true_gain=0.02,
             samples=200, interval=60, delay=0, noise=0.0, name="m"):
    path = tmp_path / f"{name}.yaml"
    path.write_text(MODEL.format(gain=gain, source=source, delay=delay))
    session = api.EngineSession()
    session.load_model(str(path))
    session.add_entity("p", "Pump", {"speed_rpm": 1000.0})
    session.add_entity("t", "Tank", {"level_pct": 50.0})
    session.add_relationship("p", "feeds", "t")
    now = api.now_utc()
    rng = random.Random(7)
    speed, level = 1000.0, 50.0
    for k in range(samples):
        step = rng.uniform(-50.0, 50.0)
        speed += step
        level += true_gain * step + (rng.gauss(0.0, noise) if noise else 0.0)
        when = now - timedelta(seconds=interval * (samples - k))
        session.add_observations("p", "speed_rpm", [(when, speed)])
        session.add_observations("t", "level_pct", [(when, level)])
    return session


def _proposed(session):
    return api.model_describe(session).to_dict()[
        "model"]["proposed_transitions"]


class TestTheGainIsRecoveredFromData:

    def test_the_fitted_gain_matches_the_one_that_generated_the_series(
            self, tmp_path):
        fitted = _proposed(_session(tmp_path, true_gain=0.05))["fitted"]
        assert len(fitted) == 1
        assert fitted[0]["gain"] == pytest.approx(0.05, abs=1e-6)

    def test_it_reports_its_support(self, tmp_path):
        entry = _proposed(_session(tmp_path))["fitted"][0]
        assert entry["n"] >= MINIMUM_PAIRED_SAMPLES
        assert 0.0 <= entry["r_squared"] <= 1.0
        assert entry["interval"][0] <= entry["gain"] <= entry["interval"][1]

    def test_the_interval_widens_with_noise(self, tmp_path):
        """A band that does not respond to noise is not a band.

        It is also what keeps the disagreement finding from firing on every
        edge anyone measured: the test below asks whether the INTERVAL
        excludes the declaration, not whether the point estimate differs.
        """
        quiet = _proposed(_session(tmp_path, noise=0.0, name="q"))["fitted"][0]
        noisy = _proposed(_session(tmp_path, noise=2.0, name="n"))["fitted"][0]
        quiet_width = quiet["interval"][1] - quiet["interval"][0]
        noisy_width = noisy["interval"][1] - noisy["interval"][0]
        assert noisy_width > quiet_width

    def test_a_correct_declaration_is_not_contradicted_under_noise(
            self, tmp_path):
        for noise in (0.1, 0.5, 2.0):
            payload = _proposed(_session(tmp_path, noise=noise,
                                         name=f"n{noise}"))
            assert payload["disagreements"] == [], (
                f"the declared gain is the one that generated the series and "
                f"at noise {noise} the engine called it a contradiction")


class TestADeclarationTheDataContradictIsAFindingNotAnEdit:

    def test_the_disagreement_is_reported(self, tmp_path):
        payload = _proposed(_session(tmp_path, gain="0.02", true_gain=0.05))
        assert len(payload["disagreements"]) == 1
        entry = payload["disagreements"][0]
        assert entry["declared_gain"] == 0.02
        assert entry["fitted_gain"] == pytest.approx(0.05, abs=1e-6)

    def test_it_carries_both_numbers_and_a_remedy(self, tmp_path):
        entry = _proposed(
            _session(tmp_path, gain="0.02", true_gain=0.05))["disagreements"][0]
        assert "0.02" in entry["remedy"]
        assert "Nothing has been changed" in entry["remedy"]

    def test_the_declaration_is_untouched_on_disk(self, tmp_path):
        """The engine reports on a system; it does not become one."""
        path = tmp_path / "m.yaml"
        session = _session(tmp_path, gain="0.02", true_gain=0.05)
        before = path.read_text()
        _proposed(session)
        assert path.read_text() == before
        assert "gain: 0.02" in path.read_text()

    def test_the_declared_gain_still_drives_the_traversal(self, tmp_path):
        """A proposal that quietly took effect would be an edit by another
        name."""
        session = _session(tmp_path, gain="0.02", true_gain=0.05)
        _proposed(session)
        values = api.traverse(
            session, ["p"], value_mode="hypothetical",
            overrides={"p": {"speed_rpm": 2000.0}}
        ).to_dict()["simulation"]["values"]
        moved = values["t"]["level_pct"]["value"] - 50.0
        declared_move = 0.02 * (2000.0 - 1000.0)
        assert moved == pytest.approx(declared_move, rel=1e-3), (
            "the traversal moved by the FITTED gain; a proposal was adopted "
            "without anyone adopting it")


class TestAnEstimatedGainProjectsNothingUntilAdopted:

    def test_the_pair_is_declared_and_the_number_is_fitted(self, tmp_path):
        payload = _proposed(_session(tmp_path, gain="estimate",
                                     source="estimated", true_gain=0.03))
        assert len(payload["fitted"]) == 1
        assert payload["fitted"][0]["gain"] == pytest.approx(0.03, abs=1e-6)
        assert payload["fitted"][0]["declared_gain"] is None

    def test_an_estimated_gain_is_never_a_disagreement(self, tmp_path):
        """There is no declaration for the data to contradict."""
        assert _proposed(_session(tmp_path, gain="estimate",
                                  source="estimated"))["disagreements"] == []

    def test_a_traversal_projects_nothing_across_it(self, tmp_path):
        session = _session(tmp_path, gain="estimate", source="estimated")
        payload = api.traverse(
            session, ["p"], value_mode="hypothetical",
            overrides={"p": {"speed_rpm": 2000.0}}).to_dict()["simulation"]
        assert payload["values"] == {}, (
            "a transition whose magnitude nobody has supplied moved a value")

    def test_and_says_why_rather_than_reading_as_a_zero_gain(self, tmp_path):
        session = _session(tmp_path, gain="estimate", source="estimated")
        reasons = {d["reason"] for d in api.traverse(
            session, ["p"], value_mode="hypothetical",
            overrides={"p": {"speed_rpm": 2000.0}}
        ).to_dict()["simulation"]["not_checked"]}
        assert "gain_not_adopted" in reasons


class TestTheTwoRefusalsAreNotTheSame:

    def test_below_the_floor_declines_with_the_count(self, tmp_path):
        payload = _proposed(_session(tmp_path, samples=30, name="few"))
        assert payload["fitted"] == []
        entry = payload["not_fitted"][0]
        assert entry["reason"] == "insufficient_samples"
        assert "29" in entry["detail"]
        assert str(MINIMUM_PAIRED_SAMPLES) in entry["detail"]

    def test_the_floor_is_reported_so_a_reader_can_check_it(self, tmp_path):
        assert _proposed(_session(tmp_path))["checked"]["sample_floor"] == (
            MINIMUM_PAIRED_SAMPLES)

    def test_a_delay_off_the_grid_is_its_own_reason(self, tmp_path):
        """Not `insufficient_samples`. More data cannot fix this one."""
        payload = _proposed(_session(tmp_path, delay=90, samples=400,
                                     name="offgrid"))
        assert payload["fitted"] == []
        entry = payload["not_fitted"][0]
        assert entry["reason"] == "delay_off_grid", (
            "a long series that pairs nothing was reported as a sample "
            "shortage, which sends the author to collect data that cannot help")
        assert "multiple of the sampling interval" in entry["detail"]

    def test_a_delay_on_the_grid_fits_normally(self, tmp_path):
        """Guard: the reason above must not fire on every delayed edge."""
        payload = _proposed(_session(tmp_path, delay=60, samples=300,
                                     name="ongrid"))
        assert payload["not_fitted"] == []
        assert payload["fitted"]

    def test_a_source_that_never_moves_is_unidentifiable(self, tmp_path):
        session = _session(tmp_path, samples=0, name="flat")
        now = api.now_utc()
        for k in range(200):
            when = now - timedelta(seconds=60 * (200 - k))
            session.add_observations("p", "speed_rpm", [(when, 1000.0)])
            session.add_observations("t", "level_pct", [(when, 50.0 + k)])
        entry = _proposed(session)["not_fitted"][0]
        assert entry["reason"] == "unidentifiable_parameter"


class TestTheAccountingIsItsOwn:

    def test_the_counts_partition(self, tmp_path):
        checked = _proposed(_session(tmp_path))["checked"]
        assert checked["fitted"] + checked["not_fitted"] == (
            checked["couplings_seen"])

    def test_a_model_with_no_transitions_fits_nothing_and_says_so(
            self, tmp_path):
        path = tmp_path / "bare.yaml"
        path.write_text("""
domain:
  id: bare
  name: No couplings
  entity_types: [Pump]
  relationship_types: [feeds]
  indicators:
    Pump: [{name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}]
""")
        session = api.EngineSession()
        session.load_model(str(path))
        session.add_entity("p", "Pump", {"speed_rpm": 1000.0})
        payload = _proposed(session)
        assert payload["checked"]["couplings_seen"] == 0
        assert payload["fitted"] == []
