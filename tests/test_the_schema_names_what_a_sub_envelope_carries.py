"""The schema declares the payload the two largest sub-envelopes carry.

one transform out. That one found `simulation` and `plan`
riding as `additionalProperties` and named them in the schema's `properties` --
both as `$ref`s to the single generic `sub_envelope` definition, which declares
the five legs and allows anything beside them. So the trajectory, the tier, the
candidate ranking and the approximation disclosures all stayed undeclared, one
level below the fix.

Worse, the fix asserted that they were not. The sentence that an internal ruling added said
the two were *shaped like every other sub-envelope*. Measured, they are the two
least like the others:

    forecasts, shadow, discovery, entailment the five legs, nothing else
    projection + raced
    simulation + assumptions, per_step, tier,
                                                 tier_reason, raced, calibration
    plan + assumptions, candidates, best,
                                                 ranked, objective, direction,
                                                 raced, calibration

A claim of sameness is worse than silence here, because it removes the reason to
look. The coverage test below is derived from what the verbs actually emit
rather than from a list written beside them, so a new payload key fails this
test instead of riding undeclared for another three releases.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from arbiter_engine import api

SCHEMA_PATH = pathlib.Path(api.__file__).parent / "schema/envelope.schema.json"
def _example_path() -> pathlib.Path:
    """The worked dynamics example, from whichever copy this tree has.

    Published beside the package as `examples/`, and kept one directory deeper
    in the tree this package is derived from, so one candidate pair serves both.
    The path parts are separate literals for the reason the sibling guide helper
    uses them that way: written as one string it is an internal path in prose,
    and the scrub rewrites it into the middle of a sentence.

    It RAISES rather than skipping. The ship leg runs these tests against the
    staged tree, and a fixture that quietly vanishes there would take its whole
    file green with it.
    """
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / "examples" / "pump_tank_dynamics.yaml",
                      here.parents[2] / "docs" / "publication"
                      / "engine-example" / "pump_tank_dynamics.yaml"):
        if candidate.exists():
            return candidate
    raise AssertionError("no pump_tank_dynamics example found in this tree")


EXAMPLE = _example_path()

LEGS = {"checked", "findings", "not_checked", "questions", "meta"}
ACTIONS = [{"template": "throttle_pump", "entity_id": "p1",
            "parameters": {"speed_rpm": 3000}, "at_s": 0}]


@pytest.fixture(scope="module")
def schema():
    return json.loads(SCHEMA_PATH.read_text())


def _session():
    session = api.EngineSession()
    session.load_model(EXAMPLE.read_text())
    session.add_entity("p1", "Pump", properties={"speed_rpm": 2000})
    session.add_entity("t1", "Tank", properties={"level_pct": 50})
    session.add_relationship("p1", "feeds", "t1")
    session.add_observations("p1", "speed_rpm",
                             [2000.0 + (i % 9) for i in range(120)])
    session.add_observations("t1", "level_pct",
                             [50.0 + 0.02 * (i % 9) for i in range(120)])
    return session


def _envelopes():
    return {
        "rollout": api.rollout(_session(), actions=ACTIONS, horizon_s=1200,
                               step_s=300, file_predictions=True).to_dict(),
        "plan": api.plan(_session(), horizon_s=1200, step_s=300,
                         file_predictions=True).to_dict(),
        "project": api.project(_session()).to_dict(),
        "check": api.check(_session()).to_dict(),
        "gaps": api.gaps(_session()).to_dict(),
    }


class TestTheSchemaIsStillValid:
    def test_it_is_a_well_formed_2020_12_schema(self, schema):
        jsonschema = pytest.importorskip("jsonschema")
        jsonschema.Draft202012Validator.check_schema(schema)

    def test_every_verb_produces_a_conforming_envelope(self, schema):
        jsonschema = pytest.importorskip("jsonschema")
        validator = jsonschema.Draft202012Validator(schema)
        for name, envelope in _envelopes().items():
            errors = sorted(validator.iter_errors(envelope),
                            key=lambda e: list(e.path))
            assert not errors, f"{name}: {errors[0].message} at {list(errors[0].path)}"


class TestEveryPayloadKeyIsDeclared:
    """DERIVED FROM THE VERBS, not from a list. The bug this closes is exactly
    a list that went stale while the code grew."""

    def test_no_sub_envelope_carries_an_undeclared_key(self, schema):
        undeclared = {}
        for name, envelope in _envelopes().items():
            for key, value in envelope.items():
                if not isinstance(value, dict) or not (LEGS & set(value.keys())):
                    continue
                entry = schema["properties"].get(key)
                assert entry is not None, f"{name}.{key} has no schema entry"
                ref = entry.get("$ref", "").rsplit("/", 1)[-1]
                assert ref, f"{name}.{key} is not a $ref"
                declared = set(
                    schema["$defs"][ref].get("properties", {}).keys()) | LEGS
                missing = set(value.keys()) - declared
                if missing:
                    undeclared[f"{name}.{key}"] = sorted(missing)
        assert not undeclared, f"undeclared payload keys: {undeclared}"

    def test_the_three_that_deviate_have_their_own_definitions(self, schema):
        for key, ref in (("simulation", "simulation_envelope"),
                         ("plan", "plan_envelope"),
                         ("projection", "projection_envelope")):
            assert schema["properties"][key]["$ref"] == f"#/$defs/{ref}"
            assert ref in schema["$defs"]

    def test_the_four_that_do_not_still_point_at_the_generic_definition(self, schema):
        for key in ("forecasts", "shadow", "discovery", "entailment"):
            assert schema["properties"][key]["$ref"] == "#/$defs/sub_envelope"


class TestTheAssumptionsLegIsDeclaredAndLeftOpen:
    def test_it_is_an_array_of_string(self, schema):
        leg = schema["$defs"]["assumptions_leg"]
        assert leg["type"] == "array"
        assert leg["items"]["type"] == "string"

    def test_it_carries_no_enum(self, schema):
        """RULED, not overlooked. An enum would make every patch-legal stamp
        addition a schema change, and could not express the parameterised
        stamp whose value comes from the domain model."""
        assert "enum" not in schema["$defs"]["assumptions_leg"]

    def test_both_sub_envelopes_that_carry_it_reference_the_one_definition(self, schema):
        for ref in ("simulation_envelope", "plan_envelope"):
            prop = schema["$defs"][ref]["properties"]["assumptions"]
            assert prop["$ref"] == "#/$defs/assumptions_leg"

    def test_a_candidate_carries_it_too(self, schema):
        prop = schema["$defs"]["plan_candidate"]["properties"]["assumptions"]
        assert prop["$ref"] == "#/$defs/assumptions_leg"


class TestTheCorrectedSentence:
    def test_the_phrase_is_never_used_affirmatively(self, schema):
        """Negative space, narrowed. The closing sentence of that CD asserted a
        sameness that made the remaining half invisible; the correction has to
        quote that phrase in order to deny it, so the banned string is the
        AFFIRMATIVE construction and not the words themselves."""
        text = schema["additionalProperties"]["description"]
        assert "above and shaped like every other sub-envelope" not in text

    def test_it_says_which_ones_deviate(self, schema):
        text = schema["additionalProperties"]["description"]
        assert "NOT shaped like every other sub-envelope" in text
        assert "six keys beside the legs" in text
