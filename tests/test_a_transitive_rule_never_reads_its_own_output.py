"""A `transitive:` roll-up, compiled to a chain that never joins its own output.

*Everything within N hops upstream* is what an author reaches for recursion to
say, and this evaluator stays polynomial only because it refuses recursion. The
shorthand keeps both: it unrolls to one rule per hop count, each body a chain
of the base predicate alone. These tests fail if the evaluator ever joins
against what it derived -- in one pass, or in the next after `adopt` has written
the derived edges back into the graph.
"""

from __future__ import annotations

import pytest

from arbiter_engine import api
from arbiter_engine.ontology.entail import (MAX_BODY_ATOMS,
                                                        expand_rules, parse_rule)

CHAIN = ["a", "b", "c", "d", "e", "f"]


def _session(max_hops=2, name="upstream_of", base="feeds", extra=None):
    rule = {"name": name, "transitive": base, "max_hops": max_hops, **(extra or {})}
    session = api.EngineSession()
    session.load_model({"domain": {
        "id": "line", "name": "a line of units",
        "entity_types": ["Unit"], "relationship_types": ["feeds", "upstream_of"],
        "indicators": {"Unit": [{"name": "load", "type": "NUMERIC",
                                 "axioms": ["BOUNDEDNESS"], "critical": 9}]},
        "rules": [rule], "closure": ["feeds"],
    }})
    for unit in CHAIN:
        session.add_entity(unit, "Unit", {"load": 1.0})
    for source, target in zip(CHAIN, CHAIN[1:]):
        session.add_relationship(source, "feeds", target)
    return session


def _derived(payload):
    return {(f["source"], f["target"]) for f in payload["derived_facts"]
            if f["predicate"] == "upstream_of"}


def _within(hops):
    return {(CHAIN[i], CHAIN[j]) for i in range(len(CHAIN))
            for j in range(i + 1, len(CHAIN)) if j - i <= hops}


class TestItNeverJoinsAgainstItsOwnOutput:

    @pytest.mark.parametrize("hops", [1, 2, 3])
    def test_one_pass_derives_exactly_the_pairs_within_n_hops(self, hops):
        assert _derived(api.entail(_session(hops)).to_dict()) == _within(hops)

    def test_adopting_and_running_again_derives_nothing_further(self):
        """The trap the cycle rule names: `adopt` writes the derived edges back,
        and a rule that could read them would reach further on every call."""
        session = _session(2)
        first = _derived(api.entail(session, adopt=True).to_dict())
        second = _derived(api.entail(session, adopt=True).to_dict())
        third = _derived(api.entail(session).to_dict())
        assert first == second == third == _within(2)

    def test_no_compiled_body_names_the_head(self):
        rules, _ = expand_rules([{"name": "upstream_of", "transitive": "feeds",
                                  "max_hops": 3}])
        for raw in rules:
            rule, why = parse_rule(raw)
            assert why is None
            assert {atom.pred for atom in rule.body} == {"feeds"}
            assert rule.head.pred == "upstream_of"
            assert len(rule.body) <= MAX_BODY_ATOMS


class TestItStaysInsideTheAtomCap:

    def test_a_hop_count_past_the_cap_is_declined_like_any_long_body(self):
        payload = api.entail(_session(MAX_BODY_ATOMS + 1)).to_dict()
        declined = {(d["reason"], d.get("rule")) for d in
                    payload["entailment"]["not_checked"]}
        assert ("depth_exceeded", f"upstream_of/{MAX_BODY_ATOMS + 1}") in declined
        assert _derived(payload) == _within(MAX_BODY_ATOMS)


class TestAShorthandItCannotReadIsRefusedByName:

    @pytest.mark.parametrize("kwargs", [
        {"max_hops": 0}, {"max_hops": True}, {"max_hops": "3"},
        {"base": "not a word"}, {"name": ""}, {"extra": {"body": ["feeds(A, B)"]}},
    ])
    def test_malformed(self, kwargs):
        payload = api.entail(_session(**kwargs)).to_dict()
        reasons = {d["reason"] for d in payload["entailment"]["not_checked"]}
        assert "malformed_rule" in reasons
        assert _derived(payload) == set()

    def test_chaining_the_derived_predicate_itself_is_recursion(self):
        payload = api.entail(_session(2, name="feeds", base="feeds")).to_dict()
        reasons = {d["reason"] for d in payload["entailment"]["not_checked"]}
        assert "recursion_unsupported" in reasons
