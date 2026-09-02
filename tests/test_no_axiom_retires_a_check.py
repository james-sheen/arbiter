"""A dispatched check must report SOMETHING, or the denominator lies about it.

Three states were already named for what a check can do wrongly: silence, where
no surface reports a real defect; misattribution, where a finding lands on the
wrong subject. An outside method document named a fourth and ranked it above
both. RETIRED: the check is skipped and `checked.invariants` still counts it as
attempted, so the envelope reports coverage the run did not have.

**Silence costs a detection. Misattribution spends trust. Retirement produces
ASSURANCE**, and assurance is the only one of the three that stops somebody
looking. It is also the one state the denominator cannot expose, because the
denominator is what corroborates it.

MONOTONICITY handed an indicator type it cannot reason about returned an empty
list -- no finding, no decline -- while seven sibling checkers on the same shape
reported. The asymmetry was the defect and the sibling form was the fix.

THE TEST IS A PARITY PROPERTY, NOT A CASE. Every axiom is taken from the `Axiom`
enum rather than listed here, so an axiom added later is covered without anybody
remembering to add it. A per-axiom test would have passed for the seven that were
right and never been written for the eighth.
"""
from __future__ import annotations

import pathlib
import tempfile

import pytest

from arbiter_engine.api import EngineSession, check
from arbiter_engine.types import Axiom

HEAD = ("domain:\n  id: r\n  name: R\n  entity_types: [Unit]\n"
        "  relationship_types: [feeds]\n  indicators:\n")

#: Two shapes an author can hand any axiom. Neither is universally wrong -- the
#: point is that whatever an axiom makes of them, it says so.
SHAPES = {
    "state": "        type: state\n        normal: [ok]\n",
    "numeric": "        type: numeric\n",
}


def _dispatch(axiom_name, shape):
    path = pathlib.Path(tempfile.mktemp(suffix=".yaml"))
    path.write_text(
        HEAD + "    Unit:\n      - name: phase\n"
        + SHAPES[shape]
        + f"        axioms: [{axiom_name}]\n")
    session = EngineSession()
    session.load_model(str(path))
    session.add_entity("u", "Unit", {"phase": "ok" if shape == "state" else 1.0})
    envelope = check(session).to_dict()
    return {
        "attempted": envelope["checked"]["invariants"],
        "findings": envelope["findings"],
        "declines": [d["reason"] for d in envelope["not_checked"]],
    }


@pytest.mark.parametrize("axiom", [a.name for a in Axiom])
@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_a_dispatched_check_reports_something(axiom, shape):
    """The parity property. An attempt that produces nothing is retirement."""
    got = _dispatch(axiom, shape)
    if not got["attempted"]:
        pytest.skip(f"{axiom} was not dispatched on a {shape} indicator")
    assert got["findings"] or got["declines"], (
        f"{axiom} on a {shape} indicator was RETIRED: "
        f"{got['attempted']} invariant(s) attempted, no finding and no decline, "
        f"so the envelope reports a cell it did not evaluate")


class TestTheInstanceThatPromptedIt:
    def test_monotonicity_declines_a_type_it_cannot_reason_about(self):
        got = _dispatch("MONOTONICITY", "state")
        assert got["declines"] == ["wrong_indicator_type"]

    def test_the_decline_names_the_axiom_and_the_type_it_got(self):
        path = pathlib.Path(tempfile.mktemp(suffix=".yaml"))
        path.write_text(HEAD + "    Unit:\n      - name: phase\n"
                        + SHAPES["state"] + "        axioms: [MONOTONICITY]\n")
        session = EngineSession()
        session.load_model(str(path))
        session.add_entity("u", "Unit", {"phase": "ok"})
        detail = check(session).to_dict()["not_checked"][0]["detail"]
        assert "MONOTONICITY" in detail and "state" in detail


class TestTheControls:
    """A fix that buys a decline by suppressing real work is the worse defect."""

    def test_monotonicity_still_finds_a_real_reversal(self):
        path = pathlib.Path(tempfile.mktemp(suffix=".yaml"))
        # `reversal_tolerance: 1` is declared, not assumed: the default is 3
        # so a single rollback is correctly below the firing line and
        # a control relying on the default would fail for a reason unrelated to
        # the claim. The first draft of this control did exactly that.
        path.write_text(HEAD + "    Unit:\n      - name: counter\n"
                        "        type: numeric\n"
                        "        axioms: [MONOTONICITY]\n"
                        "        direction: increasing\n"
                        "        monotonicity:\n"
                        "          reversal_tolerance: 1\n")
        session = EngineSession()
        session.load_model(str(path))
        session.add_entity("u", "Unit", {"counter": 1.0})
        # Up, up, down -- the fewest points that can exhibit a reversal.
        session.add_observations("u", "counter", [1.0, 2.0, 3.0, 4.0, 1.0],
                                 interval_seconds=30.0)
        envelope = check(session).to_dict()
        assert envelope["findings"], (
            "the type gate now swallows the numeric path it was never about")

    def test_a_numeric_indicator_is_not_declined_for_its_type(self):
        got = _dispatch("MONOTONICITY", "numeric")
        assert "wrong_indicator_type" not in got["declines"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
