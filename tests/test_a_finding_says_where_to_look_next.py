"""`gaps` says what the model does not declare. This says what the world might be.

Phase B4. A finding names an entity that is wrong. The operator's next
move is to decide WHERE TO LOOK, and until now the engine answered every part of
that except the question itself: it had the causal graph, the inference that
scores a node over it, and the action templates -- and no verb that put them
together facing a finding.

THE PHASE PLAN CALLED THIS A PROMOTION AND IT IS NOT, which is the correction
worth recording. `twin/hypothesis_generator.py` was named as the thing to
promote. Measured: it walks a topology for STRUCTURAL patterns -- conservation,
feedback loops, property bounds, monotonicity -- and emits a
`TopologyHypothesis` carrying a `precondition_pattern`, a `confidence` and a
`tenant_id`. None of that is `(cause, evidence_needed, test_action)` for a
finding, and `tenant_id` is an orchestrator concept a domain-free engine does
not have. Promoting it would have shipped the wrong verb under the right name.

THE RANKING IS ONLY AS GOOD AS THE EVIDENCE SEVERITY, and this file holds that
in both directions because it is the finding most likely to mislead. With every
breach at `warning` and no `causal.evidence_severity:` declared, NO finding
counts as evidence, every posterior sits at its prior, and what comes back is an
ordering of priors wearing the shape of an explanation.
"""

from __future__ import annotations

import pathlib

import pytest

from arbiter_engine import api
from arbiter_engine.inference.hypothesis import MAX_HOPS


def _example():
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / "examples",
                      here.parents[2] / "examples",
                      here.parents[2] / "docs" / "publication" / "engine-example"):
        if (candidate / "substation_feeder.yaml").is_file():
            return candidate / "substation_feeder.yaml"
    raise AssertionError("no examples directory in this tree carries it")


def _session(panel_a, panel_b):
    session = api.EngineSession()
    session.load_model(str(_example()))
    for entity_id, kind, props in (
            ("sub-1", "Supply", {"voltage_kv": 11.0}),
            ("fdr-1", "Feeder", {"current_a": 300.0}),
            ("pnl-a", "Panel", {"voltage_v": panel_a}),
            ("pnl-b", "Panel", {"voltage_v": panel_b})):
        session.add_entity(entity_id, kind, props)
    session.add_relationship("sub-1", "powers", "fdr-1")
    session.add_relationship("fdr-1", "powers", "pnl-a")
    session.add_relationship("fdr-1", "powers", "pnl-b")
    api.check(session)
    return session


def _ranked(session, entity_id="pnl-a"):
    return api.hypothesize(session, entity_id).to_dict()["hypothesis"]


#: Below the specimen's `lower_critical`, so the breach is evidence.
CRITICAL = (200.0, 201.0)
#: Inside the warning band, where nothing counts as evidence by default.
WARNING = (212.0, 214.0)


class TestTheAcceptanceCase:
    """Stated by the phase plan and reproduced here to the digit."""

    def test_the_feeder_ranks_first(self):
        ranked = _ranked(_session(*CRITICAL))["candidates"]
        assert ranked, "no candidate was ranked at all"
        assert ranked[0]["cause"] == "fdr-1", (
            f"the plan says the feeder ranks first; got "
            f"{[r['cause'] for r in ranked]}")

    def test_it_says_which_reading_would_discriminate(self):
        top = _ranked(_session(*CRITICAL))["candidates"][0]
        assert top["evidence_needed"] == "fdr-1.current_a"

    def test_the_supply_is_ranked_and_not_dropped(self):
        """Second, not absent. A verb that reported only its favourite would
        be deciding rather than ranking."""
        causes = [r["cause"] for r in _ranked(_session(*CRITICAL))["candidates"]]
        assert causes == ["fdr-1", "sub-1"], causes


class TestTheRankingIsOnlyAsGoodAsTheEvidence:
    """The finding most likely to mislead, held in both directions."""

    def test_warnings_leave_every_posterior_at_its_prior(self):
        """MEASURED: same topology, same question, opposite answers. With the
        panels in the warning band the SUPPLY outranks the feeder, because
        nothing is evidence and the order is the priors'."""
        ranked = _ranked(_session(*WARNING))["candidates"]
        assert ranked[0]["cause"] == "sub-1", (
            "the warning-band case no longer inverts the ranking, so this test "
            "has stopped demonstrating why the severity floor matters")

    def test_the_two_cases_really_differ(self):
        crit = _ranked(_session(*CRITICAL))["candidates"][0]
        warn = _ranked(_session(*WARNING))["candidates"][0]
        assert crit["cause"] != warn["cause"]
        assert crit["posterior"] > 0.5 > warn["posterior"], (
            f"critical {crit['posterior']} vs warning {warn['posterior']}")


class TestItRanksOnlyWhatWasDeclared:

    def test_an_entity_outside_the_causal_graph_is_refused_by_name(self):
        session = _session(*CRITICAL)
        session.add_entity("orphan-1", "Panel", {"voltage_v": 200.0})
        payload = _ranked(session, "orphan-1")
        reasons = {d["reason"] for d in (payload.get("not_checked") or [])}
        assert "not_identifiable" in reasons
        assert not payload["candidates"]

    def test_a_root_has_no_declared_cause_and_says_so(self):
        payload = _ranked(_session(*CRITICAL), "sub-1")
        assert not payload["candidates"]
        assert {d["reason"] for d in (payload.get("not_checked") or [])} == {
            "not_identifiable"}

    def test_the_two_refusals_are_distinguished_by_detail(self):
        """They share a reason deliberately -- growing a published closed
        vocabulary has a measured cost -- so the DETAIL has to tell them
        apart or the sharing is a loss of information."""
        session = _session(*CRITICAL)
        session.add_entity("orphan-1", "Panel", {"voltage_v": 200.0})
        outside = _ranked(session, "orphan-1")["not_checked"][0]["detail"]
        root = _ranked(session, "sub-1")["not_checked"][0]["detail"]
        assert outside != root
        assert "causal subgraph" in outside
        assert "ancestor" in root


class TestTheWalkIsBounded:

    def test_the_hop_limit_is_declared_and_reported(self):
        payload = _ranked(_session(*CRITICAL))
        assert payload["checked"]["max_hops"] == MAX_HOPS
        assert MAX_HOPS >= 1

    def test_every_candidate_is_inside_it(self):
        for row in _ranked(_session(*CRITICAL))["candidates"]:
            assert 1 <= row["hops"] <= MAX_HOPS


class TestItNamesNoActionNobodyDeclared:

    def test_a_type_with_no_action_template_reports_none(self):
        """`None` is the honest answer and is reported as one: the specimen
        declares no action, so there is no way to test any candidate, and that
        is a fact about the model worth carrying."""
        for row in _ranked(_session(*CRITICAL))["candidates"]:
            assert row["test_action"] is None
