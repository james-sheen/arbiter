"""The verb that computed a value names the declaration it had to supply.

An internal ruling closed *a time course nobody declared was invented in silence*
with two disclosures: a `missing_declaration` question naming the absent key AND
the number the engine used, and a `time_course_not_declared` stamp on every
envelope computed across that edge. The changelog and the reply to the reviewer
who reported it both describe them as one report. Measured, they were split
across two verbs:

    verb time_course_not_declared the question
    gaps -- yes, with both keys and both values
    rollout yes no -- questions: []
    plan yes no -- questions: []
    traverse yes no -- questions: []

So a caller who ran `rollout`, read twelve values computed with a 60 s time
constant standing in for a declared 600 s, and inspected the leg whose stated
purpose is *what the model never declared*, was told nothing. The bare stamp is
present and is not a lie, but it names neither which key was defaulted nor what
was used instead; the envelope that names both is produced by a verb that
computed nothing.

SCOPED TO EDGES ACTUALLY CROSSED. These verbs do not become a second `gaps`.
A question here says *this result rests on a number you did not write*, which is
a claim about the values in the envelope carrying it -- so an edge no walk
touched raises nothing, and a fully declared model stays silent.
"""
from __future__ import annotations

import copy
import pathlib

import pytest
import yaml

from arbiter_engine import api

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
BASE = yaml.safe_load(EXAMPLE.read_text())

ACTIONS = [{"template": "throttle_pump", "entity_id": "p1",
            "parameters": {"speed_rpm": 3000}, "at_s": 0}]


def _session(model):
    session = api.EngineSession()
    session.load_model(copy.deepcopy(model))
    session.add_entity("p1", "Pump", properties={"speed_rpm": 2000})
    session.add_entity("t1", "Tank", properties={"level_pct": 50})
    session.add_relationship("p1", "feeds", "t1")
    session.add_observations("p1", "speed_rpm", [2000.0] * 40)
    session.add_observations("t1", "level_pct", [50.0] * 40)
    return session


def _no_time_course():
    model = copy.deepcopy(BASE)
    del model["domain"]["relationship_rules"][0]["temporal"]
    return model


def _run(verb, model):
    session = _session(model)
    if verb == "rollout":
        return api.rollout(session, actions=ACTIONS,
                           horizon_s=3600, step_s=300).to_dict()
    if verb == "plan":
        return api.plan(session, horizon_s=3600, step_s=300).to_dict()
    if verb == "traverse":
        return api.traverse(session, ["p1"], value_mode="hypothetical",
                            overrides={"p1": {"speed_rpm": 3000}}).to_dict()
    if verb == "gaps":
        return api.gaps(session).to_dict()
    raise AssertionError(verb)


USING_VERBS = ["rollout", "plan", "traverse"]


class TestTheQuestionReachesTheVerbThatUsedTheNumber:

    @pytest.mark.parametrize("verb", USING_VERBS)
    def test_it_files_a_question(self, verb):
        envelope = _run(verb, _no_time_course())
        assert envelope["questions"], f"{verb} computed across the edge and asked nothing"

    @pytest.mark.parametrize("verb", USING_VERBS)
    def test_the_question_names_the_absent_keys(self, verb):
        asked = " ".join(q["question"] for q in _run(verb, _no_time_course())["questions"])
        assert "propagation_delay_s" in asked
        assert "time_constant_s" in asked

    @pytest.mark.parametrize("verb", USING_VERBS)
    def test_the_question_names_the_number_used_instead(self, verb):
        """The stamp says THAT a number was supplied. Only this says WHICH."""
        asked = " ".join(q["question"] for q in _run(verb, _no_time_course())["questions"])
        assert "60" in asked

    @pytest.mark.parametrize("verb", USING_VERBS)
    def test_it_is_typed_as_a_missing_declaration(self, verb):
        types = {q["gap_type"] for q in _run(verb, _no_time_course())["questions"]}
        assert types == {"missing_declaration"}

    @pytest.mark.parametrize("verb", USING_VERBS)
    def test_it_is_located_on_the_edge_that_was_crossed(self, verb):
        where = {q["location"] for q in _run(verb, _no_time_course())["questions"]}
        assert where == {"p1->t1"}


class TestTheStampIsStillThere:
    """The question is added BESIDE the stamp, not instead of it. They answer
    different questions and a reader may consume either."""

    def test_rollout_still_stamps_the_assumption(self):
        envelope = _run("rollout", _no_time_course())
        assert "time_course_not_declared" in envelope["simulation"]["assumptions"]

    def test_plan_still_stamps_the_assumption(self):
        envelope = _run("plan", _no_time_course())
        assert "time_course_not_declared" in envelope["plan"]["assumptions"]


class TestSilenceWhereSilenceIsRight:

    @pytest.mark.parametrize("verb", USING_VERBS + ["gaps"])
    def test_a_fully_declared_model_asks_nothing(self, verb):
        assert _run(verb, BASE)["questions"] == []

    def test_an_edge_no_walk_crossed_raises_nothing(self):
        """`traverse` in `current` mode asks for no values, so it applies no
        transitions and rests on no supplied number -- and must stay quiet even
        though the topology's gap is sitting right there for `gaps` to find."""
        session = _session(_no_time_course())
        walked = api.traverse(session, ["p1"], value_mode="current").to_dict()
        assert walked["questions"] == []
        assert api.gaps(_session(_no_time_course())).to_dict()["questions"]

    def test_check_is_unchanged(self):
        """`check` evaluates declared invariants over supplied observations and
        crosses no edge to do it. It was silent here before and stays silent."""
        envelope = api.check(_session(_no_time_course())).to_dict()
        assert envelope["questions"] == []


class TestTheValuesDidNotMove:
    """A reporting rule, not a contract change -- the same ruling that an internal ruling took.
    The trajectory an author already depends on is byte-for-byte what it was."""

    def test_the_shipped_trajectory_is_unchanged(self):
        envelope = _run("rollout", BASE)
        levels = [round(step["values"]["t1"]["level_pct"], 2)
                  for step in envelope["simulation"]["per_step"]]
        assert levels == [55.18, 61.01, 64.55, 66.69, 67.99, 68.78,
                          69.26, 69.55, 69.73, 69.84, 69.90, 69.94]

    def test_the_shipped_ranking_is_unchanged(self):
        candidates = _run("plan", BASE)["plan"]["candidates"]
        assert [c["objective"] for c in candidates] == [
            pytest.approx(0.0), pytest.approx(0.0), pytest.approx(0.0),
            pytest.approx(3.6666666666666665), pytest.approx(9.666666666666666)]
