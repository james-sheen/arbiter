"""A confirmed row says what its ranking rested on, and counts a reading of the named entity.

`confirmed_causes` reported where a confirmed cause stood, and not
why it stood there. With no strength declared every posterior is null, and
`hypothesize` orders its causes nearest hop first, then by entity id: measured
on an organisation model, a confirmed cause stood "rank 1 of 2" because its id
sorts first, and `ranked_first` counted it with the rest. Each row now says
`ranked_by` -- `posterior`, `hops` or `mixed` -- and `named_by`, the basis of the
reading the ranking named, and `ranked_first_by_posterior` counts only the first
places a posterior decided.

And the reading a ranking names is its type's first declared value, whatever
decides that entity's state, so a person who settled the named entity on
another of its readings was counted as not named. `settling_entity_was_named`
asks whether the settling reading is on the named entity. Every earlier field
keeps its meaning.
"""

from __future__ import annotations

import pytest

from arbiter_engine import api
from arbiter_engine.residual.cases import Case, confirmed_causes


def _case(causes, *, cause, named=None, reading=None, case_id="c-1"):
    """A case holding one ranking, then one confirmation of `cause`."""
    case = Case(case_id=case_id, entity_id="unit-z", indicator="load",
                opened_at="2026-09-28T12:00:00", basis="a test",
                severity="warning", consecutive_checks=2)
    case.stages["hypothesize"].append({
        "at": "2026-09-28T12:01:00",
        "reference": {"causes": [{"cause": c, "posterior": p} for c, p in causes],
                      "most_discriminating": named}})
    reference = {"cause": cause}
    if reading is not None:
        reference["reading"] = reading
    case.stages["confirm"].append({"at": "2026-09-28T12:05:00",
                                   "reference": reference})
    return case


def _row(case):
    [row] = confirmed_causes([case])["rows"]
    return row


class TestWhatTheRankingRestedOn:

    def test_a_ranking_by_posteriors_says_so_and_counts_its_first_place(self):
        book = confirmed_causes([_case([("unit-a", 0.8), ("unit-b", 0.4)],
                                       cause="unit-a")])
        assert book["rows"][0]["ranked_by"] == "posterior"
        assert (book["ranked_first"], book["ranked_by_posterior"],
                book["ranked_first_by_posterior"]) == (1, 1, 1)

    def test_without_a_posterior_the_rank_is_hop_order_and_is_not_counted_as_one(self):
        book = confirmed_causes([_case([("unit-a", None), ("unit-b", None)],
                                       cause="unit-a")])
        assert book["rows"][0]["ranked_by"] == "hops"
        # `ranked_first` keeps its meaning; the new count separates the kinds.
        assert (book["ranked_first"], book["ranked_by_posterior"],
                book["ranked_first_by_posterior"]) == (1, 0, 0)

    def test_some_of_each_is_mixed(self):
        row = _row(_case([("unit-a", 0.7), ("unit-b", None)], cause="unit-b"))
        assert (row["rank"], row["ranked_by"]) == (2, "mixed")

    def test_a_cause_the_ranking_did_not_hold_has_no_basis(self):
        row = _row(_case([("unit-a", 0.7)], cause="unit-q"))
        assert (row["rank"], row["ranked_by"]) == (None, None)

    @pytest.mark.parametrize("basis", ["strengths", "structure", "only_candidate"])
    def test_named_by_is_the_named_readings_basis(self, basis):
        row = _row(_case([("unit-a", None), ("unit-b", None)], cause="unit-a",
                         named={"entity": "unit-b", "reading": "unit-b.load",
                                "basis": basis}))
        assert row["named_by"] == basis


class TestAReadingOfTheNamedEntity:

    NAMED = {"entity": "unit-a", "reading": "unit-a.temp", "basis": "structure"}

    def test_another_reading_of_the_named_entity_counts_as_the_entity_named(self):
        book = confirmed_causes([_case([("unit-a", None)], cause="unit-a",
                                       named=self.NAMED, reading="unit-a.load")])
        row = book["rows"][0]
        assert (row["settling_reading_was_named"],
                row["settling_entity_was_named"]) == (False, True)
        assert (book["settling_reading_was_named"],
                book["settling_entity_was_named"]) == (0, 1)

    def test_the_named_reading_itself_counts_both_ways(self):
        row = _row(_case([("unit-a", None)], cause="unit-a", named=self.NAMED,
                         reading="unit-a.temp"))
        assert (row["settling_reading_was_named"],
                row["settling_entity_was_named"]) == (True, True)

    def test_an_entity_whose_id_extends_the_named_one_is_another_entity(self):
        row = _row(_case([("unit-a", None)], cause="unit-a", named=self.NAMED,
                         reading="unit-ab.load"))
        assert row["settling_entity_was_named"] is False

    def test_unasked_is_not_a_no(self):
        assert _row(_case([("unit-a", None)], cause="unit-a",
                          named=self.NAMED))["settling_entity_was_named"] is None
        assert _row(_case([("unit-a", None)], cause="unit-a",
                          reading="unit-a.load"))["settling_entity_was_named"] is None


def _loop(strengths):
    """Three members lead two teams in one group; a finding on the group, and
    nothing read below it, so every candidate is a question the ranking asks."""
    weight = ", causal: {weight: 0.8}" if strengths else ""
    session = api.EngineSession()
    session.load_model(f"""
domain:
  id: rested_on
  name: rested on
  entity_types: [Group, Team, Member]
  relationship_types: [leads, part_of]
  cases: {{severity: warning, consecutive_checks: 2}}
  indicators:
    Group:
      - {{name: score, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 10}}
    Team:
      - {{name: score, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 10}}
    Member:
      - {{name: score, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 10}}
      - {{name: rating, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 10}}
  relationship_rules:
    - {{type: leads, source_type: Member, target_type: Team, edge_direction: causal{weight}}}
    - {{type: part_of, source_type: Team, target_type: Group, edge_direction: causal{weight}}}
""")
    session.add_entity("g-1", "Group", {"score": 20.0})
    for team in ("t-a", "t-b"):
        session.add_entity(team, "Team", {})
        session.add_relationship(team, "part_of", "g-1")
    for member, team in (("m-1", "t-a"), ("m-2", "t-a"), ("m-3", "t-b")):
        session.add_entity(member, "Member", {})
        session.add_relationship(member, "leads", team)
    api.check(session)
    case_id = api.open_case(session, "g-1", "score",
                            basis="a test").to_dict()["case"]["case_id"]
    api.attach_stage(session, case_id, "hypothesize", api.hypothesize(session, "g-1"))
    return session, case_id


class TestOnARealRanking:

    def test_with_no_strengths_the_row_says_hops_and_structure(self):
        session, case_id = _loop(strengths=False)
        api.attach_stage(session, case_id, "confirm",
                         reference={"cause": "t-a", "reading": "t-a.score"})
        row = api.case_book(session).to_dict()["cases"]["confirmed"]["rows"][0]
        assert (row["ranked_by"], row["named_by"]) == ("hops", "structure")

    def test_with_strengths_the_row_says_posterior(self):
        session, case_id = _loop(strengths=True)
        api.attach_stage(session, case_id, "confirm", reference={"cause": "t-a"})
        book = api.case_book(session).to_dict()["cases"]["confirmed"]
        assert book["rows"][0]["ranked_by"] == "posterior"
        assert book["ranked_by_posterior"] == 1
