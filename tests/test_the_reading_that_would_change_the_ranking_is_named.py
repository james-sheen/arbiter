"""`hypothesize` names the one reading its ranking rests on most.

One question tests any upward answer: which single reading would
change it? The verb could not say. `evidence_needed` is each candidate's first
declared reading, which is the model's ordering and answers something else.
Measured on a pump feeding a tank feeding a basin: reading the tank faulty
reverses the ranking, the pump rising from 0.010 to 0.808 above the tank's
0.415, and nothing in the answer pointed at the tank.

`most_discriminating` now names it. Where strengths are declared, each outcome
of a reading is weighed by the model's own probability of it given everything
else, and the reading chosen moves the posteriors furthest; a reading already
taken counts only through the outcome it did not give. Where none are declared,
the reading is the candidate on every declared path from the most candidates,
and the assumption that makes that a test is stamped. None of the hypothetical
readings reaches the ledger: a value nobody observed is not a prediction.
"""

from __future__ import annotations

import pytest

from arbiter_engine import api
from arbiter_engine.ontology.domain_loader import load_domain

CHAIN = """
domain:
  id: discriminating_chain
  name: discriminating chain
  entity_types: [Pump, Tank, Basin]
  relationship_types: [feeds, spills]
  indicators:
    Pump:
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 4000}
    Tank:
      - {name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS], warning: 85, critical: 95}
    Basin:
      - {name: basin_level, type: NUMERIC, axioms: [BOUNDEDNESS], warning: 40, critical: 60}
  relationship_rules:
    - {type: feeds, source_type: Pump, target_type: Tank, edge_direction: causal, causal: {weight: 0.8}}
    - {type: spills, source_type: Tank, target_type: Basin, edge_direction: causal, causal: {weight: 0.7}}
"""


def _tree(causal="", members=("m-1", "m-2", "m-3"), led=("t-a", "t-a", "t-b"),
          cases=""):
    """Members lead teams, teams belong to a group; no strength anywhere."""
    model = f"""
domain:
  id: discriminating_tree
  name: discriminating tree
  entity_types: [Group, Team, Member]
  relationship_types: [leads, part_of]
{causal}{cases}
  indicators:
    Group:
      - {{name: score, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 10}}
    Team:
      - {{name: score, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 10}}
    Member:
      - {{name: score, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 10}}
  relationship_rules:
    - {{type: leads, source_type: Member, target_type: Team, edge_direction: causal}}
    - {{type: part_of, source_type: Team, target_type: Group, edge_direction: causal}}
"""
    session = api.EngineSession()
    session.load_model(model)
    session.add_entity("g-1", "Group", {"score": 20.0})
    for team in sorted(set(led)):
        session.add_entity(team, "Team", {"score": 1.0})
        session.add_relationship(team, "part_of", "g-1")
    for member, team in zip(members, led):
        session.add_entity(member, "Member", {"score": 1.0})
        session.add_relationship(member, "leads", team)
    api.check(session)
    return session


def _chain(tank=90.0, pump=1000.0):
    session = api.EngineSession()
    session.load_model(CHAIN)
    session.add_entity("pump-1", "Pump", {"speed_rpm": pump})
    session.add_entity("tank-1", "Tank", {"level_pct": tank})
    session.add_entity("basin-1", "Basin", {"basin_level": 65.0})
    session.add_relationship("pump-1", "feeds", "tank-1")
    session.add_relationship("tank-1", "spills", "basin-1")
    api.check(session)
    return session


def _hypothesis(session, subject="basin-1"):
    return api.hypothesize(session, subject).to_dict()["hypothesis"]


class TestByTheStrengths:

    def test_it_is_the_reading_that_reorders_the_ranking(self):
        named = _hypothesis(_chain())["most_discriminating"]
        assert named["entity"] == "tank-1" and named["reading"] == "tank-1.level_pct"
        assert named["basis"] == "strengths"
        assert named["changes_top_if"] == ["faulty"]
        assert named["expected_change"] > 0

    def test_a_reading_that_moves_nothing_is_not_named_by_the_strengths(
            self, monkeypatch):
        """ -- the move was measured against the ranking's posteriors,
        rounded to six places, from answers that were not rounded, so the
        difference read as a move and a reading could be named with
        `expected_change: 0.0`. Here elimination is stubbed so that no reading
        changes any posterior; the answer then comes from the graph's shape."""
        from arbiter_engine.inference import hypothesis
        monkeypatch.setattr(hypothesis, "eliminate",
                            lambda factors, target, evidence: 0.123456789)
        named = _hypothesis(_chain())["most_discriminating"]
        assert named["basis"] != "strengths"

    def test_the_named_reading_does_reorder_it(self):
        """What the name claims, measured by taking the reading."""
        before = [row["cause"] for row in _hypothesis(_chain())["candidates"]]
        after = [row["cause"] for row in _hypothesis(_chain(tank=97.0))["candidates"]]
        assert before == ["tank-1", "pump-1"] and after == ["pump-1", "tank-1"]

    def test_forcing_a_cause_says_what_it_makes_of_the_finding(self):
        """Given the rest of the evidence, as `infer` answers `do`: the tank read
        clean screens the pump off from the basin."""
        rows = {row["cause"]: row["do_would_answer"]
                for row in _hypothesis(_chain())["candidates"]}
        assert rows == {"tank-1": pytest.approx(0.703, abs=1e-6),
                        "pump-1": pytest.approx(0.01, abs=1e-6)}

    def test_no_hypothetical_reading_is_filed_in_the_ledger(self):
        session = _chain()
        filed = len(session.ledger._records)
        _hypothesis(session)
        assert len(session.ledger._records) - filed == 2, (
            "only the two ranked causes are claims; the weighed readings are not")


class TestByTheShapeOfTheGraph:

    def test_without_strengths_it_is_the_candidate_on_the_most_paths(self):
        hypothesis = _hypothesis(_tree(), subject="g-1")
        assert hypothesis["most_discriminating"] == {
            "entity": "t-a", "reading": "t-a.score", "basis": "structure",
            "splits": [3, 2]}
        assert "faults_visible_along_channels" in hypothesis["assumptions"]

    def test_one_candidate_is_its_own_answer(self):
        hypothesis = _hypothesis(_tree(), subject="t-b")
        assert hypothesis["most_discriminating"] == {
            "entity": "m-3", "reading": "m-3.score", "basis": "only_candidate"}
        assert "faults_visible_along_channels" not in hypothesis["assumptions"]

    def test_a_subject_with_nothing_upstream_names_nothing(self):
        assert _hypothesis(_tree(), subject="m-1")["most_discriminating"] is None


class TestHowFarUpstream:

    def test_undeclared_it_is_four(self):
        hypothesis = _hypothesis(_tree(), subject="g-1")
        assert hypothesis["checked"]["max_hops"] == 4
        assert "depth_exceeded" not in {d["reason"] for d in hypothesis["not_checked"]}

    def test_declared_it_bounds_the_walk_and_counts_what_it_cut(self):
        hypothesis = _hypothesis(_tree(causal="  causal: {max_hops: 1}"), subject="g-1")
        assert hypothesis["checked"]["max_hops"] == 1
        assert hypothesis["checked"]["candidates"] == 2
        assert hypothesis["checked"]["beyond_bound"] == 3
        cut = [d for d in hypothesis["not_checked"] if d["reason"] == "depth_exceeded"]
        assert cut and cut[0]["evidence"] == {"max_hops": 1, "beyond": 3}

    @pytest.mark.parametrize("written", ["0", "true", "'3'", "2.5", "null"])
    def test_a_value_that_is_not_a_whole_number_of_at_least_one_is_refused(self, written):
        model = load_domain(CHAIN.replace(
            "  relationship_types: [feeds, spills]\n",
            f"  relationship_types: [feeds, spills]\n  causal: {{max_hops: {written}}}\n"))
        rows = [r for r in model.unread_fields() if r["field"] == "causal.max_hops"]
        assert rows and rows[0]["reason"] == "malformed_value", rows
        assert "the engine's own 4 was used" in rows[0]["remedy"]

    def test_a_whole_number_is_read(self):
        model = load_domain(CHAIN.replace(
            "  relationship_types: [feeds, spills]\n",
            "  relationship_types: [feeds, spills]\n  causal: {max_hops: 2}\n"))
        assert not [r for r in model.unread_fields() if r["field"].startswith("causal")]


class TestTheCaseKeepsTheWholeRanking:

    def test_every_cause_and_the_named_reading_are_attached(self):
        members = tuple(f"m-{i}" for i in range(1, 8))
        session = _tree(members=members, led=("t-a",) * 7,
                        cases="  cases: {severity: critical, consecutive_checks: 2}\n")
        case = api.open_case(session, "g-1", "score").to_dict()["case"]
        envelope = api.hypothesize(session, "g-1")
        attached = api.attach_stage(session, case["case_id"], "hypothesize",
                                    envelope).to_dict()["case"]
        reference = attached["stages"]["hypothesize"][-1]["reference"]
        assert len(reference["causes"]) == 8, "the ranking was cut at five"
        named = envelope.to_dict()["hypothesis"]["most_discriminating"]
        assert reference["most_discriminating"] == named
        # Seven members all run through one team, so reading the team splits
        # the eight candidates eight to none and says nothing about which; a
        # member splits them one to seven, the most even split there is.
        assert named["basis"] == "structure" and named["splits"] == [1, 7]
