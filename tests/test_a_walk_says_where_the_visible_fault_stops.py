"""A walk up from a finding says where the visible fault stops.

`hypothesize` ranked every declared cause and said nothing about
where each stood. Measured on what users installed (engine 0.2.26):

- on a pump feeding a tank feeding a basin, with the tank read clean, the
  clean tank ranked first and the faulty pump second, and the reading named
  was the tank's level -- a reading already taken;
- on a department whose executive was faulty on its direct reports, no
  strength declared, the causes came back in hop-then-id order with nothing
  saying so, and the reading named was the executive's tenure;
- a fan whose checks lacked samples was named "the only declared cause" and
  read first, and nothing called it open.

Each candidate now has a `standing` from what its own checks said: `trail`
(a finding, reached through causes that are not clean), `frontier` (on the
trail with nothing that is not clean above it -- where the visible fault
stops), `open` (partial or unread, reached the same way) or `screened` (clean,
or behind one that is). A candidate read clean screens the causes whose only
way down runs through it, on the assumption `faults_visible_along_channels`
stamps. The walk is `traced`, `partly_traced`, `open`, `unexplained` or `cut`;
without every posterior the order is the standing, and `ranked_by` says so;
the reading named is one an open candidate still owes, or none, with the
reason. A posterior already filed for the same claim is not filed again, and
`model_describe` lists each declared fault channel and the types none enters.
"""

from __future__ import annotations

import pytest

from arbiter_engine import api

STAMP = "faults_visible_along_channels"


def _session(model, entities, edges):
    session = api.EngineSession()
    session.load_model(model)
    for entity_id, entity_type, properties in entities:
        session.add_entity(entity_id, entity_type, properties)
    for source, relation, target in edges:
        session.add_relationship(source, relation, target)
    api.check(session)
    return session


def _hypothesis(session, subject):
    return api.hypothesize(session, subject).to_dict()["hypothesis"]


def _standings(hypothesis):
    return {row["cause"]: row["standing"] for row in hypothesis["candidates"]}


CHAIN = {"domain": {
    "id": "walk_chain", "name": "walk chain",
    "entity_types": ["Pump", "Tank", "Basin"],
    "relationship_types": ["feeds", "spills"],
    "indicators": {
        "Pump": [{"name": "speed_rpm", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
                  "critical": 4000}],
        "Tank": [{"name": "level_pct", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
                  "warning": 85, "critical": 95}],
        "Basin": [{"name": "basin_level", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
                   "warning": 40, "critical": 60}]},
    "relationship_rules": [
        {"type": "feeds", "source_type": "Pump", "target_type": "Tank",
         "edge_direction": "causal", "causal": {"weight": 0.8}},
        {"type": "spills", "source_type": "Tank", "target_type": "Basin",
         "edge_direction": "causal", "causal": {"weight": 0.7}}]}}


def _chain(pump=None, tank=None):
    """`None` leaves that cause unread."""
    return _session(CHAIN, [
        ("pump-1", "Pump", {} if pump is None else {"speed_rpm": pump}),
        ("tank-1", "Tank", {} if tank is None else {"level_pct": tank}),
        ("basin-1", "Basin", {"basin_level": 65.0})],
        [("pump-1", "feeds", "tank-1"), ("tank-1", "spills", "basin-1")])


class TestTheChain:
    """The 0.2.17 chain: pump over its bound, tank read clean, basin over."""

    def test_a_tank_read_clean_screens_the_pump(self):
        hypothesis = _hypothesis(_chain(pump=5000.0, tank=50.0), "basin-1")
        rows = {row["cause"]: row for row in hypothesis["candidates"]}
        assert rows["pump-1"]["standing"] == "screened"
        assert rows["pump-1"]["screened_by"] == ["tank-1"]
        assert rows["tank-1"]["standing"] == "screened"
        assert rows["tank-1"]["screened_by"] is None, "screened by its own reading"
        assert STAMP in hypothesis["assumptions"]

    def test_the_finding_is_unexplained_and_no_reading_is_named(self):
        hypothesis = _hypothesis(_chain(pump=5000.0, tank=50.0), "basin-1")
        walk = hypothesis["walk"]
        assert (walk["state"], walk["frontier"], walk["open"]) == ("unexplained", [], [])
        assert walk["counts"] == {"frontier": 0, "trail": 0, "open": 0, "screened": 2}
        assert walk["ranked_by"] == "posterior", "every cause has a posterior here"
        assert hypothesis["most_discriminating"] is None
        assert "no candidate is open" in hypothesis["most_discriminating_reason"]

    def test_a_faulty_tank_is_the_trail_and_the_faulty_pump_its_frontier(self):
        hypothesis = _hypothesis(_chain(pump=5000.0, tank=97.0), "basin-1")
        assert _standings(hypothesis) == {"tank-1": "trail", "pump-1": "frontier"}
        assert hypothesis["walk"]["state"] == "traced"
        # An internal ruling added the first rung down: what the pump explains below it,
        # and the actions that apply to it -- none are declared here.
        assert hypothesis["walk"]["frontier"] == [
            {"entity": "pump-1", "findings": ["threshold_exceeded:speed_rpm"],
             "explains": [
                 {"entity": "tank-1", "hops": 1, "findings": ["threshold_exceeded:level_pct"]},
                 {"entity": "basin-1", "hops": 2,
                  "findings": ["threshold_exceeded:basin_level"]}],
             "findings_explained": 2, "actions": []}]
        assert STAMP not in hypothesis["assumptions"], "nothing is screened"

    def test_a_tank_deviating_screens_nothing_behind_it(self):
        """A finding below the floor is a finding: the tank is on the trail,
        and the pump behind it is still reached."""
        hypothesis = _hypothesis(_chain(pump=5000.0, tank=90.0), "basin-1")
        assert _standings(hypothesis) == {"tank-1": "trail", "pump-1": "frontier"}

    def test_a_reading_already_taken_is_never_the_one_named(self):
        """The tank read faulty, the pump unread: the walk asks for the pump."""
        hypothesis = _hypothesis(_chain(tank=97.0), "basin-1")
        assert _standings(hypothesis) == {"tank-1": "trail", "pump-1": "open"}
        assert hypothesis["walk"]["state"] == "open"
        assert hypothesis["most_discriminating"] == {
            "entity": "pump-1", "reading": "pump-1.speed_rpm", "basis": "only_open"}


ORG = {"domain": {
    "id": "walk_org", "name": "walk org",
    "entity_types": ["Executive", "Department"],
    "relationship_types": ["leads"],
    "indicators": {
        # Declared tenure first, so the declared order and the spelling differ.
        "Executive": [{"name": "tenure_years", "type": "NUMERIC",
                       "axioms": ["BOUNDEDNESS"], "critical": 40},
                      {"name": "direct_reports", "type": "NUMERIC",
                       "axioms": ["BOUNDEDNESS"], "warning": 15, "critical": 20}],
        "Department": [{"name": "turnover", "type": "NUMERIC",
                        "axioms": ["BOUNDEDNESS"], "critical": 20}]},
    "relationship_rules": [
        {"type": "leads", "source_type": "Executive", "target_type": "Department",
         "edge_direction": "causal"}]}}


def _org(**executives):
    """Each executive leads `dept-sales`; `None` leaves one unread."""
    entities = [("dept-sales", "Department", {"turnover": 28.0})]
    for name, reports in executives.items():
        entities.append((name.replace("_", "-"), "Executive",
                         {} if reports is None
                         else {"direct_reports": reports, "tenure_years": 3.0}))
    return _session(ORG, entities, [(name.replace("_", "-"), "leads", "dept-sales")
                                    for name in executives])


class TestTheDepartment:
    """No strength declared: every posterior is null."""

    def test_it_is_traced_to_its_executives_findings(self):
        hypothesis = _hypothesis(_org(exec_cro=22.0, exec_vp_sales=18.0), "dept-sales")
        walk = hypothesis["walk"]
        assert walk["state"] == "traced"
        # An internal ruling added the first rung down, read here by lookup.
        assert [(row["entity"], row["findings"]) for row in walk["frontier"]] == [
            ("exec-cro", ["threshold_exceeded:direct_reports"]),
            ("exec-vp-sales", ["threshold_warning:direct_reports"])]
        assert [[r["entity"] for r in row["explains"]] for row in walk["frontier"]] == [
            ["dept-sales"], ["dept-sales"]]
        assert walk["ranked_by"] == "standing"
        assert hypothesis["most_discriminating"] is None

    def test_one_executive_unread_leaves_it_partly_traced(self):
        hypothesis = _hypothesis(_org(exec_cro=22.0, exec_cmo=None), "dept-sales")
        walk = hypothesis["walk"]
        assert walk["state"] == "partly_traced"
        assert [entry["entity"] for entry in walk["open"]] == ["exec-cmo"]
        assert walk["open"][0]["needs"] == [
            {"reading": "exec-cmo.direct_reports", "reason": "missing_property"},
            {"reading": "exec-cmo.tenure_years", "reason": "missing_property"}]
        # The first VALUE the type declares, of those owed -- not the first
        # by spelling, which is the order `needs` lists them in.
        assert hypothesis["most_discriminating"] == {
            "entity": "exec-cmo", "reading": "exec-cmo.tenure_years",
            "basis": "only_open"}

    def test_executives_read_clean_leave_it_unexplained(self):
        hypothesis = _hypothesis(_org(exec_cro=5.0, exec_vp_sales=6.0), "dept-sales")
        assert hypothesis["walk"]["state"] == "unexplained"
        assert set(_standings(hypothesis).values()) == {"screened"}
        assert STAMP in hypothesis["assumptions"]


FAN = {"domain": {
    "id": "walk_fan", "name": "walk fan",
    "entity_types": ["Fan", "Zone"],
    "relationship_types": ["cools"],
    "indicators": {
        "Fan": [{"name": "rpm", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
                 "critical": 23100}],
        "Zone": [{"name": "temp", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
                  "critical": 50}]},
    "relationship_rules": [
        {"type": "cools", "source_type": "Fan", "target_type": "Zone",
         "edge_direction": "causal"}]}}


def _fan(rpm):
    return _session(FAN, [("fan-1", "Fan", {} if rpm is None else {"rpm": rpm}),
                          ("zone-1", "Zone", {"temp": 60.0})],
                    [("fan-1", "cools", "zone-1")])


class TestAFanInsideItsBoundsIsNeverTheFrontier:

    def test_unread_it_is_open_and_its_reading_is_named(self):
        hypothesis = _hypothesis(_fan(None), "zone-1")
        assert _standings(hypothesis) == {"fan-1": "open"}
        assert hypothesis["walk"]["state"] == "open"
        assert hypothesis["most_discriminating"] == {
            "entity": "fan-1", "reading": "fan-1.rpm", "basis": "only_candidate"}

    def test_read_inside_its_bounds_it_is_screened_and_the_finding_unexplained(self):
        hypothesis = _hypothesis(_fan(3000.0), "zone-1")
        assert _standings(hypothesis) == {"fan-1": "screened"}
        assert hypothesis["walk"]["state"] == "unexplained"
        assert hypothesis["most_discriminating"] is None
        assert STAMP in hypothesis["assumptions"]

    def test_read_over_its_bound_it_is_the_frontier(self):
        hypothesis = _hypothesis(_fan(30000.0), "zone-1")
        assert _standings(hypothesis) == {"fan-1": "frontier"}
        assert hypothesis["walk"]["state"] == "traced"


TREE = {"domain": {
    "id": "walk_tree", "name": "walk tree",
    "entity_types": ["Unit", "Sink"],
    "relationship_types": ["feeds", "drains"],
    "indicators": {
        "Unit": [{"name": "load", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
                  "critical": 10}],
        "Sink": [{"name": "load", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
                  "critical": 10}]},
    "relationship_rules": [
        {"type": "feeds", "source_type": "Unit", "target_type": "Unit",
         "edge_direction": "causal"},
        {"type": "drains", "source_type": "Unit", "target_type": "Sink",
         "edge_direction": "causal"}]}}


def _units(loads, edges):
    entities = [("sink-1", "Sink", {"load": 20.0})]
    entities += [(unit, "Unit", {} if load is None else {"load": load})
                 for unit, load in loads.items()]
    return _session(TREE, entities, edges)


class TestTheOrderWithoutPosteriors:
    """`a-x1` read clean with `c-y1` behind it; `b-x2` unread with `d-y2`,
    faulty, behind it. By hops and id the clean unit came first."""

    def _hypothesis(self):
        return _hypothesis(_units(
            {"a-x1": 1.0, "b-x2": None, "c-y1": 20.0, "d-y2": 20.0},
            [("a-x1", "drains", "sink-1"), ("b-x2", "drains", "sink-1"),
             ("c-y1", "feeds", "a-x1"), ("d-y2", "feeds", "b-x2")]), "sink-1")

    def test_it_is_frontier_then_open_then_screened(self):
        hypothesis = self._hypothesis()
        assert [(row["cause"], row["standing"]) for row in hypothesis["candidates"]] == [
            ("d-y2", "frontier"), ("b-x2", "open"),
            ("a-x1", "screened"), ("c-y1", "screened")]
        assert hypothesis["walk"]["ranked_by"] == "standing"
        assert hypothesis["walk"]["state"] == "partly_traced"

    def test_a_fault_behind_a_clean_cause_is_screened_by_it(self):
        rows = {row["cause"]: row for row in self._hypothesis()["candidates"]}
        assert rows["c-y1"]["screened_by"] == ["a-x1"]
        assert rows["d-y2"]["screened_by"] is None

    def test_the_counts_add_up_to_the_candidates(self):
        hypothesis = self._hypothesis()
        assert hypothesis["walk"]["counts"] == {
            "frontier": 1, "trail": 0, "open": 1, "screened": 2}


class TestARingOfFaultyCauses:

    def test_it_is_where_the_visible_fault_stops(self):
        """Two units feeding each other, both over their bound, one draining
        into the sink: neither has a cause above it that is not on the ring."""
        hypothesis = _hypothesis(_units(
            {"u-1": 20.0, "u-2": 20.0},
            [("u-1", "drains", "sink-1"), ("u-1", "feeds", "u-2"),
             ("u-2", "feeds", "u-1")]), "sink-1")
        assert _standings(hypothesis) == {"u-1": "frontier", "u-2": "frontier"}
        assert hypothesis["walk"]["state"] == "traced"

    def test_an_open_cause_above_the_ring_keeps_it_a_trail(self):
        hypothesis = _hypothesis(_units(
            {"u-1": 20.0, "u-2": 20.0, "u-3": None},
            [("u-1", "drains", "sink-1"), ("u-1", "feeds", "u-2"),
             ("u-2", "feeds", "u-1"), ("u-3", "feeds", "u-2")]), "sink-1")
        assert _standings(hypothesis) == {"u-1": "trail", "u-2": "trail",
                                          "u-3": "open"}
        assert hypothesis["walk"]["state"] == "open"


class TestAWalkWithNothingToWalk:

    def test_a_subject_outside_the_graph_is_cut(self):
        session = _units({"u-1": 1.0}, [])
        hypothesis = _hypothesis(session, "sink-1")
        assert hypothesis["walk"] == {
            "state": "cut", "frontier": [], "open": [],
            "counts": {"frontier": 0, "trail": 0, "open": 0, "screened": 0},
            "ranked_by": None}

    def test_a_subject_at_the_root_is_cut(self):
        session = _units({"u-1": 20.0}, [("u-1", "drains", "sink-1")])
        assert _hypothesis(session, "u-1")["walk"]["state"] == "cut"


class TestOneClaimIsFiledOnce:

    def test_a_walk_asked_again_files_nothing_new(self):
        session = _chain(pump=5000.0, tank=50.0)
        before = len(session.ledger._records)
        _hypothesis(session, "basin-1")
        first = len(session.ledger._records) - before
        _hypothesis(session, "basin-1")
        assert first == 2
        assert len(session.ledger._records) - before == 2

    def test_a_new_check_is_a_new_claim(self):
        session = _chain(pump=5000.0, tank=50.0)
        before = len(session.ledger._records)
        _hypothesis(session, "basin-1")
        api.check(session)
        _hypothesis(session, "basin-1")
        assert len(session.ledger._records) - before == 4


class TestTheModelSaysWhatCanBeExplained:

    def _causal(self, model):
        session = api.EngineSession()
        session.load_model(model)
        return api.model_describe(session).to_dict()["model"]["causal"]

    def test_each_fault_channel_says_what_was_declared(self):
        causal = self._causal(CHAIN)
        # An internal ruling added the end of the relation where a failure starts.
        assert causal["declared"][0] == {
            "rule": "Pump-feeds->Tank", "weight": 0.8, "weight_source": "declared",
            "leak": 0.01, "leak_source": "default",
            "propagation_delay_s": None, "time_constant_s": None, "cause": "source"}

    def test_a_strength_nobody_declared_is_none_and_says_so(self):
        [rule] = self._causal(FAN)["declared"]
        assert (rule["weight"], rule["weight_source"]) == (None, "default")

    def test_a_declared_delay_and_leak_are_reported(self):
        model = {"domain": dict(FAN["domain"], relationship_rules=[
            {"type": "cools", "source_type": "Fan", "target_type": "Zone",
             "edge_direction": "causal", "causal": {"weight": 0.5, "leak": 0.05},
             "temporal": {"propagation_delay_s": 60}}])}
        [rule] = self._causal(model)["declared"]
        assert (rule["leak"], rule["leak_source"], rule["propagation_delay_s"]) == (
            0.05, "declared", 60.0)

    def test_a_type_no_channel_enters_is_known_before_a_capture(self):
        causal = self._causal(CHAIN)
        assert causal["findable_types"] == {
            "Basin": ["Tank-spills->Basin"], "Pump": [], "Tank": ["Pump-feeds->Tank"]}
        assert causal["types_without_cause"] == ["Pump"]
        assert causal["checked"] == {"relationship_rules": 2, "causal": 2,
                                     "findable_types": 3, "without_cause": 1}

    @pytest.mark.parametrize("subject", ["pump-1"])
    def test_and_a_walk_from_it_is_cut(self, subject):
        assert _hypothesis(_chain(pump=5000.0), subject)["walk"]["state"] == "cut"
