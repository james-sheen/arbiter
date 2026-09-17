"""Entailment: what a rule may be, what it derives, and what it will not conclude
from silence.

THE TWO BOUNDS ARE ONE BOUND. At most three body atoms, and the head predicate
not in its own body: together they make evaluation a nested-loop join over a
non-recursive conjunctive query, which is polynomial. That is the project's
actual constraint -- *verification stays in P* -- and it is why a body MAY
quantify its join variable, which the shorthand *first-order* appears to forbid.

POLYNOMIAL IS NOT AFFORDABLE. Three atoms sharing no variables is cubic in the
facts: 196 facts produced 7.5 million bindings. So there is a binding budget
too, and a rule that hits it is refused by name rather than left to not return.

ABSENCE IS NOT EVIDENCE. A graph holds the edges someone fed it. Unless the
author closes a predicate in `closure:`, an entity with no fact under it is
unknown rather than false, and that is a decline rather than a silence.
"""

from __future__ import annotations

import pytest

from arbiter_engine.api import EngineSession, entail
from arbiter_engine.ontology.entail import (
    Atom, BINDING_BUDGET, MAX_BODY_ATOMS, _join, parse_atom, parse_rule,
)

CHAIN = {"name": "exposure", "head": "exposed_to(A, C)",
         "body": ["holds(A, B)", "clears_at(B, C)"]}


def _session(rules=(CHAIN,), closure=("holds", "clears_at"),
             relationship_types=("holds", "clears_at", "exposed_to"),
             indicators=None, edges=(("a1", "holds", "b1"),
                                     ("b1", "clears_at", "c1")),
             entities=("a1", "b1", "c1")):
    session = EngineSession()
    session.load_model({"domain": {
        "id": "d", "name": "d", "entity_types": ["Node"],
        "relationship_types": list(relationship_types),
        "closure": list(closure), "rules": list(rules),
        "indicators": indicators or {}}})
    for entity_id in entities:
        session.add_entity(entity_id, "Node")
    for source, relation, target in edges:
        session.add_relationship(source, relation, target)
    return session


def _sub(envelope):
    return envelope.to_dict()["entailment"]


def _reasons(envelope):
    return sorted({d["reason"] for d in _sub(envelope)["not_checked"]})


# --- the rule format --------------------------------------------------------

def test_an_atom_is_a_binary_predicate_over_variables():
    assert parse_atom("holds(A, B)") == Atom("holds", "A", "B")
    assert parse_atom("holds(A,B)") == Atom("holds", "A", "B")


def test_anything_that_is_not_one_parses_to_nothing():
    for text in ("holds(A)", "holds(A, B, C)", "holds", "", None, "holds A B"):
        assert parse_atom(text) is None


def test_a_malformed_rule_declines_rather_than_refusing_the_model():
    """The author's other rules still run. A file that will not load over one
    bad rule costs them every good one."""
    envelope = entail(_session(rules=({"name": "bad", "head": "x(A)",
                                       "body": ["holds(A, B)"]}, CHAIN)))
    assert "malformed_rule" in _reasons(envelope)
    assert _sub(envelope)["checked"]["rules_evaluated"] == 1
    assert _sub(envelope)["checked"]["facts_derived"] == 1


def test_a_rule_without_a_name_is_refused():
    rule, why = parse_rule({"head": "x(A, B)", "body": ["holds(A, B)"]})
    assert rule is None and "name" in why


# --- what the bounds are for ------------------------------------------------

def test_a_body_past_the_atom_limit_is_refused():
    long_body = ["holds(A, B)", "clears_at(B, C)", "near(C, D)", "near(D, E)"]
    envelope = entail(_session(
        rules=({"name": "long", "head": "exposed_to(A, E)", "body": long_body},),
        relationship_types=("holds", "clears_at", "near", "exposed_to")))
    assert _reasons(envelope) == ["depth_exceeded"]
    decline = _sub(envelope)["not_checked"][0]
    assert decline["evidence"] == {"atoms": 4, "limit": MAX_BODY_ATOMS}


def test_exactly_the_limit_is_allowed():
    """The boundary in the other direction, which is what says the limit is a
    limit and not an off-by-one."""
    envelope = entail(_session(
        rules=({"name": "three", "head": "exposed_to(A, D)",
                "body": ["holds(A, B)", "clears_at(B, C)", "near(C, D)"]},),
        relationship_types=("holds", "clears_at", "near", "exposed_to"),
        closure=("holds", "clears_at", "near"),
        edges=(("a1", "holds", "b1"), ("b1", "clears_at", "c1"),
               ("c1", "near", "d1")),
        entities=("a1", "b1", "c1", "d1")))
    assert _reasons(envelope) == []
    assert _sub(envelope)["checked"]["facts_derived"] == 1


def test_a_recursive_rule_is_refused():
    """One pass, no fixed point. A head in its own body is what would need
    iterating to one, and the depth of that iteration is not bounded by the
    rule -- which is the half of the constraint the atom cap does not cover."""
    envelope = entail(_session(
        rules=({"name": "loop", "head": "holds(A, C)",
                "body": ["holds(A, B)", "clears_at(B, C)"]},)))
    assert _reasons(envelope) == ["recursion_unsupported"]


def test_a_body_predicate_nobody_declared_is_refused_with_the_set():
    envelope = entail(_session(
        rules=({"name": "r", "head": "exposed_to(A, C)",
                "body": ["owns(A, B)", "clears_at(B, C)"]},)))
    assert _reasons(envelope) == ["rule_unreachable"]
    assert _sub(envelope)["not_checked"][0]["evidence"]["missing"] == ["owns"]


def test_a_rule_too_expensive_to_evaluate_says_so():
    """A body whose atoms share no variables is the full cross product. The
    refusal is the useful answer; a call that does not return is not.

    TWO atoms and 400 facts, not three and 900. The figure that matters is
    that 160,000 bindings exceed the budget -- and the fixture must stay
    finite when the budget is MUTATED AWAY, which is how this test is checked.
    Three atoms over 900 facts is 729 million bindings: unmutated it stops at
    the budget in a tenth of a second, and mutated it took the machine to
    1.8GB and an uninterruptible sleep before anything killed it.
    """
    edges = tuple((f"x{i}", "p", f"y{j}") for i in range(20) for j in range(20))
    envelope = entail(_session(
        rules=({"name": "cross", "head": "exposed_to(A, D)",
                "body": ["p(A, B)", "p(C, D)"]},),
        relationship_types=("p", "exposed_to"), closure=("p",),
        edges=edges, entities=tuple(f"x{i}" for i in range(20))))
    assert "binding_budget_exhausted" in _reasons(envelope)


# --- what it derives --------------------------------------------------------

def test_a_chain_derives_the_composed_edge():
    envelope = entail(_session())
    derived = envelope.to_dict()["derived_facts"]
    assert len(derived) == 1
    assert (derived[0]["predicate"], derived[0]["source"],
            derived[0]["target"]) == ("exposed_to", "a1", "c1")


def test_every_derived_fact_carries_the_facts_it_came_from():
    """A derived edge with no author is an edge nobody can argue with."""
    derived = entail(_session()).to_dict()["derived_facts"][0]
    assert derived["rule"] == "exposure"
    assert derived["from"] == [["holds", "a1", "b1"], ["clears_at", "b1", "c1"]]


def test_the_join_is_a_cross_product_where_the_facts_allow_one():
    session = _session(edges=(("a1", "holds", "b1"), ("a2", "holds", "b1"),
                              ("b1", "clears_at", "c1"), ("b1", "clears_at", "c2")),
                       entities=("a1", "a2", "b1", "c1", "c2"))
    derived = entail(session).to_dict()["derived_facts"]
    assert {(d["source"], d["target"]) for d in derived} == {
        ("a1", "c1"), ("a1", "c2"), ("a2", "c1"), ("a2", "c2")}


def test_the_shared_variable_actually_constrains():
    """The discriminator for the test above: change the middle term and the
    chain no longer joins, so a join that ignored variables would still pass
    the cross-product test and fail this one."""
    session = _session(edges=(("a1", "holds", "b1"), ("b2", "clears_at", "c1")),
                       entities=("a1", "b1", "b2", "c1"))
    assert entail(session).to_dict()["derived_facts"] == []


def test_an_atom_whose_variables_are_both_already_bound_still_constrains():
    """THE CASE THE INDEX DOES NOT COVER, and the reason the equality check in
    the join is not redundant.

    Candidates are looked up by whichever variable is already bound, so a
    singly-bound atom can only return facts that match it -- which is why
    removing the check left every other test green. When BOTH variables are
    bound, as in the third atom of a triangle, the lookup narrows on one and
    the other is checked by the comparison alone.

    Here `holds(a1,b1)` and `clears_at(b1,c1)` bind A and C, and the model
    declares `near(a1, c9)` rather than `near(a1, c1)`, so the triangle must
    not close.
    """
    session = _session(
        rules=({"name": "triangle", "head": "exposed_to(A, C)",
                "body": ["holds(A, B)", "clears_at(B, C)", "near(A, C)"]},),
        relationship_types=("holds", "clears_at", "near", "exposed_to"),
        closure=("holds", "clears_at", "near"),
        edges=(("a1", "holds", "b1"), ("b1", "clears_at", "c1"),
               ("a1", "near", "c9")),
        entities=("a1", "b1", "c1", "c9"))
    assert entail(session).to_dict()["derived_facts"] == []


def test_the_same_triangle_closes_when_the_third_edge_matches():
    """The discriminator: the rule above is not simply inert."""
    session = _session(
        rules=({"name": "triangle", "head": "exposed_to(A, C)",
                "body": ["holds(A, B)", "clears_at(B, C)", "near(A, C)"]},),
        relationship_types=("holds", "clears_at", "near", "exposed_to"),
        closure=("holds", "clears_at", "near"),
        edges=(("a1", "holds", "b1"), ("b1", "clears_at", "c1"),
               ("a1", "near", "c1")),
        entities=("a1", "b1", "c1"))
    derived = entail(session).to_dict()["derived_facts"]
    assert [(d["source"], d["target"]) for d in derived] == [("a1", "c1")]


def test_deriving_is_not_adopting():
    session = _session()
    entail(session)
    assert session.graph.get_relationships("a1") == ["b1"]


def test_adopting_writes_the_edge_back_marked_as_inferred():
    session = _session()
    entail(session, adopt=True)
    assert sorted(session.graph.get_relationships("a1")) == ["b1", "c1"]
    metadata = session.graph.get_edge_metadata("a1", "exposed_to", "c1")
    assert metadata["properties"]["source"] == "inferred"
    assert metadata["properties"]["proof"]["rule"] == "exposure"


# --- the open world ---------------------------------------------------------

def test_an_entity_with_no_fact_under_an_open_predicate_is_undecidable():
    envelope = entail(_session(closure=()))
    open_world = [d for d in _sub(envelope)["not_checked"]
                  if d["reason"] == "open_world_undecidable"]
    assert {d["entity_id"] for d in open_world} == {"b1", "c1"}


def test_closing_the_predicate_ends_the_question():
    """The author's statement that the feed is complete, and the only thing
    that licenses reading an absence as a no."""
    assert "open_world_undecidable" not in _reasons(entail(_session()))


# --- what it reports --------------------------------------------------------

def test_the_denominator_separates_declared_from_evaluated():
    envelope = entail(_session(rules=(CHAIN, {"name": "bad", "head": "x(A)",
                                              "body": ["holds(A, B)"]})))
    checked = _sub(envelope)["checked"]
    assert checked["rules_declared"] == 2
    assert checked["rules_evaluated"] == 1


def test_a_head_the_model_does_not_declare_is_asked_about():
    """Derived facts under an undeclared predicate reach no check."""
    envelope = entail(_session(
        rules=({"name": "r", "head": "shadows(A, C)",
                "body": ["holds(A, B)", "clears_at(B, C)"]},)))
    questions = _sub(envelope)["questions"]
    assert questions and questions[0]["gap_type"] == "missing_declaration"


def test_rules_and_bounds_disagreeing_is_a_finding():
    """Both declared by the same author, in the same file, contradicting."""
    indicators = {"Node": [{"name": "exposure", "type": "RELATIONSHIP",
                            "axioms": ["CONNECTIVITY"], "target_type": "Node",
                            "relation_type": "exposed_to",
                            "min_cardinality": 0, "max_cardinality": 1}]}
    session = _session(indicators=indicators,
                       edges=(("a1", "holds", "b1"), ("b1", "clears_at", "c1"),
                              ("b1", "clears_at", "c2")),
                       entities=("a1", "b1", "c1", "c2"))
    findings = _sub(session and entail(session))["findings"]
    assert len(findings) == 1
    assert findings[0]["problem_type"] == "derived_exceeds_cardinality:exposed_to"
    assert findings[0]["evidence"]["total"] == 2
    assert findings[0]["evidence"]["max_cardinality"] == 1


def test_declared_edges_count_towards_the_bound_too():
    """The contradiction is between the bound and EVERYTHING that ends up under
    it, not only what the rules added. One declared edge plus two derived
    passes a limit of two, and counting derived alone would miss it -- which is
    what the check did until a mutation showed the fixture could not tell."""
    indicators = {"Node": [{"name": "exposure", "type": "RELATIONSHIP",
                            "axioms": ["CONNECTIVITY"], "target_type": "Node",
                            "relation_type": "exposed_to",
                            "min_cardinality": 0, "max_cardinality": 2}]}
    session = _session(indicators=indicators,
                       edges=(("a1", "holds", "b1"), ("b1", "clears_at", "c1"),
                              ("b1", "clears_at", "c2"),
                              ("a1", "exposed_to", "c8")),
                       entities=("a1", "b1", "c1", "c2", "c8"))
    findings = _sub(entail(session))["findings"]
    assert len(findings) == 1
    assert findings[0]["evidence"]["total"] == 3
    assert findings[0]["evidence"]["derived"] == 2


def test_a_bound_the_rules_respect_is_not_a_finding():
    indicators = {"Node": [{"name": "exposure", "type": "RELATIONSHIP",
                            "axioms": ["CONNECTIVITY"], "target_type": "Node",
                            "relation_type": "exposed_to",
                            "min_cardinality": 0, "max_cardinality": 4}]}
    assert _sub(entail(_session(indicators=indicators)))["findings"] == []


def test_the_verb_evaluates_no_invariants():
    envelope = entail(_session()).to_dict()
    assert envelope["checked"]["invariants"] == 0


def test_the_verb_refuses_without_a_model():
    assert entail(EngineSession()).to_dict()["meta"]["source"] == "unavailable"


# --- the join, directly -----------------------------------------------------

def test_the_join_is_indexed_rather_than_scanned():
    """A chain over many facts must not cost what a scan costs. Asserted as a
    BINDING COUNT rather than a clock: an indexed walk visits candidates that
    can match, so the bindings it produces are the chain's length, not its
    square."""
    facts = {("holds", f"a{i}", f"b{i}") for i in range(400)}
    facts |= {("clears_at", f"b{i}", f"c{i}") for i in range(400)}
    bindings, exhausted = _join(
        (Atom("holds", "A", "B"), Atom("clears_at", "B", "C")),
        facts, BINDING_BUDGET)
    assert len(bindings) == 400
    assert not exhausted


def test_the_budget_stops_the_walk_and_says_it_did():
    facts = {("p", f"x{i}", f"y{j}") for i in range(20) for j in range(20)}
    bindings, exhausted = _join(
        (Atom("p", "A", "B"), Atom("p", "C", "D")), facts, 1000)
    assert exhausted
    assert len(bindings) == 1000
