""" -- a model with no lever gets no plan, and the spec says so beside the sentence it qualifies.

The spec said doing nothing is always a candidate. On the VA case -- `planning: {objective: expected_findings}`
and no action template -- the plan leg ranked nothing in every capture and declined `no_candidates`, and the
answers, written from the spec, had said doing nothing. The engine's posture is the right one: a choice that is
not there is not made, and the decline names it. What the spec lacked was the sentence.

A unit with a declared line, a planning objective and no lever. No domain.
"""

from __future__ import annotations

from pathlib import Path

from arbiter_engine import api


def _spec() -> str:
    """The spec, in whichever tree this file runs in: the package ships it as MODELING.md."""
    here = Path(__file__).resolve()
    for candidate in (here.parents[1] / "MODELING.md",
                      here.parents[2] / "docs" / "publication" / "domain-model-spec.md"):
        if candidate.is_file():
            return candidate.read_text()
    raise AssertionError("no spec in this tree")


def _plan() -> dict:
    session = api.EngineSession()
    session.load_model({"domain": {
        "id": "no-lever", "name": "a unit with a line and no lever", "entity_types": ["Unit"],
        "indicators": {"Unit": [{"name": "load", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"], "critical": 95}]},
        "planning": {"objective": "expected_findings"}}})
    session.add_entity("u-1", "Unit", {"load": 97.0})
    return api.plan(session).to_dict()["plan"]


class TestAModelWithNoLeverGetsNoPlan:

    def test_the_plan_ranks_nothing_and_says_why(self):
        leg = _plan()
        assert (leg["ranked"], leg["candidates"]) == (False, [])
        assert "no_candidates" in {d["reason"] for d in leg["not_checked"]}

    def test_the_spec_says_so_beside_doing_nothing(self):
        spec = _spec()
        nothing = spec.index("**Doing nothing is always a candidate")
        no_lever = spec.index("**A model with no lever gets no plan.**")
        assert 0 < no_lever - nothing < 800
        assert "`no_candidates`" in spec[no_lever:no_lever + 600]
