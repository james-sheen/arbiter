"""`transition:` and `temporal:` are nested blocks, and nothing checked them.

The loader compares every key an author types on an INDICATOR against
the set it reads, and reports the rest with a did-you-mean. One level down,
`forecast:` got the same treatment. The blocks that say how a value propagates
-- `temporal:` on a relationship rule, `transition:` beside it, and the
domain's `planning:` block -- got none of it, and they are the newest part of
the schema, which its sibling file already names as the shape most worth
misspelling.

WHAT THE AUTHOR SAW INSTEAD: nothing at all. Measured on one rule declaring
`propagation_delay: 120` and `gain_sgima: 0.002`, each one letter from a real
key:

  - the edge took the engine's DEFAULT dead time of 60 s in place of the
    declared 120 s, so `response_fraction(180)` read 0.1813 where the
    declaration says 0.0952 -- a response developing at nearly twice the rate
    the author wrote, for the whole horizon;
  - `gain_sigma` stayed 0.0, so every value the coupling drives carries no
    interval, `clearance_probability` quietly stops being a probability, and a
    rollout's projections stop being filed for want of a tolerance;
  - `unread_fields` was empty, `refused_blocks` was empty, and nothing
    declined.

The second is the whole of the band-propagation defect this package fixed the
day before, reachable again by one transposed letter and with no report.

`clamp_to_bounds` IS RETIRED HERE, and it is why this file exists. It was
parsed, stored on `Transition` and read by nothing -- a key on the published
schema surface that an author could declare and believe. It cannot be honoured
either: the only bounds this engine has are `warning:` and `critical:`, which
are DETECTION lines rather than physical limits, and clamping an imagined value
to them would cap the excursion at exactly the line a simulation exists to
cross. A tank projected to 130 would report the same finding as one projected
to 96, and `plan` ranks candidates on that difference.

`dynamics:` stays unchecked, for the reason its sibling gives: it carries a
model's own parameters, and which of those exist is the model's business.
"""
from __future__ import annotations

import pytest

from arbiter_engine.api import EngineSession, model_describe

RULE = {
    "type": "feeds", "source_type": "Pump", "target_type": "Tank",
    "temporal": {"propagation_delay_s": 120, "time_constant_s": 600,
                 "response_model": "exponential"},
    "transition": {"from": "speed_rpm", "to": "level_pct",
                   "gain": 0.02, "source": "datasheet"},
}


def _describe(rule=None, planning=None):
    domain = {
        "id": "coupling", "name": "coupling",
        "entity_types": ["Pump", "Tank"], "relationship_types": ["feeds"],
        "indicators": {
            "Pump": [{"name": "speed_rpm", "type": "NUMERIC",
                      "axioms": ["BOUNDEDNESS"], "critical": 9e9}],
            "Tank": [{"name": "level_pct", "type": "NUMERIC",
                      "axioms": ["BOUNDEDNESS"], "critical": 95}],
        },
        "relationship_rules": [rule if rule is not None else RULE],
    }
    if planning is not None:
        domain["planning"] = planning
    session = EngineSession()
    session.load_model({"domain": domain})
    return model_describe(session).to_dict()["model"]["unread_fields"]


def _unknown(fields):
    return {f["field"]: f.get("did_you_mean")
            for f in fields if f["reason"] == "unknown_key"}


def _rule(**overrides):
    out = {k: (dict(v) if isinstance(v, dict) else v)
           for k, v in RULE.items()}
    for key, value in overrides.items():
        block, _, leaf = key.partition("__")
        if leaf:
            out[block].pop(leaf, None) if value is None else None
            if value is not None:
                out[block][leaf] = value
        else:
            out[key] = value
    return out


class TestAMisspelledCouplingKeyIsReported:

    def test_a_misspelled_spread_is_caught_with_a_suggestion(self):
        """The costliest one: it silently removes every interval."""
        rule = _rule()
        rule["transition"]["gain_sgima"] = 0.002
        assert _unknown(_describe(rule)) == {
            "transition.gain_sgima": "gain_sigma"}

    def test_a_misspelled_dead_time_is_caught_with_a_suggestion(self):
        rule = _rule()
        rule["temporal"].pop("propagation_delay_s")
        rule["temporal"]["propagation_delay"] = 120
        assert _unknown(_describe(rule)) == {
            "temporal.propagation_delay": "propagation_delay_s"}

    def test_an_invented_key_is_reported_without_a_guess(self):
        rule = _rule()
        rule["transition"]["nonsense_key"] = 42
        reported = _unknown(_describe(rule))
        assert "transition.nonsense_key" in reported
        assert reported["transition.nonsense_key"] is None

    def test_a_misspelled_planning_key_is_caught(self):
        assert _unknown(_describe(planning={
            "objective": "expected_findings", "max_dpeth": 2})) == {
            "planning.max_dpeth": "max_depth"}

    def test_the_row_names_the_rule_it_came_from(self):
        rule = _rule()
        rule["transition"]["nonsense_key"] = 42
        row = [f for f in _describe(rule) if f["reason"] == "unknown_key"][0]
        assert row["rule"] == "Pump-feeds->Tank"


class TestARetiredKeyIsNoLongerSilent:

    def test_clamp_to_bounds_is_reported_rather_than_stored(self):
        """It was parsed onto `Transition` and consumed by nothing. A reader
        who declared it got no value and no warning."""
        rule = _rule()
        rule["transition"]["clamp_to_bounds"] = True
        assert "transition.clamp_to_bounds" in _unknown(_describe(rule))

    def test_nothing_still_carries_the_field(self):
        from arbiter_engine.twin.topology import Transition
        assert not hasattr(
            Transition("a", "b", 1.0, "datasheet"), "clamp_to_bounds")


class TestAnActionTemplateIsCheckedToo:
    """The block is MIXED, which is why it is checked rather than trusted. A
    mistyped `entity_property` is caught at rollout time -- the action is
    refused and counted -- and a mistyped `settle_s` is not caught anywhere:
    measured, `settle_s: 300` against a 60 s step declines
    `settle_exceeds_step`, and `settl_s: 300` declines nothing and returns a
    trajectory that reads as though the actuator were instantaneous."""

    TEMPLATE = {
        "name": "throttle_pump", "applies_to": "Pump",
        "description": "Set the pump to a specific speed.",
        "parameters_schema": {
            "speed_rpm": {"type": "number", "entity_property": "speed_rpm",
                          "candidates": [800, 1500]}},
        "effect": "set", "settle_s": 0, "source": "runbook",
    }

    def _with(self, template):
        domain = {
            "id": "acts", "name": "acts", "entity_types": ["Pump", "Tank"],
            "relationship_types": ["feeds"],
            "indicators": {
                "Pump": [{"name": "speed_rpm", "type": "NUMERIC",
                          "axioms": ["BOUNDEDNESS"], "critical": 9e9}],
                "Tank": [{"name": "level_pct", "type": "NUMERIC",
                          "axioms": ["BOUNDEDNESS"], "critical": 95}]},
            "relationship_rules": [RULE],
            "action_templates": [template],
        }
        session = EngineSession()
        session.load_model({"domain": domain})
        return _unknown(model_describe(session).to_dict()["model"]["unread_fields"])

    def test_a_misspelled_settle_time_is_caught(self):
        template = {k: v for k, v in self.TEMPLATE.items() if k != "settle_s"}
        template["settl_s"] = 300
        assert self._with(template) == {
            "action_templates.settl_s": "settle_s"}

    def test_a_misspelled_property_mapping_is_caught(self):
        template = {k: (dict(v) if isinstance(v, dict) else v)
                    for k, v in self.TEMPLATE.items()}
        template["parameters_schema"] = {
            "speed_rpm": {"type": "number", "entity_propery": "speed_rpm"}}
        assert self._with(template) == {
            "action_templates.parameters_schema.speed_rpm.entity_propery":
                "entity_property"}

    def test_a_template_in_the_other_schema_is_left_to_its_own_refusal(self):
        """THE FLOOR, and the reason this check is gated. `action_templates:`
        is the one block with a competing schema: eleven of the nineteen
        models this repository ships declare the orchestrator's richer shape,
        and `load_templates` already refuses each of those whole with
        `malformed_action: template is missing applies_to, parameters_schema`.
        That one decline names the real problem. Reporting its seven keys as
        unknown would bury it under rows calling each one a typo, when every
        one is valid in the schema the author was actually writing."""
        assert self._with({
            "name": "restart_service", "type": "remediation",
            "params": {"service": "str"}, "risk": "medium",
            "blast_radius": "single_host", "duration": "30s",
            "categories": ["restart"], "entity_types": ["Pump"],
        }) == {}

    def test_the_documented_template_reports_nothing(self):
        """`description` and a parameter's `type` are accepted and not acted
        on. Both ship in the engine's own worked example, so a check that
        reported them would fire on the file it is meant to validate."""
        assert self._with(self.TEMPLATE) == {}


class TestACorrectModelIsQuiet:

    def test_a_well_spelled_rule_reports_nothing(self):
        """The floor. A check that fires on a correct model is worse than one
        that never fires, because it trains its reader to ignore it."""
        assert _unknown(_describe()) == {}

    def test_every_documented_coupling_key_is_accepted(self):
        """Each key the guide shows, declared at once, reports nothing."""
        rule = _rule()
        rule["temporal"]["coupling_strength"] = 0.9
        rule["transition"]["gain_sigma"] = 0.002
        rule["transition"]["offset"] = 1.5
        assert _unknown(_describe(rule, planning={
            "objective": "expected_findings", "max_depth": 2,
            "max_rollouts": 50, "min_severity": "warning"})) == {}

    def test_a_rule_without_the_blocks_reports_nothing(self):
        assert _unknown(_describe({
            "type": "feeds", "source_type": "Pump",
            "target_type": "Tank"})) == {}


class TestAModelCarryingOnlyIndicatorsStillWorks:
    """`unread_fields` has to run on a `DomainModel` that carries
    ONLY `indicators`, because one already did: `test_unknown_value_cd1760`
    builds one with `__new__` and sets that single field, which is a fair
    fixture for a check whose indicator half is what it exercises.

    Reading the three new blocks as plain attributes raised `AttributeError`
    on thirty of that file's cases. None of them is in the engine lane -- the
    file sits under `tests/residual/` -- so the lane was green while the net
    was not, which is the whole reason the net is derived rather than
    assumed."""

    def test_the_indicator_half_runs_without_the_rest_of_the_model(self):
        from arbiter_engine.ontology.domain_loader import (
            DomainModel, parse_indicator)
        model = DomainModel.__new__(DomainModel)
        model.indicators = {"Unit": [parse_indicator(
            {"name": "obs", "axioms": ["BOUNDEDNESS"], "directon": "UPPER"},
            "Unit")]}
        rows = model.unread_fields()
        assert {r["field"] for r in rows if r["reason"] == "unknown_key"} == {
            "directon"}


class TestTheKeySetsMatchWhatTheParsersRead:
    """Derived, not transcribed. A key added to a parser and not to the set
    would make this check silently narrower than the schema it guards --
    which is the failure the check itself exists to report."""

    def test_the_temporal_set_is_what_the_builder_reads(self):
        from arbiter_engine.ontology.domain_loader import (
            _KNOWN_TEMPORAL_KEYS)
        assert _KNOWN_TEMPORAL_KEYS == _keys_read("temporal_block")

    def test_the_transition_set_is_what_the_builder_reads(self):
        from arbiter_engine.ontology.domain_loader import (
            _KNOWN_TRANSITION_KEYS)
        read = _keys_read("block")
        assert _KNOWN_TRANSITION_KEYS <= read
        assert {"from", "to", "gain", "source"} <= _KNOWN_TRANSITION_KEYS


def _keys_read(varname: str) -> frozenset:
    """Literal keys read off `varname` in the topology builder, by AST.

    THE ABSOLUTE IMPORTS IN THIS FILE ARE DOTTED, and that is not a style
    choice. This suite is derived: one file runs against two package roots, and
    the derivation recognises an absolute import by the DOT that follows the
    package name. An import written without that dot is carried across
    untouched, and then names a package that does not exist on the other side.

    THE PARAGRAPH THAT USED TO STAND HERE explained the same trap by
    naming the tool that performs the derivation and quoting a dotless import as
    an example. Neither survives the crossing: the tool is not in this tree, and
    the example is itself an absolute import, so it was rewritten in place and
    the published sentence gave a reader an import that does not resolve. It is
    stated as a property of this file now, which is the form that is true on
    both sides.
    """
    import ast
    import pathlib
    from arbiter_engine.twin import builder
    tree = ast.parse(pathlib.Path(builder.__file__).read_text())
    found = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == varname
                and node.args and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            found.add(node.args[0].value)
        if (isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Name)
                and node.value.id == varname
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)):
            found.add(node.slice.value)
    return frozenset(found)
