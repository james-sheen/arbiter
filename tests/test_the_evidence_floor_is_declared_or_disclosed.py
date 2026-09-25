"""The severity floor `infer` reads evidence against, and who chose it.

`infer` treats an entity as faulty evidence only when its worst
finding is HIGH or CRITICAL. That is a modelling choice, it was a literal in a
loop, and it said so nowhere. Everywhere else this engine's rule is
declare-don't-default: an undeclared time course is supplied AND stamped, a
fitted gain is a proposal until an author adopts it, an indicator with no
declared model is refused by name. This one number was simply applied.

WHY IT IS THE WORST KIND OF DEFAULT: it is invisible from the answer. A model
whose breaches are all warnings returns every posterior sitting at its prior,
which reads as a graph that is not wired up rather than as a floor the reader
did not choose. Measured while writing the specimen that first ran this verb --
the first draft used warning-level readings and the intervention changed
nothing -- and an outside review then named it as the place the engine's own
discipline had not been applied to itself.

TWO THINGS LAND TOGETHER, and neither is enough alone. `causal.evidence_severity:`
makes the floor declarable; `evidence_severity_not_declared` discloses it when
it is not declared. A declarable key with no stamp would leave every existing
model silently on the old floor, which is the state this closes.

AN UNUSABLE DECLARATION IS NO DECLARATION, and that is a decision rather than a
shortcut. Partially applying `[critical, hihg]` as `[critical]` would leave an
author reading a posterior computed against a floor they did not write and
cannot see -- the same defect one level down.

- AND IT WAS INDISTINGUISHABLE FROM NEVER HAVING TRIED. The round that
shipped the two things above closed the KEY side of this and left the VALUE
side open: a third outside review measured four different author actions
returning one bare stamp, three of them someone attempting to declare the
floor. The reading it reproduced was *not declared*, therefore *my file did not
load*, with no thread to pull. What lands below is the second half -- a stamp
BESIDE the first rather than instead of it, so the original claim and anyone
matching on it are untouched, and the refused word named in `model_describe`
where a `did_you_mean` can live.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from arbiter_engine.api import (EngineSession, check, infer,
                                            model_describe)
from arbiter_engine.assumptions import (
    EVIDENCE_SEVERITY_NOT_DECLARED, EVIDENCE_SEVERITY_UNUSABLE,
    is_known_stamp)
from arbiter_engine.types import Severity

#: Measured. Also written into the example's header, so the two move together.
AT_WARNING_UNDECLARED = 0.014182
AT_WARNING_DECLARED = 0.670634

DECLARATION = ("  causal:\n"
               "    evidence_severity: [warning, high, critical]\n\n"
               "  entity_types:")


def _examples_dir() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / "examples",
                      here.parents[2] / "docs" / "publication" / "engine-example"):
        if candidate.is_dir() and list(candidate.glob("*.yaml")):
            return candidate
    raise AssertionError("no examples directory found in this tree")


def _spec() -> str:
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / "MODELING.md",
                      here.parents[2] / "docs" / "publication" / "domain-model-spec.md"):
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    raise AssertionError("no modelling guide found in this tree")


def _base() -> str:
    return _examples_dir().joinpath(
        "substation_feeder.yaml").read_text(encoding="utf-8")


def _leg(model: str, panel_v: float) -> dict:
    session = EngineSession()
    session.load_model(model)
    session.add_entity("sub-1", "Supply", properties={"voltage_kv": 11.0})
    session.add_entity("fdr-1", "Feeder", properties={})
    session.add_entity("pnl-1", "Panel", properties={"voltage_v": panel_v})
    session.add_entity("pnl-2", "Panel", properties={"voltage_v": panel_v})
    session.add_relationship("sub-1", "powers", "fdr-1")
    session.add_relationship("fdr-1", "powers", "pnl-1")
    session.add_relationship("fdr-1", "powers", "pnl-2")
    check(session)
    return infer(session, target="sub-1").to_dict()["inference"]


#: The two stamps this file is about. Every assertion that an answer carries
#: "no stamp" or "only the first stamp" is about THESE, and is asked of these:
#: the query below targets an entity with a reading of its own, so the answer
#: also carries `target_reading_set_aside`, which says nothing about the floor
#: and would otherwise make every such assertion a claim about every stamp
#: `infer` may ever add.
FLOOR_STAMPS = (EVIDENCE_SEVERITY_NOT_DECLARED, EVIDENCE_SEVERITY_UNUSABLE)


def _floor(leg: dict) -> list:
    return [s for s in leg.get("assumptions", []) if s in FLOOR_STAMPS]


def _declaring(severities: str) -> str:
    return _base().replace(
        "  entity_types:",
        f"  causal:\n    evidence_severity: {severities}\n\n  entity_types:", 1)


class TestTheStampIsPartOfThePublishedVocabulary:

    def test_it_has_one_name(self):
        assert is_known_stamp(EVIDENCE_SEVERITY_NOT_DECLARED)

    def test_the_guide_documents_the_key_that_silences_it(self):
        """A stamp telling a reader to declare something, pointing at a key the
        modelling guide never mentions, is a disclosure with no remedy. The
        guide had no section on causal input at all until this round."""
        spec = _spec()
        assert "evidence_severity" in spec
        assert "edge_direction: causal" in spec


class TestTheDefaultIsDisclosed:

    def test_an_undeclared_model_is_stamped(self):
        assert EVIDENCE_SEVERITY_NOT_DECLARED in _leg(_base(), 230.0)["assumptions"]

    def test_it_is_stamped_whatever_the_answer_turns_out_to_be(self):
        """The disclosure is about the INPUT rule, not about the result. A
        stamp that appeared only on uninteresting answers would be decoration."""
        for panel_v in (230.0, 212.0, 200.0):
            assert EVIDENCE_SEVERITY_NOT_DECLARED in _leg(_base(), panel_v)["assumptions"]

    def test_a_declared_model_is_not_stamped(self):
        """Two-sided. A stamp that fires whatever the model says discloses
        nothing."""
        leg = _leg(_declaring("[warning, high, critical]"), 212.0)
        assert _floor(leg) == []

    def test_no_other_discipline_gained_an_assumptions_key(self):
        """The leg is emitted only when something was stamped, so a payload
        that never stamps is byte-identical to before this landed."""
        session = EngineSession()
        session.load_model(_base())
        session.add_entity("sub-1", "Supply", properties={"voltage_kv": 11.0})
        payload = check(session).to_dict()
        assert "assumptions" not in payload.get("forecasts", {})


class TestDeclaringItChangesTheAnswer:
    """A key that discloses but does not decide would be worse than the
    silence: it would name a choice the author still cannot make."""

    def test_a_warning_breach_moves_nothing_on_the_engines_floor(self):
        assert _leg(_base(), 212.0)["checked"]["posterior"] == pytest.approx(
            AT_WARNING_UNDECLARED)

    def test_the_same_breach_counts_once_warning_is_declared(self):
        assert _leg(_declaring("[warning, high, critical]"),
                    212.0)["checked"]["posterior"] == pytest.approx(
            AT_WARNING_DECLARED)

    def test_the_examples_header_states_both_figures(self):
        # The comment block, bounded by the YAML document start at column
        # zero -- not by the first occurrence of the word, which the header
        # itself now contains while telling a reader where to put the key.
        header = re.split(r"^domain:", _base(), maxsplit=1, flags=re.MULTILINE)[0]
        for value in (AT_WARNING_UNDECLARED, AT_WARNING_DECLARED):
            assert str(value) in header, value

    def test_declaring_only_critical_is_stricter_than_the_default(self):
        """The floor moves both ways, so it is a choice and not a switch."""
        strict = _leg(_declaring("[critical]"), 200.0)
        assert _floor(strict) == []
        assert strict["checked"]["posterior"] == pytest.approx(
            _leg(_base(), 200.0)["checked"]["posterior"])


class TestAnUnusableDeclarationIsNoDeclaration:

    @pytest.mark.parametrize("severities", ["[critical, hihg]", "[]", "[nonsense]"])
    def test_it_falls_back_and_says_so(self, severities):
        leg = _leg(_declaring(severities), 212.0)
        assert EVIDENCE_SEVERITY_NOT_DECLARED in leg["assumptions"], severities
        assert leg["checked"]["posterior"] == pytest.approx(AT_WARNING_UNDECLARED)

    def test_it_is_not_partly_applied(self):
        """`[critical, hihg]` must not quietly become `[critical]`. If it did,
        the answer would match the strict-floor run and carry no stamp."""
        leg = _leg(_declaring("[critical, hihg]"), 212.0)
        # The FLOOR stamps, not the list: the answer carries another stamp for
        # a reason unrelated to the floor, and a bare truthiness check would
        # then pass with the typo applied.
        assert _floor(leg), "a typo was applied silently"


def _rows(model: str) -> list:
    """The `causal.` rows of `model_describe`'s unread-fields report."""
    session = EngineSession()
    session.load_model(model)
    return [row for row
            in model_describe(session).to_dict()["model"]["unread_fields"]
            if str(row.get("field", "")).startswith("causal.")]


class TestARefusedDeclarationIsDistinguishableFromAnOmission:
    """The finding this class exists for, stated as the measurement that found
    it: write four different things, read four different reports."""

    def test_an_omission_carries_only_the_first_stamp(self):
        leg = _leg(_base(), 212.0)
        assert _floor(leg) == [EVIDENCE_SEVERITY_NOT_DECLARED]

    @pytest.mark.parametrize("severities",
                             ["[critical, hihg]", "[]", "[nonsense]",
                              "critical"])
    def test_a_refused_declaration_carries_both(self, severities):
        leg = _leg(_declaring(severities), 212.0)
        assert EVIDENCE_SEVERITY_UNUSABLE in leg["assumptions"], severities
        assert EVIDENCE_SEVERITY_NOT_DECLARED in leg["assumptions"], severities

    def test_a_usable_declaration_carries_neither(self):
        leg = _leg(_declaring("[warning, high, critical]"), 212.0)
        assert _floor(leg) == []

    def test_the_two_reports_are_not_the_same_report(self):
        """The whole finding in one assertion: these were equal before."""
        omitted = _floor(_leg(_base(), 212.0))
        refused = _floor(_leg(_declaring("[critical, hihg]"), 212.0))
        assert omitted != refused

    def test_the_second_stamp_never_arrives_alone(self):
        """`not_declared` stays true whenever `unusable` is emitted -- the
        floor really was the engine's. A consumer matching only the first name
        must not stop matching because the author tried and was refused."""
        for severities in ("[critical, hihg]", "[]", "critical"):
            leg = _leg(_declaring(severities), 212.0)
            if EVIDENCE_SEVERITY_UNUSABLE in leg["assumptions"]:
                assert EVIDENCE_SEVERITY_NOT_DECLARED in leg["assumptions"]

    def test_the_stamp_is_in_the_published_vocabulary(self):
        assert is_known_stamp(EVIDENCE_SEVERITY_UNUSABLE)

    def test_the_guide_documents_it(self):
        assert EVIDENCE_SEVERITY_UNUSABLE in _spec()


class TestModelDescribeNamesTheWordThatWasRefused:
    """A stamp cannot carry which value was rejected -- `assumptions` is a list
    of strings. The row that can carry it already existed for indicators."""

    def test_a_misspelled_severity_is_named_with_a_near_miss(self):
        rows = _rows(_declaring("[critical, hihg]"))
        assert len(rows) == 1, rows
        assert rows[0]["reason"] == "unknown_value"
        assert rows[0]["value"] == "hihg"
        assert rows[0]["did_you_mean"] == "high"

    def test_the_remedy_lists_the_severities_that_would_work(self):
        remedy = _rows(_declaring("[critical, hihg]"))[0]["remedy"]
        for member in Severity:
            assert member.value in remedy, member

    @pytest.mark.parametrize("severities,written",
                             [("critical", "critical"), ("[]", []),
                              ("", None)])
    def test_a_wrong_shape_is_not_called_an_unknown_value(self, severities,
                                                          written):
        """`critical` names a real severity and `[]` names none, so
        `unknown_value` would misdescribe both and offer no near-miss."""
        rows = _rows(_declaring(severities))
        assert len(rows) == 1, rows
        assert rows[0]["reason"] == "malformed_value"
        assert rows[0]["value"] == written
        assert rows[0]["did_you_mean"] is None

    def test_a_bare_key_is_told_it_was_written_with_no_value(self):
        """`evidence_severity:` on its own line. The author DID write the key,
        so `not a single value` would describe something they did not do."""
        remedy = _rows(_declaring(""))[0]["remedy"]
        assert "written with none" in remedy

    def test_a_usable_declaration_reports_nothing(self):
        assert _rows(_declaring("[warning, high, critical]")) == []

    def test_an_omission_reports_nothing(self):
        assert _rows(_base()) == []

    def test_a_misspelled_key_still_reports_as_a_key(self):
        """The key side closed a round earlier and must stay closed: a typo in
        the KEY is an unknown key, not an unusable value."""
        model = _base().replace(
            "  entity_types:",
            "  causal:\n    evidence_severty: [critical]\n\n  entity_types:", 1)
        rows = _rows(model)
        assert [r["reason"] for r in rows] == ["unknown_key"]
