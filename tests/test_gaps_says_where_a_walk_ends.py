"""`gaps` says where the walk up from each finding ends, and why.

`hypothesize` walks up from a finding and says where each cause
stands; `gaps` said nothing about where a walk ends. Measured on what users
installed (engine 0.2.29), on operating-health-audit's shipped capture,
`gaps.residuals` located nothing:

- not a department no executive leads, whose walk is cut;
- not the two `depends_on` instances joining processes to departments, both
  ends with findings, on a relation the model gives no causal direction;
- not a person's confirmation of a cause outside the declared graph, which
  the book counted `not_ranked` and nothing read.

On bmc-sensor-audit's Mt. Jade loop at sixteen walks the finding was
`unexplained`, and nothing was located there either.

A fourth arm now reads the walk `hypothesize` takes, infers nothing and files
nothing, and locates, with `basis: walk`: `no_cause_connected`,
`unexplained_finding`, `undeclared_channel` -- counted per relation, both
directions and neither preferred -- and `confirmed_outside_graph`. Beside them
it counts the walks it read and the states they ended in. A model that
declares no causal rule is told so by name.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from arbiter_engine import api
from arbiter_engine.inference.hypothesis import walk_up
from arbiter_engine.subenvelope import VOCABULARIES

AT = datetime(2026, 9, 15)
KINDS = {"no_cause_connected", "unexplained_finding", "undeclared_channel",
         "confirmed_outside_graph"}


def _session(model, entities, edges, *, checked=True):
    session = api.EngineSession()
    session.load_model(model)
    for entity_id, entity_type, properties in entities:
        session.add_entity(entity_id, entity_type, properties)
    for source, relation, target in edges:
        session.add_relationship(source, relation, target)
    if checked:
        with api.as_of(AT):
            api.check(session)
    return session


def _residuals(session):
    with api.as_of(AT):
        return api.gaps(session).to_dict()["residuals"]


def _walked(session, kind=None):
    """The walk arm's rows, by kind: a confirmation's `basis` is the person's."""
    return [h for h in _residuals(session)["hypotheses"]
            if h["kind"] in KINDS and (kind is None or h["kind"] == kind)]


def _declined(residuals):
    return {(d["reason"], d["location"]) for d in residuals["not_checked"]}


def _org_model(*, depends_on=None):
    """The shape of operating-health-audit's model: `leads` and `reports_to`
    causal, `depends_on` and `funds` declared as relations and nothing more."""
    rules = [
        {"type": "leads", "source_type": "Executive", "target_type": "Department",
         "edge_direction": "causal"},
        {"type": "reports_to", "source_type": "Department", "target_type": "Division",
         "edge_direction": "causal"}]
    if depends_on is not None:
        rules.append(dict({"type": "depends_on", "source_type": "Process",
                           "target_type": "Department"}, **depends_on))
    return {"domain": {
        "id": "walk_across", "name": "walk across",
        "entity_types": ["Executive", "Department", "Division", "Process", "Project"],
        "relationship_types": ["leads", "reports_to", "depends_on", "funds"],
        # When a case closes is the model's to say; a confirmation needs a case.
        "cases": {"severity": "warning", "consecutive_checks": 2},
        "indicators": {
            "Executive": [{"name": "direct_reports", "type": "NUMERIC",
                           "axioms": ["BOUNDEDNESS"], "warning": 15, "critical": 20}],
            # Two readings, so a department over both carries two findings and
            # the counts per direction differ, as on the shipped capture.
            "Department": [{"name": "turnover", "type": "NUMERIC",
                            "axioms": ["BOUNDEDNESS"], "critical": 20},
                           {"name": "absence", "type": "NUMERIC",
                            "axioms": ["BOUNDEDNESS"], "critical": 10}],
            "Division": [{"name": "margin_drop", "type": "NUMERIC",
                          "axioms": ["BOUNDEDNESS"], "critical": 10}],
            "Process": [{"name": "error_rate", "type": "NUMERIC",
                         "axioms": ["BOUNDEDNESS"], "critical": 10}],
            "Project": [{"name": "overrun", "type": "NUMERIC",
                         "axioms": ["BOUNDEDNESS"], "critical": 10}]},
        "relationship_rules": rules}}


def _org(*, ops_margin=2.0, depends_on=None, extra_edges=()):
    """Eleven findings on the shipped capture's shape: `dept-sales` led by two
    executives over their bounds; `dept-support` led by nobody; two processes
    depending on those departments; a project funding a division that shows
    nothing. The export also carries one `reports_to` against the rule's types,
    between two entities a causal edge already joins."""
    entities = [
        ("exec-a", "Executive", {"direct_reports": 22.0}),
        ("exec-b", "Executive", {"direct_reports": 18.0}),
        ("dept-sales", "Department", {"turnover": 28.0, "absence": 12.0}),
        ("dept-support", "Department", {"turnover": 31.0, "absence": 14.0}),
        ("div-commercial", "Division", {"margin_drop": 12.0}),
        ("div-ops", "Division", {"margin_drop": ops_margin}),
        ("proc-onboarding", "Process", {"error_rate": 12.0}),
        ("proc-sales", "Process", {"error_rate": 11.0}),
        ("proj-expansion", "Project", {"overrun": 15.0})]
    edges = [
        ("exec-a", "leads", "dept-sales"), ("exec-b", "leads", "dept-sales"),
        ("dept-sales", "reports_to", "div-commercial"),
        ("dept-support", "reports_to", "div-ops"),
        ("div-commercial", "reports_to", "dept-sales"),
        ("proc-onboarding", "depends_on", "dept-support"),
        ("proc-sales", "depends_on", "dept-sales"),
        ("proj-expansion", "funds", "div-ops")] + list(extra_edges)
    return _session(_org_model(depends_on=depends_on), entities, edges)


class TestTheShippedShape:

    def test_a_department_nobody_leads_has_no_cause_connected(self):
        [row] = _walked(_org(), "no_cause_connected")
        assert row == {"kind": "no_cause_connected", "at": "dept-support",
                       "basis": "walk", "relation": "leads",
                       "subjects": ["dept-support"],
                       "evidence_needed": "dept-support.leads"}

    def test_both_processes_are_undeclared_channels_on_depends_on(self):
        rows = _walked(_org(), "undeclared_channel")
        assert [(row["between"], row["relation"]) for row in rows] == [
            (["proc-onboarding", "dept-support"], "depends_on"),
            (["proc-sales", "dept-sales"], "depends_on")]
        for row in rows:
            assert row["evidence_needed"] is None
            assert "`depends_on` from Process to Department" in row["reason"]

    def test_a_channel_names_every_walk_it_touches(self):
        rows = {tuple(row["between"]): row for row in _walked(_org(), "undeclared_channel")}
        # `dept-sales` is on `div-commercial`'s trail, so that walk touches it too.
        assert rows[("proc-sales", "dept-sales")]["subjects"] == [
            "dept-sales", "div-commercial", "proc-sales"]

    def test_nothing_at_the_project_whose_division_shows_nothing(self):
        assert not [row for row in _walked(_org())
                    if "proj-expansion" in str(row)]

    def test_a_relation_a_causal_edge_already_joins_is_not_reported(self):
        """`div-commercial reports_to dept-sales` runs against the rule's types,
        between two entities with findings, and `dept-sales reports_to
        div-commercial` already joins them."""
        assert not [row for row in _walked(_org(), "undeclared_channel")
                    if row["relation"] == "reports_to"]

    def test_the_counts_say_what_each_direction_would_connect(self):
        counts = _residuals(_org())["checked"]["undeclared_channels"]
        # At the source, the departments' four findings; at the target, the
        # processes' two. Both are given and neither is preferred.
        assert counts == {"depends_on": {"instances": 2, "if_cause_is_source": 4,
                                         "if_cause_is_target": 2}}

    def test_the_walk_states_are_counted(self):
        checked = _residuals(_org())["checked"]
        assert checked["walks_read"] == 8
        assert checked["walk_states"] == {"traced": 2, "partly_traced": 0, "open": 0,
                                          "unexplained": 0, "cut": 6}

    def test_nothing_else_is_located(self):
        assert {row["kind"] for row in _walked(_org())} == {
            "no_cause_connected", "undeclared_channel"}
        assert len(_walked(_org())) == 3


class TestOnlyWhatTheRulesSay:

    def test_a_type_no_causal_rule_targets_has_no_cause_to_connect(self):
        """Both processes and the project are cut with a finding, and no causal
        rule targets their types: nothing is missing there."""
        located = {row["at"] for row in _walked(_org(), "no_cause_connected")}
        assert not located & {"proc-onboarding", "proc-sales", "proj-expansion",
                              "exec-a", "exec-b"}

    def test_a_frontier_entity_is_located_with_every_walk_that_reached_it(self):
        """The operations division over its bound: its walk stops at
        `dept-support`, which nobody leads."""
        [row] = _walked(_org(ops_margin=15.0), "no_cause_connected")
        assert (row["at"], row["subjects"]) == ("dept-support",
                                                ["dept-support", "div-ops"])

    def test_once_the_division_shows_a_finding_the_project_is_a_channel(self):
        rows = _walked(_org(ops_margin=15.0), "undeclared_channel")
        assert (["proj-expansion", "div-ops"], "funds") in [
            (row["between"], row["relation"]) for row in rows]

    def test_a_relation_declared_causal_is_walked_not_located(self):
        session = _org(depends_on={"edge_direction": "causal"})
        assert not _walked(session, "undeclared_channel")
        assert _residuals(session)["checked"]["undeclared_channels"] == {}

    def test_a_rule_that_gives_no_direction_is_still_silent(self):
        rows = _walked(_org(depends_on={}), "undeclared_channel")
        assert len(rows) == 2


def _fan_model(vents=False):
    rules = [{"type": "cools", "source_type": "Fan", "target_type": "Zone",
              "edge_direction": "causal"},
             {"type": "drives", "source_type": "Zone", "target_type": "Fan"}]
    return {"domain": {
        "id": "walk_fan_across", "name": "walk fan across",
        "entity_types": ["Fan", "Zone"],
        "relationship_types": ["cools", "drives"] + (["vents"] if vents else []),
        "indicators": {
            "Fan": [{"name": "rpm", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
                     "critical": 23100}],
            "Zone": [{"name": "temp", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
                      "critical": 50}]},
        "relationship_rules": rules}}


def _fan(*, vents=False):
    """A zone over its bound, cooled by a fan reading inside its own; the zone
    drives the fan, a relation with no causal direction."""
    entities = [("fan-1", "Fan", {"rpm": 3000.0}), ("zone-1", "Zone", {"temp": 60.0})]
    edges = [("fan-1", "cools", "zone-1"), ("zone-1", "drives", "fan-1")]
    if vents:
        entities.append(("zone-2", "Zone", {"temp": 70.0}))
        edges.append(("zone-2", "vents", "zone-1"))
    return _session(_fan_model(vents), entities, edges)


class TestAnUnexplainedFinding:

    def test_it_is_located_with_no_candidate_and_the_reason(self):
        [row] = _walked(_fan(), "unexplained_finding")
        assert (row["at"], row["screened"], row["candidates"]) == (
            "zone-1", ["fan-1"], [])
        assert row["evidence_needed"] is None
        assert "no relation without a causal direction" in row["reason"]

    def test_a_relation_it_drives_toward_a_clean_fan_is_no_candidate(self):
        """`drives` joins the zone to the fan, which shows nothing and is
        already joined causally."""
        assert not _walked(_fan(), "undeclared_channel")

    def test_an_undeclared_channel_at_it_is_its_candidate(self):
        [row] = _walked(_fan(vents=True), "unexplained_finding")
        assert row["candidates"] == [{"between": ["zone-2", "zone-1"],
                                      "relation": "vents"}]
        assert "a causal direction declared on a candidate" in row["reason"]


READING = {"proc-onboarding": "error_rate", "exec-a": "direct_reports",
           "dept-support": "turnover"}


def _with_case(cause, subject="dept-support", indicator="turnover"):
    session = _org()
    with api.as_of(AT):
        case_id = api.open_case(session, subject, indicator,
                                basis="over its bound").to_dict()["case"]["case_id"]
        api.attach_stage(session, case_id, "hypothesize",
                         api.hypothesize(session, subject))
    with api.as_of(AT + timedelta(minutes=5)):
        api.attach_stage(session, case_id, "confirm", reference={
            "cause": cause, "reading": f"{cause}.{READING[cause]}",
            "basis": "the operations lead, from the onboarding review"})
    return session, case_id


class TestAConfirmationOutsideTheGraph:

    def test_it_is_located_between_the_cause_and_the_subject(self):
        session, case_id = _with_case("proc-onboarding")
        [row] = _walked(session, "confirmed_outside_graph")
        assert row["between"] == ["proc-onboarding", "dept-support"]
        assert row["basis"] == "the operations lead, from the onboarding review"
        assert (row["case_id"], row["indicator"]) == (case_id, "turnover")
        assert _residuals(session)["checked"]["confirmations_read"] == 1

    def test_a_declared_ancestor_is_not(self):
        session, _ = _with_case("exec-a", subject="dept-sales")
        assert _residuals(session)["checked"]["confirmations_read"] == 1
        assert not _walked(session, "confirmed_outside_graph")

    def test_the_subject_named_as_its_own_cause_is_not(self):
        session, _ = _with_case("dept-support")
        assert _residuals(session)["checked"]["confirmations_read"] == 1
        assert not _walked(session, "confirmed_outside_graph")


class TestOneWalkTwoVerbs:

    def test_the_arm_reads_the_walk_hypothesize_takes(self):
        session = _org(ops_margin=15.0)
        with api.as_of(AT):
            findings = api.check(session).to_dict()["findings"]
            for unit in {finding["entity_id"] for finding in findings}:
                told = api.hypothesize(session, unit).to_dict()["hypothesis"]["walk"]
                read = walk_up(session, unit, check=api.check)["walk"]
                assert read["state"] == told["state"], unit
                assert ({row["entity"] for row in read["frontier"]}
                        == {row["entity"] for row in told["frontier"]}), unit
                assert ({row["entity"] for row in read["open"]}
                        == {row["entity"] for row in told["open"]}), unit

    def test_gaps_files_nothing_where_hypothesize_would(self):
        """With strengths declared every candidate has a posterior, and
        `hypothesize` files each one; `gaps` walks the same finding and files
        nothing."""
        model = _fan_model()
        model["domain"]["relationship_rules"][0]["causal"] = {"weight": 0.8, "leak": 0.01}
        model["domain"]["causal"] = {"root_prior": 0.05}
        session = _session(model, [("fan-1", "Fan", {}), ("zone-1", "Zone", {"temp": 60.0})],
                           [("fan-1", "cools", "zone-1")])
        before = len(session.ledger.records())
        _residuals(session)
        assert len(session.ledger.records()) == before
        with api.as_of(AT):
            api.hypothesize(session, "zone-1")
        assert len(session.ledger.records()) > before, "the control filed nothing"


class TestTheArmRefusesByName:

    def test_a_model_with_no_causal_rule_is_missing_config(self):
        model = _org_model()
        for rule in model["domain"]["relationship_rules"]:
            rule.pop("edge_direction")
        session = _session(model, [("dept-a", "Department", {"turnover": 30.0})], [])
        residuals = _residuals(session)
        assert ("missing_config", "walk") in _declined(residuals)
        assert not _walked(session)
        assert residuals["checked"]["walks_read"] == 0

    def test_before_any_check_it_is_precondition_unmet(self):
        session = _session(_org_model(), [("dept-a", "Department", {"turnover": 30.0})],
                           [], checked=False)
        assert ("precondition_unmet", "walk") in _declined(_residuals(session))

    def test_every_reason_is_a_discovery_name(self):
        for session in (_org(), _fan(),
                        _session(_org_model(), [("dept-a", "Department",
                                                 {"turnover": 30.0})], [],
                                 checked=False)):
            reasons = {d["reason"] for d in _residuals(session)["not_checked"]}
            assert reasons <= VOCABULARIES["discovery"], reasons

    def test_every_row_says_what_would_settle_it_or_why_nothing_does(self):
        rows = (_walked(_org(ops_margin=15.0)) + _walked(_fan(vents=True))
                + _walked(_with_case("proc-onboarding")[0]))
        assert {row["kind"] for row in rows} == KINDS
        for row in rows:
            assert row["evidence_needed"] is not None or row.get("reason"), row
