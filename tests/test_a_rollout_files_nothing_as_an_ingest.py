"""A plan's rollout files nothing as an ingest, and imagines what it did.

A rollout copies the session's history into a private one for every
option a plan rolls out, and writes each step it imagines into that copy. Both
went through the store's `add`, which hands every reading to the DT production
record when the record is switched on: one run of a case's plans filed 5.4
million readings as ingests, where the case had posted 16,447. The copy goes in
in bulk now (`add_restored`) and the steps through `add_imagined`; neither files
anything, and the copy and the steps are the same reading for reading.

A node with two remedies and a past, planned and rolled out with the record on,
and again with every one of those writes put back through `add`.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

import pytest

from arbiter_engine import api
from arbiter_engine.history import observation_production as op
from arbiter_engine.history.observation import InMemoryObservationHistory
from arbiter_engine.twin.actions import ActionInstance

MODEL = """
domain:
  id: remedies
  name: A node with two remedies
  entity_types: [Node]
  relationship_types: [hosts]
  indicators:
    Node:
      - {name: memory_used_pct, type: NUMERIC, role: percentage, axioms: [BOUNDEDNESS, HOMEOSTASIS],
         warning: 80, critical: 90, window: 1h, homeostasis: {setpoint: 60, tolerance: 15}}
      - {name: cpu_cores, type: NUMERIC, axioms: [BOUNDEDNESS], lower_warning: 3.5, lower_critical: 3.0}
  action_templates:
    - name: evict
      applies_to: Node
      parameters_schema:
        memory_used_pct: {type: number, entity_property: memory_used_pct, candidates: [95, 70]}
      effect: set
      source: runbook
    - name: reserve
      applies_to: Node
      parameters_schema:
        cpu_cores: {type: number, entity_property: cpu_cores, candidates: [4.0]}
      effect: set
      source: runbook
  planning:
    objective: expected_findings
"""
AT = datetime(2026, 3, 1, 12, 0)
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


@pytest.fixture(autouse=True)
def _recording(monkeypatch):
    """The production record switched on, as a deployed Core runs it, its heartbeat reset either side."""
    monkeypatch.setattr(op, "DT_OBSERVATION_PRODUCTION_ENABLED", True)
    op.reset_ingest_heartbeat_for_test()
    yield
    op.reset_ingest_heartbeat_for_test()


def _session(tmp_path) -> api.EngineSession:
    path = tmp_path / "remedies.yaml"
    path.write_text(MODEL)
    session = api.EngineSession()
    session.load_model(str(path))
    session.add_entity("node1", "Node", {"memory_used_pct": 92.0, "cpu_cores": 3.2})
    past = [AT - timedelta(minutes=40 - i) for i in range(40)]
    session.add_observations("node1", "memory_used_pct",
                             [(when, 60.0 + i) for i, when in enumerate(past)])
    session.add_observations("node1", "cpu_cores", [(when, 3.2) for when in past])
    with api.as_of(AT):
        api.check(session)
    return session


def _without_ids(value):
    """The answer with every random id set aside: a rollout files its records under a fresh one."""
    if isinstance(value, dict):
        return {k: _without_ids(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_without_ids(v) for v in value]
    if isinstance(value, str):
        return UUID.sub("<id>", value)
    return value


def _planned(session):
    with api.as_of(AT):
        return _without_ids(api.plan(session, horizon_s=600.0, step_s=150.0).to_dict())


def _rolled(session):
    with api.as_of(AT):
        return _without_ids(api.rollout(
            session, actions=[ActionInstance("evict", "node1", {"memory_used_pct": 70.0}, 0.0)],
            horizon_s=600.0, step_s=150.0).to_dict())


def _through_add(monkeypatch):
    """Every copy and every imagined step written as they were before: one `add` a reading."""
    monkeypatch.setattr(InMemoryObservationHistory, "add_restored",
                        lambda self, e, p, rows: [self.add(e, p, v, t) for t, v in rows] and None)
    monkeypatch.setattr(InMemoryObservationHistory, "add_imagined",
                        lambda self, e, p, v, t=None: self.add(e, p, v, t))


class TestARolloutFilesNothing:

    def test_the_session_files_what_it_was_fed_and_the_plan_files_nothing(self, tmp_path):
        session = _session(tmp_path)
        fed = op.get_ingest_count_total()
        assert fed == 80, "the session's own readings are arrivals, and were filed"
        planned = _planned(session)
        assert planned["plan"]["checked"].get("candidates", 0) or planned["plan"].get("candidates")
        _rolled(session)
        assert op.get_ingest_count_total() == fed, "a rollout's copy or its steps were filed as ingests"

    def test_put_back_through_add_they_were_filed(self, tmp_path, monkeypatch):
        """The control: the same plan, its writes through `add`, files what the copies and steps hold."""
        session = _session(tmp_path)
        fed = op.get_ingest_count_total()
        _through_add(monkeypatch)
        _planned(session)
        assert op.get_ingest_count_total() > fed


class TestTheAnswersAreTheSame:

    def test_a_plan(self, tmp_path, monkeypatch):
        session = _session(tmp_path)
        planned = _planned(session)
        _through_add(monkeypatch)
        assert planned == _planned(session)

    def test_a_rollout(self, tmp_path, monkeypatch):
        session = _session(tmp_path)
        rolled = _rolled(session)
        assert rolled["simulation"]["checked"]["history_seeded"] == 80
        _through_add(monkeypatch)
        assert rolled == _rolled(session)
