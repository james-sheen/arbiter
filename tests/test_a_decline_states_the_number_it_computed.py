"""A decline that quotes a constant where its own arithmetic belongs.

`infer` declines `no_report_probability` when no `report_above` was
passed -- the engine computed a posterior and is refusing to say whether it is
alarming. The sentence it declines with carried the literal `0.31` at every
call, beside an `evidence` key holding the posterior it had just computed.
Measured on the example this round shipped: the message read `whether 0.31 is
alarming` while the answer was 0.014182.

WHY THIS IS THE WORST PLACE FOR IT. A decline is the engine explaining what it
did NOT decide, and a reader has no second copy to check it against -- the
whole point of reading a decline is that you did not compute the thing
yourself. Every other number this engine reports is derived; this one was
typed, and it disagreed with the key sitting beside it in the same dict.

FOUND BY RUNNING THE VERB, not by reading it. The verb had no shipped model
so nothing in the suite had ever produced this decline against a
real graph, and three static reviews of this engine read past the constant.

The census below is the half that matters more than the fix: it asserts NO
decline or finding message anywhere in the engine carries a bare decimal, so
the next one cannot arrive quietly.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from arbiter_engine.api import EngineSession, check, infer


def _engine_root() -> pathlib.Path:
    """The package, under whichever name this tree calls it."""
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / "arbiter_engine",
                      here.parents[2] / "detection"):
        if candidate.is_dir():
            return candidate
    raise AssertionError("no engine package found in this tree")


def _examples_dir() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / "examples",
                      here.parents[2] / "docs" / "publication" / "engine-example"):
        if candidate.is_dir() and list(candidate.glob("*.yaml")):
            return candidate
    raise AssertionError("no examples directory found in this tree")


CAUSAL_EXAMPLE = "substation_feeder.yaml"


def _session() -> EngineSession:
    session = EngineSession()
    session.load_model(
        _examples_dir().joinpath(CAUSAL_EXAMPLE).read_text(encoding="utf-8"))
    session.add_entity("sub-1", "Supply", properties={"voltage_kv": 11.0})
    session.add_entity("fdr-1", "Feeder", properties={})
    session.add_entity("pnl-1", "Panel", properties={"voltage_v": 230.0})
    session.add_entity("pnl-2", "Panel", properties={"voltage_v": 230.0})
    session.add_relationship("sub-1", "powers", "fdr-1")
    session.add_relationship("fdr-1", "powers", "pnl-1")
    session.add_relationship("fdr-1", "powers", "pnl-2")
    check(session)
    return session


def _decline() -> dict:
    leg = infer(_session(), target="sub-1").to_dict()["inference"]
    rows = [row for row in leg["not_checked"]
            if row["reason"] == "no_report_probability"]
    assert rows, (
        "the verb did not decline for a missing `report_above`, so every "
        "assertion below would be vacuous")
    return rows[0]


class TestTheDeclineAgreesWithItself:

    def test_it_states_a_number_at_all(self):
        """Guards the guard: a message with no digits in it would pass the
        agreement test below by having nothing to disagree with."""
        assert re.search(r"\d+\.\d+", _decline()["detail"]), _decline()["detail"]

    def test_the_number_it_states_is_the_number_it_computed(self):
        row = _decline()
        stated = {float(m) for m in re.findall(r"\d+\.\d+", row["detail"])}
        assert row["evidence"]["posterior"] in stated, (
            f"the decline says {sorted(stated)} and its evidence says "
            f"{row['evidence']['posterior']}")

    def test_it_moves_when_the_answer_moves(self):
        """Two-sided. A message that happened to contain the right constant
        for one input is indistinguishable from a derived one until the input
        changes."""
        first = _decline()["detail"]
        session = _session()
        session.add_entity("fdr-1", "Feeder", properties={"current_a": 450.0})
        check(session)
        leg = infer(session, target="sub-1").to_dict()["inference"]
        second = [row for row in leg["not_checked"]
                  if row["reason"] == "no_report_probability"][0]["detail"]
        assert first != second, (
            "the decline read identically for two different posteriors")


#: A number written into a message, where the code has the real one to hand.
#: Deliberately narrow: it looks only inside the message strings a caller
#: reads, not at thresholds, version numbers or arithmetic.
_BARE_DECIMAL = re.compile(r'"[^"]*?\b\d+\.\d{1,6}\b[^"]*?"')
_MESSAGE_ARG = re.compile(r"\b(?:detail|remedy|reason)\s*=\s*\(?\s*((?:f?\"[^\"]*\"\s*)+)")


def _message_literals():
    for path in sorted(_engine_root().rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for match in _MESSAGE_ARG.finditer(source):
            blob = match.group(1)
            # An f-string interpolates, so a decimal inside one is derived.
            if re.match(r"\s*f\"", blob):
                continue
            for literal in _BARE_DECIMAL.findall(blob):
                yield path, literal


class TestNoMessageQuotesANumberInsteadOfDerivingIt:

    def test_the_census_finds_message_strings_to_look_at(self):
        """Guards the guard. A regex that matched nothing would make the
        assertion below a green that measured no code at all."""
        found = sum(1 for _ in _MESSAGE_ARG.finditer(
            (_engine_root() / "inference" / "runner.py").read_text(encoding="utf-8")))
        assert found >= 3, f"only {found} message arguments found in one module"

    def test_no_message_carries_a_bare_decimal(self):
        offenders = [f"{path.name}: {literal}"
                     for path, literal in _message_literals()]
        assert offenders == [], offenders
