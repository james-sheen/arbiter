"""No name in this package cites a record you cannot read.

The 0.1.9 release renamed an exported constant for one reason, stated in its own
changelog entry: the old name cited a private tracker record, and that was "the
one claim on this surface a reader could not check". This holds the package to
that reason everywhere, not just on the name that prompted it.

WHAT IT CHECKS AND WHAT IT DOES NOT. Identifiers only -- every NAME token in
every shipped module. Not prose: a docstring may legitimately mention the test
that pins a behaviour, and a paragraph explaining a rename has to be able to say
what the old name was. Forbidding that would mean an erratum could not describe
the thing it corrects, which is the shape this project already refuses elsewhere.

A NAME IS DIFFERENT FROM A SENTENCE. You can read a sentence and judge it. You
cannot look up `classify_escalation_tier_per_cd1280`, and it appears in a
traceback, in `dir()`, and in any tooling that walks this package.

CASE-INSENSITIVE, AND THE PATTERN IS WIDER THAN IT LOOKS. A first census here
used a case-sensitive pattern and missed six constants spelled `_CD####`. A
second required a leading underscore and would have missed the exported name
that prompted the rule. This one requires neither.
"""
from __future__ import annotations

import io
import pathlib
import re
import tokenize

import pytest

from arbiter_engine import api as _anchor

#: `cd1234`, ``, `_cd_1234`. Three to five digits: the records this
#: project cites are four, and the range is wider than the practice on purpose.
CITATION = re.compile(r"cd[-_ ]?\d{3,5}", re.IGNORECASE)

#: The package root, reached through a module rather than named. The import
#: above is rewritten at build time, so this file walks the source tree here and
#: the installed package there without carrying either name.
PACKAGE = pathlib.Path(_anchor.__file__).parent


def _modules():
    return sorted(PACKAGE.rglob("*.py"))


def _identifiers(path: pathlib.Path) -> set[str]:
    names = set()
    with open(path, encoding="utf-8") as handle:
        for token in tokenize.generate_tokens(handle.readline):
            if token.type == tokenize.NAME and CITATION.search(token.string):
                names.add(token.string)
    return names


class TestNoShippedIdentifierCitesARecord:
    def test_the_package_is_clean(self):
        carriers = {str(p.relative_to(PACKAGE)): sorted(_identifiers(p))
                    for p in _modules() if _identifiers(p)}
        assert carriers == {}, (
            f"these identifiers name a record no reader of this package can "
            f"look up: {carriers}. Name the thing rather than the record -- the "
            f"0.1.9 changelog renamed an exported constant for exactly this")


class TestTheCheckCouldFail:
    """Without these, a clean result is indistinguishable from a broken walk."""

    def test_the_pattern_matches_the_shapes_that_have_appeared(self):
        for spelling in ("_env_bool_cd1213", "_SEVERITY_RANK_CD1121",
                         "CD508_ENTITY_PROPERTY_KEY",
                         "classify_escalation_tier_per_cd1280"):
            assert CITATION.search(spelling), spelling

    def test_the_pattern_does_not_match_ordinary_words(self):
        """`cd` is a common fragment. A rule that fired on `discard1234` would be
        turned off within a week, taking the signal with it."""
        for innocent in ("checked", "record_count", "cd", "cd12", "second_1234"):
            assert not CITATION.search(innocent), innocent

    def test_the_walk_reaches_the_package(self):
        assert len(_modules()) > 30, "the module walk found almost nothing"

    def test_a_planted_identifier_would_be_caught(self, tmp_path):
        planted = tmp_path / "planted.py"
        planted.write_text("def _helper_per_cd9999():\n    return None\n",
                           encoding="utf-8")
        assert _identifiers(planted) == {"_helper_per_cd9999"}

    def test_prose_is_deliberately_not_caught(self, tmp_path):
        """The scope, asserted rather than described. A docstring naming the test
        that pins a behaviour is a cross-reference, not a citation in a name."""
        prose = tmp_path / "prose.py"
        prose.write_text('"""See test_something_cd1234 for why."""\n'
                         '# renamed from _old_cd1234\n', encoding="utf-8")
        assert _identifiers(prose) == set()
