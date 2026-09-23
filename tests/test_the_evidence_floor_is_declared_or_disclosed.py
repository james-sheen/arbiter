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
"""

from __future__ import annotations

import pathlib
import re

import pytest

from arbiter_engine.api import EngineSession, check, infer
from arbiter_engine.assumptions import (
    EVIDENCE_SEVERITY_NOT_DECLARED, is_known_stamp)

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
        assert leg.get("assumptions", []) == []

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
        assert strict.get("assumptions", []) == []
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
        assert leg["assumptions"], "a typo was applied silently"
