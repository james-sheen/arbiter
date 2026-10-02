"""Where the visible fault stops, each frontier entity says what it explains below it.

the walk up from a finding says where the visible fault stops, and its
frontier entry carried the entity and its own findings: nothing below it. Measured
on what users installed (engine 0.2.31), on operating-health-audit's shipped
capture: `exec-cro` is on `dept-sales`'s frontier, and nothing said it accounts
for the department's two findings and the division's one, or which actions apply
to it. `traverse` forward from it walks every edge and re-reads bounds -- not the
answer. And no `plan` candidate said whether it acts on a frontier entity of an
open case.

Each frontier entry now carries `explains`, the entities downstream of it along
declared causal edges, within the walk's bound, that show a finding at the walk's
instant, with `findings_explained`; and `actions`, every declared template that
applies to its type. Each `plan` candidate names the open cases whose last walk
holds an entity it acts on at the frontier, read from the case book. No ranking
moves.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import yaml

from arbiter_engine import api

AT = datetime(2026, 10, 2, 12, 0)


def _org(*, max_hops=None, depends_on=None, audit_finding=True, cases=False):
    """An executive over its bound leading a department over its bound, which
    reports to a division over its bound; the executive also audits a process,
    a relation with no causal direction, and that process shows a finding."""
    rules = [
        {"type": "leads", "source_type": "Executive", "target_type": "Department",
         "edge_direction": "causal"},
        {"type": "reports_to", "source_type": "Department", "target_type": "Division",
         "edge_direction": "causal"}]
    if depends_on:
        rules.append({"type": "depends_on", "source_type": "Process",
                      "target_type": "Department", "cause": "target"})
    domain = {
        "id": "rung", "name": "rung",
        "entity_types": ["Executive", "Department", "Division", "Process"],
        "relationship_types": ["leads", "reports_to", "audits", "depends_on"],
        "indicators": {
            "Executive": [{"name": "direct_reports", "type": "NUMERIC",
                           "axioms": ["BOUNDEDNESS"], "critical": 20}],
            "Department": [{"name": "turnover", "type": "NUMERIC",
                            "axioms": ["BOUNDEDNESS"], "critical": 20},
                           {"name": "absence", "type": "NUMERIC",
                            "axioms": ["BOUNDEDNESS"], "critical": 10}],
            "Division": [{"name": "margin_drop", "type": "NUMERIC",
                          "axioms": ["BOUNDEDNESS"], "critical": 10}],
            "Process": [{"name": "error_rate", "type": "NUMERIC",
                         "axioms": ["BOUNDEDNESS"], "critical": 10}]},
        "action_templates": [
            {"name": "coach", "applies_to": "Executive",
             "description": "A coaching plan for an executive.",
             "parameters_schema": {"hours": {"type": "number"}}, "effect": "set",
             "source": "a test's fixture"},
            {"name": "add_people", "applies_to": "Department",
             "description": "Add people to a department.",
             "parameters_schema": {"people": {"type": "number"}}, "effect": "add",
             "source": "a test's fixture"}],
        "relationship_rules": rules}
    if max_hops is not None:
        domain["causal"] = {"max_hops": max_hops}
    if cases:
        domain["cases"] = {"severity": "warning", "consecutive_checks": 2}
    session = api.EngineSession()
    session.load_model({"domain": domain})
    for entity_id, entity_type, properties in (
            ("exec-a", "Executive", {"direct_reports": 22.0}),
            ("dept-a", "Department", {"turnover": 28.0, "absence": 12.0}),
            ("div-a", "Division", {"margin_drop": 12.0}),
            ("proc-audited", "Process", {"error_rate": 14.0 if audit_finding else 2.0}),
            ("proc-a", "Process", {"error_rate": 11.0})):
        session.add_entity(entity_id, entity_type, properties)
    for source, relation, target in (
            ("exec-a", "leads", "dept-a"), ("dept-a", "reports_to", "div-a"),
            ("exec-a", "audits", "proc-audited"), ("proc-a", "depends_on", "dept-a")):
        session.add_relationship(source, relation, target)
    with api.as_of(AT):
        api.check(session)
    return session


def _frontier(session, unit):
    with api.as_of(AT):
        walk = api.hypothesize(session, unit).to_dict()["hypothesis"]["walk"]
    return {row["entity"]: row for row in walk["frontier"]}


class TestWhatAFrontierEntityExplains:

    def test_the_executive_explains_the_department_and_its_division(self):
        row = _frontier(_org(), "dept-a")["exec-a"]
        assert [(r["entity"], r["hops"], r["findings"]) for r in row["explains"]] == [
            ("dept-a", 1, ["threshold_exceeded:absence", "threshold_exceeded:turnover"]),
            ("div-a", 2, ["threshold_exceeded:margin_drop"])]
        assert row["findings_explained"] == 3

    def test_only_along_declared_causal_edges(self):
        """The executive audits a process that shows a finding, along a relation
        with no causal direction: not explained."""
        row = _frontier(_org(), "dept-a")["exec-a"]
        assert "proc-audited" not in [r["entity"] for r in row["explains"]]

    def test_a_relation_whose_cause_is_its_target_is_walked_down_too(self):
        row = _frontier(_org(depends_on=True), "dept-a")["exec-a"]
        assert [r["entity"] for r in row["explains"]] == ["dept-a", "div-a", "proc-a"]
        assert row["findings_explained"] == 4

    def test_within_the_walks_bound(self):
        row = _frontier(_org(max_hops=1), "dept-a")["exec-a"]
        assert [r["entity"] for r in row["explains"]] == ["dept-a"]

    def test_at_the_walks_instant(self):
        """The division was over its bound at an earlier check and is not now."""
        session = _org()
        session.add_entity("div-a", "Division", {"margin_drop": 2.0})
        with api.as_of(AT + timedelta(minutes=5)):
            api.check(session)
            walk = api.hypothesize(session, "dept-a").to_dict()["hypothesis"]["walk"]
        [row] = walk["frontier"]
        assert [r["entity"] for r in row["explains"]] == ["dept-a"]
        assert row["findings_explained"] == 2

    def test_the_actions_that_apply_to_its_type(self):
        assert _frontier(_org(), "dept-a")["exec-a"]["actions"] == ["coach"]

    def test_gaps_reads_the_same_rung(self):
        with api.as_of(AT):
            session = _org()
            from arbiter_engine.inference.hypothesis import walk_up
            walk = walk_up(session, "dept-a")["walk"]
        [row] = walk["frontier"]
        assert (row["findings_explained"], row["actions"]) == (3, ["coach"])

    def test_a_case_keeps_the_frontier_as_it_did(self):
        """What a frontier entity explains is the walk's; a case keeps each
        frontier entity and its own findings, as 0.2.31 kept them."""
        session = _org(cases=True)
        with api.as_of(AT):
            case_id = api.open_case(session, "dept-a", "turnover",
                                    basis="a test").to_dict()["case"]["case_id"]
            api.attach_stage(session, case_id, "hypothesize",
                             api.hypothesize(session, "dept-a"))
        kept = session.ledger.case_book.get(case_id).stages["hypothesize"][-1]["reference"]
        assert [sorted(row) for row in kept["walk"]["frontier"]] == [["entity", "findings"]]


def _planning():
    """The engine's pump and tank planning example, with a case criterion and
    the pump's channel into the tank declared causal by the new key, with no
    dead time."""
    here = Path(__file__).resolve()
    for candidate in (here.parents[1] / "examples", here.parents[2] / "examples",
                      here.parents[2] / "docs" / "publication" / "engine-example"):
        if (candidate / "pump_tank_planning.yaml").is_file():
            model = yaml.safe_load((candidate / "pump_tank_planning.yaml").read_text())
            break
    else:
        raise AssertionError("no examples directory in this tree carries the example")
    model["domain"]["cases"] = {"severity": "warning", "consecutive_checks": 2}
    for rule in model["domain"]["relationship_rules"]:
        if rule["type"] == "feeds":
            rule["cause"] = "source"
            # Read the pump at the finding's instant: a declared dead time would
            # read it before this fixture fed it, and leave it open.
            rule.setdefault("temporal", {})["propagation_delay_s"] = 0
    session = api.EngineSession()
    session.load_model(model)
    for entity_id, entity_type, properties in (
            ("pump1", "Pump", {"speed_rpm": 4200.0}),
            ("tank1", "Tank", {"level_pct": 97.0}),
            ("valve1", "Valve", {"open_pct": 0.0})):
        session.add_entity(entity_id, entity_type, properties)
    session.add_relationship("pump1", "feeds", "tank1")
    session.add_relationship("valve1", "drains", "tank1")
    return session


def _rank(session, case_id, minutes):
    with api.as_of(AT + timedelta(minutes=minutes)):
        api.check(session)
        api.attach_stage(session, case_id, "hypothesize", api.hypothesize(session, "tank1"))


def _plans(session, minutes):
    with api.as_of(AT + timedelta(minutes=minutes)):
        leg = api.plan(session).to_dict()["plan"]
    return {c["plan"]: c for c in leg["candidates"]}


def _acting_on(plans, entity):
    return [c for c in plans.values() if any(a["entity_id"] == entity for a in c["actions"])]


def _acting_only_on(plans, entity):
    return [c for c in plans.values()
            if c["actions"] and all(a["entity_id"] == entity for a in c["actions"])]


class TestAPlanSaysWhetherItActsWhereAWalkStopped:

    def _opened(self):
        session = _planning()
        with api.as_of(AT):
            api.check(session)
            case_id = api.open_case(session, "tank1", "level_pct",
                                    basis="a test").to_dict()["case"]["case_id"]
        _rank(session, case_id, 1)
        return session, case_id

    def test_a_plan_on_the_frontier_names_the_open_case(self):
        session, case_id = self._opened()
        plans = _plans(session, 2)
        on_pump, valve_only = _acting_on(plans, "pump1"), _acting_only_on(plans, "valve1")
        assert on_pump and valve_only
        assert all(c["on_frontier_of"] == [case_id] for c in on_pump)
        assert all(c["on_frontier_of"] == [] for c in valve_only)
        assert plans["do_nothing"]["on_frontier_of"] == []

    def test_no_ranking_moves(self):
        session, _case_id = self._opened()
        with api.as_of(AT + timedelta(minutes=2)):
            leg = api.plan(session).to_dict()["plan"]
        bare = _planning()
        with api.as_of(AT + timedelta(minutes=2)):
            api.check(bare)
            plain = api.plan(bare).to_dict()["plan"]
        assert [c["plan"] for c in leg["candidates"]] == [c["plan"] for c in plain["candidates"]]
        assert leg.get("best") == plain.get("best")

    def test_only_the_last_walk_counts(self):
        """The pump repaired and the tank still over its bound: the last walk
        screens the pump, and no plan on it names the case."""
        session, _case_id = self._opened()
        session.add_entity("pump1", "Pump", {"speed_rpm": 3000.0})
        _rank(session, _case_id, 2)
        assert all(c["on_frontier_of"] == [] for c in _acting_on(_plans(session, 3), "pump1"))

    def test_only_an_open_case_counts(self):
        session, case_id = self._opened()
        session.add_entity("tank1", "Tank", {"level_pct": 50.0})
        for minutes in (2, 3):
            with api.as_of(AT + timedelta(minutes=minutes)):
                api.check(session)
        assert session.ledger.case_book.get(case_id).status == "resolved"
        assert all(c["on_frontier_of"] == [] for c in _acting_on(_plans(session, 4), "pump1"))

    def test_the_pump_says_what_it_explains_and_what_acts_on_it(self):
        session, _case_id = self._opened()
        with api.as_of(AT + timedelta(minutes=2)):
            walk = api.hypothesize(session, "tank1").to_dict()["hypothesis"]["walk"]
        [row] = walk["frontier"]
        assert (row["entity"], [r["entity"] for r in row["explains"]], row["actions"]) == (
            "pump1", ["tank1"], ["throttle_pump"])
