"""Planning: the engine proposes, and ranks only against a declared objective.

`rollout` answers *what happens if I do this*. `plan` answers *which
of these should I do*, and that question has no answer the arithmetic supplies
on its own -- minimising expected findings and maximising the chance of
clearing a severity are different questions that disagree on real inputs. So
the objective is declared, and without a declaration every candidate is still
evaluated and none is ranked.

THE WEIGHT DIRECTION IS THE LOAD-BEARING TEST IN THIS FILE. `Severity.
priority_score` is a RANK -- critical is 1, info is 5 -- and the design note's
objective sums it and minimises. Measured over four candidate plans, that
picks *one CRITICAL* over *three INFO*: it recommends the plan that breaks the
most important thing, because a rank used as a magnitude inverts the order.
A planner wrong in that direction is worse than no planner, and it would pass
any test that only checked a ranking existed.

The weight is DERIVED as `1/priority_score` rather than tabulated, which is
the constraint that matters: a second severity table is how two parts of one
engine come to disagree about which finding is worse, and the first thing to
reorder one and not the other would be silent.
"""
from __future__ import annotations

import pytest

from arbiter_engine import api
from arbiter_engine.twin.actions import ActionInstance
from arbiter_engine.twin.planner import severity_weight
from arbiter_engine.types import Severity

MODEL = """
domain:
  id: planning
  name: A node with two remedies
  entity_types: [Node]
  relationship_types: [hosts]
  indicators:
    Node:
      - name: memory_used_pct
        type: NUMERIC
        role: percentage
        axioms: [BOUNDEDNESS]
        warning: 80
        critical: 90
      - name: cpu_cores
        type: NUMERIC
        axioms: [BOUNDEDNESS]
        lower_warning: 3.5
        lower_critical: 3.0
  action_templates:
    - name: evict
      applies_to: Node
      parameters_schema:
        memory_used_pct:
          type: number
          entity_property: memory_used_pct
          candidates: [95, 70]
      effect: set
      source: runbook
    - name: reserve
      applies_to: Node
      parameters_schema:
        cpu_cores:
          type: number
          entity_property: cpu_cores
          candidates: [4.0]
      effect: set
      source: runbook
{planning}
"""

WITH_OBJECTIVE = """  planning:
    objective: expected_findings
"""


def _session(tmp_path, planning: str = "", name: str = "m"):
    path = tmp_path / f"{name}.yaml"
    path.write_text(MODEL.format(planning=planning))
    session = api.EngineSession()
    session.load_model(str(path))
    session.add_entity("node1", "Node",
                       {"memory_used_pct": 88.0, "cpu_cores": 3.2})
    return session


def _plan(session, **kw):
    kw.setdefault("horizon_s", 300.0)
    kw.setdefault("step_s", 150.0)
    return api.plan(session, **kw).to_dict()["plan"]


class TestTheWeightPointsTheRightWay:
    """The refutation, pinned as arithmetic rather than as a ranking."""

    def test_the_score_is_a_rank_where_lower_is_more_severe(self):
        """The premise. If this inverts, everything below means the opposite."""
        assert Severity.CRITICAL.priority_score < Severity.INFO.priority_score

    def test_a_critical_finding_costs_more_than_an_info_finding(self):
        assert severity_weight(Severity.CRITICAL) > severity_weight(
            Severity.INFO)

    def test_one_critical_costs_more_than_three_info(self):
        """The exact comparison the note's objective gets backwards."""
        one_critical = severity_weight(Severity.CRITICAL)
        three_info = 3 * severity_weight(Severity.INFO)
        assert one_critical > three_info, (
            "minimising this objective would prefer a plan that causes one "
            "CRITICAL finding over one that causes three INFO findings")

    def test_the_weight_is_monotone_across_the_whole_scale(self):
        ordered = sorted(Severity, key=lambda s: s.priority_score)
        weights = [severity_weight(s) for s in ordered]
        assert weights == sorted(weights, reverse=True)

    def test_it_introduces_no_second_scale(self):
        """Derived from priority_score, so the two cannot drift apart."""
        for member in Severity:
            assert severity_weight(member) == pytest.approx(
                1.0 / member.priority_score)


class TestAPlanWithoutADeclaredObjectiveRanksNothing:

    def test_it_declines_rather_than_choosing_one(self, tmp_path):
        payload = _plan(_session(tmp_path))
        assert payload["ranked"] is False
        assert "no_objective" in [d["reason"] for d in payload["not_checked"]]

    def test_it_still_evaluates_every_candidate(self, tmp_path):
        """The work is done; only the judgement is withheld."""
        payload = _plan(_session(tmp_path))
        assert payload["checked"]["candidates_evaluated"] >= 4
        assert all(c["objective"] is None for c in payload["candidates"])

    def test_it_names_no_best(self, tmp_path):
        assert "best" not in _plan(_session(tmp_path))

    def test_an_unknown_objective_is_refused_by_name(self, tmp_path):
        payload = _plan(_session(
            tmp_path, "  planning:\n    objective: vibes\n", "vibes"))
        assert payload["ranked"] is False
        detail = " ".join(d.get("detail") or "" for d in payload["not_checked"])
        assert "vibes" in detail

    def test_clearance_without_a_severity_is_refused(self, tmp_path):
        """A probability of avoiding an unspecified thing is not a number."""
        payload = _plan(_session(
            tmp_path,
            "  planning:\n    objective: clearance_probability\n", "clear"))
        assert payload["ranked"] is False
        assert "no_objective" in [d["reason"] for d in payload["not_checked"]]


class TestADeclaredObjectiveRanks:

    def test_it_ranks_and_names_a_best(self, tmp_path):
        payload = _plan(_session(tmp_path, WITH_OBJECTIVE, "obj"))
        assert payload["ranked"] is True
        assert payload["objective"] == "expected_findings"
        assert payload["best"]

    def test_the_ranking_is_ordered_by_the_objective(self, tmp_path):
        values = [c["objective"] for c in
                  _plan(_session(tmp_path, WITH_OBJECTIVE, "obj"))["candidates"]]
        assert values == sorted(values), (
            "expected_findings is minimised, so the list must ascend")

    def test_doing_nothing_is_always_a_candidate(self, tmp_path):
        """A planner that cannot return `leave it alone` always recommends
        acting."""
        plans = [c["plan"] for c in
                 _plan(_session(tmp_path, WITH_OBJECTIVE, "obj"))["candidates"]]
        assert "do_nothing" in plans

    def test_a_tie_breaks_toward_fewer_actions(self, tmp_path):
        """Deliberate, not insertion order.

        Sorting on the objective alone left this to the order candidates were
        appended in -- `do_nothing` first, and a stable sort -- so the right
        answer came out for a reason that would change the moment the
        evaluation order did.
        """
        payload = _plan(_session(tmp_path, WITH_OBJECTIVE, "obj"))
        best = payload["candidates"][0]
        tied = [c for c in payload["candidates"]
                if c["objective"] == best["objective"]]
        assert len(tied) > 1, "guard: no tie here makes this vacuous"
        assert len(best["actions"]) == min(len(c["actions"]) for c in tied)
        assert "ties_break_toward_fewer_actions" in payload["assumptions"]


class TestClearanceProbabilityReportsItsBand:

    CLEARANCE = ("  planning:\n    objective: clearance_probability\n"
                 "    min_severity: critical\n")

    def test_it_reports_an_interval(self, tmp_path):
        payload = _plan(_session(tmp_path, self.CLEARANCE, "cp"))
        assert payload["ranked"] is True
        assert all(c["interval"] is not None for c in payload["candidates"])

    def test_the_degenerate_band_is_stamped_as_determinism(self, tmp_path):
        """A band of [1.0, 1.0] is honest and needs its reason stated.

        It is narrow because the transition model is deterministic, not
        because the sample count was large, and a reader is entitled to know
        which.
        """
        payload = _plan(_session(tmp_path, self.CLEARANCE, "cp"))
        assert "deterministic_transitions" in payload["assumptions"]

    def test_it_is_maximised_not_minimised(self, tmp_path):
        values = [c["objective"] for c in
                  _plan(_session(tmp_path, self.CLEARANCE, "cp"))["candidates"]]
        assert values == sorted(values, reverse=True)


class TestTheBudgetCountsWhatItDidNotTry:

    BUDGET = ("  planning:\n    objective: expected_findings\n"
              "    max_rollouts: 2\n")

    def test_an_exhausted_budget_declines_once_with_a_count(self, tmp_path):
        payload = _plan(_session(tmp_path, self.BUDGET, "budget"))
        budget = [d for d in payload["not_checked"]
                  if d["reason"] == "budget_exhausted"]
        assert len(budget) == 1, (
            "one decline carrying the count, the way discovery.py reports "
            "pairs_untested")
        assert payload["checked"]["plans_untested"] > 0

    def test_it_still_ranks_what_it_did_try(self, tmp_path):
        payload = _plan(_session(tmp_path, self.BUDGET, "budget"))
        assert payload["ranked"] is True
        assert payload["candidates"]

    def test_a_sufficient_budget_declines_nothing(self, tmp_path):
        payload = _plan(_session(tmp_path, WITH_OBJECTIVE, "obj"))
        assert payload["checked"]["plans_untested"] == 0
        assert "budget_exhausted" not in [d["reason"]
                                          for d in payload["not_checked"]]


class TestNothingToChooseBetweenIsSaidOutLoud:

    def test_a_template_without_candidates_is_reported(self, tmp_path):
        text = MODEL.format(planning=WITH_OBJECTIVE).replace(
            "          candidates: [95, 70]\n", "").replace(
            "          candidates: [4.0]\n", "")
        path = tmp_path / "nocand.yaml"
        path.write_text(text)
        session = api.EngineSession()
        session.load_model(str(path))
        session.add_entity("node1", "Node",
                           {"memory_used_pct": 88.0, "cpu_cores": 3.2})
        payload = _plan(session)
        assert "no_candidates" in [d["reason"] for d in payload["not_checked"]]

    def test_a_caller_may_supply_candidates_instead(self, tmp_path):
        """The model declaring none is not the end of the road."""
        payload = _plan(
            _session(tmp_path, WITH_OBJECTIVE, "obj"),
            candidates=[ActionInstance("evict", "node1",
                                       {"memory_used_pct": 50.0}, 0.0)])
        assert payload["ranked"] is True
        assert any("evict" in c["plan"] for c in payload["candidates"])


class TestEachCandidateCarriesWhatLimitedIt:

    def test_a_candidate_reports_its_own_rollout_denominators(self, tmp_path):
        for candidate in _plan(
                _session(tmp_path, WITH_OBJECTIVE, "obj"))["candidates"]:
            assert "steps_completed" in candidate["checked"]
            assert "transitions_attempted" in candidate["checked"]

    def test_a_candidate_carries_its_own_declines(self, tmp_path):
        """The declines that limited a plan travel WITH the plan.

        The fixture needs an edge with no declared transition for there to BE
        a decline: this file's base model has no relationships at all, so an
        empty declines list there is correct and asserting otherwise pinned a
        falsehood. A pooled decline would be the defect -- a reader comparing
        two candidates must be able to see which one the refusal limited.
        """
        text = MODEL.format(planning=WITH_OBJECTIVE).replace(
            "  action_templates:",
            "  relationship_rules:\n"
            "    - type: hosts\n"
            "      source_type: Node\n"
            "      target_type: Node\n"
            "      temporal: {propagation_delay_s: 0, time_constant_s: 1}\n"
            "  action_templates:")
        path = tmp_path / "declines.yaml"
        path.write_text(text)
        session = api.EngineSession()
        session.load_model(str(path))
        session.add_entity("node1", "Node",
                           {"memory_used_pct": 88.0, "cpu_cores": 3.2})
        session.add_entity("node2", "Node",
                           {"memory_used_pct": 40.0, "cpu_cores": 8.0})
        session.add_relationship("node1", "hosts", "node2")
        candidates = _plan(session)["candidates"]
        acting = [c for c in candidates if c["actions"]]
        assert acting, "guard: no acting candidate makes this vacuous"
        assert any("missing_dynamics" in c["declines"] for c in acting), (
            "an edge with a temporal block and no transition limited these "
            "rollouts, and no candidate carries the refusal")

    def test_the_search_denominator_is_its_own(self, tmp_path):
        payload = _plan(_session(tmp_path, WITH_OBJECTIVE, "obj"))
        assert payload["checked"]["rollouts_run"] >= payload[
            "checked"]["candidates_evaluated"] - 1


class TestAPlanNeverDispatches:

    def test_the_session_entities_are_untouched(self, tmp_path):
        session = _session(tmp_path, WITH_OBJECTIVE, "obj")
        before = dict(session.entities["node1"].properties)
        api.plan(session, horizon_s=300.0, step_s=150.0)
        assert session.entities["node1"].properties == before

    def test_the_history_is_untouched(self, tmp_path):
        from datetime import timedelta
        session = _session(tmp_path, WITH_OBJECTIVE, "obj")
        now = api.now_utc()
        for k in range(10):
            session.add_observations(
                "node1", "memory_used_pct",
                [(now - timedelta(minutes=10 - k), 88.0)])

        def count():
            history = session.reading_history()
            return {key: len(history.get_values(
                key[0], key[1], timedelta(days=3650)))
                for key in history.series_keys()}

        before = count()
        api.plan(session, horizon_s=300.0, step_s=150.0)
        assert count() == before

    def test_the_payload_carries_no_executable_instruction(self, tmp_path):
        """A ranked list is a recommendation. It names templates and values;
        it returns nothing an executor could run without a person."""
        payload = _plan(_session(tmp_path, WITH_OBJECTIVE, "obj"))
        for candidate in payload["candidates"]:
            for action in candidate["actions"]:
                assert set(action) == {
                    "template", "entity_id", "parameters", "at_s"}
