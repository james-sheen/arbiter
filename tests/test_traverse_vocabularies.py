"""`traverse` takes two closed vocabularies, and they must behave alike.

One of them used to reach an enum lookup unguarded, so an unrecognised word left
the library as `KeyError: 'BACKWARD'` -- an uncaught exception from a function
whose product is saying what it could not do, naming an upper-cased token the
caller never typed. Its sibling declined into an envelope two lines above.

THE ASYMMETRY IS THE SUBJECT, NOT EITHER PARAMETER. Both are pinned here, in one
file, so a third argument added later has an obvious shape to match and a place
that goes red if it does not.

AND THE FIRST FIX NARROWED THE INPUT. Written to match the guarded sibling, it
refused `FORWARD` -- which the previous release accepts, because the unguarded
lookup upper-cased whatever it was given. Withdrawing an accepted input is not
something a patch release may do, so both vocabularies now FOLD case: one widens,
neither narrows, and the pair answers in the canonical spelling.
"""
from __future__ import annotations

import tempfile
import textwrap

import pytest

from arbiter_engine.api import EngineSession, traverse

MODEL = """
    domain:
      id: v
      name: V
      entity_types: [Node, Pod]
      relationship_types: [hosts]
      indicators:
        Node:
          - name: cpu_pct
            type: NUMERIC
            role: percentage
            axioms: [BOUNDEDNESS]
            warning: 80
            critical: 95
    """


@pytest.fixture
def session():
    path = tempfile.mktemp(suffix=".yaml")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(textwrap.dedent(MODEL))
    s = EngineSession()
    s.load_model(path)
    s.add_entity("n1", "Node", {"cpu_pct": 99})
    s.add_entity("p1", "Pod", {})
    s.add_relationship("n1", "hosts", "p1")
    return s


def _reason(envelope):
    return envelope.to_dict()["meta"].get("reason")


class TestNeitherVocabularyRaises:
    @pytest.mark.parametrize("kwargs", [
        {"direction": "backward"},
        {"direction": ""},
        {"direction": None},
        {"value_mode": "sideways"},
        {"value_mode": None},
    ])
    def test_an_unrecognised_word_declines_rather_than_raising(self, session, kwargs):
        """The whole finding. `None` is in the list because the fold has to cope
        with a non-string too -- the old path raised AttributeError on it."""
        assert _reason(traverse(session, ["n1"], **kwargs))

    @pytest.mark.parametrize("kwargs,expected", [
        ({"direction": "backward"}, ["forward", "reverse", "bidirectional"]),
        ({"value_mode": "sideways"}, ["current", "hypothetical", "projected"]),
    ])
    def test_the_refusal_names_what_would_have_worked(self, session, kwargs, expected):
        """A refusal that does not name the set leaves the author guessing at the
        same vocabulary that just rejected them."""
        reason = _reason(traverse(session, ["n1"], **kwargs))
        for word in expected:
            assert word in reason, f"{word} missing from {reason!r}"


class TestBothFoldCase:
    @pytest.mark.parametrize("direction", ["forward", "FORWARD", "Reverse",
                                           "bidirectional", "BiDirectional"])
    def test_every_direction_spelling_is_accepted(self, session, direction):
        assert _reason(traverse(session, ["n1"], direction=direction)) is None

    @pytest.mark.parametrize("value_mode", ["current", "CURRENT", "Hypothetical"])
    def test_every_value_mode_spelling_is_accepted(self, session, value_mode):
        assert _reason(traverse(session, ["n1"], value_mode=value_mode)) is None

    def test_the_previous_release_loses_no_input_it_accepted(self, session):
        """The narrowing check, stated as its own case rather than left implicit
        in the parametrised list above. `FORWARD` worked before this change and
        must go on working."""
        assert _reason(traverse(session, ["n1"], direction="FORWARD")) is None


class TestTheValidSetIsDerived:
    def test_the_direction_set_comes_from_the_enum(self, session):
        """A vocabulary written beside the one it copies is a place to drift.
        This asserts the refusal names exactly the enum's members -- so adding a
        direction cannot leave the message describing the old set."""
        from arbiter_engine.twin.topology import TraversalDirection
        reason = _reason(traverse(session, ["n1"], direction="nonsense"))
        for member in TraversalDirection:
            assert member.value in reason, f"{member.value} missing from {reason!r}"
