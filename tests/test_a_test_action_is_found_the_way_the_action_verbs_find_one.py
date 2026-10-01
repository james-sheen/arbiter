"""`hypothesize` names a test action by the rule the action verbs use.

It matched a template's `applies_to` against the candidate's type exactly. The
action verbs ask `actions.applies()`, under which a subtype reaches the templates
of every type it `extends:`. So a `SmallPump extends Pump` candidate was told the
model declares no way to test it, while `file_action` and `plan` would apply the
`Pump` template to it. It also read the templates raw, so a template the action
verbs refuse as malformed could be offered as a test.
"""

from __future__ import annotations

from arbiter_engine import api
from arbiter_engine.inference.hypothesis import _test_action
from arbiter_engine.twin import actions

TEMPLATE = """
    - name: {name}
      applies_to: {applies_to}
      description: Restart it.
      parameters_schema:
        speed_rpm:
          type: number
          entity_property: speed_rpm
          candidates: [1000]
      effect: set
      settle_s: 30
      source: runbook
"""

MALFORMED = """
    - name: inspect_pump
      applies_to: Pump
      description: Look at it.
"""


def _model(templates: str) -> str:
    return f"""
domain:
  id: test-action
  name: Test action
  entity_types:
    - Pump
    - {{name: SmallPump, extends: Pump}}
    - Tank
  relationship_types: [feeds]
  indicators:
    Pump:
      - name: speed_rpm
        type: NUMERIC
        axioms: [BOUNDEDNESS]
        warning: 3000
        critical: 3500
    Tank:
      - name: level_pct
        type: NUMERIC
        axioms: [BOUNDEDNESS]
        warning: 85
        critical: 95
  relationship_rules:
    - type: feeds
      source_type: Pump
      target_type: Tank
      edge_direction: causal
      causal: {{weight: 0.6, leak: 0.01}}
    - type: feeds
      source_type: SmallPump
      target_type: Tank
      edge_direction: causal
      causal: {{weight: 0.6, leak: 0.01}}
  action_templates:{templates}
"""


def _test_actions(templates: str) -> dict:
    session = api.EngineSession()
    session.load_model(_model(templates))
    session.add_entity("BIG", "Pump", {"speed_rpm": 1500.0})
    session.add_entity("SMALL", "SmallPump", {"speed_rpm": 1500.0})
    session.add_entity("T1", "Tank", {"level_pct": 99.0})
    session.add_relationship("BIG", "feeds", "T1")
    session.add_relationship("SMALL", "feeds", "T1")
    api.check(session)
    leg = api.hypothesize(session, "T1").to_dict()["hypothesis"]
    return {row["cause"]: row["test_action"] for row in leg["candidates"]}


def test_a_subtype_is_named_its_parents_template():
    named = _test_actions(TEMPLATE.format(name="restart_pump", applies_to="Pump"))
    assert named["SMALL"] == "restart_pump", named


def test_an_exact_match_is_named_as_before():
    named = _test_actions(TEMPLATE.format(name="restart_pump", applies_to="Pump"))
    assert named["BIG"] == "restart_pump", named


def test_a_parent_is_not_named_its_subtypes_template():
    named = _test_actions(TEMPLATE.format(name="restart_small", applies_to="SmallPump"))
    assert named == {"BIG": None, "SMALL": "restart_small"}, named


def test_a_template_the_action_verbs_refuse_is_not_offered():
    named = _test_actions(MALFORMED)
    assert named == {"BIG": None, "SMALL": None}, named


def test_the_answer_agrees_with_actions_applies_for_every_candidate():
    templates = TEMPLATE.format(name="restart_pump", applies_to="Pump")
    session = api.EngineSession()
    session.load_model(_model(templates))
    accepted, _refused = actions.load_templates(session.model)
    lineage = getattr(session.model, "lineage", None)
    for entity_type in ("Pump", "SmallPump", "Tank"):
        expected = next((name for name, template in accepted.items()
                         if actions.applies(template, entity_type, lineage)), None)
        assert _test_action(session.model, entity_type) == expected, entity_type
