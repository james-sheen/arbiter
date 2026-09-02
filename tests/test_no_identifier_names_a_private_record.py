"""No name in this package cites a record you cannot read.

The 0.1.9 release renamed an exported constant for one reason, stated in its own
changelog entry: the old name cited a private tracker record, and that was "the
one claim on this surface a reader could not check". This holds the package to
that reason everywhere, not just on the name that prompted it.

WHAT IT CHECKS AND WHAT IT DOES NOT. Identifiers -- every NAME token in every
shipped module -- and the string constants shaped like one. Not prose: a
docstring may legitimately mention the test that pins a behaviour, and a
paragraph explaining a rename has to be able to say what the old name was.
Forbidding that would mean an erratum could not describe the thing it corrects,
which is the shape this project already refuses elsewhere.

A NAME CAN HIDE IN A STRING, and the constant that prompted all of this was one:
`__cd508_axiom_thresholds__` was a wire key, read out of `Entity.properties` and
typed by a caller. A NAME-token pass cannot see it. So string constants are
checked too, on the narrow test that decides the question -- does it look like
something you would type -- and a sentence mentioning a record stays out, for
the reason in the paragraph above. Measured when this arm was added: three at the
time, all keys or provenance values, none of them in a published module.

The two arms need each other and neither is redundant. An identifier is caught
by shape wherever it appears; a string is caught only if it is name-shaped, and
`"see cd1234 for why"` is deliberately not.

A NAME IS DIFFERENT FROM A SENTENCE. You can read a sentence and judge it. You
cannot look up `classify_escalation_tier_per_cd1280`, and it appears in a
traceback, in `dir()`, and in any tooling that walks this package.

CASE-INSENSITIVE, AND THE PATTERN IS WIDER THAN IT LOOKS. A first census here
used a case-sensitive pattern and missed six constants spelled `_CD####`. A
second required a leading underscore and would have missed the exported name
that prompted the rule. This one requires neither.
"""
from __future__ import annotations

import ast
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

#: What separates a name from a sentence. One token, no spaces, no punctuation:
#: exactly what you could type as an identifier or a dict key, which is the
#: question -- can a reader who meets this look it up.
NAME_SHAPED = re.compile(r"\A[A-Za-z_][A-Za-z_0-9]*\Z")


def _modules():
    return sorted(PACKAGE.rglob("*.py"))


def _identifiers(path: pathlib.Path) -> set[str]:
    names = set()
    with open(path, encoding="utf-8") as handle:
        for token in tokenize.generate_tokens(handle.readline):
            if token.type == tokenize.NAME and CITATION.search(token.string):
                names.add(token.string)
    return names


def _docstring_nodes(tree: ast.AST) -> set:
    """The string constants that ARE prose by position, so they can be excluded.

    A docstring is the first statement of a module, class or function; nothing
    else about the node tells you. `ast.get_docstring` answers per node, so the
    set is collected once and the walk below tests membership.
    """
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                found.add(id(body[0].value))
    return found


def _name_shaped_strings(path: pathlib.Path) -> set:
    """Name-shaped string constants citing a record. Docstrings excluded."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = _docstring_nodes(tree)
    return {node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
            and NAME_SHAPED.match(node.value)
            and CITATION.search(node.value)}


class TestNoShippedIdentifierCitesARecord:
    def test_the_package_is_clean(self):
        carriers = {str(p.relative_to(PACKAGE)): sorted(_identifiers(p))
                    for p in _modules() if _identifiers(p)}
        assert carriers == {}, (
            f"these identifiers name a record no reader of this package can "
            f"look up: {carriers}. Name the thing rather than the record -- the "
            f"0.1.9 changelog renamed an exported constant for exactly this")


class TestNoShippedStringHidesOne:
    """The same rule, for the shape the rule was written about.

    `__cd508_axiom_thresholds__` travelled in `Entity.properties`. It was a
    value a caller typed and a key the engine read, and no identifier pass would
    have found it -- which is why the arm above, added first, could report clean
    while the exact defect it was named for sat one token type away.
    """

    def test_no_key_or_tag_cites_a_record(self):
        carriers = {str(p.relative_to(PACKAGE)): sorted(_name_shaped_strings(p))
                    for p in _modules() if _name_shaped_strings(p)}
        assert carriers == {}, (
            f"these string constants are names -- keys, tags, provenance values "
            f"-- citing a record no reader can look up: {carriers}. A caller "
            f"types these; renaming one is a wire change and belongs in the "
            f"changelog, which is the argument for catching it here")


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


class TestTheStringArmCouldFail:
    """Same discipline as the arm above: planted, innocent, and scope."""

    def test_the_wire_key_that_prompted_the_rule_would_be_caught(self, tmp_path):
        planted = tmp_path / "planted.py"
        planted.write_text('KEY = "__cd508_axiom_thresholds__"\n', encoding="utf-8")
        assert _name_shaped_strings(planted) == {"__cd508_axiom_thresholds__"}

    def test_the_three_shapes_that_were_actually_here_would_be_caught(self, tmp_path):
        """Not hypotheses. These were live in the tree when this arm was added:
        a provenance value, a metadata key and an evidence tag."""
        found = tmp_path / "found.py"
        found.write_text(
            'PROVENANCE = {"bridge": "cd1468"}\n'
            'META_KEY = "cd190_propagation_failed"\n'
            'TAG = "cd1466"\n', encoding="utf-8")
        assert _name_shaped_strings(found) == {
            "cd1468", "cd190_propagation_failed", "cd1466"}

    def test_a_sentence_mentioning_a_record_is_not_caught(self, tmp_path):
        """The scope, asserted, and its edge stated rather than implied.

        A log line explaining why something declined may cite the record that
        decided it; forbidding that would forbid the erratum from describing
        what it corrects. The build scrub removes the HYPHENATED spelling from
        prose on the way out, which is the spelling those lines use and the only
        one it looks for.

        So an unhyphenated citation inside a sentence -- `see cd1234 for why` --
        is caught by neither instrument. That is a real gap and it is narrow: it
        needs prose, in the rarer spelling, and it costs a reader a reference
        they cannot follow rather than a name they cannot import. Widening the
        scrub to see it would red on the changelog entry that names the very
        identifiers this file made us rename, which is the trade and the reason
        it is written down here instead of closed.
        """
        prose = tmp_path / "prose.py"
        prose.write_text(
            'LOG = "resolve_axiom_threshold: malformed override"\n'
            'NOTE = "see cd1234 for why"\n'
            'HEADER = "# auto-discovery scaffolded YAML"\n',
            encoding="utf-8")
        assert _name_shaped_strings(prose) == set()

    def test_a_docstring_is_not_caught_even_when_it_is_one_word(self, tmp_path):
        """A one-word docstring is name-shaped by the pattern and prose by
        position, and position wins. Without this the exclusion would depend on
        docstrings happening to contain spaces."""
        doc = tmp_path / "doc.py"
        doc.write_text('"""cd1234"""\ndef f():\n    """cd5678"""\n',
                       encoding="utf-8")
        assert _name_shaped_strings(doc) == set()

    def test_ordinary_keys_are_not_caught(self, tmp_path):
        innocent = tmp_path / "innocent.py"
        innocent.write_text('D = {"record_count": 1, "checked": 2, "cd12": 3}\n',
                            encoding="utf-8")
        assert _name_shaped_strings(innocent) == set()

    def test_the_walk_parses_every_shipped_module(self):
        """A SyntaxError swallowed anywhere would make this silently partial."""
        assert sum(1 for p in _modules() if ast.parse(
            p.read_text(encoding="utf-8")) is not None) == len(_modules())
