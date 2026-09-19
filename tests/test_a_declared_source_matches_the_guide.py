"""`Transition.is_declared` agrees with the vocabulary the guide publishes.

THE PROPERTY HAD NO CALLERS AND THE WRONG SET. It tested
`source in ("datasheet", "contract", "runbook")`. MODELING.md documents
`datasheet | contract | measured | estimated` for a transition's `source:`,
and `runbook` is an ACTION TEMPLATE's provenance -- a different declaration in
a different block. So the property rejected two of the four values the guide
tells an author to write, and accepted one the guide never offers.

Nothing failed, because nothing called it. That is the whole hazard: a
predicate with no callers is not inert, it is UNTESTED, and the first caller
inherits an answer nobody ever checked. The check is now derived from a named
tuple beside it, and this file pins that tuple against the guide's own list so
the two cannot drift apart again in silence.
"""
from __future__ import annotations

import pathlib

import pytest

from arbiter_engine.twin.topology import Transition

DOCUMENTED = ("datasheet", "contract", "measured", "estimated")


def _transition(source: str) -> Transition:
    return Transition(from_property="a", to_property="b", gain=1.0,
                      source=source)


class TestEveryDocumentedSourceCounts:

    @pytest.mark.parametrize("source", DOCUMENTED)
    def test_a_value_the_guide_offers_is_declared(self, source):
        assert _transition(source).is_declared, (
            f"`source: {source}` is one of the four values MODELING.md tells "
            f"an author to write, and the engine does not count it as a "
            f"declaration")

    def test_the_named_tuple_is_the_documented_set(self):
        assert tuple(Transition.DECLARED_SOURCES) == DOCUMENTED


class TestAFittedGainIsNotADeclaration:
    """The distinction the property exists to make."""

    @pytest.mark.parametrize("source", ["learned", "lstm_v1", "garch_v3", ""])
    def test_a_producer_identity_is_not_declared(self, source):
        assert not _transition(source).is_declared

    def test_runbook_is_not_a_transition_source(self):
        """It is an action template's provenance, and was accepted here."""
        assert not _transition("runbook").is_declared


class TestTheGuideStillSaysWhatThisAssumes:
    """The pin that makes the two sides one fact rather than two copies.

    Skipped rather than failed where the guide is not in this tree: it is
    generated into the published repository, so a source checkout may not
    carry it, and a test that fails for being in the wrong tree teaches a
    reader to ignore it.
    """

    def _guide(self):
        here = pathlib.Path(__file__).resolve()
        for parent in here.parents[:6]:
            candidate = parent / "MODELING.md"
            if candidate.is_file():
                return candidate
        return None

    def test_the_guide_lists_exactly_these_four(self):
        guide = self._guide()
        if guide is None:
            pytest.skip("MODELING.md is not in this tree")
        text = guide.read_text(encoding="utf-8")
        assert "datasheet | contract | measured | estimated" in text, (
            "the guide's documented `source:` vocabulary has moved and "
            "`Transition.DECLARED_SOURCES` still names the old one")
