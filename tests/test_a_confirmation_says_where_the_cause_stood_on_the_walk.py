"""A case keeps the walk, and a confirmation is read back against it.

measured on what users installed (engine 0.2.30): a `hypothesize`
attachment kept each cause and its posterior, the reading named and the order,
and nothing of the walk. A confirmed row said the cause's rank and not where it
stood, so on bmc-sensor-audit's Mt. Jade board, after sixteen cycles, the fan
the walk had read sound and screened was confirmed and read "rank 1 of 1",
counted in `ranked_first`: the walk's own surprise, counted as a success.
Nothing counted a case reopened after a resolution, and the `gaps` attachment
dropped the relation and reason step 3 had added.

The attachment now keeps each cause's standing, state and needs, the walk's
state and frontier, and the declared causes past the bound by name. A row reads
the cause's standing on the last walk before the confirmation -- or
`beyond_bound`, or `not_connected` -- with that walk's state, the
confirmation's basis and how many walks came before, all from the record: both
verticals confirm on a session holding the ledger and nothing else.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from arbiter_engine import api
from arbiter_engine.residual.cases import Case, confirmed_causes
from arbiter_engine.residual.sqlite_ledger import SqlitePredictionLedger

AT = datetime(2026, 9, 15)
BOARD = {"severity": "warning", "consecutive_checks": 2}


def _session(model, entities, edges, *, ledger=None):
    session = api.EngineSession(ledger=ledger) if ledger is not None else api.EngineSession()
    session.load_model(model)
    for entity_id, entity_type, properties in entities:
        session.add_entity(entity_id, entity_type, properties)
    for source, relation, target in edges:
        session.add_relationship(source, relation, target)
    return session


def _open(session, entity_id, indicator, minutes=0):
    with api.as_of(AT + timedelta(minutes=minutes)):
        api.check(session)
        return api.open_case(session, entity_id, indicator,
                             basis="over its bound").to_dict()["case"]["case_id"]


def _rank(session, case_id, subject, minutes):
    with api.as_of(AT + timedelta(minutes=minutes)):
        api.check(session)
        ranking = api.hypothesize(session, subject)
        api.attach_stage(session, case_id, "hypothesize", ranking)
    return ranking.to_dict()["hypothesis"]


def _confirm(session, case_id, cause, minutes, basis="the review board"):
    reference = {"cause": cause, "reading": f"{cause}.reading"}
    if basis is not None:
        reference["basis"] = basis
    with api.as_of(AT + timedelta(minutes=minutes)):
        api.attach_stage(session, case_id, "confirm", reference=reference)


def _book(session):
    return api.case_book(session).to_dict()["cases"]


def _row(session, cause):
    [row] = [row for row in _book(session)["confirmed"]["rows"] if row["cause"] == cause]
    return row


def _org_model():
    """The shape of operating-health-audit's model: `leads` and `reports_to`
    causal, `depends_on` declared as a relation and nothing more."""
    return {"domain": {
        "id": "record_org", "name": "record org",
        "entity_types": ["Executive", "Department", "Division", "Process"],
        "relationship_types": ["leads", "reports_to", "depends_on"],
        "cases": BOARD,
        "indicators": {
            "Executive": [{"name": "direct_reports", "type": "NUMERIC",
                           "axioms": ["BOUNDEDNESS"], "warning": 15, "critical": 20}],
            "Department": [{"name": "turnover", "type": "NUMERIC",
                            "axioms": ["BOUNDEDNESS"], "critical": 20}],
            "Division": [{"name": "margin_drop", "type": "NUMERIC",
                          "axioms": ["BOUNDEDNESS"], "critical": 10}],
            "Process": [{"name": "error_rate", "type": "NUMERIC",
                         "axioms": ["BOUNDEDNESS"], "critical": 10}]},
        "relationship_rules": [
            {"type": "leads", "source_type": "Executive", "target_type": "Department",
             "edge_direction": "causal"},
            {"type": "reports_to", "source_type": "Department",
             "target_type": "Division", "edge_direction": "causal"}]}}


def _org(ledger=None):
    """`dept-sales` led by two executives over their bounds, `dept-support`
    led by nobody, and a process depending on it along a relation no rule
    gives a causal direction."""
    return _session(_org_model(), [
        ("exec-cro", "Executive", {"direct_reports": 22.0}),
        ("exec-vp-sales", "Executive", {"direct_reports": 18.0}),
        ("dept-sales", "Department", {"turnover": 28.0}),
        ("dept-support", "Department", {"turnover": 31.0}),
        ("proc-onboarding", "Process", {"error_rate": 12.0})],
        [("exec-cro", "leads", "dept-sales"), ("exec-vp-sales", "leads", "dept-sales"),
         ("proc-onboarding", "depends_on", "dept-support")], ledger=ledger)


def _fan_model():
    """A fan cooling a zone: the Mt. Jade board's one candidate."""
    return {"domain": {
        "id": "record_fan", "name": "record fan",
        "entity_types": ["Fan", "Zone"], "relationship_types": ["cools"],
        "cases": BOARD,
        "indicators": {
            "Fan": [{"name": "rpm", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
                     "critical": 23100}],
            "Zone": [{"name": "temp", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
                      "critical": 50}]},
        "relationship_rules": [{"type": "cools", "source_type": "Fan",
                                "target_type": "Zone", "edge_direction": "causal"}]}}


def _fan():
    """The fan unread, so the walk's one candidate is open."""
    return _session(_fan_model(), [("fan-1", "Fan", {}), ("zone-1", "Zone", {"temp": 60.0})],
                    [("fan-1", "cools", "zone-1")])


def _fan_read_sound(session):
    session.add_entity("fan-1", "Fan", {"rpm": 3000.0})


class TestTheAttachmentKeepsTheWalk:

    def test_each_cause_keeps_its_standing_state_and_needs(self):
        session = _org()
        case_id = _open(session, "dept-sales", "turnover")
        _rank(session, case_id, "dept-sales", 1)
        kept = session.ledger.case_book.get(case_id).stages["hypothesize"][-1]["reference"]
        assert kept["causes"] == [
            {"cause": "exec-cro", "posterior": None, "standing": "frontier",
             "state": "faulty", "needs": []},
            {"cause": "exec-vp-sales", "posterior": None, "standing": "frontier",
             "state": "deviating", "needs": []}]

    def test_the_walk_keeps_its_state_and_frontier(self):
        session = _org()
        case_id = _open(session, "dept-sales", "turnover")
        _rank(session, case_id, "dept-sales", 1)
        kept = session.ledger.case_book.get(case_id).stages["hypothesize"][-1]["reference"]
        assert kept["walk"] == {"state": "traced", "frontier": [
            {"entity": "exec-cro", "findings": ["threshold_exceeded:direct_reports"]},
            {"entity": "exec-vp-sales", "findings": ["threshold_warning:direct_reports"]}]}
        assert (kept["ranked_by"], kept["beyond_bound"], kept["reported"]) == (
            "standing", [], None)

    def test_an_open_cause_keeps_the_readings_its_check_could_not_take(self):
        session = _fan()
        case_id = _open(session, "zone-1", "temp")
        _rank(session, case_id, "zone-1", 1)
        [cause] = session.ledger.case_book.get(case_id).stages["hypothesize"][-1][
            "reference"]["causes"]
        assert (cause["standing"], cause["state"]) == ("open", "unread")
        assert [need["reading"] for need in cause["needs"]] == ["fan-1.rpm"]

    def test_the_gaps_attachment_keeps_relation_and_reason(self):
        session = _org()
        case_id = _open(session, "dept-support", "turnover")
        with api.as_of(AT):
            api.attach_stage(session, case_id, "gaps", api.gaps(session))
        kept = session.ledger.case_book.get(case_id).stages["gaps"][-1]["reference"]
        [channel] = [h for h in kept["hypotheses"] if h["kind"] == "undeclared_channel"]
        assert channel["relation"] == "depends_on"
        assert "causal direction" in channel["reason"]
        [unconnected] = [h for h in kept["hypotheses"] if h["kind"] == "no_cause_connected"]
        assert (unconnected["relation"], "reason" in unconnected) == ("leads", False)


def _chain(max_hops):
    """Three hops of `feeds` down to a basin, and a pump nothing connects."""
    model = {"domain": {
        "id": "record_chain", "name": "record chain",
        "entity_types": ["Unit"], "relationship_types": ["feeds"],
        "cases": BOARD, "causal": {"max_hops": max_hops},
        "indicators": {"Unit": [{"name": "level", "type": "NUMERIC",
                                 "axioms": ["BOUNDEDNESS"], "critical": 50}]},
        "relationship_rules": [{"type": "feeds", "source_type": "Unit",
                                "target_type": "Unit", "edge_direction": "causal"}]}}
    return _session(model, [(unit, "Unit", {"level": 60.0})
                            for unit in ("u-a", "u-b", "u-c", "u-d", "u-lone")],
                    [("u-a", "feeds", "u-b"), ("u-b", "feeds", "u-c"),
                     ("u-c", "feeds", "u-d")])


class TestOutOfReach:

    def test_the_leg_names_the_causes_past_the_bound_beside_their_count(self):
        session = _chain(max_hops=1)
        with api.as_of(AT):
            api.check(session)
            leg = api.hypothesize(session, "u-d").to_dict()["hypothesis"]
        assert [c["cause"] for c in leg["candidates"]] == ["u-c"]
        assert leg["beyond_bound"] == ["u-a", "u-b"]
        assert leg["checked"]["beyond_bound"] == 2

    def test_nothing_past_the_bound_is_an_empty_list(self):
        session = _chain(max_hops=3)
        with api.as_of(AT):
            api.check(session)
            leg = api.hypothesize(session, "u-d").to_dict()["hypothesis"]
        assert leg["beyond_bound"] == []
        assert "beyond_bound" not in leg["checked"]

    def test_a_declared_cause_past_the_bound_is_not_a_cause_nothing_connects(self):
        session = _chain(max_hops=1)
        case_id = _open(session, "u-d", "level")
        _rank(session, case_id, "u-d", 1)
        _confirm(session, case_id, "u-a", 2)
        _confirm(session, case_id, "u-lone", 3)
        assert _row(session, "u-a")["standing"] == "beyond_bound"
        assert _row(session, "u-lone")["standing"] == "not_connected"
        by_standing = _book(session)["confirmed"]["by_standing"]
        assert (by_standing["beyond_bound"], by_standing["not_connected"]) == (1, 1)


class TestTheShippedShape:

    def test_the_cause_confirmed_on_dept_sales_stood_on_the_frontier(self):
        session = _org()
        case_id = _open(session, "dept-sales", "turnover")
        _rank(session, case_id, "dept-sales", 1)
        _confirm(session, case_id, "exec-cro", 5)
        row = _row(session, "exec-cro")
        assert {key: row[key] for key in ("rank", "of", "standing", "walk_state",
                                          "basis", "walks_before")} == {
            "rank": 1, "of": 2, "standing": "frontier", "walk_state": "traced",
            "basis": "the review board", "walks_before": 1}

    def test_a_process_confirmed_on_a_department_nobody_leads_is_not_connected(self):
        session = _org()
        case_id = _open(session, "dept-support", "turnover")
        _rank(session, case_id, "dept-support", 1)
        _confirm(session, case_id, "proc-onboarding", 5)
        row = _row(session, "proc-onboarding")
        assert (row["standing"], row["walk_state"], row["rank"]) == (
            "not_connected", "cut", None)

    def test_a_session_holding_only_the_ledger_reads_the_same_row(self, tmp_path):
        path = str(tmp_path / "book.sqlite")
        session = _org(ledger=SqlitePredictionLedger(path))
        case_id = _open(session, "dept-sales", "turnover")
        _rank(session, case_id, "dept-sales", 1)
        bare = api.EngineSession(ledger=SqlitePredictionLedger(path))
        assert bare.model is None and not bare.entities
        _confirm(bare, case_id, "exec-cro", 5)
        row = _row(bare, "exec-cro")
        assert (row["standing"], row["walk_state"], row["walks_before"]) == (
            "frontier", "traced", 1)

    def test_a_confirmation_with_no_basis_says_none(self):
        session = _org()
        case_id = _open(session, "dept-sales", "turnover")
        _rank(session, case_id, "dept-sales", 1)
        _confirm(session, case_id, "exec-cro", 5, basis=None)
        assert _row(session, "exec-cro")["basis"] is None


class TestAScreenedCauseConfirmed:

    def test_a_cause_confirmed_while_open_is_counted_open(self):
        session = _fan()
        case_id = _open(session, "zone-1", "temp")
        _rank(session, case_id, "zone-1", 1)
        _confirm(session, case_id, "fan-1", 2)
        book = _book(session)["confirmed"]
        assert (book["rows"][0]["standing"], book["rows"][0]["walk_state"]) == (
            "open", "open")
        assert (book["by_standing"]["open"], book["confirmed_after_screened"]) == (1, 0)

    def test_a_cause_the_walk_screened_is_the_walks_own_surprise(self):
        session = _fan()
        case_id = _open(session, "zone-1", "temp")
        _rank(session, case_id, "zone-1", 1)
        _fan_read_sound(session)
        _rank(session, case_id, "zone-1", 2)
        _confirm(session, case_id, "fan-1", 3)
        book = _book(session)["confirmed"]
        row = book["rows"][0]
        assert (row["standing"], row["walk_state"], row["walks_before"]) == (
            "screened", "unexplained", 2)
        assert book["confirmed_after_screened"] == 1
        assert book["by_standing"]["screened"] == 1
        # `ranked_first` keeps its meaning: the one candidate is ranked first.
        assert (row["rank"], row["of"], book["ranked_first"]) == (1, 1, 1)

    def test_the_last_walk_before_the_confirmation_is_the_one_read(self):
        session = _fan()
        case_id = _open(session, "zone-1", "temp")
        _rank(session, case_id, "zone-1", 1)
        _confirm(session, case_id, "fan-1", 2)
        _fan_read_sound(session)
        _rank(session, case_id, "zone-1", 3)
        rows = _book(session)["confirmed"]["rows"]
        assert [(row["standing"], row["walks_before"]) for row in rows] == [("open", 1)]
        _confirm(session, case_id, "fan-1", 4)
        rows = _book(session)["confirmed"]["rows"]
        assert [(row["standing"], row["walks_before"]) for row in rows] == [
            ("open", 1), ("screened", 2)]
        assert _book(session)["confirmed"]["confirmed_after_screened"] == 1

    def test_a_confirmation_before_any_walk_has_no_standing(self):
        session = _fan()
        case_id = _open(session, "zone-1", "temp")
        _confirm(session, case_id, "fan-1", 1)
        row = _book(session)["confirmed"]["rows"][0]
        assert (row["standing"], row["walk_state"], row["walks_before"]) == (None, None, 0)

    def test_a_stage_that_could_not_run_is_not_a_walk(self):
        session = _fan()
        case_id = _open(session, "zone-1", "temp")
        _rank(session, case_id, "zone-1", 1)
        with api.as_of(AT + timedelta(minutes=2)):
            api.attach_stage(session, case_id, "hypothesize",
                             api.hypothesize(api.EngineSession(), "zone-1"))
        _confirm(session, case_id, "fan-1", 3)
        row = _book(session)["confirmed"]["rows"][0]
        # The last stage before the confirmation took no walk, as it took no rank.
        assert (row["standing"], row["rank"], row["walks_before"]) == (None, None, 1)


def _kept_case(reference, *, cause):
    """A case holding one ranking as `reference`, then one confirmation."""
    case = Case(case_id="c-1", entity_id="unit-z", indicator="load",
                opened_at="2026-10-01T12:00:00", basis="a test",
                severity="warning", consecutive_checks=2)
    case.stages["hypothesize"].append({"at": "2026-10-01T12:01:00", "reference": reference})
    case.stages["confirm"].append({"at": "2026-10-01T12:05:00",
                                   "reference": {"cause": cause}})
    return case


class TestAnOlderRanking:

    OLD = {"causes": [{"cause": "unit-a", "posterior": None},
                      {"cause": "unit-b", "posterior": None}],
           "most_discriminating": None, "ranked_by": "standing"}

    def test_a_ranking_that_kept_no_walk_gives_no_standing(self):
        book = confirmed_causes([_kept_case(dict(self.OLD), cause="unit-a")])
        row = book["rows"][0]
        assert (row["standing"], row["walk_state"]) == (None, None)
        assert (row["rank"], row["of"], row["ranked_by"], row["walks_before"]) == (
            1, 2, "standing", 1)
        assert set(book["by_standing"].values()) == {0}
        assert book["confirmed_after_screened"] == 0
        assert book["ranked_first"] == 1

    def test_a_cause_the_old_ranking_did_not_hold_is_not_called_not_connected(self):
        row = confirmed_causes([_kept_case(dict(self.OLD), cause="unit-q")])["rows"][0]
        assert (row["rank"], row["standing"]) == (None, None)

    def test_a_ranking_cut_by_report_above_does_not_say_what_it_left_out(self):
        kept = {"causes": [{"cause": "unit-a", "posterior": 0.9, "standing": "trail"}],
                "most_discriminating": None, "ranked_by": "posterior",
                "walk": {"state": "partly_traced", "frontier": []},
                "beyond_bound": [], "reported": 1}
        assert confirmed_causes([_kept_case(kept, cause="unit-a")])[
            "rows"][0]["standing"] == "trail"
        assert confirmed_causes([_kept_case(kept, cause="unit-b")])[
            "rows"][0]["standing"] is None


def _tank():
    """Two tanks, each over its level bound, each with a temperature too."""
    model = {"domain": {
        "id": "record_tank", "name": "record tank", "entity_types": ["Tank"],
        "cases": BOARD,
        "indicators": {"Tank": [
            {"name": "level", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"], "critical": 95},
            {"name": "temp", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"], "critical": 80}]}}}
    return _session(model, [(tank, "Tank", {"level": 99.0, "temp": 20.0})
                            for tank in ("t-1", "t-2")], [])


def _set(session, minutes, tank="t-1", **readings):
    session.add_entity(tank, "Tank", dict({"level": 99.0, "temp": 20.0}, **readings))
    with api.as_of(AT + timedelta(minutes=minutes)):
        api.check(session)


class TestReopenings:

    def _resolved_then_back(self):
        session = _tank()
        first = _open(session, "t-1", "level")
        _set(session, 10, level=50.0)
        _set(session, 20, level=50.0)
        assert session.ledger.case_book.get(first).status == "resolved"
        _set(session, 30)
        return session

    def test_a_case_opened_after_its_problem_resolved_is_a_reopening(self):
        session = self._resolved_then_back()
        _open(session, "t-1", "level", minutes=31)
        book = _book(session)
        assert {key: book[key] for key in ("opened", "resolved", "open", "reopened")} == {
            "opened": 2, "resolved": 1, "open": 1, "reopened": 1}

    def test_a_case_on_another_indicator_is_a_new_problem(self):
        session = self._resolved_then_back()
        _set(session, 31, temp=90.0)
        _open(session, "t-1", "temp", minutes=32)
        assert _book(session)["reopened"] == 0

    def test_a_case_on_another_entity_is_a_new_problem(self):
        session = self._resolved_then_back()
        _open(session, "t-2", "level", minutes=31)
        assert _book(session)["reopened"] == 0

    def test_a_second_case_while_the_first_is_open_is_not_a_reopening(self):
        session = _tank()
        _open(session, "t-1", "level")
        _open(session, "t-1", "level", minutes=1)
        assert _book(session)["reopened"] == 0

    def test_each_case_counts_once_however_many_resolved_before_it(self):
        session = self._resolved_then_back()
        second = _open(session, "t-1", "level", minutes=31)
        _set(session, 40, level=50.0)
        _set(session, 50, level=50.0)
        assert session.ledger.case_book.get(second).status == "resolved"
        _set(session, 60)
        _open(session, "t-1", "level", minutes=61)
        assert _book(session)["reopened"] == 2
