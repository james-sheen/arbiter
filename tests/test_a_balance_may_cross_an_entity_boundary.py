"""CONSERVATION and CONSISTENCY reaching across a declared edge.

THE CASE THE FORMAT COULD NOT EXPRESS. A balance whose two halves live on
different entities — what leaves one thing arrives at several others — and a
reading that must agree with the same reading taken somewhere else. Both were
declarable only when every property sat on one entity, which is the rare case
rather than the common one.

WHY THE TWO CALLERS DIFFER ON `aggregate`, and why that is not a convenience
flag. A balance SUMS its output side by definition: three outfeeds carry three
parts of one flow. An agreement COMPARES: three readings are three candidate
answers, and picking one without being told would make the verdict depend on
iteration order. The test that shows this is the one where `min` agrees and
`median` does not, on identical data.

AN ABSENT PEER IS NOT A ZERO, and across an edge there is one more way to be
absent than the engine had already learned about: no edge at all. That is the
one most likely to mean the model is unfinished, so it declines rather than
resolving to an empty sum — the alternative reports a 100% deficit as a fault
in the system when the fault is a relationship nobody declared.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from arbiter_engine.api import EngineSession, check
from arbiter_engine.clock import as_of
from arbiter_engine.history.observation import InMemoryObservationHistory
from arbiter_engine.interfaces import Entity, RelationshipGraph
from arbiter_engine.ontology.axioms.peers import (
    AGGREGATES, PeerRef, parse_reference, resolve_peer,
)

T0 = datetime(2026, 5, 1, 12, 0)
#: Inside the conservation accounting window, which is a global parameter and
#: NOT the indicator's `window:` -- freezing outside it starves the check and
#: every assertion below becomes a decline about samples.
AT = T0 + timedelta(minutes=3)

FEEDS = {"via": "feeds", "property": "arrived"}


# --- the reference itself ---------------------------------------------------

def test_a_bare_string_is_still_a_property_of_this_entity():
    assert parse_reference("arrived")[:2] == ("arrived", None)


def test_a_mapping_crosses_one_edge():
    assert parse_reference(FEEDS)[1] == PeerRef("feeds", "arrived")


def test_a_reference_missing_either_half_is_refused():
    assert "needs both" in parse_reference({"property": "arrived"})[2]
    assert "needs both" in parse_reference({"via": "feeds"})[2]


def test_an_aggregate_outside_the_set_is_refused():
    why = parse_reference(dict(FEEDS, aggregate="mode"))[2]
    assert why and sorted(AGGREGATES) == ["max", "mean", "median", "min", "sum"]


# --- the resolver -----------------------------------------------------------

def _graph_and_entities(values=(40.0, 55.0), relation="feeds", prop="arrived"):
    graph = RelationshipGraph()
    entities = {"a": Entity(id="a", type="A", name="a", properties={})}
    for index, value in enumerate(values):
        target = f"t{index}"
        graph.add_relationship("a", relation, target)
        entities[target] = Entity(id=target, type="T", name=target,
                                  properties={prop: value})
    return graph, entities


def _resolve(ref, require_aggregate, **kw):
    graph, entities = _graph_and_entities(**kw)
    return resolve_peer(entities["a"], ref, graph, entities,
                        InMemoryObservationHistory(), timedelta(hours=1),
                        require_aggregate=require_aggregate)


def test_a_balance_reads_every_target_the_edge_reaches():
    resolved = _resolve(PeerRef("feeds", "arrived"), require_aggregate=False)
    assert sorted(resolved.values) == [40.0, 55.0]
    assert resolved.targets == ["t0", "t1"]


def test_an_edge_that_reaches_nobody_declines_rather_than_summing_to_zero():
    """The one most likely to mean the model is unfinished. Resolved as an
    empty sum it becomes a 100% deficit reported as a fault in the system."""
    resolved = _resolve(PeerRef("nowhere", "arrived"), require_aggregate=False)
    assert resolved.reason == "precondition_unmet"
    assert "no `nowhere` edge from a" in resolved.detail


def test_targets_that_carry_no_such_property_decline():
    resolved = _resolve(PeerRef("feeds", "absent"), require_aggregate=False)
    assert resolved.reason == "missing_property"
    assert "the edge is declared and the property is not" in resolved.detail


def test_without_the_entity_index_the_far_side_cannot_be_read():
    graph, entities = _graph_and_entities()
    resolved = resolve_peer(entities["a"], PeerRef("feeds", "arrived"), graph,
                            None, InMemoryObservationHistory(),
                            timedelta(hours=1), require_aggregate=False)
    assert resolved.reason == "precondition_unmet"


def test_an_agreement_over_several_readings_needs_to_be_told_how_to_combine():
    resolved = _resolve(PeerRef("feeds", "arrived"), require_aggregate=True)
    assert resolved.reason == "missing_config"
    assert "aggregate" in resolved.detail


def test_one_reading_needs_no_aggregate():
    """The discriminator: requiring one unconditionally would refuse the
    commonest shape, which is a single peer."""
    resolved = _resolve(PeerRef("feeds", "arrived"), require_aggregate=True,
                        values=(40.0,))
    assert resolved.ok and resolved.values == [40.0]


def test_a_declared_aggregate_combines_them():
    resolved = _resolve(PeerRef("feeds", "arrived", "median"),
                        require_aggregate=True)
    assert resolved.values == [47.5]


# --- CONSERVATION across the boundary ---------------------------------------

def _balance_session(arrived, sent=100.0, reference=None, **conservation):
    config = {"input_property": "sent",
              "output_properties": [reference or FEEDS]}
    config.update(conservation)
    session = EngineSession()
    session.load_model({"domain": {
        "id": "d", "name": "d", "entity_types": ["Source", "Sink"],
        "relationship_types": ["feeds"],
        "indicators": {"Source": [
            {"name": "sent", "type": "NUMERIC", "axioms": ["CONSERVATION"],
             "window": "1h", "conservation": config}]}}})
    session.add_entity("a", "Source")
    for index, value in enumerate(arrived):
        target = f"t{index}"
        session.add_entity(target, "Sink")
        session.add_relationship("a", "feeds", target)
        session.history.add(target, "arrived", value,
                            timestamp=T0 + timedelta(minutes=1))
    session.history.add("a", "sent", sent, timestamp=T0 + timedelta(minutes=1))
    return session


def _run(session):
    with as_of(AT):
        return check(session).to_dict()


def test_a_deficit_across_the_boundary_is_a_finding():
    envelope = _run(_balance_session((40.0, 40.0)))
    assert [f["problem_type"] for f in envelope["findings"]] == \
        ["conservation_violation:sent"]
    assert "20.0% deficit" in envelope["findings"][0]["reason"]


def test_a_balance_that_holds_across_the_boundary_is_not():
    """The discriminator: a check that fires either way is not a check."""
    assert _run(_balance_session((50.0, 50.0)))["findings"] == []


def test_a_relative_allowance_tolerates_the_deficit():
    assert _run(_balance_session((40.0, 40.0), loss_margin=0.30))["findings"] == []


def test_a_fixed_allowance_tolerates_it_too():
    """For a loss that does not scale with the input -- a per-transaction fee,
    a constant bleed."""
    assert _run(_balance_session((40.0, 40.0), loss_absolute=25.0))["findings"] == []


def test_a_fixed_allowance_smaller_than_the_deficit_does_not():
    assert len(_run(_balance_session((40.0, 40.0), loss_absolute=5.0))["findings"]) == 1


def test_a_balance_whose_edge_reaches_nobody_declines():
    envelope = _run(_balance_session(
        (40.0, 40.0), reference={"via": "nowhere", "property": "arrived"}))
    assert [d["reason"] for d in envelope["not_checked"]] == ["precondition_unmet"]
    assert envelope["findings"] == []


def test_a_balance_whose_targets_lack_the_property_declines():
    envelope = _run(_balance_session(
        (40.0, 40.0), reference={"via": "feeds", "property": "absent"}))
    assert [d["reason"] for d in envelope["not_checked"]] == ["missing_property"]


def test_a_malformed_reference_declines_as_configuration():
    envelope = _run(_balance_session((40.0, 40.0), reference={"property": "arrived"}))
    assert [d["reason"] for d in envelope["not_checked"]] == ["missing_config"]


def test_a_same_entity_output_still_works():
    """The existing form is unchanged: the whole point is that a reference may
    cross an edge, not that it must."""
    session = _balance_session((), reference="received")
    session.history.add("a", "received", 100.0, timestamp=T0 + timedelta(minutes=1))
    assert _run(session)["findings"] == []


# --- CONSISTENCY across the boundary ----------------------------------------

def _agreement_session(peers, reading=100.0, tolerance=0.001, aggregate="median"):
    reference = {"via": "quoted_on", "property": "reading"}
    if aggregate:
        reference["aggregate"] = aggregate
    session = EngineSession()
    session.load_model({"domain": {
        "id": "d", "name": "d", "entity_types": ["Point", "Probe"],
        "relationship_types": ["quoted_on"],
        "indicators": {"Point": [
            {"name": "reading", "type": "NUMERIC", "role": "percentage",
             "axioms": ["CONSISTENCY"], "window": "1h",
             "consistency": {"agrees_with": [reference],
                             "tolerance": tolerance}}]}}})
    session.add_entity("p1", "Point", {"reading": reading})
    for index, value in enumerate(peers):
        probe = f"q{index}"
        session.add_entity(probe, "Probe", {"reading": value})
        session.add_relationship("p1", "quoted_on", probe)
        session.history.add(probe, "reading", value,
                            timestamp=T0 + timedelta(minutes=1))
    return session


def test_peers_that_disagree_across_the_boundary_are_a_finding():
    envelope = _run(_agreement_session((105.0, 106.0)))
    assert [f["problem_type"] for f in envelope["findings"]] == \
        ["redundant_disagreement:reading"]
    assert "reading via quoted_on" in envelope["findings"][0]["reason"]


def test_peers_that_agree_are_not():
    assert _run(_agreement_session((100.02, 100.05)))["findings"] == []


def test_the_declared_aggregate_decides_the_verdict():
    """THE REASON IT MUST BE DECLARED. Identical data, identical tolerance:
    against the smaller reading the point agrees, against the middle one it
    does not. Nothing in the model says which the author meant, so the engine
    asks rather than picking."""
    assert _run(_agreement_session((100.0, 110.0), aggregate="min"))["findings"] == []
    assert len(_run(_agreement_session((100.0, 110.0),
                                       aggregate="median"))["findings"]) == 1


def test_several_peers_without_an_aggregate_decline():
    envelope = _run(_agreement_session((100.0, 110.0), aggregate=None))
    assert [d["reason"] for d in envelope["not_checked"]] == ["missing_config"]
    assert envelope["findings"] == []


def test_an_agreement_whose_edge_reaches_nobody_declines():
    session = _agreement_session(())
    envelope = _run(session)
    assert [d["reason"] for d in envelope["not_checked"]] == ["precondition_unmet"]


# --- the denominator --------------------------------------------------------

def test_a_cross_entity_cell_is_still_one_cell():
    """Reaching across an edge does not multiply the denominator: the balance
    is one (axiom, entity, indicator) however many targets it read."""
    assert _run(_balance_session((40.0, 40.0)))["checked"]["invariants"] == 1
