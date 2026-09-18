"""Every simulation decline reason is produced by an INPUT, not by a literal.

`test_every_decline_reason_has_a_producer.py` searches the tree for each
reason written as a string literal. That test is right about what it pins and
it states its own limit: a name it cannot find is a name a reader grepping for
it cannot find either. What it cannot see is whether any input actually
REACHES the line the literal sits on.

An internal ruling found that difference the expensive way. `cycle_unsupported` was
written, was found by the literal search, and could not fire: the traversal's
`if next_id in visited: continue` returns before the transition code runs, so
an edge closing a loop never reached the branch that would have reported it.
A dead member passed a test whose entire subject is dead members.

Worse than dead, in that case. The back-edge's contribution was dropped from
the reported value and nothing said so, which is a silent wrong number rather
than a missing refusal.

SO THIS FILE CONSTRUCTS AN INPUT PER REASON. It is the more expensive test and
it is the one that can fail for the right reason. The axiom half of the
vocabulary -- the `NotEvaluatedReason` members folded in so a rollout can pass
the reasoner's own declines through -- is pinned by a representative rather
than one case each: those members are already reachable through `check`, and
what needs proving here is that the ROLLOUT is a path to them at all.
"""
from __future__ import annotations

import pathlib
import tempfile

import pytest

from arbiter_engine import api
from arbiter_engine.subenvelope import VOCABULARIES
from arbiter_engine.twin.actions import ActionInstance
from arbiter_engine.twin.topology import (
    TraversalDirection, TraversalRequest, ValueMode)
from arbiter_engine.twin.traverser import TopologyTraverser
from arbiter_engine.types import NotEvaluatedReason

#: The members this vocabulary owns. The rest are the axiom enum, folded in so
#: a rollout can carry the reasoner's declines without inventing second names
#: for them.
AXIOM_REASONS = {reason.value for reason in NotEvaluatedReason}

BASE = """
domain:
  id: base
  name: Base
  entity_types: [P, T]
  relationship_types: [feeds]
  indicators:
    P: [{name: v, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}]
    T: [{name: w, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}]
  relationship_rules:
    - {type: feeds, source_type: P, target_type: T,
       temporal: {propagation_delay_s: 0, time_constant_s: 1, response_model: step},
       transition: {from: v, to: w, gain: 1.0, source: datasheet}}
  action_templates:
    - {name: act, applies_to: P,
       parameters_schema: {v: {type: number, entity_property: v}},
       effect: set, settle_s: 600}
"""


def _model(tmp_path, text, name):
    path = tmp_path / f"{name}.yaml"
    path.write_text(text)
    return str(path)


def _base(tmp_path):
    session = api.EngineSession()
    session.load_model(_model(tmp_path, BASE, "base"))
    session.add_entity("p", "P", {"v": 1.0})
    session.add_entity("t", "T", {"w": 1.0})
    session.add_relationship("p", "feeds", "t")
    return session


def _reasons(envelope):
    return {d["reason"] for d in envelope.to_dict()["simulation"]["not_checked"]}


def _act(**kw):
    kw.setdefault("template", "act")
    kw.setdefault("entity_id", "p")
    kw.setdefault("parameters", {"v": 9.0})
    kw.setdefault("at_s", 0.0)
    return ActionInstance(**kw)


class TestTheLoopCaseThatWasDead:
    """The find, pinned on its own because it was silent twice over."""

    CYCLE = """
domain:
  id: cyc
  name: Feedback
  entity_types: [A, B]
  relationship_types: [drives]
  indicators:
    A: [{name: v, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}]
    B: [{name: v, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}]
  relationship_rules:
    - {type: drives, source_type: A, target_type: B,
       temporal: {propagation_delay_s: 0, time_constant_s: 1, response_model: step},
       transition: {from: v, to: v, gain: 1.0, source: datasheet}}
    - {type: drives, source_type: B, target_type: A,
       temporal: {propagation_delay_s: 0, time_constant_s: 1, response_model: step},
       transition: {from: v, to: v, gain: 0.5, source: datasheet}}
"""

    def _loop(self, tmp_path):
        session = api.EngineSession()
        session.load_model(_model(tmp_path, self.CYCLE, "cyc"))
        session.add_entity("a", "A", {"v": 1.0})
        session.add_entity("b", "B", {"v": 1.0})
        session.add_relationship("a", "drives", "b")
        session.add_relationship("b", "drives", "a")
        return session

    def test_a_cycle_in_the_graph_is_reported(self, tmp_path):
        # Named for the engine's own word. The reason is `cycle_unsupported`,
        # so a method called after the control-theory term made the reader
        # map between two vocabularies for one thing -- and, incidentally,
        # spelled `feedback_` plus three words, which is indistinguishable
        # from an internal filename to the scrub that guards the built tree.
        envelope = api.traverse(self._loop(tmp_path), ["a"],
                                value_mode="hypothetical",
                                overrides={"a": {"v": 5.0}})
        assert "cycle_unsupported" in _reasons(envelope), (
            "an edge closing a loop was skipped silently; its contribution is "
            "missing from the reported value and nothing says so")

    def test_the_refusal_names_the_edge_that_closed_the_loop(self, tmp_path):
        declines = api.traverse(
            self._loop(tmp_path), ["a"], value_mode="hypothetical",
            overrides={"a": {"v": 5.0}}).to_dict()["simulation"]["not_checked"]
        cycle = [d for d in declines if d["reason"] == "cycle_unsupported"]
        assert cycle and cycle[0]["location"] == "b->a"

    def test_an_acyclic_model_reports_no_cycle(self, tmp_path):
        """Guard: a reason that fires on every input is as useless as a dead one."""
        assert "cycle_unsupported" not in _reasons(api.traverse(
            _base(tmp_path), ["p"], value_mode="hypothetical",
            overrides={"p": {"v": 9.0}}))


class TestEachOwnedReasonHasAnInput:

    def test_missing_dynamics(self, tmp_path):
        session = _base(tmp_path)
        session.add_entity("q", "P", {"v": 1.0})
        session.add_relationship("t", "feeds", "q")
        assert "missing_dynamics" in _reasons(api.traverse(
            session, ["p"], value_mode="hypothetical",
            overrides={"p": {"v": 9.0}}))

    def test_missing_declaration(self, tmp_path):
        text = BASE.replace(
            "transition: {from: v, to: w, gain: 1.0, source: datasheet}",
            "transition: {from: v, to: w, source: datasheet}")
        session = api.EngineSession()
        session.load_model(_model(tmp_path, text, "partial"))
        session.add_entity("p", "P", {"v": 1.0})
        session.add_entity("t", "T", {"w": 1.0})
        session.add_relationship("p", "feeds", "t")
        assert "missing_declaration" in _reasons(api.traverse(
            session, ["p"], value_mode="hypothetical",
            overrides={"p": {"v": 9.0}}))

    def test_missing_property(self, tmp_path):
        text = BASE.replace(
            "P: [{name: v, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}]",
            "P: [{name: v, type: STATE, axioms: []}]")
        session = api.EngineSession()
        session.load_model(_model(tmp_path, text, "nonnum"))
        session.add_entity("p", "P", {"v": "fast"})
        session.add_entity("t", "T", {"w": 1.0})
        session.add_relationship("p", "feeds", "t")
        assert "missing_property" in _reasons(api.traverse(
            session, ["p"], value_mode="hypothetical",
            overrides={"p": {"v": "slow"}}))

    def test_budget_exhausted(self, tmp_path):
        topology = api._build_topology(_base(tmp_path))
        result = TopologyTraverser(topology).traverse(TraversalRequest(
            start_nodes=["p"], direction=TraversalDirection.FORWARD,
            value_mode=ValueMode.HYPOTHETICAL,
            overrides={"p": {"v": 9.0}}, max_transitions=0))
        assert "budget_exhausted" in {d.reason
                                      for d in result.simulation_declines}

    @pytest.mark.parametrize("reason,kwargs", [
        ("settle_exceeds_step", {"horizon_s": 180.0, "step_s": 60.0}),
        ("malformed_request", {"horizon_s": 30.0, "step_s": 60.0}),
    ])
    def test_rollout_shape_reasons(self, tmp_path, reason, kwargs):
        assert reason in _reasons(
            api.rollout(_base(tmp_path), actions=[_act()], **kwargs))

    @pytest.mark.parametrize("reason,action", [
        ("unknown_action", {"template": "nope"}),
        ("unknown_parameter", {"parameters": {"zz": 1.0}}),
        ("wrong_entity_type", {"entity_id": "t"}),
        ("missing_entity", {"entity_id": "ghost"}),
        ("malformed_action", {"at_s": 9999.0}),
    ])
    def test_action_refusal_reasons(self, tmp_path, reason, action):
        assert reason in _reasons(api.rollout(
            _base(tmp_path), actions=[_act(**action)],
            horizon_s=180.0, step_s=60.0))

    def test_gain_not_adopted(self, tmp_path):
        """`gain: estimate` declares the pair and withholds the number."""
        text = BASE.replace(
            "transition: {from: v, to: w, gain: 1.0, source: datasheet}",
            "transition: {from: v, to: w, gain: estimate, source: estimated}")
        session = api.EngineSession()
        session.load_model(_model(tmp_path, text, "estimate"))
        session.add_entity("p", "P", {"v": 1.0})
        session.add_entity("t", "T", {"w": 1.0})
        session.add_relationship("p", "feeds", "t")
        assert "gain_not_adopted" in _reasons(api.traverse(
            session, ["p"], value_mode="hypothetical",
            overrides={"p": {"v": 9.0}}))

    def test_insufficient_samples(self, tmp_path):
        assert "insufficient_samples" in _reasons(api.rollout(
            _base(tmp_path), horizon_s=120.0, step_s=60.0,
            seed_mode="projected"))

    def test_internal_error(self, tmp_path, monkeypatch):
        """The boundary 0.1.18 put on the other verbs, reached the same way.

        Patched on `api`, not on the defining module: `api` binds these at
        import, so patching the source has no effect -- the trap the 0.1.17
        round already walked into once.
        """
        def boom(*a, **k):
            raise RuntimeError("synthetic")
        monkeypatch.setattr(api, "_build_topology", boom)
        assert "internal_error" in _reasons(api.rollout(
            _base(tmp_path), horizon_s=120.0, step_s=60.0))

    def test_precondition_unmet(self, tmp_path):
        session = _base(tmp_path)
        object.__setattr__(session, "reasoner", None) if hasattr(
            session, "reasoner") else None
        session.reasoner = None
        assert "precondition_unmet" in _reasons(api.rollout(
            session, actions=[_act()], horizon_s=120.0, step_s=60.0))


class TestTheAxiomFoldInIsAPathNotADecoration:
    """The 14 members folded in from `NotEvaluatedReason`.

    They are already reachable through `check`. What needs proving is that a
    ROLLOUT reaches them -- that the reasoner's declines over an IMAGINED
    state are carried rather than dropped. A representative is enough for
    that; one construction per member would be pinning the axiom layer twice.
    """

    DECLINING = """
domain:
  id: declines
  name: Axioms that cannot answer
  entity_types: [P, T]
  relationship_types: [feeds]
  indicators:
    P: [{name: v, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}]
    T:
      - {name: w, type: NUMERIC, axioms: [BOUNDEDNESS]}
      - {name: lat, type: NUMERIC, axioms: [RESPONSIVENESS]}
  relationship_rules:
    - {type: feeds, source_type: P, target_type: T,
       temporal: {propagation_delay_s: 0, time_constant_s: 1, response_model: step},
       transition: {from: v, to: w, gain: 1.0, source: datasheet}}
  action_templates:
    - {name: act, applies_to: P,
       parameters_schema: {v: {type: number, entity_property: v}}, effect: set}
"""

    def test_an_axiom_that_cannot_answer_declines_through_the_rollout(
            self, tmp_path):
        session = api.EngineSession()
        session.load_model(_model(tmp_path, self.DECLINING, "declining"))
        session.add_entity("p", "P", {"v": 1.0})
        session.add_entity("t", "T", {"w": 1.0, "lat": 5.0})
        session.add_relationship("p", "feeds", "t")
        reasons = _reasons(api.rollout(
            session, actions=[_act()], horizon_s=180.0, step_s=60.0))
        carried = reasons & AXIOM_REASONS
        assert carried, (
            "the reasoner declined over the imagined state and the rollout "
            "carried none of it; the folded-in half of the vocabulary would "
            "be decoration")
        assert {"missing_role", "no_threshold"} <= carried

    def test_the_fold_in_is_what_makes_those_legal(self):
        """Without it the sub-envelope would refuse its own declines."""
        assert AXIOM_REASONS <= set(VOCABULARIES["simulation"])


class TestThePlannersTwoHaveInputsToo:
    """`plan` refuses in two ways a rollout cannot, and both are the same
    refusal: a choice the model did not supply."""

    PLAN_MODEL = """
domain:
  id: planreach
  name: Planner reachability
  entity_types: [Node]
  relationship_types: [hosts]
  indicators:
    Node: [{name: v, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}]
  action_templates:
    - name: act
      applies_to: Node
      parameters_schema:
        v: {type: number, entity_property: v%(candidates)s}
      effect: set
%(planning)s
"""

    def _plan(self, tmp_path, *, candidates: str, planning: str, name: str):
        text = self.PLAN_MODEL % {"candidates": candidates,
                                  "planning": planning}
        path = tmp_path / f"{name}.yaml"
        path.write_text(text)
        session = api.EngineSession()
        session.load_model(str(path))
        session.add_entity("node1", "Node", {"v": 1.0})
        return {d["reason"] for d in api.plan(
            session, horizon_s=120.0,
            step_s=60.0).to_dict()["plan"]["not_checked"]}

    def test_no_objective(self, tmp_path):
        assert "no_objective" in self._plan(
            tmp_path, candidates=", candidates: [1, 2]", planning="",
            name="noobj")

    def test_no_candidates(self, tmp_path):
        assert "no_candidates" in self._plan(
            tmp_path, candidates="",
            planning="  planning:\n    objective: expected_findings\n",
            name="nocand")


class TestTheVocabularyHasNoUnexplainedMember:

    def test_every_member_is_either_owned_or_an_axiom_reason(self):
        """A member that is neither is one nobody has placed."""
        owned = {
            "missing_dynamics", "missing_declaration", "missing_property",
            "cycle_unsupported", "budget_exhausted", "internal_error",
            "malformed_request", "settle_exceeds_step", "unknown_action",
            "unknown_parameter", "wrong_entity_type", "missing_entity",
            "malformed_action", "precondition_unmet", "insufficient_samples",
            # the planner's two.
            "no_objective", "no_candidates",
            # the pair is declared, the magnitude is not.
            "gain_not_adopted",
        }
        unexplained = set(VOCABULARIES["simulation"]) - owned - AXIOM_REASONS
        assert unexplained == set(), (
            f"{unexplained} is in the simulation vocabulary and this file "
            f"neither constructs an input for it nor places it in the axiom "
            f"fold-in")
