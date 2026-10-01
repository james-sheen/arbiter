"""A cause is read at the instant its declared delays imply, not at the finding's.

A finding is found at one instant, and a cause a declared hop or two
upstream acted earlier, by the dead times declared along the way. `hypothesize`
read every entity at the finding's instant, so a fault that reached the finding
and then cleared was invisible to the ranking. Measured on a pump feeding a
tank feeding a basin, 60 s per edge: a tank fault one delay back, cleared by
the finding's instant, ranked the tank first at 0.415 against the pump's 0.010;
read at their delays, the pump leads at 0.808.

ONLY A DECLARED DELAY MOVES A READ. The engine's own 60 s, which a transition
falls back to, would put a monthly reading on the month before. A model that
declares none gets exactly the evidence, the ranking and the stamps it always
did, and this file holds that as closely as the change itself.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from arbiter_engine import api
from arbiter_engine.clock import as_of

T0 = datetime(2026, 9, 28, 12, 0, 0)


def _edge(kind, source, target, weight, delay, tau, extra=""):
    temporal = ""
    parts = []
    if delay is not None:
        parts.append(f"propagation_delay_s: {delay}")
    if tau is not None:
        parts.append(f"time_constant_s: {tau}")
    if parts:
        temporal = f"      temporal: {{{', '.join(parts)}}}\n"
    return (f"    - type: {kind}\n      source_type: {source}\n"
            f"      target_type: {target}\n      edge_direction: causal\n"
            f"      causal: {{weight: {weight}}}\n{temporal}{extra}")


def _model(feeds=60, spills=60, tau=120, bypass=None, transitions=False):
    """A pump feeds a tank, the tank spills into a basin; delays in seconds or
    None for undeclared, and optionally a direct pump-to-basin bypass."""
    transition = ("      transition: {from: speed_rpm, to: level_pct, gain: 0.02, "
                  "source: datasheet}\n") if transitions else ""
    rules = (_edge("feeds", "Pump", "Tank", 0.8, feeds, tau, transition)
             + _edge("spills", "Tank", "Basin", 0.7, spills, tau))
    types = "[feeds, spills]"
    if bypass is not None:
        rules += _edge("bypasses", "Pump", "Basin", 0.6, bypass, None)
        types = "[feeds, spills, bypasses]"
    return f"""
domain:
  id: read_at_delay
  name: read at delay
  entity_types: [Pump, Tank, Basin]
  relationship_types: {types}
  indicators:
    Pump:
      - {{name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 4000}}
    Tank:
      - {{name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS], warning: 85, critical: 95}}
    Basin:
      - {{name: basin_level, type: NUMERIC, axioms: [BOUNDEDNESS], warning: 40, critical: 60}}
  relationship_rules:
{rules}"""


def _session(model, *, tank=None, pump=None, bypass=False):
    """Checked at T0, with the basin in breach at T0. `tank` and `pump` are
    `(seconds before T0, value)` series; the tank's newest value is current."""
    tank = tank or [(120, 50.0), (60, 97.0), (0, 50.0)]
    pump = pump if pump is not None else [(s, 1000.0) for s in range(300, -1, -30)]
    with as_of(T0):
        session = api.EngineSession()
        session.load_model(model)
        session.add_entity("pump-1", "Pump", {"speed_rpm": pump[-1][1] if pump else 1000.0})
        session.add_entity("tank-1", "Tank", {"level_pct": tank[-1][1]})
        session.add_entity("basin-1", "Basin", {"basin_level": 65.0})
        session.add_relationship("pump-1", "feeds", "tank-1")
        session.add_relationship("tank-1", "spills", "basin-1")
        if bypass:
            session.add_relationship("pump-1", "bypasses", "basin-1")
        session.add_observations(
            "tank-1", "level_pct", [(T0 - timedelta(seconds=s), v) for s, v in tank])
        if pump:
            session.add_observations(
                "pump-1", "speed_rpm", [(T0 - timedelta(seconds=s), v) for s, v in pump])
        session.add_observations("basin-1", "basin_level", [(T0, 65.0)])
        api.check(session)
    return session


def _hypothesis(session):
    with as_of(T0):
        return api.hypothesize(session, "basin-1").to_dict()["hypothesis"]


def _ranking(hypothesis):
    return [(row["cause"], row["posterior"]) for row in hypothesis["candidates"]]


class TestACauseIsReadAtItsDelay:

    def test_a_cleared_fault_one_delay_back_moves_the_ranking(self):
        ranked = _ranking(_hypothesis(_session(_model())))
        assert [cause for cause, _ in ranked] == ["pump-1", "tank-1"], ranked
        assert ranked[0][1] == pytest.approx(0.808468, abs=1e-6)
        assert ranked[1][1] == pytest.approx(0.415239, abs=1e-6)

    def test_without_a_declared_delay_the_finding_is_read_as_before(self):
        hypothesis = _hypothesis(_session(_model(feeds=None, spills=None, tau=None)))
        assert _ranking(hypothesis) == [("tank-1", pytest.approx(0.415239, abs=1e-6)),
                                        ("pump-1", pytest.approx(0.010417, abs=1e-6))]
        assert "read_at" not in hypothesis
        # the pump read clean is screened, on the stamped assumption;
        # and the chain declares weights and no leak.
        assert hypothesis["assumptions"] == ["evidence_severity_not_declared",
                                             "leak_not_declared",
                                             "target_reading_set_aside",
                                             "faults_visible_along_channels"]
        assert all(row["read_at"] is None for row in hypothesis["candidates"])

    def test_each_cause_says_when_it_was_read(self):
        hypothesis = _hypothesis(_session(_model()))
        read_at = hypothesis["read_at"]
        assert read_at["anchor"] == T0.isoformat()
        assert read_at["entities"] == {
            "pump-1": [(T0 - timedelta(seconds=120)).isoformat()],
            "tank-1": [(T0 - timedelta(seconds=60)).isoformat()]}
        rows = {row["cause"]: row for row in hypothesis["candidates"]}
        assert rows["pump-1"]["path"] == ["pump-1->tank-1", "tank-1->basin-1"]
        assert rows["tank-1"]["read_at"] == [(T0 - timedelta(seconds=60)).isoformat()]


class TestOnlyADeclaredDelayMovesARead:

    def test_a_transition_with_no_temporal_block_moves_nothing(self):
        """The edge carries the engine's 60 s for the transition's sake; the
        read ignores it, because nobody declared it."""
        hypothesis = _hypothesis(_session(_model(feeds=None, spills=None, tau=None,
                                                 transitions=True)))
        assert "read_at" not in hypothesis
        assert [cause for cause, _ in _ranking(hypothesis)] == ["tank-1", "pump-1"]

    def test_an_edge_that_declares_none_adds_nothing_and_is_stamped(self):
        hypothesis = _hypothesis(_session(_model(feeds=None, spills=60)))
        assert hypothesis["read_at"]["entities"]["pump-1"] == [
            (T0 - timedelta(seconds=60)).isoformat()]
        assert "time_course_not_declared" in hypothesis["assumptions"]


class TestTheStampsSayWhatTheReadAssumed:

    def test_a_shifted_read_is_stamped(self):
        assert "evidence_read_at_declared_delay" in _hypothesis(
            _session(_model()))["assumptions"]

    @pytest.mark.parametrize("tau, stamped", [(120, True), (None, False)])
    def test_a_declared_time_constant_is_read_at_the_dead_time(self, tau, stamped):
        hypothesis = _hypothesis(_session(_model(tau=tau)))
        assert ("read_at_dead_time" in hypothesis["assumptions"]) is stamped

    def test_paths_of_unequal_delay_are_each_read_and_any_fault_counts(self):
        """The pump reaches the basin through the tank (120 s) and directly
        (10 s); a fault only at the direct path's instant still counts."""
        def tank_posterior(pump):
            hypothesis = _hypothesis(_session(_model(bypass=10), pump=pump,
                                              bypass=True))
            row = next(r for r in hypothesis["candidates"] if r["cause"] == "tank-1")
            return hypothesis, row["posterior"]

        faulted, with_fault = tank_posterior(
            [(300, 1000.0), (120, 1000.0), (10, 4100.0), (0, 1000.0)])
        _clean, without = tank_posterior(
            [(300, 1000.0), (120, 1000.0), (10, 1000.0), (0, 1000.0)])
        assert faulted["read_at"]["entities"]["pump-1"] == [
            (T0 - timedelta(seconds=10)).isoformat(),
            (T0 - timedelta(seconds=120)).isoformat()]
        assert "read_at_each_path_delay" in faulted["assumptions"]
        assert with_fault > without, "the pump's fault did not count as evidence"


class TestAnInstantWithNoReadingIsNamed:

    def test_a_cause_with_no_reading_then_is_left_out_by_name(self):
        """The pump's history starts after the instant its delays imply."""
        pump = [(60, 1000.0), (0, 1000.0)]
        hypothesis = _hypothesis(_session(_model(), pump=pump))
        declined = [d for d in hypothesis["not_checked"]
                    if d["reason"] == "insufficient_samples"]
        assert [d["entity"] for d in declined] == ["pump-1"], declined
        assert declined[0]["evidence"]["read_at"] == [
            (T0 - timedelta(seconds=120)).isoformat()]

    def test_with_a_reading_then_nothing_is_declined(self):
        hypothesis = _hypothesis(_session(_model()))
        assert not [d for d in hypothesis["not_checked"]
                    if d["reason"] == "insufficient_samples"]


class TestTheLiveSessionIsUntouched:

    def test_its_entities_and_last_check_are_as_they_were(self):
        session = _session(_model())
        before = {key: dict(entity.properties) for key, entity in session.entities.items()}
        result, checked_at = session._last_result, session._last_checked_at
        _hypothesis(session)
        assert {key: dict(entity.properties)
                for key, entity in session.entities.items()} == before
        assert session._last_result is result
        assert session._last_checked_at == checked_at

    def test_a_shifted_cause_is_filed_as_a_claim_about_its_instant(self):
        session = _session(_model())
        _hypothesis(session)
        filed = {record.entity_id: record.predicted_at
                 for record in session.ledger._records if record.kind == "stated"}
        assert filed["pump-1"] == T0 - timedelta(seconds=120)
        assert filed["tank-1"] == T0 - timedelta(seconds=60)
