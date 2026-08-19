"""The envelope has a schema, and the schema is true of the engine.

A consumer pins `>=0.1.6,<0.2` and nothing stated what `0.2` was allowed to
break. The describe payload's nesting had already moved once between releases,
silently: a reader that worked got `None` from a lookup, which reads as *this
engine does not support that* rather than *this moved*, and the consumer wrote a
tolerant reader that tried both locations.

So there are two artifacts and this file tests the join between them. The schema
is a document; `meta.schema_version` is the field that tells a reader which
document applies. Neither is worth anything if the engine emits something else,
which is what the derivation walk below checks: every enum in the schema is
compared against the producer that generates its members, and every envelope the
engine can emit is checked for keys the schema forbids.

Runs against both trees. The schema resolves relative to the engine package
rather than by repository path, which is why it lives beside the code that emits
the envelope — a schema only checkable in the tree it was written in is the half
that does not matter.
"""

import json
from pathlib import Path

import pytest

import arbiter_engine as _engine
from arbiter_engine.api import (
    attest, check, gaps, model_describe, traverse,
)
from arbiter_engine.envelope import (
    ENVELOPE_SCHEMA_VERSION, unavailable_envelope,
)
from arbiter_engine.types import (
    Axiom, NotEvaluatedReason, Severity,
)

from conftest import ENTITY_ID, session_for

SCHEMA_PATH = Path(_engine.__file__).parent / "schema" / "envelope.schema.json"


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def _envelopes() -> dict:
    """One envelope per tool, plus the two shapes a tool can answer with.

    Built once per call rather than cached, because `attest` reads the session's
    last result and the walk would otherwise depend on test order.
    """
    session = session_for("BOUNDEDNESS")
    session.entities[ENTITY_ID].properties["level_pct"] = 99.0
    session.add_observations(ENTITY_ID, "level_pct", [99.0] * 12)
    check(session)
    return {
        "model_describe": model_describe(session),
        "check": check(session),
        "gaps": gaps(session),
        "traverse": traverse(session, [ENTITY_ID]),
        "attest": attest(session, "threshold_exceeded:level_pct"),
        "unavailable": unavailable_envelope("nothing loaded"),
    }


class TestTheSchemaShips:
    def test_it_is_beside_the_engine_package(self):
        assert SCHEMA_PATH.is_file(), (
            f"no schema at {SCHEMA_PATH}; a consumer cannot validate against a "
            f"document the package does not carry")

    def test_it_is_valid_json_and_declares_its_dialect(self, schema):
        assert schema["$schema"].startswith("https://json-schema.org/")
        assert schema["type"] == "object"

    def test_it_requires_all_five_legs(self, schema):
        assert set(schema["required"]) == {
            "checked", "findings", "not_checked", "questions", "meta"}


class TestTheVersionField:
    def test_every_envelope_carries_it(self):
        """Unconditional, including `unavailable`. A field present only
        sometimes cannot be branched on, which is the one thing a version field
        is for — and an unavailable envelope is exactly when a reader most
        needs to know what shape it is reading."""
        for name, envelope in _envelopes().items():
            meta = envelope.to_dict()["meta"]
            assert meta["schema_version"] == ENVELOPE_SCHEMA_VERSION, (
                f"{name} carries no schema_version")

    def test_it_is_not_the_package_version(self):
        """Tying them would make every patch release look like a contract
        change, which trains a reader to ignore the field."""
        assert isinstance(ENVELOPE_SCHEMA_VERSION, int)
        assert ENVELOPE_SCHEMA_VERSION >= 1


class TestTheSchemaIsTrueOfTheEngine:
    """The half that a document cannot do for itself.

    Each enum below is compared against the PRODUCER of its members, not
    against a list somebody typed twice. A closed enum with a missing member
    produces a confident misclassification, and the way that happens is
    exactly this: a schema written by reading the code once.
    """

    def test_the_decline_reasons_match_their_enum(self, schema):
        declared = set(schema["properties"]["not_checked"]["items"]
                       ["properties"]["reason"]["enum"])
        assert declared == {r.value for r in NotEvaluatedReason}

    def test_the_axiom_names_match_their_enum(self, schema):
        declared = set(schema["properties"]["not_checked"]["items"]
                       ["properties"]["axiom"]["enum"])
        assert declared == {a.value for a in Axiom}

    def test_the_severity_names_match_their_enum(self, schema):
        declared = set(schema["properties"]["findings"]["items"]
                       ["properties"]["severity"]["enum"]) - {None}
        assert declared == {s.value for s in Severity}

    def test_the_source_vocabulary_matches_the_module(self, schema):
        from arbiter_engine.envelope import (
            SOURCE_LIVE, SOURCE_UNAVAILABLE, SOURCE_WARMING_UP,
        )
        declared = set(schema["properties"]["meta"]["properties"]
                       ["source"]["enum"])
        assert declared == {SOURCE_LIVE, SOURCE_WARMING_UP, SOURCE_UNAVAILABLE}

    def test_the_checked_summary_fields_match_the_dataclass(self, schema):
        import dataclasses
        from arbiter_engine.envelope import CheckedSummary
        declared = set(schema["properties"]["checked"]["properties"])
        assert declared == {f.name for f in dataclasses.fields(CheckedSummary)}

    def test_no_envelope_emits_a_meta_key_the_schema_forbids(self, schema):
        """`meta` is `additionalProperties: false`, so this is a real
        constraint rather than a description."""
        allowed = set(schema["properties"]["meta"]["properties"])
        assert schema["properties"]["meta"]["additionalProperties"] is False
        for name, envelope in _envelopes().items():
            extra = set(envelope.to_dict()["meta"]) - allowed
            assert not extra, f"{name} emits {extra} under meta"

    def test_no_decline_emits_a_key_the_schema_forbids(self, schema):
        """The decline record is the leg with the most fields and the one a
        consumer parses hardest. Walked over a session engineered to produce
        the sample-floor record, which carries the most keys of any shape."""
        item = schema["properties"]["not_checked"]["items"]
        assert item["additionalProperties"] is False
        allowed = set(item["properties"])
        session = session_for("STABILITY")
        session.entities[ENTITY_ID].properties["speed_rpm"] = 1.0
        session.add_observations(ENTITY_ID, "speed_rpm", [1.0, 2.0, 3.0])
        records = check(session).to_dict()["not_checked"]
        assert records, "the fixture produced no decline to check"
        for record in records:
            extra = set(record) - allowed
            assert not extra, f"a decline emits {extra}"


class TestItValidatesForReal:
    """A structural walk catches a forbidden key; only a validator catches a
    type. Guarded because `jsonschema` is not an engine dependency and must not
    become one — the checks above run everywhere and are the ones that would
    catch a drift between the schema and the producer."""

    @pytest.mark.parametrize("name", [
        "model_describe", "check", "gaps", "traverse", "attest", "unavailable"])
    def test_each_tools_envelope_validates(self, schema, name):
        jsonschema = pytest.importorskip(
            "jsonschema",
            reason="`jsonschema` is not installed and is deliberately not a "
                   "dependency of this engine; the derivation checks above "
                   "cover the schema-versus-producer join either way.")
        jsonschema.validate(_envelopes()[name].to_dict(), schema)

    def test_the_validator_rejects_a_broken_envelope(self, schema):
        """Non-vacuity. A validator that accepts everything reports rigour and
        provides none — proved by PLANTING the breakage rather than by trusting
        that validation happened."""
        jsonschema = pytest.importorskip("jsonschema", reason="see above")
        broken = _envelopes()["check"].to_dict()
        broken["meta"]["source"] = "definitely_not_a_source"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(broken, schema)

    def test_the_validator_rejects_a_missing_leg(self, schema):
        jsonschema = pytest.importorskip("jsonschema", reason="see above")
        broken = _envelopes()["check"].to_dict()
        del broken["not_checked"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(broken, schema)


class TestTheEnumsWereDerivedNotTranscribed:
    """The walk above found this on its first run, which is the argument for it.

    The schema's axiom enum was written as lowercase names — plausible, tidy,
    and not what `Axiom` holds. Every finding the engine emits carries the
    uppercase form, so a consumer validating a real response against the
    shipped schema would have been told their engine was broken.

    A schema is a vocabulary written down, and a vocabulary written down
    instead of derived is the failure this project has the longest record of.
    The two tests below are the guard, kept separate from the enum walk so the
    reason survives a future edit to it.
    """

    def test_the_axiom_enum_is_the_engines_own_spelling(self, schema):
        declared = set(schema["properties"]["findings"]["items"]
                       ["properties"]["axiom"]["enum"]) - {None}
        assert declared == {a.value for a in Axiom}
        assert all(name.isupper() for name in declared), (
            "the axiom names are not what the engine emits")

    def test_the_severity_enum_is_the_engines_own_spelling(self, schema):
        declared = set(schema["properties"]["findings"]["items"]
                       ["properties"]["severity"]["enum"]) - {None}
        assert declared == {s.value for s in Severity}
        assert all(name.islower() for name in declared), (
            "the severity names are not what the engine emits; they differ in "
            "case from the axiom names, which is exactly the kind of detail a "
            "transcription gets consistent and the producer does not")
