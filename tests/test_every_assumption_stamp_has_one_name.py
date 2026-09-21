"""The assumption stamps are a vocabulary, not twenty scattered literals.

Until this, every stamp was a bare string written at the site that
emitted it -- twenty sites across four modules -- and nothing anywhere held the
list. Three consequences, all measured:

*The published guides between them named six of the twenty. The JSON schema,
  which `meta.schema_version` advertises as the wire contract, did not contain
  the word `assumptions` at all.
*`COMPATIBILITY.md` grants a patch release permission to ADD a stamp. So the
  project published a rule for changing a vocabulary it had never published,
  and a consumer told the list may grow had nothing to diff the growth against.
*An outside comparison of this engine reproduced all three of its ENUMERATED
  vocabularies exactly -- the fourteen decline reasons, the six gap types, the
  eight raced outcomes -- and reported this one at NINE of twenty. The
  difference between those outcomes is not the reader's care. It is whether the
  vocabulary was ever written down.

The stamps are what the engine offers as its trust surface: the list that says
which approximations a number rests on. A trust surface nobody can enumerate is
the shape of defect this project exists to refuse.

NOT AN ENUM ON THE WIRE, deliberately, and `test_the_schema_names_what_a_sub_envelope_carries`
pins that decision. Two reasons: an enum would make every patch-legal addition
a schema change, and one stamp is parameterised with a property name drawn from
the domain model rather than from any vocabulary this package could hold.
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

from arbiter_engine import api
from arbiter_engine.assumptions import (
    ACTION_PROPERTY_FROM_PARAMETER_NAME_PREFIX,
    ASSUMPTION_STAMPS,
    ASSUMPTION_STAMP_PREFIXES,
    is_known_stamp,
)

PACKAGE = pathlib.Path(api.__file__).parent
def _example_path() -> pathlib.Path:
    """The worked dynamics example, from whichever copy this tree has.

    Published beside the package as `examples/`, and kept one directory deeper
    in the tree this package is derived from, so one candidate pair serves both.
    The path parts are separate literals for the reason the sibling guide helper
    uses them that way: written as one string it is an internal path in prose,
    and the scrub rewrites it into the middle of a sentence.

    It RAISES rather than skipping. The ship leg runs these tests against the
    staged tree, and a fixture that quietly vanishes there would take its whole
    file green with it.
    """
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / "examples" / "pump_tank_dynamics.yaml",
                      here.parents[2] / "docs" / "publication"
                      / "engine-example" / "pump_tank_dynamics.yaml"):
        if candidate.exists():
            return candidate
    raise AssertionError("no pump_tank_dynamics example found in this tree")


EXAMPLE = _example_path()


def _guide() -> str:
    """The modelling guide, from whichever copy this tree has.

    The same two candidates the rest of the suite uses, and the same refusal to
    fall through: a guide check that SKIPS when it cannot find the guide is a
    green that means nothing, and the published tree is the one where this pin
    matters most. The two paths differ by exactly one level of nesting, which is
    why one pair serves both trees.
    """
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / "MODELING.md",
                      here.parents[2] / "docs" / "publication"
                      / "domain-model-spec.md"):
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    raise AssertionError("no modelling guide found to check against")

ACTIONS = [{"template": "throttle_pump", "entity_id": "p1",
            "parameters": {"speed_rpm": 3000}, "at_s": 0}]


def _session(model_text=None):
    session = api.EngineSession()
    session.load_model(model_text or EXAMPLE.read_text())
    session.add_entity("p1", "Pump", properties={"speed_rpm": 2000})
    session.add_entity("t1", "Tank", properties={"level_pct": 50})
    session.add_relationship("p1", "feeds", "t1")
    session.add_observations("p1", "speed_rpm", [2000.0] * 40)
    session.add_observations("t1", "level_pct", [50.0] * 40)
    return session


def _emitted():
    """Every stamp a battery over the shipped example actually produces."""
    seen = set()
    rolled = api.rollout(_session(), actions=ACTIONS,
                         horizon_s=3600, step_s=300).to_dict()
    seen |= set(rolled["simulation"].get("assumptions") or [])
    planned = api.plan(_session(), horizon_s=3600, step_s=300).to_dict()
    seen |= set(planned["plan"].get("assumptions") or [])
    for candidate in planned["plan"].get("candidates") or []:
        seen |= set(candidate.get("assumptions") or [])
    return seen


class TestTheVocabularyIsWellFormed:
    def test_no_stamp_is_listed_twice(self):
        assert len(ASSUMPTION_STAMPS) == len(set(ASSUMPTION_STAMPS))

    def test_every_stamp_is_a_lowercase_identifier(self):
        for stamp in ASSUMPTION_STAMPS:
            assert re.fullmatch(r"[a-z][a-z0-9_]*", stamp), stamp

    def test_a_prefix_is_not_also_a_plain_stamp(self):
        for prefix in ASSUMPTION_STAMP_PREFIXES:
            assert prefix.rstrip(":") not in ASSUMPTION_STAMPS


class TestNothingEmitsAStampTheVocabularyDoesNotHold:
    def test_the_shipped_example_emits_only_known_stamps(self):
        emitted = _emitted()
        assert emitted, "the battery produced no stamps at all"
        unknown = {s for s in emitted if not is_known_stamp(s)}
        assert not unknown, f"emitted but not in the vocabulary: {sorted(unknown)}"

    def test_no_module_writes_a_stamp_as_a_bare_literal(self):
        """The literal is the drift. A name is a NameError; a string is a typo
        nobody finds until a reader greps for a stamp that is spelled two ways.
        """
        offenders = {}
        known = set(ASSUMPTION_STAMPS)
        for path in sorted(PACKAGE.rglob("*.py")):
            if path.name == "assumptions.py":
                continue
            tree = ast.parse(path.read_text())
            docstrings = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.FunctionDef,
                                     ast.AsyncFunctionDef, ast.ClassDef)):
                    body = node.body
                    if body and isinstance(body[0], ast.Expr) and \
                            isinstance(body[0].value, ast.Constant):
                        docstrings.add(id(body[0].value))
            hits = [n.value for n in ast.walk(tree)
                    if isinstance(n, ast.Constant)
                    and isinstance(n.value, str)
                    and n.value in known
                    and id(n) not in docstrings]
            if hits:
                offenders[path.name] = sorted(set(hits))
        assert not offenders, f"bare stamp literals survive: {offenders}"


class TestTheParameterisedStampIsRecognised:
    def test_a_value_behind_the_prefix_is_known(self):
        assert is_known_stamp(
            ACTION_PROPERTY_FROM_PARAMETER_NAME_PREFIX + "speed_rpm")

    def test_the_bare_prefix_alone_is_not(self):
        """A prefix with nothing behind it names no property and is not a
        disclosure about anything."""
        assert not is_known_stamp(ACTION_PROPERTY_FROM_PARAMETER_NAME_PREFIX)

    def test_an_invented_stamp_is_not_known(self):
        assert not is_known_stamp("the_engine_did_something_unspecified")


class TestThePublishedTableIsDerivedNotTranscribed:
    """The guide's table is pinned to the constant, in BOTH directions.

    A table that merely contains every stamp would pass while listing ten that
    no longer exist; a table merely contained BY the vocabulary would pass while
    omitting half of it. The failure this whole CD is about is the second one.
    """

    def _table_stamps(self):
        text = _guide()
        start = text.index("## The assumption stamps")
        end = text.index("\n## ", start + 10)
        return [m.group(1) for m in
                re.finditer(r"^\| `([a-z][a-z0-9_]*)` \|", text[start:end],
                            re.MULTILINE)]

    def test_the_table_lists_exactly_the_vocabulary(self):
        assert self._table_stamps() == list(ASSUMPTION_STAMPS)

    def test_the_parameterised_stamp_is_described_beside_it(self):
        text = _guide()
        start = text.index("## The assumption stamps")
        end = text.index("\n## ", start + 10)
        assert ACTION_PROPERTY_FROM_PARAMETER_NAME_PREFIX in text[start:end]

    def test_the_guide_says_the_list_may_grow_in_a_patch(self):
        """Publishing the baseline without the rule would read as a closed set
        and make the next patch-legal addition look like a breach."""
        text = _guide()
        start = text.index("## The assumption stamps")
        end = text.index("\n## ", start + 10)
        section = text[start:end]
        assert "patch release may" in section
        assert "no `enum`" in section
