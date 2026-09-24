"""A cycle across rules is recursion, and the per-rule check could not see it.

`entail` refuses a rule whose head predicate appears in its own body,
and the module states why: one pass, no fixed point, and the bounds are what
keep evaluation polynomial. That check is correct and it is a self-loop test on
a one-node graph -- the only recursion visible when you look at one rule at a
time.

Two rules can be mutually recursive while neither is recursive alone:

    p(A, C):- q(A, B), link(B, C)
    q(A, C):- p(A, B), link(B, C)

Neither head is in its own body. Both bodies are inside the atom cap. Every
static check passed, and `entail(adopt=True)` writes the derived edges into the
graph, so the NEXT call joins against them. MEASURED before the fix, on a
seven-entity chain, the derived count over six passes ran 1, 2, 3, 4, 5, 5 --
with no decline at any point, stopping only because the chain ran out of
entities. The depth was a property of the DATA, which is the precise thing the
atom cap and the recursion refusal exist together to prevent.

The single-call guarantee was never wrong. It was not the guarantee anybody
needed, because `adopt` is what makes the next call a second iteration.

WHAT STAYS LEGAL. A rule consuming an earlier rule's head is an acyclic chain,
its depth bounded by the number of rules rather than the size of the graph -- a
finite union of conjunctive queries, still in P. That is the UNROLLING the
project rule permits, and the last class here holds it open: it converges on
its own, in as many passes as there are rules, and then stops.
"""

import pytest

from arbiter_engine.api import EngineSession, entail
from arbiter_engine.ontology.entail import (
    Atom, Rule, predicate_cycles,
)

CHAIN_ENTITIES = ["a1", "b1", "c1", "d1", "e1", "f1", "g1"]

CYCLE_RULES = [
    {"name": "p_from_q", "head": "p(A, C)", "body": ["q(A, B)", "link(B, C)"]},
    {"name": "q_from_p", "head": "q(A, C)", "body": ["p(A, B)", "link(B, C)"]},
]
ACYCLIC_RULES = [
    {"name": "p_from_q", "head": "p(A, C)", "body": ["q(A, B)", "link(B, C)"]},
    {"name": "r_from_p", "head": "r(A, C)", "body": ["p(A, B)", "link(B, C)"]},
]


def _session(rules, predicates):
    session = EngineSession()
    session.load_model({"domain": {
        "id": "d", "name": "d", "entity_types": ["Node"],
        "relationship_types": list(predicates),
        "closure": list(predicates), "rules": list(rules),
        "indicators": {}}})
    for entity_id in CHAIN_ENTITIES:
        session.add_entity(entity_id, "Node")
    session.add_relationship("a1", "q", "b1")
    for source, target in zip(CHAIN_ENTITIES[1:], CHAIN_ENTITIES[2:]):
        session.add_relationship(source, "link", target)
    return session


def _pass(session):
    sub = entail(session, adopt=True).to_dict()["entailment"]
    return (sub["checked"]["facts_derived"],
            sorted({d["reason"] for d in sub["not_checked"]}),
            sub["not_checked"])


class TestNeitherRuleIsRecursiveByItself:
    """The premise. If either rule tripped the per-rule check, this file would
    be testing the check that already existed."""

    @pytest.mark.parametrize("rule", CYCLE_RULES)
    def test_no_head_appears_in_its_own_body(self, rule):
        head = rule["head"].split("(")[0]
        assert head not in {atom.split("(")[0] for atom in rule["body"]}

    @pytest.mark.parametrize("rule", CYCLE_RULES)
    def test_each_body_is_inside_the_atom_cap(self, rule):
        from arbiter_engine.ontology.entail import MAX_BODY_ATOMS
        assert len(rule["body"]) <= MAX_BODY_ATOMS


class TestTheEvaluatorDoesNotLoopOnItsOwnOutput:
    """The test that an internal ruling asks for, stated as a property rather than a case: run
    the verb until it stops changing, and require that it STOPS."""

    def test_a_cycle_is_refused_outright(self):
        derived, reasons, rows = _pass(_session(CYCLE_RULES, ["p", "q", "link"]))
        assert derived == 0
        assert reasons == ["recursion_unsupported"]
        cycle = [r for r in rows if r["reason"] == "recursion_unsupported"][0]
        assert set(cycle["evidence"]["cycle"]) == {"p", "q"}

    def test_repeating_adopt_derives_nothing_further(self):
        """The shape of the original defect: it was invisible in ONE call and
        only a second call could show it."""
        session = _session(CYCLE_RULES, ["p", "q", "link"])
        counts = [_pass(session)[0] for _ in range(4)]
        assert counts == [0, 0, 0, 0], (
            f"derived counts across four adopting passes were {counts}; a "
            f"rising count is the evaluator consuming its own output")

    def test_an_acyclic_chain_converges_rather_than_growing(self):
        """The floor, and the half that keeps this from being a ban on
        derivation: the legal case must still derive, and must still STOP."""
        session = _session(ACYCLIC_RULES, ["p", "q", "r", "link"])
        counts = [_pass(session)[0] for _ in range(5)]
        assert counts[0] > 0, "the acyclic chain derives nothing at all"
        assert counts[-1] == counts[-2], (
            f"counts {counts} have not settled; an acyclic chain must reach a "
            f"fixed point in at most as many passes as there are rules")
        assert max(counts) <= len(ACYCLIC_RULES), (
            f"counts {counts} exceed the rule count, so the depth is bounded "
            f"by the graph rather than by the rules")

    def test_the_acyclic_chain_is_not_refused(self):
        _, reasons, _ = _pass(_session(ACYCLIC_RULES, ["p", "q", "r", "link"]))
        assert "recursion_unsupported" not in reasons, (
            "a finite unrolling is what the project rule permits; refusing it "
            "would make the fix a ban on derivation")


class TestTheCycleFinderIsKeyedOnTheShape:
    """Unit-level, because the property is about the rule GRAPH and a session
    test can only reach it through one model at a time."""

    def _rule(self, name, head, body):
        def atom(text):
            pred, rest = text.split("(", 1)
            left, right = (v.strip() for v in rest.rstrip(")").split(","))
            return Atom(pred.strip(), left, right)
        return Rule(name, atom(head), tuple(atom(b) for b in body))

    def test_a_self_loop_is_a_cycle_of_length_one(self):
        rule = self._rule("r", "p(A, C)", ["p(A, B)", "link(B, C)"])
        assert predicate_cycles([rule]) == [("p",)]

    def test_two_rules_close_a_cycle_of_length_two(self):
        rules = [self._rule("a", "p(A, C)", ["q(A, B)", "link(B, C)"]),
                 self._rule("b", "q(A, C)", ["p(A, B)", "link(B, C)"])]
        assert [set(c) for c in predicate_cycles(rules)] == [{"p", "q"}]

    def test_three_rules_close_a_cycle_of_length_three(self):
        """The reason the finder walks rather than pattern-matching pairs."""
        rules = [self._rule("a", "p(A, C)", ["q(A, B)", "link(B, C)"]),
                 self._rule("b", "q(A, C)", ["r(A, B)", "link(B, C)"]),
                 self._rule("c", "r(A, C)", ["p(A, B)", "link(B, C)"])]
        assert [set(c) for c in predicate_cycles(rules)] == [{"p", "q", "r"}]

    def test_an_acyclic_chain_has_no_cycle(self):
        rules = [self._rule("a", "p(A, C)", ["q(A, B)", "link(B, C)"]),
                 self._rule("b", "r(A, C)", ["p(A, B)", "link(B, C)"])]
        assert predicate_cycles(rules) == []

    def test_a_diamond_is_not_a_cycle(self):
        """Two rules reading one predicate and a third reading both is a DAG;
        a finder keyed on *a predicate appears twice* would call it a loop."""
        rules = [self._rule("a", "p(A, C)", ["s(A, B)", "link(B, C)"]),
                 self._rule("b", "q(A, C)", ["s(A, B)", "link(B, C)"]),
                 self._rule("c", "t(A, C)", ["p(A, B)", "q(B, C)"])]
        assert predicate_cycles(rules) == []
