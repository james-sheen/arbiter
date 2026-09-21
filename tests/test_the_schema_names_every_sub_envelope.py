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


class TestTheTwoSimulationVerbsAreNamed:

    @pytest.mark.parametrize("name", ["simulation", "plan"])
    def test_the_schema_declares_it(self, schema, name):
        assert name in schema["properties"], (
            f"{name} is produced by a verb and absent from the wire contract")

    @pytest.mark.parametrize("name", ["simulation", "plan"])
    def test_it_is_shaped_like_every_other_sub_envelope(self, schema, name):
        assert schema["properties"][name].get("$ref") == "#/$defs/sub_envelope"

    @pytest.mark.parametrize("name", ["simulation", "plan"])
    def test_it_is_not_required(self, schema, name):
        """An envelope from a verb that does not produce it -- or from an
        engine predating it -- must still validate."""
        assert name not in schema.get("required", [])


class TestEverySubEnvelopeSharesOneShape:

    def test_no_sub_envelope_is_declared_inline(self, schema):
        """A second inline shape is how the two contracts drift apart."""
        for name, spec in schema["properties"].items():
            if name in LEGS:
                continue
            assert spec.get("$ref") == "#/$defs/sub_envelope", name

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
