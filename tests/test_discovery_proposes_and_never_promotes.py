"""The discovery runner: what it counts, what it challenges, and the line it
will not cross without being asked.

Three properties, in the order they matter:

- **It challenges what is declared.** A discipline that can only ever propose
  additions cannot tell you that an edge you already believe is unsupported by
  your own data, which is the more useful half. Declared pairs are therefore
  tested FIRST, before any budget is spent exploring.
- **It counts what it did not test.** The pair space is quadratic, so the
  honest answer to *did you look at everything* is usually no, and
  `pairs_untested` is that number rather than a silence.
- **It promotes nothing.** A lead-lag result is predictive precedence, which
  two series driven by an undeclared third also produce. Proposals are returned
  and adopted only by a caller, and `faithfulness_unverifiable` is declined on
  every run rather than assumed away.

The declared-edge lookup has its own test because it failed silently once: the
graph returns target IDS, unpacking them as `(relation, target)` pairs does not
raise for a two-character id, and every declared edge read as undeclared. The
counts looked entirely reasonable.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

import pytest

from arbiter_engine.api import EngineSession, discover
from arbiter_engine.causal.discovery import (
    MINIMUM_PAIRED_SAMPLES, run_discovery,
)
from arbiter_engine.clock import as_of
from arbiter_engine.history.observation import InMemoryObservationHistory

T0 = datetime(2026, 7, 1)
N = 400
END = T0 + timedelta(seconds=60 * N)

MODEL = {"domain": {"id": "d", "name": "d", "entity_types": ["Unit"],
                    "relationship_types": ["feeds"],
                    "indicators": {"Unit": [
                        {"name": "a", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
                         "window": "30d", "critical": 1e9},
                        {"name": "b", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
                         "window": "30d", "critical": 1e9}]}}}


def _session(link=True, samples=N, seed=9, declare_edge=True):
    history = InMemoryObservationHistory(retention_period=timedelta(days=3650),
                                         max_observations_per_key=10 ** 6)
    session = EngineSession(history=history)
    session.load_model(MODEL)
    for entity_id in ("u1", "u2"):
        session.add_entity(entity_id, "Unit")
    if declare_edge:
        session.add_relationship("u1", "feeds", "u2")
    rng = random.Random(seed)
    a1 = [0.0] * samples; b1 = [0.0] * samples
    a2 = [0.0] * samples; b2 = [0.0] * samples
    for t in range(1, samples):
        a1[t] = 0.5 * a1[t - 1] + rng.gauss(0, 1)
        driven = 0.9 * a1[t - 2] if (link and t >= 2) else 0.0
        b1[t] = 0.4 * b1[t - 1] + driven + rng.gauss(0, 1)
        a2[t] = 0.5 * a2[t - 1] + rng.gauss(0, 1)
        b2[t] = 0.4 * b2[t - 1] + rng.gauss(0, 1)
    for t in range(samples):
        stamp = T0 + timedelta(seconds=60 * t)
        for entity_id, va, vb in (("u1", a1, b1), ("u2", a2, b2)):
            history.add(entity_id, "a", va[t], timestamp=stamp)
            history.add(entity_id, "b", vb[t], timestamp=stamp)
    return session


def _run(session, **kw):
    with as_of(END):
        return run_discovery(session, **kw)


def _reasons(sub):
    return sorted({d.reason for d in sub.not_checked})


# --- the denominator --------------------------------------------------------

def test_every_ordered_pair_is_counted():
    sub, _ = _run(_session(), alpha=0.01)
    assert sub.checked["pairs_seen"] == 10
    assert sub.checked["pairs_tested"] == 10


def test_each_pair_costs_two_directions_times_the_lag_family():
    sub, _ = _run(_session(), alpha=0.01, lags=(1, 2))
    assert sub.checked["tests_run"] == sub.checked["pairs_tested"] * 2 * 2


def test_a_budget_stops_the_walk_and_the_remainder_is_counted():
    sub, _ = _run(_session(), alpha=0.01, budget_pairs=3)
    assert sub.checked["pairs_tested"] == 3
    assert sub.checked["pairs_untested"] == 7
    assert sub.checked["pairs_seen"] == 10


def test_the_budget_reports_itself_once_rather_than_per_pair():
    """Seven untested pairs are one fact about the budget, not seven declines."""
    sub, _ = _run(_session(), alpha=0.01, budget_pairs=3)
    budget = [d for d in sub.not_checked if d.reason == "untested_pair"]
    assert len(budget) == 1
    assert budget[0].evidence["untested"] == 7


def test_a_trending_pair_is_declined_rather_than_tested():
    """The gate, exercised THROUGH the runner. The unit tests cover the gate
    itself; nothing covered the runner consulting it, so removing the call left
    the suite green while every non-stationary pair got a p-value the tests are
    not valid for."""
    session = _session()
    for t in range(N):
        stamp = T0 + timedelta(seconds=60 * t)
        session.history.add("u2", "a", 100.0 + 0.5 * t, timestamp=stamp)
    sub, _ = _run(session, alpha=0.01)
    assert "nonstationary_series" in _reasons(sub)
    drifting = [d for d in sub.not_checked if d.reason == "nonstationary_series"]
    assert any("u2.a" in d.scope["pair"] for d in drifting)


def test_a_declined_pair_is_not_counted_as_tested():
    """The denominator has to tell the two apart, or a run that looked at
    nothing reports the same number as one that looked at everything."""
    session = _session()
    for t in range(N):
        session.history.add("u2", "a", 100.0 + 0.5 * t,
                            timestamp=T0 + timedelta(seconds=60 * t))
    sub, _ = _run(session, alpha=0.01)
    assert sub.checked["pairs_tested"] < sub.checked["pairs_seen"]


def test_a_short_series_declines_with_the_count_it_had():
    sub, _ = _run(_session(samples=MINIMUM_PAIRED_SAMPLES - 20), alpha=0.01)
    short = [d for d in sub.not_checked if d.reason == "insufficient_samples"]
    assert short
    assert short[0].evidence["required"] == MINIMUM_PAIRED_SAMPLES


# --- challenging what is declared ------------------------------------------

def test_a_declared_edge_with_no_support_is_a_finding():
    sub, _ = _run(_session(), alpha=0.01)
    unsupported = [f for f in sub.findings
                   if f.problem_type.startswith("declared_edge_unsupported")]
    assert unsupported, "the declared edge was never challenged"
    assert unsupported[0].evidence["relation"] == "feeds"
    assert unsupported[0].evidence["p_corrected"] > 0.01


def test_no_edge_declared_means_nothing_to_challenge():
    """The discriminator for the test above: same data, no declaration."""
    sub, _ = _run(_session(declare_edge=False), alpha=0.01)
    assert not [f for f in sub.findings
                if f.problem_type.startswith("declared_edge_unsupported")]


def test_declared_pairs_are_tested_before_the_budget_runs_out():
    """Ordering, proved by starving the walk. With a budget of four, the four
    declared pairs must be the ones that got tested."""
    sub, _ = _run(_session(), alpha=0.01, budget_pairs=4)
    assert len([f for f in sub.findings
                if f.problem_type.startswith("declared_edge_unsupported")]) == 4


# --- proposing, and not promoting ------------------------------------------

def test_a_real_lead_becomes_a_proposal():
    _, proposals = _run(_session(link=True), alpha=0.01)
    assert len(proposals) == 1
    assert (proposals[0].input_property, proposals[0].output_property) == ("a", "b")
    assert proposals[0].lag_seconds == 2.0
    assert proposals[0].granger_p_value < 0.01


def test_no_lead_means_no_proposal():
    _, proposals = _run(_session(link=False), alpha=0.01)
    assert proposals == []


def test_a_proposal_says_it_was_not_adopted():
    _, proposals = _run(_session(), alpha=0.01)
    assert proposals[0].llm_validated is False
    assert "not adopted" in proposals[0].validation_reason


def test_discovering_does_not_reach_the_reasoner():
    """The rule, mechanically. A lead-lag result is precedence, not structure;
    letting it change what gets checked would close a loop the engine is not
    entitled to close."""
    session = _session()
    seen = []
    session.reasoner.set_io_relationships = lambda records: seen.append(records)
    _run(session, alpha=0.01)
    assert seen == []


def test_adopting_is_a_separate_act_that_does_reach_it():
    session = _session()
    seen = []
    session.reasoner.set_io_relationships = lambda records: seen.append(records)
    _run(session, alpha=0.01)
    with as_of(END):
        adopted = discover(session, alpha=0.01)
    assert session.adopt_io_relationships() == 1
    assert len(seen) == 1 and len(seen[0]) == 1


# --- the level it will not choose ------------------------------------------

def test_without_a_level_there_are_no_findings_and_no_proposals():
    sub, proposals = _run(_session(), alpha=None)
    assert sub.findings == []
    assert proposals == []
    assert "no_significance_level" in _reasons(sub)


def test_the_tests_still_ran_and_their_p_values_are_reported():
    """Declining to rule is not declining to measure."""
    sub, _ = _run(_session(), alpha=None)
    assert sub.checked["pairs_tested"] == 10
    level = [d for d in sub.not_checked if d.reason == "no_significance_level"][0]
    assert level.evidence["pairs_with_results"] == 10
    assert level.evidence["corrected_p"]


def test_a_level_is_asked_for_rather_than_assumed():
    sub, _ = _run(_session(), alpha=None)
    assert any(q.gap.gap_type.value == "missing_threshold" for q in sub.questions)


# --- what it always says ----------------------------------------------------

def test_faithfulness_is_declined_on_every_run():
    """It licenses reading any of this as structure and cannot be tested from
    observational data. A discipline that assumed it silently would be
    asserting its own precondition."""
    for alpha in (None, 0.01):
        sub, _ = _run(_session(), alpha=alpha)
        assert "faithfulness_unverifiable" in _reasons(sub)


def test_a_third_series_preceding_both_ends_is_named():
    """Not proof of confounding, but the one case the run already measured."""
    session = _session()
    history = session.history
    rng = random.Random(21)
    driver = [0.0] * N
    for t in range(1, N):
        driver[t] = 0.5 * driver[t - 1] + rng.gauss(0, 1)
    for t in range(N):
        stamp = T0 + timedelta(seconds=60 * t)
        for entity_id in ("u1", "u2"):
            history.add(entity_id, "a", driver[t], timestamp=stamp)
            history.add(entity_id, "b", 0.9 * driver[max(t - 2, 0)] + rng.gauss(0, 0.2),
                        timestamp=stamp)
    sub, _ = _run(session, alpha=0.01)
    assert "latent_confounding_possible" in _reasons(sub)


# --- the verb ---------------------------------------------------------------

def test_the_verb_evaluates_no_invariants():
    with as_of(END):
        envelope = discover(_session(), alpha=0.01).to_dict()
    assert envelope["checked"]["invariants"] == 0
    assert envelope["discovery"]["checked"]["pairs_seen"] == 10


def test_the_findings_leg_and_the_discipline_agree():
    with as_of(END):
        envelope = discover(_session(), alpha=0.01).to_dict()
    assert len(envelope["findings"]) == len(envelope["discovery"]["findings"]) == 4


def test_the_proposals_ride_the_payload_marked_unadopted():
    with as_of(END):
        envelope = discover(_session(), alpha=0.01).to_dict()
    assert envelope["proposed_io_relationships"][0]["adopted"] is False


def test_the_verb_refuses_without_a_model_or_entities():
    assert discover(EngineSession()).to_dict()["meta"]["source"] == "unavailable"
    session = EngineSession()
    session.load_model(MODEL)
    assert discover(session).to_dict()["meta"]["reason"] == "no entities supplied"
