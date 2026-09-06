"""Every leg the wire contract requires is named where a reader will look.

THE DEFECT THIS EXISTS FOR. `questions` was a required member of the envelope
and appeared in no prose in this repository -- named in the schema, named in one
line of COMPATIBILITY.md about ordering, and nowhere a person learning the engine
would find it. The README's envelope section listed three legs where the schema
required five. Nothing was broken, every test passed, and the surface was
invisible: it surfaced only when somebody drawing up what a new vertical would
have to build registered a shipped capability as a missing one.

That is the failure mode a suite cannot normally see, because nothing calls
documentation. So the check is the derivation: the required members come out of
the schema the package ships, and the README has to name each one. A sixth leg
added tomorrow turns this red on the day it lands, rather than on the day
somebody notices the document is short.

DERIVED, NOT LISTED. A tuple of leg names typed into this file would be a second
copy of the schema's `required` array, and a second copy does not fail when the
original grows -- it stays true about what it lists and silent about the rest,
which is the same shape as the defect above one level up.
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from arbiter_engine import api as _anchor

PACKAGE = pathlib.Path(_anchor.__file__).parent

#: The heading the envelope is described under, and the one after it. Matched by
#: title rather than by position: a section number moves when a section is
#: inserted above it, and this file would then check the wrong prose while
#: staying green.
SECTION = re.compile(r"^## The envelope$(.*?)^## ", re.M | re.S)


def _schema() -> pathlib.Path:
    """The wire contract, from the package that ships it.

    One expression resolves in both trees because the build renames the package
    and not the layout: `detection/schema/` here, `arbiter_engine/schema/` in the
    published repository.
    """
    path = PACKAGE / "schema" / "envelope.schema.json"
    assert path.is_file(), f"no envelope schema at {path}"
    return path


def _readme() -> pathlib.Path:
    """The README, in either tree this file runs in.

    Shipped, it sits beside `tests/`. In the repository it is the merged source
    the build renders from. Both are tried and the failure names both, because a
    resolver that silently picks the wrong one would compare the claim against a
    document nobody reads.
    """
    candidates = [
        pathlib.Path(__file__).resolve().parents[1] / "README.md",
        pathlib.Path(__file__).resolve().parents[2]
        / "docs" / "publication" / "README-merged.md",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise AssertionError(f"no README found; looked at {candidates}")


def _required_legs() -> list[str]:
    return list(json.loads(_schema().read_text(encoding="utf-8"))["required"])


def _envelope_section(text: str) -> str:
    found = SECTION.search(text)
    assert found, (
        "the README no longer has a section headed `## The envelope`; the "
        "claim this guards has gone and so has the guard")
    return found.group(1)


def _names(leg: str, prose: str) -> bool:
    """Does the prose name this leg?

    Word-boundary matched, which is exactly right for these names rather than
    incidentally so: `_` is a word character, so `checked` does NOT match inside
    `not_checked` and does match in `checked.invariants`. A substring test would
    call `checked` documented on the strength of the word `not_checked` being
    present, which is the wrong answer for the one pair most likely to occur.
    """
    return re.search(rf"\b{re.escape(leg)}\b", prose) is not None


class TestTheRequiredLegsAreDerivable:
    def test_the_schema_declares_some(self):
        """The non-vacuity half. Every assertion below is of the form *each
        required leg is named*, and that is TRUE of an empty list -- so a schema
        that lost its `required` array would turn this file green rather than
        red."""
        assert len(_required_legs()) >= 4, (
            f"only {len(_required_legs())} required members found; this file "
            f"cannot be checking anything meaningful")

    def test_questions_is_one_of_them(self):
        """Pinned by name because it is the specific leg this file was written
        for. If it stops being required, this guard should be re-read rather
        than quietly keep passing on the other four."""
        assert "questions" in _required_legs()


class TestTheReadmeNamesEveryLeg:
    @pytest.mark.parametrize("leg", _required_legs())
    def test_the_envelope_section_names_it(self, leg):
        prose = _envelope_section(_readme().read_text(encoding="utf-8"))
        assert _names(leg, prose), (
            f"`{leg}` is a required member of every envelope and the README's "
            f"envelope section does not name it. A shipped surface no document "
            f"names is indistinguishable from one that does not exist")

    def test_the_section_says_which_verb_fills_questions(self):
        """Naming the key is not enough on its own. `check` returns `questions`
        empty and `gaps` is the verb that fills it, so a reader who finds the key
        and calls the verb they already use learns that it does nothing."""
        prose = _envelope_section(_readme().read_text(encoding="utf-8"))
        assert _names("gaps", prose), (
            "the envelope section names `questions` without naming `gaps`, "
            "which is the only verb that fills it")


class TestTheMatcherCanFail:
    """Every probe asserts its own mutation. A check that cannot go red is not
    evidence, and the three below are the ways this one could pass vacuously."""

    def test_a_leg_the_prose_omits_is_reported_missing(self):
        prose = _envelope_section(_readme().read_text(encoding="utf-8"))
        assert not _names("perambulations", prose)

    def test_removing_a_leg_from_the_prose_breaks_the_check(self):
        prose = _envelope_section(_readme().read_text(encoding="utf-8"))
        for leg in _required_legs():
            elided = re.sub(rf"\b{re.escape(leg)}\b", "xxx", prose)
            assert not _names(leg, elided), (
                f"eliding `{leg}` left the check passing, so the check is not "
                f"reading what it claims to read")

    def test_a_substring_match_would_have_answered_differently(self):
        """The reason for the word boundary, asserted rather than described. On
        a section that names `not_checked` and not `checked`, a substring test
        says documented and this one says missing."""
        sample = "not_checked   what was NOT evaluated, and why"
        assert "checked" in sample
        assert not _names("checked", sample)
