"""Inference: the arithmetic, the intervention, and the numbers it will not supply.

EVERY VALUE BELOW IS HAND-COMPUTED. A probabilistic routine tested against
itself cannot be falsified, and "it returned a number between 0 and 1" is
satisfied by almost any defect. So the conditionals, the marginal and the
posteriors are each checked against Bayes worked out by hand from the same
declared weights, and the noisy-OR table is checked against its own definition.

THE CLAIM THIS VERB EXISTS FOR is that intervening is not observing. With a
confounder C driving both X and Y, observing X=1 also tells you C is probably
faulty and drags P(Y) up with it; `do(x=1)` cuts C -> X so it cannot. Measured
on the fixture below: 0.748 observed against 0.345 intervened. A verb that
computed the first and called it the second would be wrong in the direction
that matters -- it would recommend acting on X.

WHAT IT WILL NOT SUPPLY is an edge weight. A posterior is a product of them,
so one the engine chose makes the answer partly a statement about the engine
with no way to tell which part, and `cpt_missing` stops the answer instead.
"""

from __future__ import annotations

import itertools

import pytest

from arbiter_engine.api import EngineSession, check, infer
from arbiter_engine.inference.causal import (
    DEFAULT_WEIGHT, SOURCE_DECLARED, SOURCE_DEFAULT, causal_subgraph,
)
from arbiter_engine.inference.runner import ROOT_PRIOR, Query, run_inference
from arbiter_engine.inference.ve import (
    FACTOR_VARIABLE_LIMIT, Factor, FactorTooWide, eliminate, noisy_or_factor,
)

LEAK = 0.02
W_FEED, W_VENUE = 0.7, 0.5


def _model(rules, entity_types=("Feed", "Venue", "Strategy"),
           relationship_types=("serves", "routes_to")):
    return {"domain": {"id": "d", "name": "d",
                       "entity_types": list(entity_types),
                       "relationship_types": list(relationship_types),
                       "relationship_rules": list(rules), "indicators": {}}}


def _causal(source, target, relation, weight=None, latent=None,
            direction="causal"):
    rule = {"source_type": source, "target_type": target, "type": relation,
            "edge_direction": direction}
    if weight is not None:
        rule["causal"] = {"weight": weight, "leak": LEAK}
    if latent:
        rule["latent_confounder"] = latent
    return rule


def _fan_in(weights=(W_FEED, W_VENUE)):
    """Feed -> Strategy <- Venue, both declared."""
    session = EngineSession()
    session.load_model(_model([
        _causal("Feed", "Strategy", "serves", weights[0]),
        _causal("Venue", "Strategy", "routes_to", weights[1])]))
    session.add_entity("feed1", "Feed")
    session.add_entity("venue1", "Venue")
    session.add_entity("strat1", "Strategy")
    session.add_relationship("feed1", "serves", "strat1")
    session.add_relationship("venue1", "routes_to", "strat1")
    return session


def _confounded():
    """C -> X, C -> Y, X -> Y. The shape where observing and intervening part."""
    session = EngineSession()
    session.load_model(_model(
        [_causal("C", "X", "to_x", 0.9), _causal("C", "Y", "to_y", 0.9),
         _causal("X", "Y", "x_to_y", 0.3)],
        entity_types=("C", "X", "Y"),
        relationship_types=("to_x", "to_y", "x_to_y")))
    for entity_id, entity_type in (("c", "C"), ("x", "X"), ("y", "Y")):
        session.add_entity(entity_id, entity_type)
    session.add_relationship("c", "to_x", "x")
    session.add_relationship("c", "to_y", "y")
    session.add_relationship("x", "x_to_y", "y")
    return session


def _posterior(session, target, **kw):
    sub = run_inference(session, Query(target=target, do=kw.pop("do", {})), **kw)
    return sub.checked.get("posterior")


def _reasons(sub):
    return sorted({d.reason for d in sub.not_checked})


# --- the noisy-OR table, against its own definition -------------------------

@pytest.mark.parametrize("feed,venue", list(itertools.product((0, 1), repeat=2)))
def test_the_conditional_table_is_noisy_or(feed, venue):
    factor = noisy_or_factor("s", ("f", "v"), (W_FEED, W_VENUE), LEAK)
    survives = (1 - LEAK) * ((1 - W_FEED) ** feed) * ((1 - W_VENUE) ** venue)
    assert factor.table[(1, feed, venue)] == pytest.approx(1 - survives)
    assert factor.table[(0, feed, venue)] == pytest.approx(survives)


def test_a_node_with_no_faulty_parent_still_has_the_leak():
    factor = noisy_or_factor("s", ("f",), (W_FEED,), LEAK)
    assert factor.table[(1, 0)] == pytest.approx(LEAK)


def test_each_column_of_the_table_sums_to_one():
    factor = noisy_or_factor("s", ("f", "v"), (W_FEED, W_VENUE), LEAK)
    for parents in itertools.product((0, 1), repeat=2):
        total = factor.table[(0,) + parents] + factor.table[(1,) + parents]
        assert total == pytest.approx(1.0)


# --- elimination, against Bayes by hand -------------------------------------

def _hand_child(feed, venue):
    return 1 - (1 - LEAK) * ((1 - W_FEED) ** feed) * ((1 - W_VENUE) ** venue)


def _factors():
    prior = lambda name: Factor((name,), {(0,): 1 - ROOT_PRIOR, (1,): ROOT_PRIOR})
    return [prior("f"), prior("v"),
            noisy_or_factor("s", ("f", "v"), (W_FEED, W_VENUE), LEAK)]


def test_the_marginal_is_the_hand_computed_sum():
    hand = sum((ROOT_PRIOR if f else 1 - ROOT_PRIOR)
               * (ROOT_PRIOR if v else 1 - ROOT_PRIOR) * _hand_child(f, v)
               for f in (0, 1) for v in (0, 1))
    assert eliminate(_factors(), "s", {}) == pytest.approx(hand)


def test_the_posterior_on_a_parent_rises_when_the_child_is_faulty():
    """Explaining away, in the direction that must hold: seeing the child
    faulty makes each parent more likely, not less."""
    raised = eliminate(_factors(), "f", {"s": 1})
    lowered = eliminate(_factors(), "f", {"s": 0})
    assert lowered < ROOT_PRIOR < raised


def test_the_posterior_on_a_parent_is_the_hand_computed_one():
    def joint(f, v, s):
        p = (ROOT_PRIOR if f else 1 - ROOT_PRIOR) * (ROOT_PRIOR if v else 1 - ROOT_PRIOR)
        child = _hand_child(f, v)
        return p * (child if s else 1 - child)
    for observed in (0, 1):
        numerator = sum(joint(1, v, observed) for v in (0, 1))
        denominator = numerator + sum(joint(0, v, observed) for v in (0, 1))
        assert eliminate(_factors(), "f", {"s": observed}) == pytest.approx(
            numerator / denominator)


def test_evidence_the_model_gives_probability_zero_returns_nothing():
    """Rather than dividing by zero. The caller turns it into a decline naming
    the disagreement between the model and the observations.

    TWO CASES, because they are two code paths and this test covered one while
    appearing to cover both. Restricting on impossible evidence eliminates the
    target variable entirely, and the early return handles that; a target that
    SURVIVES with no mass left is the one that reaches the division.
    """
    restricted_away = Factor(("x",), {(0,): 1.0, (1,): 0.0})
    assert eliminate([restricted_away], "x", {"x": 1}) is None

    no_mass_left = Factor(("x",), {(0,): 0.0, (1,): 0.0})
    assert eliminate([no_mass_left], "x", {}) is None


def test_a_factor_wider_than_the_limit_is_refused():
    parents = tuple(f"p{i}" for i in range(FACTOR_VARIABLE_LIMIT + 1))
    with pytest.raises(FactorTooWide):
        noisy_or_factor("child", parents, (0.5,) * len(parents), LEAK)


# --- intervening is not observing -------------------------------------------

def test_intervening_cuts_the_incoming_edges():
    """THE CLAIM. Observing X=1 also says the confounder is probably faulty;
    do(X=1) does not, so it must give a LOWER answer here. A verb that
    conditioned instead would recommend acting on X."""
    session = _confounded()
    intervened = _posterior(session, "y", do={"x": 1})
    observed = _observe_x_by_hand()
    assert intervened < observed
    assert intervened == pytest.approx(0.344870, abs=1e-5)
    assert observed == pytest.approx(0.748395, abs=1e-5)


def _observe_x_by_hand():
    prior, w_cx, w_cy, w_xy = ROOT_PRIOR, 0.9, 0.9, 0.3

    def noisy(parents, weights):
        survive = 1 - LEAK
        for state, weight in zip(parents, weights):
            if state:
                survive *= (1 - weight)
        return 1 - survive

    numerator = denominator = 0.0
    for c in (0, 1):
        p_c = prior if c else 1 - prior
        p_x = noisy((c,), (w_cx,))
        numerator += p_c * p_x * noisy((c, 1), (w_cy, w_xy))
        denominator += p_c * p_x
    return numerator / denominator


def test_intervening_still_propagates_downstream():
    """The discriminator: cutting the incoming edges must not cut the outgoing
    ones, or `do` would simply disconnect the node and answer the prior."""
    session = _confounded()
    assert _posterior(session, "y", do={"x": 1}) > _posterior(session, "y")


def test_an_intervention_on_a_root_changes_nothing_about_its_parents():
    """A root has no incoming edges, so surgery is a no-op there and the two
    answers must agree. Where a verb that cut the WRONG edges would not."""
    session = _fan_in()
    assert _posterior(session, "strat1", do={"feed1": 1}) == pytest.approx(
        0.71335, abs=1e-5)


# --- the numbers it will not supply -----------------------------------------

def test_an_undeclared_weight_stops_the_answer():
    session = EngineSession()
    session.load_model(_model([_causal("Feed", "Strategy", "serves", weight=None)]))
    session.add_entity("feed1", "Feed")
    session.add_entity("strat1", "Strategy")
    session.add_relationship("feed1", "serves", "strat1")
    sub = run_inference(session, Query(target="strat1"))
    assert _reasons(sub) == ["cpt_missing"]
    assert sub.checked["answered"] == 0
    assert sub.not_checked[0].evidence["edges"] == ["feed1->strat1"]


def test_the_undeclared_weight_is_asked_for():
    session = EngineSession()
    session.load_model(_model([_causal("Feed", "Strategy", "serves", weight=None)]))
    session.add_entity("feed1", "Feed")
    session.add_entity("strat1", "Strategy")
    session.add_relationship("feed1", "serves", "strat1")
    sub = run_inference(session, Query(target="strat1"))
    assert sub.questions
    assert "causal.weight" in sub.questions[0].question_text


def test_a_declared_weight_is_labelled_as_one():
    session = _fan_in()
    graph = causal_subgraph(session.model, session.graph, session.entities)
    assert graph.sources() == {SOURCE_DECLARED: 2}
    assert graph.weights[("feed1", "strat1")].weight == W_FEED


def test_an_undeclared_weight_is_labelled_default_and_worth_the_stated_number():
    session = EngineSession()
    session.load_model(_model([_causal("Feed", "Strategy", "serves", weight=None)]))
    session.add_entity("feed1", "Feed")
    session.add_entity("strat1", "Strategy")
    session.add_relationship("feed1", "serves", "strat1")
    graph = causal_subgraph(session.model, session.graph, session.entities)
    assert graph.weights[("feed1", "strat1")].source == SOURCE_DEFAULT
    assert graph.weights[("feed1", "strat1")].weight == DEFAULT_WEIGHT


def test_without_a_reporting_line_there_is_no_finding():
    session = _fan_in()
    sub = run_inference(session, Query(target="strat1"))
    assert sub.findings == []
    assert "no_report_probability" in _reasons(sub)
    assert sub.not_checked[0].evidence["posterior"] == pytest.approx(0.077943, abs=1e-5)


def test_a_declared_line_decides():
    session = _fan_in()
    assert run_inference(session, Query(target="strat1"),
                         report_above=0.9).findings == []
    assert run_inference(session, Query(target="strat1"),
                         report_above=0.01).findings


# --- what the subgraph is ---------------------------------------------------

def test_only_edges_declared_causal_are_in_the_subgraph():
    """`discover` proposes structure from lead-lag and calls it precedence.
    Letting that in here would close a loop the engine may not close."""
    session = EngineSession()
    session.load_model(_model([
        _causal("Feed", "Strategy", "serves", W_FEED),
        _causal("Venue", "Strategy", "routes_to", W_VENUE, direction="structural")]))
    session.add_entity("feed1", "Feed")
    session.add_entity("venue1", "Venue")
    session.add_entity("strat1", "Strategy")
    session.add_relationship("feed1", "serves", "strat1")
    session.add_relationship("venue1", "routes_to", "strat1")
    graph = causal_subgraph(session.model, session.graph, session.entities)
    assert sorted(graph.weights) == [("feed1", "strat1")]


def test_a_target_on_no_causal_edge_is_unavailable_rather_than_answered():
    session = _fan_in()
    session.add_entity("lonely", "Feed")
    sub = run_inference(session, Query(target="lonely"))
    assert sub.source == "unavailable"
    assert "causal" in sub.reason


def test_a_cycle_is_refused_and_the_loop_is_named():
    session = EngineSession()
    session.load_model(_model(
        [_causal("A", "B", "ab", 0.5), _causal("B", "A", "ba", 0.5)],
        entity_types=("A", "B"), relationship_types=("ab", "ba")))
    session.add_entity("a1", "A")
    session.add_entity("b1", "B")
    session.add_relationship("a1", "ab", "b1")
    session.add_relationship("b1", "ba", "a1")
    sub = run_inference(session, Query(target="a1"))
    assert _reasons(sub) == ["cycle_unsupported"]
    assert sub.not_checked[0].evidence["cycle"]


def test_a_declared_latent_makes_an_intervention_unidentifiable():
    session = EngineSession()
    session.load_model(_model([
        _causal("Feed", "Strategy", "serves", W_FEED, latent="ClearingHouse")]))
    session.add_entity("feed1", "Feed")
    session.add_entity("strat1", "Strategy")
    session.add_relationship("feed1", "serves", "strat1")
    sub = run_inference(session, Query(target="strat1", do={"feed1": 1}))
    assert _reasons(sub) == ["not_identifiable"]
    assert sub.not_checked[0].evidence["latent"] == "ClearingHouse"


def test_the_same_latent_does_not_block_a_plain_observation():
    """The discriminator. A latent confounds an INTERVENTION; conditioning on
    what you saw is still well defined."""
    session = EngineSession()
    session.load_model(_model([
        _causal("Feed", "Strategy", "serves", W_FEED, latent="ClearingHouse")]))
    session.add_entity("feed1", "Feed")
    session.add_entity("strat1", "Strategy")
    session.add_relationship("feed1", "serves", "strat1")
    sub = run_inference(session, Query(target="strat1"))
    assert "not_identifiable" not in _reasons(sub)
    assert sub.checked["answered"] == 1


# --- the verb ---------------------------------------------------------------

def test_the_verb_evaluates_no_invariants():
    envelope = infer(_fan_in(), "strat1", report_above=0.01).to_dict()
    assert envelope["checked"]["invariants"] == 0
    assert envelope["inference"]["checked"]["queries"] == 1


def test_the_answer_names_where_its_numbers_came_from():
    envelope = infer(_fan_in(), "strat1", report_above=0.01).to_dict()
    evidence = envelope["findings"][0]
    payload = envelope["inference"]["findings"][0]["evidence"]
    assert payload["cpt_sources"] == {SOURCE_DECLARED: 2}
    assert payload["root_prior_source"] == "default"
    assert payload["method"] == "exact_ve"


def test_nothing_checked_yet_means_nothing_observed():
    """With no check behind it, every node is unseen — which is the honest
    reading and not the same as every node being clean."""
    sub = run_inference(_fan_in(), Query(target="strat1"))
    assert sub.checked["unobserved"] == 3
    assert sub.checked["evidence"] == 0


def test_a_node_the_check_declined_is_unobserved_rather_than_clean():
    """THE CASE THAT MATTERS, and the one the test above does not reach: a
    check that RAN and could not evaluate a cell. Treating that as clean is
    the silence the `not_checked` leg exists to stop, and it would push every
    posterior down.

    The fixture declares an indicator with a window no observation falls in,
    so the pass declines rather than passing.
    """
    session = EngineSession()
    session.load_model({"domain": {
        "id": "d", "name": "d", "entity_types": ["Feed", "Strategy"],
        "relationship_types": ["serves"],
        "relationship_rules": [_causal("Feed", "Strategy", "serves", W_FEED)],
        "indicators": {"Feed": [{"name": "rate", "type": "NUMERIC",
                                 "axioms": ["STABILITY"], "window": "1h",
                                 "expect_variation": True}]}}})
    session.add_entity("feed1", "Feed")
    session.add_entity("strat1", "Strategy")
    session.add_relationship("feed1", "serves", "strat1")
    session.add_observations("feed1", "rate", [1.0, 2.0])   # under the floor
    check(session)

    declined = {str(getattr(r, "entity_id", ""))
                for r in (session._last_result.not_evaluated or ())}
    assert "feed1" in declined, "the fixture did not produce a decline"

    sub = run_inference(session, Query(target="strat1"))
    assert sub.checked["unobserved"] == 1
    assert sub.checked["evidence"] == 0


def test_an_entity_the_check_cleared_is_observed_clean():
    """The discriminator: unobserved and clean must not collapse into each
    other in the other direction either."""
    session = _fan_in()
    check(session)
    sub = run_inference(session, Query(target="strat1"))
    assert sub.checked["evidence"] == 2
    assert sub.checked["unobserved"] == 0


def test_evidence_the_model_calls_impossible_is_a_decline():
    """The model and the observations disagreeing, named rather than papered
    over. With `weight: 0` and `leak: 0` declared, the child can never be
    faulty under this model -- so a check that finds it critical is evidence
    the model gives probability zero, and there is no posterior to report.

    Reachable ONLY through a declared zero: with any positive leak every
    configuration has positive probability, which is why this needs a fixture
    that declares one rather than a fixture that happens to be unlucky.
    """
    session = EngineSession()
    session.load_model({"domain": {
        "id": "d", "name": "d", "entity_types": ["Feed", "Strategy"],
        "relationship_types": ["serves"],
        "relationship_rules": [{"source_type": "Feed", "target_type": "Strategy",
                                "type": "serves", "edge_direction": "causal",
                                "causal": {"weight": 0.0, "leak": 0.0}}],
        "indicators": {"Strategy": [{"name": "load", "type": "NUMERIC",
                                     "axioms": ["BOUNDEDNESS"], "window": "1h",
                                     "critical": 10}]}}})
    session.add_entity("feed1", "Feed")
    session.add_entity("strat1", "Strategy", {"load": 9999.0})
    session.add_relationship("feed1", "serves", "strat1")
    session.add_observations("strat1", "load", [9999.0] * 10)
    check(session)

    sub = run_inference(session, Query(target="feed1"))
    assert _reasons(sub) == ["evidence_conflict"]
    assert sub.checked["answered"] == 0


def test_the_posterior_is_filed_for_grading():
    session = _fan_in()
    run_inference(session, Query(target="strat1"))
    assert len(session.ledger.records()) == 1


def test_the_verb_refuses_without_a_model_or_entities():
    assert infer(EngineSession(), "x").to_dict()["meta"]["source"] == "unavailable"
    session = EngineSession()
    session.load_model(_model([]))
    assert infer(session, "x").to_dict()["meta"]["reason"] == "no entities supplied"
