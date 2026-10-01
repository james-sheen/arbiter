"""The prior on a root cause is the model's to declare, and stamped when it is not.

every posterior rests on the prior of each root cause it reaches: a
cause with no declared parent, neither observed nor set. That prior was the
engine's 0.05, no model key could declare it, and it was reported only in the
evidence of a posterior that raised a finding -- beside a comment naming a
`priors` key that never existed. A weight nobody declared stops the answer and
a leak nobody declared is stamped; the root prior was neither.

A model now declares it under `causal.root_prior`, a probability strictly
between 0 and 1, refused by name otherwise. An answer resting on the engine's
own is stamped `root_prior_not_declared`, and `model_describe` and a finding's
evidence report the prior in effect and where it came from.
"""

from __future__ import annotations

import pytest

from arbiter_engine import api
from arbiter_engine.assumptions import (ASSUMPTION_STAMPS,
                                                    ROOT_PRIOR_NOT_DECLARED)

STAMP = ROOT_PRIOR_NOT_DECLARED


def _session(root_prior=None, pump=1000.0, written=True):
    """A pump feeding a tank over its bound; `pump=None` leaves the root unread."""
    domain = {
        "id": "root_prior", "name": "root prior", "entity_types": ["Pump", "Tank"],
        "relationship_types": ["feeds"],
        "indicators": {
            "Pump": [{"name": "rpm", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
                      "critical": 4000}],
            "Tank": [{"name": "level", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
                      "critical": 95}]},
        "relationship_rules": [{"type": "feeds", "source_type": "Pump",
                                "target_type": "Tank", "edge_direction": "causal",
                                "causal": {"weight": 0.8, "leak": 0.01}}]}
    if written:
        domain["causal"] = {"root_prior": root_prior}
    session = api.EngineSession()
    session.load_model({"domain": domain})
    session.add_entity("p", "Pump", {} if pump is None else {"rpm": pump})
    session.add_entity("t", "Tank", {"level": 99.0})
    session.add_relationship("p", "feeds", "t")
    api.check(session)
    return session


def _answer(session, target="p", **kwargs):
    return api.infer(session, target, **kwargs).to_dict()["inference"]


class TestDeclaredOrStamped:

    def test_undeclared_it_is_the_engines_and_says_so(self):
        answer = _answer(_session(written=False))
        assert STAMP in answer["assumptions"]

    def test_declared_at_the_engines_value_it_is_the_same_answer_unstamped(self):
        stamped = _answer(_session(written=False))
        declared = _answer(_session(root_prior=0.05))
        assert declared["checked"]["posterior"] == stamped["checked"]["posterior"]
        assert STAMP not in declared["assumptions"]

    def test_a_declared_prior_is_the_one_the_answer_uses(self):
        answer = _answer(_session(root_prior=0.2))
        assert answer["checked"]["posterior"] == pytest.approx(0.952494, abs=1e-6)
        assert STAMP not in answer["assumptions"]


class TestOnlyARootTheAnswerLeansOnCounts:

    def test_a_root_read_is_evidence_and_its_prior_drops_out(self):
        """The pump has a reading: asking about the tank leans on no prior."""
        assert STAMP not in _answer(_session(written=False), target="t")["assumptions"]

    def test_a_root_unread_enters_at_its_prior(self):
        assert STAMP in _answer(_session(written=False, pump=None),
                                target="t")["assumptions"]

    def test_a_root_set_by_do_enters_at_the_value_set(self):
        answer = _answer(_session(written=False, pump=None), target="t", do={"p": 1})
        assert STAMP not in answer["assumptions"]


class TestAValueThatIsNotAProbabilityIsRefused:

    @pytest.mark.parametrize("written", [0, 1, 1.5, -0.1, "0.1", True, None])
    def test_it_is_refused_by_name_and_the_engines_used(self, written):
        session = _session(root_prior=written)
        rows = [r for r in session.model.unread_fields() if r["field"] == "causal.root_prior"]
        assert rows and rows[0]["reason"] == "malformed_value", rows
        assert "the engine's own 0.05 was used" in rows[0]["remedy"]
        assert STAMP in _answer(session)["assumptions"]

    def test_a_probability_is_read(self):
        session = _session(root_prior=0.02)
        assert not [r for r in session.model.unread_fields()
                    if r["field"].startswith("causal")]


class TestEveryReaderSaysTheSame:

    def test_a_ranking_carries_the_stamp_its_inferences_made(self):
        leg = api.hypothesize(_session(written=False, pump=None), "t").to_dict()["hypothesis"]
        assert STAMP in leg["assumptions"]

    @pytest.mark.parametrize("root_prior,value,source", [
        (None, 0.05, "default"), (0.2, 0.2, "declared")])
    def test_the_model_reports_the_prior_in_effect(self, root_prior, value, source):
        session = _session(root_prior=root_prior, written=root_prior is not None)
        causal = api.model_describe(session).to_dict()["model"]["causal"]
        assert (causal["root_prior"], causal["root_prior_source"]) == (value, source)

    def test_a_finding_carries_the_prior_in_effect(self):
        answer = api.infer(_session(root_prior=0.2), "p",
                           report_above=0.5).to_dict()["inference"]
        [finding] = answer["findings"]
        assert (finding["evidence"]["root_prior"],
                finding["evidence"]["root_prior_source"]) == (0.2, "declared")

    def test_the_stamp_is_in_the_published_vocabulary(self):
        assert STAMP in ASSUMPTION_STAMPS
