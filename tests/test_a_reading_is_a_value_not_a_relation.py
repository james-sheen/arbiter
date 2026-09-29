"""A reading named to a person is a value they can take, never a relation.

`hypothesize` names the reading its ranking rests on most, and each
candidate's `evidence_needed`, as the type's first declared reading. It took the
first declared INDICATOR, relationship ones included, so on a model whose types
list the edges they must have before their values, every name was a relation:
`dept-sales.reports_to`, an edge CONNECTIVITY checks against the graph, where the
department declares a headcount anyone can read. A RELATIONSHIP indicator is now
skipped by its declared type, and a type that declares only relations names no
reading and says so with null. `gaps` names the reading on an undeclared channel
by the same rule.
"""

from __future__ import annotations

from arbiter_engine import api


def _tree(member_values=True):
    """Members lead teams and teams belong to a group, and every type lists the
    edge it must have BEFORE the values it reports -- the order that exposed it."""
    member = ("      - {name: score, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 10}\n"
              if member_values else "")
    model = f"""
domain:
  id: reading_is_a_value
  name: reading is a value
  entity_types: [Group, Team, Member]
  relationship_types: [leads, part_of]
  indicators:
    Group:
      - {{name: score, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 10}}
    Team:
      - {{name: belongs, type: RELATIONSHIP, axioms: [CONNECTIVITY], target_type: Group, relation_type: part_of, min_cardinality: 1}}
      - {{name: score, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 10}}
    Member:
      - {{name: leads_a_team, type: RELATIONSHIP, axioms: [CONNECTIVITY], target_type: Team, relation_type: leads, min_cardinality: 1}}
{member}  relationship_rules:
    - {{type: leads, source_type: Member, target_type: Team, edge_direction: causal}}
    - {{type: part_of, source_type: Team, target_type: Group, edge_direction: causal}}
"""
    session = api.EngineSession()
    session.load_model(model)
    session.add_entity("g-1", "Group", {"score": 20.0})
    for team in ("t-a", "t-b"):
        session.add_entity(team, "Team", {"score": 1.0})
        session.add_relationship(team, "part_of", "g-1")
    for member, team in (("m-1", "t-a"), ("m-2", "t-a"), ("m-3", "t-b")):
        session.add_entity(member, "Member", {"score": 1.0} if member_values else {})
        session.add_relationship(member, "leads", team)
    api.check(session)
    return session


def _hypothesis(session, subject="g-1"):
    return api.hypothesize(session, subject).to_dict()["hypothesis"]


class TestTheReadingNamedIsAValue:

    def test_the_ranking_names_the_teams_score_not_its_edge(self):
        named = _hypothesis(_tree())["most_discriminating"]
        assert named["entity"] == "t-a" and named["basis"] == "structure"
        assert named["reading"] == "t-a.score"

    def test_every_candidate_asks_for_a_value(self):
        rows = {row["cause"]: row["evidence_needed"]
                for row in _hypothesis(_tree())["candidates"]}
        assert rows == {"t-a": "t-a.score", "t-b": "t-b.score",
                        "m-1": "m-1.score", "m-2": "m-2.score", "m-3": "m-3.score"}

    def test_a_type_that_declares_only_a_relation_names_no_reading(self):
        """The entity is still the one to look at; there is no value to name."""
        hypothesis = _hypothesis(_tree(member_values=False), subject="t-b")
        assert hypothesis["most_discriminating"] == {
            "entity": "m-3", "reading": None, "basis": "only_candidate"}
        assert [row["evidence_needed"] for row in hypothesis["candidates"]] == [None]


class TestGapsNamesAValueOnAChannelNobodyDeclared:

    def test_the_reading_on_an_undeclared_channel_skips_the_sources_relations(self):
        session = api.EngineSession()
        session.load_model("""
domain:
  id: channel_reading
  name: channel reading
  entity_types: [Valve, Tank]
  relationship_types: [vents]
  indicators:
    Valve:
      - {name: vents_a_tank, type: RELATIONSHIP, axioms: [CONNECTIVITY], target_type: Tank, relation_type: vents, min_cardinality: 1}
      - {name: open_pct, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 100}
    Tank:
      - {name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 95}
  relationship_rules:
    - {type: vents, source_type: Valve, target_type: Tank}
""")
        session.add_entity("valve-1", "Valve", {"open_pct": 10.0})
        session.add_entity("tank-1", "Tank", {"level_pct": 50.0})
        session.add_relationship("valve-1", "vents", "tank-1")
        candidates, needed = api._undeclared_channels(session, "tank-1", "level_pct")
        assert candidates == ["vents"]
        assert needed == "valve-1.open_pct"
