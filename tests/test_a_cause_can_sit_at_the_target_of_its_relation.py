"""A rule names the end of its relation where a failure starts: `cause: target`.

ruling 4 -- a process depends on a department, and a failure runs from the
department to the process: against the edge the author feeds. The engine read a
causal rule as the direction of its edge, so `depends_on` could be declared only
the wrong way round. Measured on what users installed (engine 0.2.31), on
operating-health-audit's shipped capture: declared `edge_direction: causal`, the
process became the department's cause, and `proc-sales-cycle` joined the sales
department's frontier. A key for the cause at the target, under any spelling, was
named `unknown_key` and moved nothing.

The ruling: one rule-level key, `cause`, `source` or `target`. It stands alone.
Beside `edge_direction: causal`, which names the source, `cause: target`
contradicts it, so neither applies and the pair is named -- an engine before the
key reads only `edge_direction` and would walk the rule backwards, while a rule
carrying `cause:` alone reads there as no causal direction at all.
"""

from __future__ import annotations

from datetime import datetime

from arbiter_engine import api
from arbiter_engine.inference.causal import cause_end

AT = datetime(2026, 10, 2, 12, 0)


def _org_model(depends_on=None):
    """The shape of operating-health-audit's model: `leads` and `reports_to`
    causal, `depends_on` a relation and, with `depends_on`, a rule for it."""
    rules = [
        {"type": "leads", "source_type": "Executive", "target_type": "Department",
         "edge_direction": "causal"},
        {"type": "reports_to", "source_type": "Department", "target_type": "Division",
         "edge_direction": "causal"}]
    if depends_on is not None:
        rules.append(dict({"type": "depends_on", "source_type": "Process",
                           "target_type": "Department"}, **depends_on))
    return {"domain": {
        "id": "cause_end", "name": "cause end",
        "entity_types": ["Executive", "Department", "Division", "Process"],
        "relationship_types": ["leads", "reports_to", "depends_on"],
        "indicators": {
            "Executive": [{"name": "direct_reports", "type": "NUMERIC",
                           "axioms": ["BOUNDEDNESS"], "critical": 20}],
            "Department": [{"name": "turnover", "type": "NUMERIC",
                            "axioms": ["BOUNDEDNESS"], "critical": 20}],
            "Division": [{"name": "margin_drop", "type": "NUMERIC",
                          "axioms": ["BOUNDEDNESS"], "critical": 10}],
            "Process": [{"name": "error_rate", "type": "NUMERIC",
                         "axioms": ["BOUNDEDNESS"], "critical": 10}]},
        "relationship_rules": rules}}


def _org(depends_on=None, *, lone_process=False):
    """`dept-sales` led by an executive over its bound; `dept-support` led by
    nobody; each with a process depending on it, both over their bounds.
    `lone_process` adds a process over its bound that depends on nothing."""
    session = api.EngineSession()
    session.load_model(_org_model(depends_on))
    entities = [
        ("exec-cro", "Executive", {"direct_reports": 22.0}),
        ("dept-sales", "Department", {"turnover": 28.0}),
        ("dept-support", "Department", {"turnover": 31.0}),
        ("div-commercial", "Division", {"margin_drop": 12.0}),
        ("proc-sales", "Process", {"error_rate": 11.0}),
        ("proc-onboarding", "Process", {"error_rate": 12.0})]
    if lone_process:
        entities.append(("proc-lone", "Process", {"error_rate": 14.0}))
    for entity_id, entity_type, properties in entities:
        session.add_entity(entity_id, entity_type, properties)
    for source, relation, target in (
            ("exec-cro", "leads", "dept-sales"),
            ("dept-sales", "reports_to", "div-commercial"),
            ("proc-sales", "depends_on", "dept-sales"),
            ("proc-onboarding", "depends_on", "dept-support")):
        session.add_relationship(source, relation, target)
    with api.as_of(AT):
        api.check(session)
    return session


def _walk(session, unit):
    with api.as_of(AT):
        return api.hypothesize(session, unit).to_dict()["hypothesis"]


def _residuals(session):
    with api.as_of(AT):
        return api.gaps(session).to_dict()["residuals"]


def _described(session):
    with api.as_of(AT):
        payload = api.model_describe(session).to_dict()
    return payload.get("model") or payload


def _rows_on(described, field):
    return [row for row in described.get("unread_fields") or [] if row.get("field") == field]


class TestTheKey:

    def test_the_four_ways_a_rule_can_say_it(self):
        assert cause_end({"edge_direction": "causal"}) == "source"
        assert cause_end({"cause": "target"}) == "target"
        assert cause_end({"cause": "source"}) == "source"
        assert cause_end({"edge_direction": "flow"}) is None

    def test_the_pair_that_contradicts_itself_applies_neither(self):
        assert cause_end({"edge_direction": "causal", "cause": "target"}) is None
        assert cause_end({"edge_direction": "causal", "cause": "source"}) == "source"

    def test_a_value_that_is_not_an_end_is_not_applied(self):
        assert cause_end({"cause": "sideways"}) is None
        assert cause_end({"edge_direction": "causal", "cause": "sideways"}) == "source"


class TestTheLoaderNamesWhatItDidNotApply:

    def test_the_key_alone_is_read(self):
        described = _described(_org({"cause": "target"}))
        assert _rows_on(described, "cause") == []
        assert ("Process-depends_on->Department", "target") in [
            (row["rule"], row["cause"]) for row in described["causal"]["declared"]]

    def test_beside_edge_direction_causal_it_is_refused_by_name(self):
        described = _described(_org({"cause": "target", "edge_direction": "causal"}))
        [row] = _rows_on(described, "cause")
        assert (row["reason"], row["value"], row["rule"]) == (
            "malformed_value", "target", "Process-depends_on->Department")
        assert "neither was applied" in row["remedy"]
        assert "Process-depends_on->Department" not in [
            row["rule"] for row in described["causal"]["declared"]]

    def test_another_value_is_named_and_not_applied(self):
        described = _described(_org({"cause": "sideways"}))
        [row] = _rows_on(described, "cause")
        assert (row["reason"], row["value"]) == ("unknown_value", "sideways")

    def test_a_process_is_findable_once_a_channel_enters_it(self):
        assert "Process" in _described(_org())["causal"]["types_without_cause"]
        causal = _described(_org({"cause": "target"}))["causal"]
        assert "Process" not in causal["types_without_cause"]
        assert causal["findable_types"]["Process"] == ["Process-depends_on->Department"]

    def test_hypothesize_is_declared_by_the_key_alone(self):
        model = _org_model({"cause": "target"})
        for rule in model["domain"]["relationship_rules"][:2]:
            rule.pop("edge_direction")
        session = api.EngineSession()
        session.load_model(model)
        with api.as_of(AT):
            stages = api.model_describe(session).to_dict()
        stages = (stages.get("model") or stages)["stages"]
        assert stages["hypothesize"]["declared"] is True


class TestTheWalkRunsFromTheEndTheRuleNames:

    def test_the_process_walks_to_its_department(self):
        walk = _walk(_org({"cause": "target"}), "proc-onboarding")
        assert [c["cause"] for c in walk["candidates"]] == ["dept-support"]
        assert [row["entity"] for row in walk["walk"]["frontier"]] == ["dept-support"]

    def test_the_department_is_not_walked_to_its_process(self):
        walk = _walk(_org({"cause": "target"}), "dept-sales")
        assert [c["cause"] for c in walk["candidates"]] == ["exec-cro"]

    def test_the_source_end_walks_the_other_way(self):
        """`cause: source` says what `edge_direction: causal` says: the process
        is the department's cause, and its own walk is cut."""
        session = _org({"cause": "source"})
        assert [c["cause"] for c in _walk(session, "dept-support")["candidates"]] == [
            "proc-onboarding"]
        assert _walk(session, "proc-onboarding")["walk"]["state"] == "cut"

    def test_the_refused_pair_walks_neither_way(self):
        session = _org({"cause": "target", "edge_direction": "causal"})
        assert _walk(session, "proc-onboarding")["walk"]["state"] == "cut"
        assert [c["cause"] for c in _walk(session, "dept-support")["candidates"]] == []


class TestWhereTheDeclarationEnds:

    def test_the_department_nobody_leads_is_where_the_process_walk_stops(self):
        rows = [row for row in _residuals(_org({"cause": "target"}))["hypotheses"]
                if row["kind"] == "no_cause_connected"]
        assert [(row["at"], row["relation"], row["subjects"]) for row in rows] == [
            ("dept-support", "leads", ["dept-support", "proc-onboarding"])]

    def test_a_declared_relation_is_no_longer_an_undeclared_channel(self):
        before = _residuals(_org())
        assert before["checked"]["undeclared_channels"]["depends_on"]["instances"] == 2
        after = _residuals(_org({"cause": "target"}))
        assert after["checked"]["undeclared_channels"] == {}
        assert not [row for row in after["hypotheses"] if row["kind"] == "undeclared_channel"]

    def test_a_process_that_depends_on_nothing_has_no_cause_connected(self):
        """With the cause at the target, the cause arrives on an edge OUT of the
        process: one with none is located, and one with its edge is not."""
        rows = [row for row in _residuals(_org({"cause": "target"}, lone_process=True))[
            "hypotheses"] if row["kind"] == "no_cause_connected"]
        assert ("proc-lone", "depends_on", "proc-lone.depends_on") in [
            (row["at"], row["relation"], row["evidence_needed"]) for row in rows]
        assert not [row for row in rows if row["at"] in ("proc-sales", "proc-onboarding")]

    def test_the_channel_reason_names_the_key(self):
        [row, *_] = [row for row in _residuals(_org())["hypotheses"]
                     if row["kind"] == "undeclared_channel"]
        assert "`cause: source` or `cause: target`" in row["reason"]
        assert "no reading settles it" in row["reason"]
