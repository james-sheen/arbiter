"""`infer` answers whether everything ELSE implicates the target, and now says so.

The target's own reading is left out of the evidence, deliberately: conditioning
on it would answer 1 or 0 by construction. What was missing was any sign of it on
the answer. Measured on the shipped substation specimen with the feeder unread:

    supply at 11.0 kV (healthy)          P(sub-1 faulty) = 0.670634
    supply at  9.0 kV (critical breach)  P(sub-1 faulty) = 0.670634

and a reader asking whether the supply was faulty got the same number for both,
with nothing saying the reading that would have settled it had been excluded.

THE OTHER DIRECTION IS WORSE, and it is the case this file leans on hardest. With
the feeder READ CLEAN at 300 A, `hypothesize` ranked it first at 0.962 and named
its own current as the evidence needed -- sending an operator to take a reading
already taken. The ranking is right about the graph; what it lacked was the row
saying what the candidate's own meter had said.

Two defects of the same shape sat beside it and are held here too: a ranking that
dropped every stamp its inferences applied, and an intervention on the target
that was set aside with the reading, so forcing it healthy and forcing it faulty
returned one posterior.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

from arbiter_engine import api
from arbiter_engine.assumptions import (
    ASSUMPTION_STAMPS, EVIDENCE_SEVERITY_NOT_DECLARED, TARGET_READING_SET_ASIDE)


def _example() -> pathlib.Path:
    """Whichever copy this tree has -- the published tree ships `examples/`,
    the tree this is maintained in keeps it under a publication directory."""
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / "examples",
                      here.parents[2] / "examples",
                      here.parents[2] / "docs" / "publication" / "engine-example"):
        if (candidate / "substation_feeder.yaml").is_file():
            return candidate / "substation_feeder.yaml"
    raise AssertionError("no examples directory in this tree carries it")


#: The review's setup, which its figures depend on: the feeder carries no
#: reading, so it is UNOBSERVED rather than clean.
UNREAD = {}
#: Read, and inside every bound.
READ_CLEAN = {"current_a": 300.0}


def _session(supply_kv=11.0, feeder=None, panels=(200.0, 200.0), model=None):
    session = api.EngineSession()
    session.load_model(str(model or _example()))
    session.add_entity("sub-1", "Supply", {"voltage_kv": supply_kv})
    session.add_entity("fdr-1", "Feeder", dict(UNREAD if feeder is None else feeder))
    session.add_entity("pnl-1", "Panel", {"voltage_v": panels[0]})
    session.add_entity("pnl-2", "Panel", {"voltage_v": panels[1]})
    session.add_relationship("sub-1", "powers", "fdr-1")
    session.add_relationship("fdr-1", "powers", "pnl-1")
    session.add_relationship("fdr-1", "powers", "pnl-2")
    api.check(session)
    return session


def _inference(session, target, **kwargs):
    return api.infer(session, target, **kwargs).to_dict()["inference"]


def _hypothesis(session, entity_id="pnl-1"):
    return api.hypothesize(session, entity_id).to_dict()["hypothesis"]


class TestTheAnswerIsUnchanged:
    """The semantics were right. Nothing in this file may move a posterior."""

    def test_a_breach_and_a_healthy_reading_still_get_one_posterior(self):
        healthy = _inference(_session(11.0), "sub-1")["checked"]["posterior"]
        breach = _inference(_session(9.0), "sub-1")["checked"]["posterior"]
        assert healthy == breach == pytest.approx(0.670634, abs=1e-6)

    def test_the_ranking_still_moves_with_the_supply(self):
        """The supply's breach IS evidence about everything below it."""
        at_11 = _hypothesis(_session(11.0))["candidates"][0]
        at_9 = _hypothesis(_session(9.0))["candidates"][0]
        assert at_11["cause"] == at_9["cause"] == "fdr-1"
        assert at_11["posterior"] == pytest.approx(0.962165, abs=1e-6)
        assert at_9["posterior"] == pytest.approx(0.999804, abs=1e-6)


class TestTheAnswerSaysWhichReadingItLeftOut:

    def test_a_breach_that_was_set_aside_is_stamped(self):
        inference = _inference(_session(9.0), "sub-1")
        assert TARGET_READING_SET_ASIDE in inference.get("assumptions", [])

    def test_it_says_what_the_reading_would_have_set(self):
        reading = _inference(_session(9.0), "sub-1")["checked"]["target_reading"]
        assert reading == {"state": "faulty", "severity": "critical"}

    def test_a_clean_reading_set_aside_is_stamped_too(self):
        """A clean reading hidden misleads as far as a faulty one, the other
        way -- which is the case `hypothesize` got wrong."""
        inference = _inference(_session(11.0), "sub-1")
        assert TARGET_READING_SET_ASIDE in inference.get("assumptions", [])
        assert inference["checked"]["target_reading"] == {
            "state": "clean", "severity": None}

    def test_a_warning_under_the_engines_floor_reads_clean_and_says_warning(self):
        """Under the default floor a warning is not evidence, so the state is
        `clean` -- and `clean` alone would read as *nothing was found*."""
        session = _session(11.0, READ_CLEAN, panels=(200.0, 212.0))
        reading = _inference(session, "pnl-2")["checked"]["target_reading"]
        assert reading == {"state": "clean", "severity": "warning"}

    def test_an_unread_target_has_nothing_to_set_aside(self):
        inference = _inference(_session(11.0), "fdr-1")
        assert TARGET_READING_SET_ASIDE not in inference.get("assumptions", [])
        assert "target_reading" not in inference["checked"]

    def test_a_finding_carries_it_because_a_finding_travels_alone(self):
        inference = _inference(_session(9.0), "sub-1", report_above=0.5)
        assert inference["findings"], "no finding at report_above 0.5"
        evidence = inference["findings"][0]["evidence"]
        assert evidence["target_reading"] == {"state": "faulty",
                                              "severity": "critical"}


class TestACandidateCarriesItsOwnReading:

    def test_a_feeder_read_clean_says_so_beside_its_rank(self):
        """THE CASE. Ranked first on the graph, read clean on its own meter --
        both facts on one row, instead of the second sent to be collected."""
        top = _hypothesis(_session(11.0, READ_CLEAN))["candidates"][0]
        assert top["cause"] == "fdr-1"
        assert top["posterior"] == pytest.approx(0.962165, abs=1e-6)
        assert top["own_reading"] == {"state": "clean", "severity": None}

    def test_an_unread_candidate_carries_none(self):
        """`None` is the case `evidence_needed` is written for."""
        top = _hypothesis(_session(11.0))["candidates"][0]
        assert top["cause"] == "fdr-1"
        assert top["own_reading"] is None
        assert top["evidence_needed"] == "fdr-1.current_a"

    def test_a_candidate_in_breach_says_so(self):
        rows = {r["cause"]: r for r in _hypothesis(_session(9.0))["candidates"]}
        assert rows["sub-1"]["own_reading"] == {"state": "faulty",
                                                "severity": "critical"}


class TestTheRankingCarriesItsStamps:

    def test_the_engines_evidence_floor_is_disclosed(self):
        """The verb's docstring says to read this stamp before the ranking; the
        ranking used to arrive without it."""
        assumptions = _hypothesis(_session(9.0)).get("assumptions", [])
        assert EVIDENCE_SEVERITY_NOT_DECLARED in assumptions
        assert TARGET_READING_SET_ASIDE in assumptions

    def test_a_declared_floor_removes_it(self, tmp_path):
        """Propagated, not constant: declare the floor and the stamp goes."""
        document = yaml.safe_load(_example().read_text())
        document["domain"]["causal"] = {"evidence_severity": ["high", "critical"]}
        path = tmp_path / "declared.yaml"
        path.write_text(yaml.safe_dump(document))
        assumptions = _hypothesis(_session(9.0, model=path)).get("assumptions", [])
        assert EVIDENCE_SEVERITY_NOT_DECLARED not in assumptions
        assert TARGET_READING_SET_ASIDE in assumptions

    def test_they_arrive_in_the_vocabularys_order(self):
        """Two or more, or an ordering check is satisfied by an empty list --
        which is what this verb returned before it carried any."""
        assumptions = _hypothesis(_session(9.0)).get("assumptions", [])
        assert len(assumptions) >= 2, assumptions
        positions = [ASSUMPTION_STAMPS.index(s) for s in assumptions]
        assert positions == sorted(positions)


class TestAnInterventionOnTheTargetIsTheAnswer:
    """`P(x | do(x = v))` is `v`. It returned 0.984981 for both values."""

    @pytest.mark.parametrize("forced", [0, 1])
    def test_it_answers_the_forced_value(self, forced):
        inference = _inference(_session(11.0, READ_CLEAN), "fdr-1",
                               do={"fdr-1": forced})
        assert inference["checked"]["posterior"] == float(forced)
        assert inference["checked"]["method"] == "intervention"

    def test_it_files_nothing(self):
        """A value the caller forced is not a prediction about the world."""
        session = _session(11.0, READ_CLEAN)
        before = len(list(session.ledger.records()))
        _inference(session, "fdr-1", do={"fdr-1": 1})
        assert len(list(session.ledger.records())) == before

    def test_an_intervention_elsewhere_is_unchanged(self):
        """The guide's own figure: the supply with the feeder FORCED faulty is
        its prior, because the intervention cuts the edge coming in."""
        inference = _inference(_session(11.0, READ_CLEAN), "sub-1",
                               do={"fdr-1": 1})
        assert inference["checked"]["method"] == "exact_ve"
        assert inference["checked"]["posterior"] == pytest.approx(0.05, abs=1e-6)
