"""An answer under `do` is not filed in the ledger.

`infer` filed every answered posterior as a stated prediction about
now, an intervened one included. Measured with the pump and the tank both
reading clean: `infer("t", do={"p": 1})` answered 0.802 and filed it, so the
ledger would grade the tank against a pump nobody set. The modelling guide
already says of `do_would_answer` that a value nobody observed is not a
prediction; `infer` now keeps the same rule.
"""

from __future__ import annotations

from arbiter_engine import api


def _session():
    session = api.EngineSession()
    session.load_model({"domain": {
        "id": "filed", "name": "filed", "entity_types": ["Pump", "Tank"],
        "relationship_types": ["feeds"],
        "indicators": {
            "Pump": [{"name": "rpm", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
                      "critical": 4000}],
            "Tank": [{"name": "level", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
                      "critical": 95}]},
        "relationship_rules": [{"type": "feeds", "source_type": "Pump",
                                "target_type": "Tank", "edge_direction": "causal",
                                "causal": {"weight": 0.8, "leak": 0.01}}]}})
    session.add_entity("p", "Pump", {"rpm": 1000.0})
    session.add_entity("t", "Tank", {"level": 50.0})
    session.add_relationship("p", "feeds", "t")
    api.check(session)
    return session


def _filed(session):
    return len(session.ledger._records)


class TestTheLedgerKeepsClaimsAboutTheWorld:

    def test_an_intervened_answer_is_given_and_not_filed(self):
        session = _session()
        before = _filed(session)
        answer = api.infer(session, "t", do={"p": 1}).to_dict()["inference"]
        assert answer["checked"]["posterior"] > 0.5
        assert _filed(session) == before

    def test_the_same_question_unforced_is_filed(self):
        session = _session()
        before = _filed(session)
        api.infer(session, "t")
        assert _filed(session) == before + 1

    def test_forcing_the_target_itself_files_nothing(self):
        session = _session()
        before = _filed(session)
        answer = api.infer(session, "t", do={"t": 1}).to_dict()["inference"]
        assert answer["checked"]["posterior"] == 1.0
        assert _filed(session) == before
