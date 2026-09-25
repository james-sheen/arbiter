"""`n` and `r_squared` say how well a gain fits. They do not say it helps.

Phase B1. A fitted gain has carried its evidence since the learner
shipped -- the sample count, the coefficient of determination, the confidence
interval. Every one of those answers *how well does this number fit the data it
was fitted on*, and none of them answers the question an author actually has,
which is *would adopting it have caught more of what happened*.

Those come apart. A gain can fit a window almost exactly and change no verdict,
because the axioms it feeds were nowhere near a threshold in that window; and a
gain with a middling r-squared can move a trajectory across a declared line and
turn a miss into a hit. So the second question is answered by REPLAY: score the
corpus as the model is declared, score it again with the proposal substituted,
and report both.

TWO THINGS THIS FILE HOLDS THAT THE PHASE PLAN GOT WRONG.

The plan asked for `{hit_rate_before, hit_rate_after}`. `SurpriseScore` carries
NO rate, deliberately -- the one real corpus this project holds answers two
different questions whose merger into a single attribute is the defect CLM-014
exists to prevent, and a ratio here would reintroduce it one level down, in a
field a reader would quote precisely because it looks comparable. The counts
travel with their denominator instead.

And a proposal with no corpus is REFUSED, not scored. `replay_unavailable`
carries its reason, for the same rule the benchmark already applies to a window
that never observed its subject: a proposal nobody could test is not a proposal
that failed, and a zero cannot tell those apart.
"""

from __future__ import annotations

import random
from datetime import timedelta

import pytest

from arbiter_engine import api
from arbiter_engine.surprises import (
    REPLAY_UNAVAILABLE, load_surprises)

MODEL = """
domain:
  id: replaylearn
  name: One declared coupling, fitted and replayed
  entity_types: [Pump, Tank]
  relationship_types: [feeds]
  indicators:
    Pump: [{name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}]
    Tank: [{name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS], warning: 60}]
  relationship_rules:
    - type: feeds
      source_type: Pump
      target_type: Tank
      temporal:
        propagation_delay_s: 0
        time_constant_s: 1
        response_model: step
      transition:
        from: speed_rpm
        to: level_pct
        gain: estimate
        source: datasheet
"""


def _session(tmp_path, *, true_gain=0.02, samples=200, interval=60):
    path = tmp_path / "m.yaml"
    path.write_text(MODEL)
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
        level += true_gain * step
        when = now - timedelta(seconds=interval * (samples - k))
        session.add_observations("p", "speed_rpm", [(when, speed)])
        session.add_observations("t", "level_pct", [(when, level)])
    return session


def _fitted(session, surprises=None):
    payload = api.model_describe(session, surprises).to_dict()["model"]
    return payload["proposed_transitions"]["fitted"]


class TestTheFixtureReallyProducesAProposal:
    """The premise. Everything below measures nothing if nothing fits."""

    def test_one_gain_is_fitted(self, tmp_path):
        fitted = _fitted(_session(tmp_path))
        assert len(fitted) == 1, f"expected one proposal, got {fitted}"

    def test_it_carries_the_evidence_it_always_did(self, tmp_path):
        entry = _fitted(_session(tmp_path))[0]
        for key in ("n", "r_squared", "interval", "gain"):
            assert key in entry, f"{key} is no longer reported"


class TestWithoutACorpusItIsARefusal:

    def test_the_status_is_the_refusal_and_not_a_number(self, tmp_path):
        replay = _fitted(_session(tmp_path))[0]["replay"]
        assert replay["status"] == REPLAY_UNAVAILABLE

    def test_it_carries_a_reason_a_reader_can_act_on(self, tmp_path):
        replay = _fitted(_session(tmp_path))[0]["replay"]
        assert "corpus" in replay["reason"]

    def test_no_count_is_reported_as_zero(self, tmp_path):
        """The whole point. A proposal scored zero for want of a record reads
        exactly like one that was tested and found useless."""
        replay = _fitted(_session(tmp_path))[0]["replay"]
        for key in ("detected_before", "detected_after", "delta"):
            assert key not in replay, (
                f"{key} is present on a replay that never ran, and a reader "
                f"cannot tell that from a replay that ran and found nothing")


class TestWithACorpusItReportsCounts:

    CORPUS = {
        "surprises": {
            "domain": "replaylearn",
            "entries": [{
                "id": "tank-high",
                "description": "the tank sat above its warning line",
                "subject": {"entity": "t", "type": "Tank",
                            "property": "level_pct"},
                "window": {"start": "2026-01-01T00:00:00",
                           "end": "2026-01-01T01:00:00"},
                "counts_as_detected_when": {
                    "axiom": "BOUNDEDNESS",
                    "severity_in": ["warning", "high", "critical"]},
                "confirmed": True,
                "anticipated": False,
                "source": "fixture, not a field record",
            }],
        }
    }

    def _corpus(self):
        corpus, declines = load_surprises(self.CORPUS)
        assert not declines, f"the fixture corpus has unread keys: {declines}"
        return corpus

    def test_the_replay_ran(self, tmp_path):
        replay = _fitted(_session(tmp_path), self._corpus())[0]["replay"]
        assert replay["status"] == "replayed", replay

    def test_it_reports_counts_with_their_denominator(self, tmp_path):
        replay = _fitted(_session(tmp_path), self._corpus())[0]["replay"]
        for key in ("confirmed", "detected_before", "detected_after", "delta"):
            assert key in replay, f"{key} missing from {replay}"
        assert replay["delta"] == (replay["detected_after"]
                                   - replay["detected_before"])

    def test_it_reports_no_rate(self, tmp_path):
        """The correction to the phase plan, held here so it cannot drift
        back: a ratio is what merged two senses of the alpha figure, and this
        field would be quoted precisely because it looks comparable."""
        replay = _fitted(_session(tmp_path), self._corpus())[0]["replay"]
        assert not [k for k in replay if "rate" in k], (
            f"a rate reappeared on a replay: {sorted(replay)}")


class TestTheEngineIsStillNotAnEditor:
    """The governance claim, and the one worth a test of its own. Replay has to
    substitute the proposal to measure it; leaving it there would make the
    engine an editor, which is what every proposal surface here refuses."""

    def test_the_declared_gain_is_unchanged_afterwards(self, tmp_path):
        session = _session(tmp_path)
        rule = session.model.relationship_rules[0]
        before = rule["transition"]["gain"]
        _fitted(session, TestWithACorpusItReportsCounts()._corpus())
        assert rule["transition"]["gain"] == before, (
            f"the model's declared gain is now {rule['transition']['gain']!r}, "
            f"was {before!r} — replay edited the model it was measuring")

    def test_it_is_restored_even_when_the_replay_finds_nothing(self, tmp_path):
        session = _session(tmp_path)
        rule = session.model.relationship_rules[0]
        before = rule["transition"]["gain"]
        _fitted(session)
        assert rule["transition"]["gain"] == before
