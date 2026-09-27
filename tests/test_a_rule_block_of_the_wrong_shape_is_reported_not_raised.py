"""A rule's block of the wrong shape, or a number that is not one, is reported -- not raised.

Found while was being landed, and present on the tree before it:

  - `temporal:` written as a list -- the shape `transition:` accepts -- or as a
    number raised `AttributeError` out of `model_describe`, through the topology
    builder, so the report that exists to name a model's mistakes could not be
    produced for it at all;
  - a temporal number written with its unit, `propagation_delay_s: 120s`, raised
    `ValueError` the same way;
  - `causal: 0.8`, a weight written without its block, came back from `infer` as
    `internal_error` -- an engine fault's name for an author's mistake;
  - a strength written `"0.8"` or `low` was read as no weight at all, or as the
    engine's own leak, with nothing said.

Every reader now skips such a declaration as though it were absent, and
`unread_fields` names it. The check and each reader ask ONE resolver, so the
check is exactly as strict as the reader it speaks for: a quoted `"120"` that
`float()` reads is applied and not reported, and a quoted `"0.8"` that causal
inference ignores is reported. A transition's shape is not here -- the builder
already refuses such a block by name, in `model_describe`'s `transitions`.
"""

from __future__ import annotations

import pytest

from arbiter_engine import api
from arbiter_engine.inference.causal import resolve_strength
from arbiter_engine.temporal.temporal_edge import resolve_number
from arbiter_engine.twin.topology import TIME_COURSE_KEYS

RULE = {
    "type": "feeds", "source_type": "Pump", "target_type": "Tank",
    "edge_direction": "causal", "causal": {"weight": 0.7, "leak": 0.02},
    "temporal": {"propagation_delay_s": 120, "time_constant_s": 600,
                 "response_model": "exponential"},
    "transition": {"from": "speed_rpm", "to": "level_pct", "gain": 0.02,
                   "source": "datasheet"},
}


def _domain(rule):
    return {"domain": {
        "id": "shape", "name": "shape", "entity_types": ["Pump", "Tank"],
        "relationship_types": ["feeds"],
        "indicators": {
            "Pump": [{"name": "speed_rpm", "type": "NUMERIC",
                      "axioms": ["BOUNDEDNESS"], "critical": 9e9,
                      "dynamics": {"model": "persistence"}}],
            "Tank": [{"name": "level_pct", "type": "NUMERIC",
                      "axioms": ["BOUNDEDNESS"], "critical": 95}]},
        "relationship_rules": [rule]}}


def _rule(block=None, key=None, value=None):
    rule = {k: (dict(v) if isinstance(v, dict) else v) for k, v in RULE.items()}
    if block is None:
        return rule
    if key is None:
        rule[block] = value
    elif block == "":
        rule[key] = value
    else:
        rule[block][key] = value
    return rule


def _session(rule):
    session = api.EngineSession()
    session.load_model(_domain(rule))
    session.add_entity("p1", "Pump", {"speed_rpm": 1000.0})
    session.add_entity("t1", "Tank", {"level_pct": 50.0})
    session.add_relationship("p1", "feeds", "t1")
    return session


def _named(session):
    rows = api.model_describe(session).to_dict()["model"]["unread_fields"]
    return {r["field"]: r.get("value") for r in rows
            if r["reason"] == "unknown_value"}


def _edge(session):
    edges = [e for bucket in api._build_topology(session).edges.values()
             for e in bucket]
    assert len(edges) == 1
    return edges[0]


def _infer_reasons(session):
    payload = api.infer(session, "t1").to_dict()
    return {d["reason"] for d in payload["inference"]["not_checked"]}


def _every_verb_completes(session):
    api.model_describe(session)
    api.check(session)
    api.traverse(session, "p1")
    api.rollout(session, actions=[], horizon_s=120, step_s=60)
    assert "internal_error" not in _infer_reasons(session)


class TestABlockOfTheWrongShapeIsSkippedAndNamed:

    @pytest.mark.parametrize("block, value", [
        ("temporal", [{"propagation_delay_s": 5}]),
        ("temporal", 5),
        ("causal", 0.8),
        ("causal", [{"weight": 0.7}]),
    ])
    def test_every_verb_completes_and_the_block_is_named(self, block, value):
        session = _session(_rule(block, None, value))
        _every_verb_completes(session)
        rows = [r for r in api.model_describe(session).to_dict()["model"]
                ["unread_fields"] if r["field"] == block]
        assert [r["reason"] for r in rows] == ["unknown_value"]
        assert "not a mapping" in rows[0]["remedy"]
        assert rows[0]["rule"] == "Pump-feeds->Tank"

    def test_a_skipped_time_course_is_the_engines_own_and_says_so(self):
        """Skipped means absent: the edge carries the engine's numbers and
        asks for both, exactly as it does when no block was written."""
        edge = _edge(_session(_rule("temporal", None, [
            {"propagation_delay_s": 5}])))
        assert edge.undeclared_time_course == TIME_COURSE_KEYS

    def test_a_weight_without_its_block_asks_for_the_weight(self):
        assert "cpt_missing" in _infer_reasons(
            _session(_rule("causal", None, 0.8)))


class TestANumberThatIsNotOneIsNamed:

    @pytest.mark.parametrize("block, key, raw", [
        ("temporal", "propagation_delay_s", "120s"),
        ("temporal", "time_constant_s", "slow"),
        ("temporal", "coupling_strength", "x"),
        ("", "conservation_tolerance", "5%"),
        ("causal", "weight", "high"),
        ("causal", "leak", "low"),
    ])
    def test_it_is_named_and_nothing_raises(self, block, key, raw):
        session = _session(_rule(block, key, raw))
        _every_verb_completes(session)
        assert _named(session) == {(f"{block}.{key}" if block else key): raw}

    def test_a_delay_written_with_its_unit_is_left_to_the_engine(self):
        """The rest of the block still applies, and the time course asks for
        the one number it could not read."""
        edge = _edge(_session(_rule("temporal", "propagation_delay_s", "120s")))
        assert edge.time_constant_s == 600.0
        assert edge.undeclared_time_course == ("propagation_delay_s",)


class TestTheCheckIsExactlyAsStrictAsItsReader:

    def test_a_quoted_number_the_builder_reads_is_applied_and_not_named(self):
        session = _session(_rule("temporal", "propagation_delay_s", "120"))
        assert _named(session) == {}
        assert _edge(session).propagation_delay_s == 120.0

    def test_a_quoted_strength_inference_ignores_is_named(self):
        """Causal inference reads only a number, and really does ignore the
        string -- which is why it is reported."""
        session = _session(_rule("causal", "weight", "0.8"))
        assert _named(session) == {"causal.weight": "0.8"}
        assert "cpt_missing" in _infer_reasons(session)


class TestTheResolversNeverRaise:

    @pytest.mark.parametrize("raw, expected", [
        (None, (None, None)), ("", (None, None)), (120, (120.0, None)),
        ("120", (120.0, None)), ("120s", (None, "120s")),
        ([5], (None, "[5]")), ({"a": 1}, (None, "{'a': 1}")),
    ])
    def test_resolve_number(self, raw, expected):
        assert resolve_number(raw) == expected

    @pytest.mark.parametrize("raw, expected", [
        (None, (None, None)), (0.8, (0.8, None)), (1, (1.0, None)),
        ("0.8", (None, "0.8")), (True, (None, "True")), ([0.8], (None, "[0.8]")),
    ])
    def test_resolve_strength(self, raw, expected):
        assert resolve_strength(raw) == expected


class TestTheYamlBuilderPathToo:
    """The builder's second path, which reads the same blocks through
    `_build_edge` rather than `_apply_declared_rule`."""

    @staticmethod
    def _edges(rule):
        from arbiter_engine.interfaces import (
            Entity, RelationshipGraph)
        from arbiter_engine.twin.builder import TopologyBuilder
        entities = {
            "p1": Entity(id="p1", type="Pump", name="p1",
                         properties={"speed_rpm": 1000.0}),
            "t1": Entity(id="t1", type="Tank", name="t1",
                         properties={"level_pct": 50.0}),
        }
        graph = RelationshipGraph()
        graph.add_relationship("p1", "feeds", "t1")
        topology = TopologyBuilder().build_from_yaml(
            _domain(rule), entities, graph)
        return [e for bucket in topology.edges.values() for e in bucket]

    def test_a_list_where_the_time_course_belongs_is_skipped(self):
        edges = self._edges(_rule("temporal", None, [{"propagation_delay_s": 5}]))
        assert edges and all(e.propagation_delay_s != 5 for e in edges)

    def test_a_tolerance_that_is_not_a_number_keeps_the_default(self):
        edges = self._edges(_rule("", "conservation_tolerance", "5%"))
        assert edges and all(e.conservation_tolerance == 0.05 for e in edges)
