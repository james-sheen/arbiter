"""A state the model calls bad, on an entity that is in it.

`bad:` loaded, landed on the indicator spec as `problematic_states`, and was read
by NOTHING in the package. A model saying `bad: [Failed]` about an entity whose
phase was `Failed` produced an envelope byte-identical to declaring nothing at
all -- no finding, no decline, and no `dropped_declarations` row, because the
loader recognised the key perfectly well and there was simply no consumer.

That is a third category beside the two the envelope already separates. An
unrecognised VALUE is reported in `dropped_declarations`. An unrecognised KEY is
refused by the loader. A RECOGNISED KEY WITH NO CONSUMER passes both and is
invisible from every surface.

Removing the key was the other candidate repair and the measurement ruled it out:
twenty-nine STATE indicators across six shipped domain files, eleven of them
declaring `bad:`. The vocabulary is in use and means what it says.

**`normal:` is deliberately not a check.** See the checker's own docstring: a
value in neither list is not a fault, and firing on one would report `Pending` and
`Succeeded` on every pod phase in the shipped k8s model.
"""
from __future__ import annotations

import pytest

yaml = pytest.importorskip("yaml")

from arbiter_engine.api import (  # noqa: E402
    EngineSession, attest, check, model_describe,
)

VOCABULARY = {"normal": ["Running"], "bad": ["Failed", "Unknown"]}


def _session(value, **indicator):
    spec = {"name": "phase", "type": "STATE", "axioms": ["STABILITY"]}
    spec.update(indicator)
    session = EngineSession()
    session.load_model(yaml.safe_dump({"domain": {
        "id": "state-probe", "name": "state probe",
        "entity_types": ["Pod"], "relationship_types": ["runs_on"],
        "indicators": {"Pod": [spec]}}}))
    session.add_entity("pod-1", "Pod", {"phase": value}, "pod-1")
    return session


def _findings(value, **indicator):
    return [f for f in check(_session(value, **indicator)).to_dict()["findings"]
            if f["problem_type"].startswith("declared_bad_state")]


class TestTheDeclaredBadStateFires:
    @pytest.mark.parametrize("value", ["Failed", "Unknown"])
    def test_a_state_the_model_calls_bad_is_reported(self, value):
        found = _findings(value, **VOCABULARY)
        assert len(found) == 1
        assert found[0]["severity"] == "high"
        assert value in found[0]["reason"]

    def test_the_finding_carries_what_the_model_called_healthy(self):
        """`normal:`'s consumer, asserted on the surface that actually shows it.

        A finding in `check`'s envelope carries axiom, entity, problem_type,
        reason and severity -- and no evidence. The first version of this test
        looked for evidence there and failed, which is the right failure: a
        consumer nobody can read is the defect this file is about, so the
        assertion belongs where a caller can reach it. `attest` is that surface.
        """
        session = _session("Failed", **VOCABULARY)
        check(session)
        attested = attest(session, "declared_bad_state:phase").to_dict()
        evidence = attested["evidence"][0]["evidence"]
        assert evidence["normal_states"] == ["Running"]
        assert evidence["problematic_states"] == ["Failed", "Unknown"]
        assert evidence["state"] == "Failed"


class TestItStaysQuietWhereItShould:
    def test_a_normal_state_is_not_reported(self):
        assert _findings("Running", **VOCABULARY) == []

    def test_a_state_in_NEITHER_list_is_not_reported(self):
        """The control that decides the design. `Pending` is in neither list and
        is ordinary; a rule firing on *not in normal* would report it, and the
        shipped k8s model would light up on every pod that is starting."""
        assert _findings("Pending", **VOCABULARY) == []

    def test_declaring_no_bad_states_checks_nothing(self):
        assert _findings("Failed", normal=["Running"]) == []

    def test_an_entity_with_no_value_is_not_reported(self):
        session = EngineSession()
        session.load_model(yaml.safe_dump({"domain": {
            "id": "state-probe", "name": "state probe",
            "entity_types": ["Pod"], "relationship_types": ["runs_on"],
            "indicators": {"Pod": [dict(
                {"name": "phase", "type": "STATE", "axioms": ["STABILITY"]},
                **VOCABULARY)]}}}))
        session.add_entity("pod-1", "Pod", {}, "pod-1")
        found = [f for f in check(session).to_dict()["findings"]
                 if f["problem_type"].startswith("declared_bad_state")]
        assert found == []


class TestTheSilenceIsGone:
    def test_a_bad_state_and_a_normal_one_no_longer_agree(self):
        """The defect, stated as the thing that used to be true. Before this
        check the two envelopes were identical, which is why nothing could fail
        on it -- there was no test to write that would have gone red."""
        bad = check(_session("Failed", **VOCABULARY)).to_dict()
        good = check(_session("Running", **VOCABULARY)).to_dict()
        assert bad["findings"] != good["findings"]
        assert bad["checked"] == good["checked"], (
            "the denominator moved between the two, so the difference above is "
            "not the finding this file is about")


class TestTheVocabularyIsVisibleWithoutRunningACheck:
    def test_model_describe_reports_it(self):
        described = model_describe(_session("Running", **VOCABULARY)).to_dict()
        states = described["model"]["indicators"]["Pod"][0]["states"]
        assert states == {"normal": ["Running"], "problematic": ["Failed", "Unknown"]}

    def test_an_indicator_declaring_none_carries_no_states_key(self):
        """Absent rather than empty. An empty vocabulary here would read as one
        that was declared and came out empty, which is a different statement."""
        described = model_describe(_session("Running")).to_dict()
        assert "states" not in described["model"]["indicators"]["Pod"][0]
