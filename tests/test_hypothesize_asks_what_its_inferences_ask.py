"""`hypothesize` carries the questions the inferences behind it raise.

Each candidate is scored by an inference, and an inference that needs an edge
nobody gave a strength asks for one: *how strongly does a fault at P1 break
T1?* `infer` returns that question. `hypothesize` returned the decline beside
the ranking and dropped the question, so a ranking that could not be scored
said what was missing and never asked for it. It asks once per edge, however
many candidates rest on that edge.
"""

from __future__ import annotations

from arbiter_engine import api

MODEL = """
domain:
  id: chain-of-causes
  name: Chain of causes
  entity_types: [Pump, Valve, Tank]
  relationship_types: [feeds]
  indicators:
    Pump:
      - name: speed_rpm
        type: NUMERIC
        axioms: [BOUNDEDNESS]
        warning: 3000
        critical: 3500
    Valve:
      - name: opening_pct
        type: NUMERIC
        axioms: [BOUNDEDNESS]
        warning: 85
        critical: 95
    Tank:
      - name: level_pct
        type: NUMERIC
        axioms: [BOUNDEDNESS]
        warning: 85
        critical: 95
  relationship_rules:
    - type: feeds
      source_type: Pump
      target_type: Valve
      edge_direction: causal
{weight}
    - type: feeds
      source_type: Valve
      target_type: Tank
      edge_direction: causal
{weight}
"""

WEIGHT = "      causal: {weight: 0.6, leak: 0.01}"


def _session(weighted: bool) -> api.EngineSession:
    session = api.EngineSession()
    session.load_model(MODEL.replace("{weight}", WEIGHT if weighted else ""))
    session.add_entity("P1", "Pump", {"speed_rpm": 1500.0})
    session.add_entity("V1", "Valve", {"opening_pct": 50.0})
    session.add_entity("T1", "Tank", {"level_pct": 99.0})
    session.add_relationship("P1", "feeds", "V1")
    session.add_relationship("V1", "feeds", "T1")
    api.check(session)
    return session


def _texts(questions) -> list:
    return [q.get("question") or q.get("question_text") or q.get("text") or str(q)
            for q in questions or []]


def test_an_unweighted_edge_is_asked_about():
    session = _session(weighted=False)
    asked = _texts(api.hypothesize(session, "T1").to_dict()["hypothesis"].get("questions"))
    inferred = _texts(api.infer(session, "T1").to_dict()["inference"].get("questions"))
    assert inferred, "the probe's inference raised no question to compare with"
    for text in inferred:
        assert text in asked, (text, asked)


def test_each_edge_is_asked_about_once():
    """Both candidates rest on the edge into the tank, and the question about
    it appears once."""
    asked = _texts(api.hypothesize(_session(weighted=False), "T1")
                   .to_dict()["hypothesis"].get("questions"))
    assert len(asked) == len(set(asked)), asked
    assert any("V1 break T1" in text for text in asked), asked


def test_a_weighted_edge_raises_no_question():
    leg = api.hypothesize(_session(weighted=True), "T1").to_dict()["hypothesis"]
    assert not leg.get("questions"), leg.get("questions")
