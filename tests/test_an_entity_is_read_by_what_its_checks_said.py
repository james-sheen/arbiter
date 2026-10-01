"""An entity is read by what its checks said, not by which records are absent.

The inference used to call an entity faulty on a finding at the evidence floor,
leave it out on a decline of any reason, and call it clean otherwise. So an
entity nothing was checked on read clean, and an entity carrying a decline no
reading could cure -- a threshold nobody declared -- could never read clean at
all. On a consulting model that declares no threshold for most of what it reads,
that was every unit.

Each entity now has a state from its own checks: `faulty`, `deviating`,
`clean`, `partial` or `unread`. A check is one declared axiom on one declared
indicator, and it ran unless it declined. Which declines block `clean` is
answered by who would cure them: a reading, a declaration, nobody, or the
engine. Counting an entity clean beside declines no reading would cure is the
ruling the posterior stamps.
"""

from __future__ import annotations

import pytest

from arbiter_engine.api import EngineSession, check, hypothesize
from arbiter_engine.assumptions import CLEAN_BESIDE_DECLINES_NO_READING_CURES
from arbiter_engine.inference.runner import Query, entity_evidence, run_inference
from arbiter_engine.types import (DECLINE_REMEDIES, DECLINE_REMEDY,
                                              NotEvaluatedReason, decline_remedy)


def _model(unit_indicators):
    """A unit feeding a tank along a declared causal edge."""
    return {"domain": {
        "id": "evidence", "name": "Evidence",
        "entity_types": ["Unit", "Tank"],
        "relationship_types": ["feeds"],
        "relationship_rules": [{"type": "feeds", "source_type": "Unit",
                                "target_type": "Tank", "edge_direction": "causal",
                                "causal": {"weight": 0.6, "leak": 0.01}}],
        "indicators": {
            "Unit": unit_indicators,
            "Tank": [{"name": "level", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
                      "window": "1h", "critical": 95}]}}}


BOUNDED = {"name": "load", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
           "window": "1h", "warning": 5, "critical": 10}
UNBOUNDED = {"name": "spare", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
             "window": "1h"}
SECOND = {"name": "temp", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
          "window": "1h", "critical": 10}


def _session(unit_indicators, unit_properties):
    session = EngineSession()
    session.load_model(_model(unit_indicators))
    session.add_entity("u1", "Unit", unit_properties)
    session.add_entity("t1", "Tank", {"level": 99.0})
    session.add_relationship("u1", "feeds", "t1")
    check(session)
    return session


def _evidence(session, entity_id="u1"):
    return entity_evidence(session, entity_id)


class TestWhoWouldCureEachDecline:

    def test_every_reason_has_an_answer(self):
        assert set(DECLINE_REMEDY) == {r.value for r in NotEvaluatedReason}
        assert set(DECLINE_REMEDY.values()) <= set(DECLINE_REMEDIES)

    @pytest.mark.parametrize("reason,remedy", [
        ("insufficient_samples", "reading"), ("missing_property", "reading"),
        ("missing_config", "declaration"), ("no_threshold", "declaration"),
        ("missing_role", "declaration"), ("no_rule_for_role", "nobody"),
        ("undefined_for_values", "nobody"), ("checker_error", "engine"),
        ("not_applicable", "engine")])
    def test_the_answer_the_guide_gives(self, reason, remedy):
        assert decline_remedy(reason) == remedy

    def test_a_reason_nobody_classified_never_reads_clean(self):
        assert decline_remedy("a_reason_from_a_newer_engine") == "reading"


class TestTheFiveStates:

    def test_a_check_that_ran_and_passed_beside_a_missing_threshold_is_clean(self):
        summary = _evidence(_session([BOUNDED, UNBOUNDED], {"load": 1.0, "spare": 3.0}))
        assert summary["state"] == "clean", summary
        assert summary["looked"] == [1, 2]
        assert summary["declines_no_reading_cures"] == ["no_threshold"]
        assert summary["needs"] == []

    def test_a_reading_the_check_could_not_take_makes_it_partial(self):
        """`temp` ran and passed; `load` was never supplied."""
        summary = _evidence(_session([BOUNDED, SECOND], {"temp": 1.0}))
        assert summary["state"] == "partial", summary
        assert summary["looked"] == [1, 2]
        assert summary["needs"] == [{"reading": "u1.load", "reason": "missing_property"}]

    def test_every_check_declining_is_unread_whatever_the_reasons(self):
        """`load` was never supplied and `spare` has no threshold: nothing ran."""
        summary = _evidence(_session([BOUNDED, UNBOUNDED], {"spare": 3.0}))
        assert summary["state"] == "unread", summary
        assert summary["looked"] == [0, 2]

    def test_nothing_ran_is_unread_never_clean(self):
        summary = _evidence(_session([], {}))
        assert summary["state"] == "unread", summary
        assert summary["looked"] == [0, 0]

    def test_a_finding_at_the_floor_is_faulty(self):
        summary = _evidence(_session([BOUNDED], {"load": 12.0}))
        assert summary["state"] == "faulty", summary
        assert summary["findings"]

    def test_a_finding_below_the_floor_is_deviating(self):
        summary = _evidence(_session([BOUNDED], {"load": 7.0}))
        assert summary["state"] == "deviating", summary
        assert summary["severity"] == "warning"


class TestThePosteriorReadsTheStates:

    def test_clean_beside_a_missing_threshold_is_evidence_and_says_so(self):
        session = _session([BOUNDED, UNBOUNDED], {"load": 1.0, "spare": 3.0})
        sub = run_inference(session, Query(target="t1")).to_dict()
        assert sub["checked"]["evidence"] == 1
        assert CLEAN_BESIDE_DECLINES_NO_READING_CURES in sub.get("assumptions", [])

    def test_partial_is_left_out_and_nothing_is_stamped(self):
        session = _session([BOUNDED, SECOND], {"temp": 1.0})
        sub = run_inference(session, Query(target="t1")).to_dict()
        assert sub["checked"]["evidence"] == 0
        assert CLEAN_BESIDE_DECLINES_NO_READING_CURES not in sub.get("assumptions", [])

    def test_unread_is_left_out(self):
        sub = run_inference(_session([], {}), Query(target="t1")).to_dict()
        assert sub["checked"]["evidence"] == 0


class TestACandidateCarriesWhatItsChecksSaid:

    def test_each_candidate_has_its_evidence(self):
        session = _session([BOUNDED, SECOND], {"temp": 1.0})
        leg = hypothesize(session, "t1").to_dict()["hypothesis"]
        evidence = {row["cause"]: row["evidence"] for row in leg["candidates"]}
        assert evidence["u1"]["state"] == "partial"
        assert evidence["u1"]["needs"] == [{"reading": "u1.load",
                                            "reason": "missing_property"}]

    def test_an_unread_candidate_has_no_own_reading_to_report(self):
        session = _session([], {})
        leg = hypothesize(session, "t1").to_dict()["hypothesis"]
        row = next(r for r in leg["candidates"] if r["cause"] == "u1")
        assert row["own_reading"] is None
        assert row["evidence"]["state"] == "unread"
