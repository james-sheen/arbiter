"""Every sub-envelope a verb produces is named in the wire schema.

`envelope.schema.json` listed the five legs and six sub-envelopes,
and `simulation` and `plan` -- the two the 0.2.3 release was about -- rode as
additional properties. The prose beside `additionalProperties` enumerated six
smaller tool-specific keys and mentioned neither, so the contract's own
inventory was stale by exactly the surface that release added, and a consumer
validating an envelope got no shape guarantee for the simulation verbs.

Reported from outside, as the recommendation to validate the four legs and
`meta` and then read `simulation`/`plan` defensively. That advice was correct
against the schema as written, which is the problem.

THIS TEST IS DERIVED, NOT TRANSCRIBED. The expected set comes from the verbs
themselves, so a sub-envelope added later and not named in the schema fails
here rather than waiting to be noticed by a reader.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import arbiter_engine as _engine

# Beside the engine PACKAGE, derived from the package itself. A path spelled
# from this file's own parents is right in one tree and wrong in the other:
# the published package is not named `detection` and its tests do not sit one
# directory deeper. The ship leg refuses that, which is what it is for.
SCHEMA = Path(_engine.__file__).parent / "schema" / "envelope.schema.json"

#: The legs every envelope carries, which are not sub-envelopes.
LEGS = {"checked", "findings", "not_checked", "questions", "meta"}


@pytest.fixture(scope="module")
def schema():
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def _composes_sub_envelope(schema, spec) -> bool:
    """Does this property reach `#/$defs/sub_envelope`, directly or through one
    definition that composes it?

    One level of indirection is allowed and no more: a specialised
    definition may say *the shared shape, plus my payload*, which is what
    `simulation`, `plan` and `projection` do. Anything deeper would be a second
    description of the five legs, which is what this test exists to prevent.
    """
    ref = spec.get("$ref")
    if ref == "#/$defs/sub_envelope":
        return True
    if not ref or not ref.startswith("#/$defs/"):
        return False
    target = schema["$defs"].get(ref.rsplit("/", 1)[-1])
    if not isinstance(target, dict):
        return False
    return any(member.get("$ref") == "#/$defs/sub_envelope"
               for member in target.get("allOf", [])
               if isinstance(member, dict))


class TestTheTwoSimulationVerbsAreNamed:

    @pytest.mark.parametrize("name", ["simulation", "plan"])
    def test_the_schema_declares_it(self, schema, name):
        assert name in schema["properties"], (
            f"{name} is produced by a verb and absent from the wire contract")

    @pytest.mark.parametrize("name", ["simulation", "plan"])
    def test_it_is_built_on_the_shared_sub_envelope_shape(self, schema, name):
        """ AMENDED THIS TEST, because it pinned a false claim.

        It asserted `$ref == sub_envelope` under the name *is shaped like
        every other sub-envelope*, which is the sentence also wrote
        into the schema and which is not true: `simulation` carries six keys
        beside the legs and `plan` eight, where four of the others carry none.
        The INTENT was that no sub-envelope be declared inline, so that the
        shared shape cannot drift. That intent survives -- each of these now
        composes `sub_envelope` through `allOf` and adds only its own payload.
        """
        assert _composes_sub_envelope(schema, schema["properties"][name])

    @pytest.mark.parametrize("name", ["simulation", "plan"])
    def test_it_is_not_required(self, schema, name):
        """An envelope from a verb that does not produce it -- or from an
        engine predating it -- must still validate."""
        assert name not in schema.get("required", [])


class TestEverySubEnvelopeSharesOneShape:

    def test_no_sub_envelope_is_declared_inline(self, schema):
        """A second inline shape is how the two contracts drift apart.

        - the check is now *reaches the shared shape*, not *is the
        shared shape*. Three sub-envelopes carry payload the others do not and
        have their own definitions; all three still compose this one, so there
        is exactly one description of the five legs in the document.
        """
        for name, spec in schema["properties"].items():
            if name in LEGS:
                continue
            assert _composes_sub_envelope(schema, spec), name

    def test_the_known_set_is_accounted_for(self, schema):
        declared = set(schema["properties"]) - LEGS
        assert declared == {
            "forecasts", "shadow", "projection", "entailment", "inference",
            "discovery", "simulation", "plan"}


class TestTheProseNoLongerMisdescribesThem:

    def test_the_additional_properties_note_says_they_are_named_above(
            self, schema):
        """The sentence that enumerated six smaller keys beside these two
        without mentioning either. Pinned so the inventory cannot go stale
        again in silence."""
        note = schema["additionalProperties"]["description"]
        assert "simulation" in note and "plan" in note
        assert "named in `properties`" in note
