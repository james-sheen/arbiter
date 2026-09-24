"""`plan` searches COMBINATIONS, and until now nothing shipped showed it.

`twin/planner.search` has run a greedy receding-horizon search over
action combinations since 0.2.3: `planning.max_depth` rounds, `max_rollouts`
as the budget, a `budget_exhausted` decline naming the limit. Two outside
documents read the engine as LACKING combination search, and both were reading
the shipped tree correctly:

  *`DEFAULT_MAX_DEPTH = 1`, so nothing searches unless a model says otherwise;
  *no shipped example said otherwise;
  *and the depth was absent from the envelope, so a depth-1 field and a
    depth-2 field whose every pair was refused are the same shape on the wire.

The third is the one that made the first two invisible. A reader cannot tell a
search that found nothing from a search that never ran, so the default was
undiscoverable from any answer the engine gave.

WHY THIS IS A SECOND EXAMPLE AND NOT AN EDIT TO THE FIRST.
`pump_tank_dynamics` declares one action template, so every two-action plan
there sets one property twice at one instant and is refused -- correctly
which means `max_depth: 2` in that file would buy three dead rows
and nothing else. Adding the second lever to it was tried and reverted: it is
the suite's canonical SINGLE-coupling fixture, and thirty-one tests across
four files rest on that shape. Bumping `couplings_declared == 1` to `2` in
each of them would have been softening rows to fit a change, not fixing them,
and the file's own first line calls itself the smallest model. So the levers
live in a sibling, which is the arrangement `substation_feeder.yaml` and
`substation_feeder_surprises.yaml` already use: one subject, one aspect per
file.

THIS FILE ASSERTS AGAINST THE SHIPPED EXAMPLE, not an inline model. The claim
being guarded is that the published tree DEMONSTRATES the search, and a test
that built its own model would leave exactly the gap the outside documents
found.
"""

import pathlib
import re

import pytest

from arbiter_engine import api

def _example(name: str) -> pathlib.Path:
    """Whichever copy this tree has.

    The built package ships `examples/` at its root and again under
    the package; the tree this is maintained in has it under a publication
    directory, and the suite itself sits one level DEEPER here than it does
    there. Counting parents answers the question in one tree and not the
    other -- caught by the ship leg, which is the lane that runs the published
    layout, with eighteen failures this file could not produce locally.
    Walking for it asks the question that matters in both.
    """
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / "examples",
                      here.parents[2] / "examples",
                      here.parents[2] / "docs" / "publication" / "engine-example"):
        if (candidate / name).is_file():
            return candidate / name
    raise AssertionError(f"no examples directory in this tree carries {name}")


EXAMPLE = _example("pump_tank_planning.yaml")

#: The starting state the example's own comment names beside its figures. A
#: number measured from a state nobody stated is not reproducible, so the
#: state travels with the numbers -- here and in the file.
START = {"pump1": ("Pump", {"speed_rpm": 3700.0}),
         "tank1": ("Tank", {"level_pct": 88.0}),
         "valve1": ("Valve", {"open_pct": 0.0})}
EDGES = [("pump1", "feeds", "tank1"), ("valve1", "drains", "tank1")]

#: What the example CLAIMS, in the file, in a comment a reader will trust.
#: Each row is checked twice: the engine still produces it, AND the file still
#: says it. One direction alone is how a number written in two places drifts --
#: a passing measurement beside prose nobody re-read.
CLAIMED = [
    ("do nothing", 50.00),
    ("set_valve(0)", 50.00),
    ("throttle_pump(1500)", 9.33),
    ("throttle_pump(1500) + set_valve(25)", 8.67),
    ("throttle_pump(1500) + set_valve(50)", 12.33),
]


def _label(candidate):
    actions = candidate.get("actions") or []
    if not actions:
        return "do nothing"
    return " + ".join(
        f"{a['template']}({list(a['parameters'].values())[0]:g})"
        for a in actions)


@pytest.fixture(scope="module")
def plan():
    session = api.EngineSession()
    session.load_model(str(EXAMPLE))
    for entity_id, (kind, properties) in START.items():
        session.add_entity(entity_id, kind, properties)
    for source, relation, target in EDGES:
        session.add_relationship(source, relation, target)
    return api.plan(session, horizon_s=1800.0, step_s=60.0).to_dict()["plan"]


@pytest.fixture(scope="module")
def scored(plan):
    return {_label(c): c["objective"] for c in plan["candidates"]
            if c.get("objective") is not None}


class TestTheShippedExampleSearchesCombinations:

    def test_the_example_declares_a_depth_above_one(self):
        assert re.search(r"^\s*max_depth:\s*2\s*$",
                         EXAMPLE.read_text(), re.M), (
            "the shipped example no longer declares a search depth, so "
            "nothing published demonstrates that `plan` searches at all")

    def test_a_two_action_candidate_is_reached(self, plan):
        pairs = [c for c in plan["candidates"] if len(c.get("actions") or []) > 1]
        assert pairs, "max_depth 2 produced no two-action candidate"

    def test_the_best_plan_is_a_pair_and_beats_every_single_action(self, plan):
        """THE CLAIM EXISTS FOR. A ranking of single actions cannot
        reach this row, so its presence is the whole difference between
        ranking and searching."""
        assert plan["ranked"]
        best = plan["candidates"][0]
        assert len(best.get("actions") or []) == 2, (
            f"the best plan is {_label(best)}, not a combination")
        singles = [c["objective"] for c in plan["candidates"]
                   if len(c.get("actions") or []) == 1
                   and c.get("objective") is not None]
        assert singles, "no single action scored, so there is nothing to beat"
        assert best["objective"] < min(singles), (
            f"the best pair scores {best['objective']}, which does not beat "
            f"the best single action at {min(singles)} -- the example no "
            f"longer demonstrates that a combination can win")

    def test_a_second_lever_set_to_a_no_op_ties_the_single_action(self, scored):
        """The internal check that the pair's advantage is real rather than an
        artefact of scoring two actions: closing the drain is doing nothing to
        it, and must score exactly what the throttle alone scores."""
        assert scored["throttle_pump(1500) + set_valve(0)"] == pytest.approx(
            scored["throttle_pump(1500)"])

    def test_the_second_lever_has_an_optimum_not_a_direction(self, scored):
        """Half open is WORSE than the throttle alone while a quarter open is
        better. That is the case a ranking of single actions cannot find, and
        it is why this model is worth shipping rather than a monotone one."""
        alone = scored["throttle_pump(1500)"]
        assert scored["throttle_pump(1500) + set_valve(25)"] < alone
        assert scored["throttle_pump(1500) + set_valve(50)"] > alone


class TestTheExamplesOwnFiguresStillHold:
    """The file states five numbers in a comment. A comment is the one place
    a measurement can go false in silence."""

    @pytest.mark.parametrize("label,claimed", CLAIMED)
    def test_the_engine_still_produces_it(self, scored, label, claimed):
        assert label in scored, f"{label} is no longer a candidate"
        assert scored[label] == pytest.approx(claimed, abs=0.005)

    @pytest.mark.parametrize("label,claimed", CLAIMED)
    def test_the_file_still_states_it(self, label, claimed):
        assert f"{claimed:.2f}" in EXAMPLE.read_text(), (
            f"the example no longer states {claimed:.2f} for {label}; a "
            f"figure removed from the prose is a figure nothing re-reads")


class TestTheSearchBudgetIsOnTheEnvelope:
    """The third half. The counts were there; the LIMITS were not, and
    the limit is what says whether a search happened."""

    def test_both_limits_are_reported(self, plan):
        assert plan["checked"]["max_depth"] == 2
        assert plan["checked"]["max_rollouts"] == 200

    def test_the_limits_are_named_as_the_model_declares_them(self, plan):
        """A reader who wants to change one should not have to translate.

        Asked of the VERB'S OWN DOCSTRING, which is where the declaration
        block is published. The first draft searched the example file too,
        where `max_depth:` appears because the example declares it -- so the
        assertion passed on the half that could not fail.
        """
        block = api.plan.__doc__
        for key in ("max_depth", "max_rollouts"):
            assert key in plan["checked"], f"{key} absent from the envelope"
            assert f"{key}:" in block, (
                f"the envelope reports `{key}` under a name the published "
                f"declaration block does not use")


class TestADefaultedDepthSaysSo:
    """Keyed on the KEY BEING ABSENT, not on the value being 1 -- a model that
    declares `max_depth: 1` has made a choice and is not stamped."""

    def _stamps(self, tmp_path, text):
        path = tmp_path / "m.yaml"
        path.write_text(text)
        session = api.EngineSession()
        session.load_model(str(path))
        for entity_id, (kind, properties) in START.items():
            session.add_entity(entity_id, kind, properties)
        for source, relation, target in EDGES:
            session.add_relationship(source, relation, target)
        out = api.plan(session, horizon_s=1800.0, step_s=60.0).to_dict()["plan"]
        return out["assumptions"], out["checked"]["max_depth"]

    def test_absent_is_stamped(self, tmp_path):
        text = re.sub(r"\n\s*max_depth:\s*2\s*\n?$", "\n", EXAMPLE.read_text())
        stamps, depth = self._stamps(tmp_path, text)
        assert depth == 1
        assert "search_depth_not_declared" in stamps

    def test_declared_at_one_is_not_stamped(self, tmp_path):
        stamps, depth = self._stamps(
            tmp_path, EXAMPLE.read_text().replace("max_depth: 2", "max_depth: 1"))
        assert depth == 1
        assert "search_depth_not_declared" not in stamps, (
            "an author who chose depth 1 is told the engine chose for them")

    def test_the_shipped_example_is_not_stamped(self, plan):
        assert "search_depth_not_declared" not in plan["assumptions"]
