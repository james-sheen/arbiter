"""A leak nobody declared is spent, and the answer says so.

a weight nobody declared stops the answer, by name, because a
posterior is a product of weights and one the engine chose would make the
number partly a statement about the engine. The LEAK -- the chance a node is
faulty with no faulty parent -- was spent instead, and nothing said so, though
the engine's own comment beside it said it was refused. Measured on one declared
edge of 0.8: the answer is 0.808468 with no leak and with a leak of 0.01
declared, and 0.181034 with 0.2. The engine's number decided it.

It is spent still, and stamped `leak_not_declared` wherever it reaches the
answer: at each node at the head of an edge the answer depends on, the leak in
effect is the largest its incoming rules give, and the stamp says when that is
the engine's.
"""

from __future__ import annotations

import pytest

from arbiter_engine import api
from arbiter_engine.assumptions import ASSUMPTION_STAMPS, LEAK_NOT_DECLARED


def _rule(kind, source, weight=0.8, leak=None):
    causal = {} if weight is None else {"weight": weight}
    if leak is not None:
        causal["leak"] = leak
    return {"type": kind, "source_type": source, "target_type": "Tank",
            "edge_direction": "causal", "causal": causal}


def _session(*rules, readings=None):
    """A pump and, where a second rule names it, a valve, each feeding a tank."""
    sources = [rule["source_type"] for rule in rules]
    model = {"domain": {
        "id": "leak", "name": "leak",
        "entity_types": sorted(set(sources)) + ["Tank"],
        "relationship_types": [rule["type"] for rule in rules],
        "indicators": dict(
            {source: [{"name": "load", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
                       "critical": 10}] for source in sources},
            Tank=[{"name": "level", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
                   "critical": 95}]),
        "relationship_rules": list(rules)}}
    session = api.EngineSession()
    session.load_model(model)
    session.add_entity("t", "Tank", {"level": 99.0})
    for rule in rules:
        entity = rule["source_type"].lower()
        session.add_entity(entity, rule["source_type"], {"load": 1.0})
        session.add_relationship(entity, rule["type"], "t")
    api.check(session)
    return session


def _answer(session, target="pump"):
    return api.infer(session, target).to_dict()["inference"]


class TestTheStamp:

    def test_a_leak_nobody_declared_is_stamped(self):
        answer = _answer(_session(_rule("feeds", "Pump")))
        assert LEAK_NOT_DECLARED in answer["assumptions"]

    def test_it_is_the_engines_number_that_decided(self):
        """Undeclared and a declared 0.01 give one answer: the engine's."""
        unstamped = _answer(_session(_rule("feeds", "Pump", leak=0.01)))
        stamped = _answer(_session(_rule("feeds", "Pump")))
        assert stamped["checked"]["posterior"] == unstamped["checked"]["posterior"]
        assert LEAK_NOT_DECLARED not in unstamped["assumptions"]

    def test_a_declared_leak_is_not_stamped(self):
        answer = _answer(_session(_rule("feeds", "Pump", leak=0.2)))
        assert answer["checked"]["posterior"] == pytest.approx(0.181034, abs=1e-6)
        assert LEAK_NOT_DECLARED not in answer["assumptions"]

    def test_a_weight_nobody_declared_stops_the_answer_before_the_leak(self):
        answer = _answer(_session(_rule("feeds", "Pump", weight=None)))
        assert "cpt_missing" in {d["reason"] for d in answer["not_checked"]}
        assert LEAK_NOT_DECLARED not in (answer.get("assumptions") or [])


class TestTheLeakInEffectIsTheLargest:
    """A pump and a valve both feed the tank, each by its own rule."""

    def test_one_declared_below_the_engines_beside_one_undeclared_is_stamped(self):
        session = _session(_rule("feeds", "Pump", leak=0.005), _rule("vents", "Valve"))
        assert LEAK_NOT_DECLARED in _answer(session)["assumptions"]

    def test_one_declared_above_it_is_the_one_in_effect(self):
        session = _session(_rule("feeds", "Pump", leak=0.2), _rule("vents", "Valve"))
        assert LEAK_NOT_DECLARED not in _answer(session)["assumptions"]


class TestEveryReaderSaysTheSame:

    def test_a_ranking_carries_the_stamp_its_inferences_made(self):
        leg = api.hypothesize(_session(_rule("feeds", "Pump")), "t").to_dict()["hypothesis"]
        assert LEAK_NOT_DECLARED in leg["assumptions"]

    @pytest.mark.parametrize("leak,source", [(None, "default"), (0.2, "declared")])
    def test_the_model_reports_the_leak_by_the_same_predicate(self, leak, source):
        session = _session(_rule("feeds", "Pump", leak=leak))
        [rule] = api.model_describe(session).to_dict()["model"]["causal"]["declared"]
        assert rule["leak_source"] == source

    def test_the_stamp_is_in_the_published_vocabulary(self):
        assert LEAK_NOT_DECLARED in ASSUMPTION_STAMPS
