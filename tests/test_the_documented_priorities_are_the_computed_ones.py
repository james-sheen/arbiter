"""Every priority number the guides quote is one this engine still produces.

THE DEFECT THIS EXISTS FOR. Two guides explained `priority` by quoting measured
values -- a dangling edge at `0.03` reached from elsewhere, structural gaps at a
flat `0.5`, the two populations on different scales. All three were true when
written. Days later the ranking was put on one scale, and the prose describing
the old behaviour survived the change reading as current: the same release
shipped code saying `0.333` and `0.8` and documents saying `0.03` and `0.5`.

Nothing could go red. The ranking has its own test and that test passed, because
it asks the code what it computes. No test asked whether the documents still
described it, so the surface that a reader actually learns the engine from was
the one surface with no guard on it.

DERIVED FROM A RUN, NOT TRANSCRIBED. The permitted set is measured here by
running the engine, not typed in -- a list of allowed numbers in this file would
be a third copy of the weight table, true about what it lists and silent about
the rest. Change a weight and this goes red on the day the weight changes,
naming the guide that now disagrees.

The predicate is deliberately the strict one: a quoted value must be one the
described run PRODUCED, not merely one the formula could reach. `0.5` is
reachable -- a MISSING_NODE one hop out -- so a test asking only whether a
number is expressible would have called the flat-`0.5` claim documented and
stayed green on exactly the sentence that was wrong.
"""
from __future__ import annotations

import pathlib
import re

import pytest

yaml = pytest.importorskip("yaml")

from arbiter_engine.api import (  # noqa: E402
    EngineSession, gaps, traverse)

#: The passage each guide explains `priority` in, found by the claim it opens
#: with rather than by a section number or an offset. Both guides state it in
#: the same words, which is why one anchor reaches both; a heading number would
#: move the day a section is inserted above it and this file would then read the
#: wrong prose while staying green.
ANCHOR = re.compile(
    r"[*]{1,2}`priority` is a distance.*?(?=\n\n)", re.S)

#: A decimal with a fractional part. The formula itself is written `1 / (1 +
#: hops)`, and those bare integers are the arithmetic rather than a measurement,
#: so they are deliberately out of scope.
DECIMAL = re.compile(r"\b\d+\.\d+\b")

MODEL = {"domain": {
    "id": "rank", "name": "rank", "entity_types": ["A", "B"],
    "relationship_types": ["links"],
    "indicators": {
        "A": [{"name": "p", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
               "critical": 9},
              {"name": "q", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
               "critical": 9}],
        "B": [{"name": "r", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
               "critical": 9}]}}}


def _session() -> EngineSession:
    """The run both guides describe: structural gaps and one dangling edge."""
    session = EngineSession()
    session.load_model(yaml.safe_dump(MODEL))
    for i in range(3):
        session.add_entity(f"a{i}", "A", {"p": 1.0}, f"a{i}")   # q never supplied
    session.add_entity("b1", "B", {"r": 1.0}, "b1")
    session.add_relationship("a0", "links", "b1")
    session.add_relationship("b1", "links", "ghost")
    return session


def _measured() -> set[float]:
    """Priorities this engine produces, including the start-node case.

    Both are needed because both are quoted: the guides contrast what a gap
    scores when the walk had to reach it against what the same gap scores as
    the walk's own start.
    """
    walked = {q["priority"] for q in gaps(_session()).to_dict()["questions"]}
    at_start = {q["priority"]
                for q in traverse(_session(), ["ghost"]).to_dict()["questions"]}
    return walked | at_start


def _guides() -> dict[str, pathlib.Path]:
    """Both guides, in either tree this file runs in.

    Shipped they sit beside `tests/`; in this repository they are the sources
    the build renders from. Every name resolves or the failure says which did
    not -- a resolver that quietly returned the ones it found would check the
    guides it could reach and report clean on the one it could not.
    """
    root = pathlib.Path(__file__).resolve().parents[1]
    repo = pathlib.Path(__file__).resolve().parents[2] / "docs" / "publication"
    wanted = {"README": (root / "README.md", repo / "README-merged.md"),
              "BRIDGES": (root / "BRIDGES.md", repo / "bridge-guide.md")}
    found, missing = {}, []
    for name, candidates in wanted.items():
        for candidate in candidates:
            if candidate.is_file():
                found[name] = candidate
                break
        else:
            missing.append(f"{name}: looked at {[str(c) for c in candidates]}")
    assert not missing, "; ".join(missing)
    return found


def _passage(path: pathlib.Path) -> str:
    text = path.read_text(encoding="utf-8")
    found = ANCHOR.search(text)
    assert found, (
        f"{path.name} no longer explains `priority` in the words this guards; "
        "the claim has moved or gone, and so has the guard on it")
    return found.group(0)


@pytest.mark.parametrize("name", ["README", "BRIDGES"])
class TestTheQuotedNumbersAreTheProducedOnes:
    def test_every_quoted_priority_was_produced_by_a_run(self, name):
        path = _guides()[name]
        measured = _measured()
        quoted = {float(x) for x in DECIMAL.findall(_passage(path))}
        stale = quoted - measured
        assert not stale, (
            f"{path.name} quotes {sorted(stale)} as a priority; this engine "
            f"produces {sorted(measured)} for the run it describes")

    def test_the_passage_quotes_enough_to_be_checked(self, name):
        """Non-vacuity. Every assertion above ranges over the numbers the
        passage quotes, and all of them hold of a passage that quotes none --
        which is the state a guide reaches by deleting the explanation rather
        than correcting it."""
        quoted = DECIMAL.findall(_passage(_guides()[name]))
        assert len(quoted) >= 3, (
            f"{name} quotes {quoted}; too few numbers left to be checking "
            "anything about the scale")


class TestTheRunItselfStillDistinguishesThePopulations:
    def test_the_structural_gaps_are_not_one_constant(self):
        """The control. If the weights stopped applying, the measured set would
        collapse and the test above would go green against a guide describing a
        scale nothing computes."""
        walked = {q["gap_type"]: q["priority"]
                  for q in gaps(_session()).to_dict()["questions"]}
        structural = {walked[t] for t in ("missing_edge", "missing_property")}
        assert len(structural) == 2, walked
