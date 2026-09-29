"""An indicator given as a mapping is read exactly as the model loader reads it.

The reasoner's loader takes indicators as parsed specs or as mappings. The
mapping route had a parser of its own, a copy patched one key at a time, and it
never learned four forms: ``homeostasis:`` (a setpoint and a tolerance),
``flow:``, ``expect_variation:``, and a bound written as ``{from_property: ...}``,
which it could not turn into a float, so the whole indicator was dropped. A
platform that loads models as mappings therefore missed findings the engine
reports on the same input -- six of them, measured by running the published
verticals' own models through both.

There is one parser now. These tests hold the two routes to the same spec for
every form, and hold the mapping route to naming what it cannot read.
"""
from __future__ import annotations

import copy

import pytest

from arbiter_engine.history import InMemoryObservationHistory
from arbiter_engine.interfaces import Entity, RelationshipGraph
from arbiter_engine.ontology.domain_loader import load_domain
from arbiter_engine.ontology.reasoner import UnifiedAxiomReasoner

#: One of each form the model loader reads, on one entity type.
INDICATORS = {
    "Line": [
        {"name": "cycle_time_s", "type": "NUMERIC", "axioms": ["HOMEOSTASIS"],
         "homeostasis": {"setpoint": 60, "tolerance": 4}, "window": "2h"},
        {"name": "weld_current_a", "type": "NUMERIC", "axioms": ["STABILITY"],
         "expect_variation": True},
        {"name": "parts_in", "type": "NUMERIC", "axioms": ["CONSERVATION"], "flow": "in",
         "conservation": {"input_property": "parts_in",
                          "output_properties": ["parts_out"]}},
        {"name": "margin", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
         "lower_critical": {"from_property": "requirement"}, "warning": 900},
        {"name": "speed", "type": "NUMERIC", "axioms": ["HOMEOSTASIS", "BOUNDEDNESS"],
         "direction": "UPPER", "critical": 12.5, "violation_severity": "critical"},
        {"name": "state", "type": "STATE", "axioms": ["STABILITY"], "timeout": "10m",
         "normal": ["running"], "transient": ["starting"], "bad": ["jammed"]},
        {"name": "feeds", "type": "RELATIONSHIP", "axioms": ["CONNECTIVITY"],
         "target_type": "Line", "relation_type": "feeds", "min_cardinality": 1},
        {"name": "count", "type": "NUMERIC", "axioms": ["MONOTONICITY", "CONSISTENCY"],
         "role": "count",
         "monotonicity": {"expected_direction": "increasing", "allow_reset": True},
         "consistency": {"agrees_with": ["count_mes"], "tolerance": 0.01}},
    ],
}
MODEL = {"domain": {"id": "one-parser", "name": "one parser (test)",
                    "entity_types": ["Line"], "indicators": INDICATORS}}


def _through_mappings(indicators):
    loader = UnifiedAxiomReasoner().loader
    loader.set_domain_indicators(copy.deepcopy(indicators))
    return loader


def _by_name(specs):
    return {spec.name: spec for spec in specs}


def test_every_form_reads_the_same_by_either_route():
    loader = _through_mappings(INDICATORS)
    assert loader.unread_indicator_fields() == [], "the fixture declares only what is read"
    mapped = _by_name(loader.get_indicators("Line"))
    modelled = _by_name(load_domain(copy.deepcopy(MODEL)).indicators["Line"])
    assert sorted(mapped) == sorted(modelled)
    for name, spec in modelled.items():
        assert mapped[name] == spec, name


@pytest.mark.parametrize("name, attribute, expected", [
    ("cycle_time_s", "homeostasis_config", {"setpoint": 60, "tolerance": 4}),
    ("weld_current_a", "expect_variation", True),
    ("parts_in", "flow_direction", "in"),
    ("margin", "threshold_sources", {"lower_critical": "requirement"}),
])
def test_the_four_forms_the_mapping_route_used_to_drop(name, attribute, expected):
    spec = _by_name(_through_mappings(INDICATORS).get_indicators("Line"))[name]
    assert getattr(spec, attribute) == expected


def test_a_bound_read_from_another_property_is_judged():
    reasoner = UnifiedAxiomReasoner()
    reasoner.loader.set_domain_indicators(copy.deepcopy(
        {"Line": [i for i in INDICATORS["Line"] if i["name"] == "margin"]}))
    under = Entity(id="line-1", type="Line", name="line-1",
                   properties={"margin": 100.0, "requirement": 150.0})
    above = Entity(id="line-2", type="Line", name="line-2",
                   properties={"margin": 200.0, "requirement": 150.0})
    result = reasoner.detect([under, above], RelationshipGraph(), InMemoryObservationHistory())
    found = {(p.entity_id, p.problem_type)
             for p in list(result.problems) + list(getattr(result, "warnings", []))}
    assert ("line-1", "below_critical_threshold:margin") in found
    assert not {f for f in found if f[0] == "line-2"}


def test_a_key_nothing_reads_is_named_and_costs_only_itself():
    loader = _through_mappings({"Line": [
        {"name": "flow_rate", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
         "warnig": 5, "critical": 9}]})
    [spec] = loader.get_indicators("Line")
    assert spec.critical_threshold == 9.0
    [row] = loader.unread_indicator_fields()
    assert (row["indicator"], row["field"], row["reason"], row["did_you_mean"]) == \
        ("flow_rate", "warnig", "unknown_key", "warning")


def test_a_value_nothing_recognises_is_named():
    loader = _through_mappings({"Line": [
        {"name": "flow_rate", "type": "numric", "axioms": ["BOUNDEDNESS"], "critical": 9}]})
    rows = loader.unread_indicator_fields()
    assert [(r["field"], r["reason"], r["value"]) for r in rows] == \
        [("type", "unknown_value", "numric")]


def test_the_mapping_route_names_what_the_model_names():
    unread = copy.deepcopy(MODEL)
    unread["domain"]["indicators"]["Line"].append(
        {"name": "temp", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
         "expect_variation": True, "directon": "higher_is_worse", "critical": 80})
    mapped = _through_mappings(unread["domain"]["indicators"]).unread_indicator_fields()
    modelled = load_domain(unread).unread_fields()
    assert mapped == modelled
    assert {(r["field"], r["reason"]) for r in mapped} == {
        ("expect_variation", "axiom_not_declared"), ("directon", "unknown_key")}


def test_loading_the_same_mappings_twice_names_each_field_once():
    loader = UnifiedAxiomReasoner().loader
    bad = {"Line": [{"name": "flow_rate", "axioms": ["BOUNDEDNESS"], "warnig": 5}]}
    loader.set_domain_indicators(copy.deepcopy(bad))
    loader.set_domain_indicators(copy.deepcopy(bad), merge=False)
    assert len(loader.unread_indicator_fields()) == 1
