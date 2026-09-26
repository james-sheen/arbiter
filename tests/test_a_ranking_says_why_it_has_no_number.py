"""A ranking of causes with no strength declared says why it has no numbers.

Found by the first vertical to declare fault channels the way the plan asked --
the direction a failure travels, and no strength, because nothing gives one.
`infer` on such a model declines `cpt_missing`, by name. `hypothesize` ran that
same inference for each candidate, kept its posterior (`None`) and its stamps,
and dropped its declines: the ranking came back with every posterior `null` and
an empty `not_checked`, which reads as an answer with nothing wrong in it.
"""

from __future__ import annotations

from arbiter_engine import api
from arbiter_engine.subenvelope import VOCABULARIES

from test_a_finding_says_where_to_look_next import CRITICAL, _session as _declared


def _undeclared_strengths():
    session = api.EngineSession()
    session.load_model({"domain": {
        "id": "o", "name": "an organisation", "entity_types": ["Exec", "Dept"],
        "relationship_types": ["leads"],
        "indicators": {
            "Dept": [{"name": "margin", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
                      "critical": 50, "lower_critical": 1}],
            "Exec": [{"name": "load", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
                      "critical": 9}]},
        "relationship_rules": [{"type": "leads", "source_type": "Exec",
                                "target_type": "Dept", "edge_direction": "causal"}],
    }})
    session.add_entity("e1", "Exec", {"load": 1.0})
    session.add_entity("e2", "Exec", {"load": 1.0})
    session.add_entity("d1", "Dept", {"margin": 0.5})
    session.add_relationship("e1", "leads", "d1")
    session.add_relationship("e2", "leads", "d1")
    api.check(session)
    return session


def test_the_ranking_declines_what_its_inferences_declined():
    hypothesis = api.hypothesize(_undeclared_strengths(), "d1").to_dict()["hypothesis"]
    assert "cpt_missing" in {d["reason"] for d in hypothesis["not_checked"]}
    assert {d["reason"] for d in hypothesis["not_checked"]} <= VOCABULARIES["inference"]


def test_each_cause_says_why_it_has_no_posterior():
    candidates = api.hypothesize(_undeclared_strengths(), "d1").to_dict()["hypothesis"]["candidates"]
    assert {c["cause"] for c in candidates} == {"e1", "e2"}
    for candidate in candidates:
        assert candidate["posterior"] is None
        assert candidate["declined"] == ["cpt_missing"]


def test_one_missing_strength_is_one_decline_not_one_per_candidate():
    declines = api.hypothesize(_undeclared_strengths(), "d1").to_dict()["hypothesis"]["not_checked"]
    keys = [(d["reason"], tuple(sorted((k, str(v)) for k, v in d.items()
                                       if k not in ("reason", "detail", "evidence"))))
            for d in declines]
    assert len(keys) == len(set(keys))


def test_a_ranking_with_its_strengths_declared_declines_nothing():
    hypothesis = api.hypothesize(_declared(*CRITICAL), "pnl-a").to_dict()["hypothesis"]
    assert all(c["declined"] == [] for c in hypothesis["candidates"])
    assert all(c["posterior"] is not None for c in hypothesis["candidates"])
