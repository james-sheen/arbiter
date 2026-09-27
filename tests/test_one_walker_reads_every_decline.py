"""One walker for every decline an envelope carries, published beside the names.

Two verticals each copied a walker over the lists a decline is reported under
into their own loop tests, and the copies drifted: one read four lists and the
other two, so a refusal under `not_fitted` passed its published-name check
without being read. The walker now ships beside the vocabularies it checks
against, and these tests hold it to every list the engine reports a decline
under -- including one a later release adds.
"""

from __future__ import annotations

import ast
import copy
import json
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from arbiter_engine import api, subenvelope
from arbiter_engine.subenvelope import (
    DECLINE_KEYS, PUBLISHED_REASONS, VOCABULARIES, declined_reasons,
    unpublished_reasons)
from arbiter_engine.types import NotEvaluatedReason

PACKAGE = Path(subenvelope.__file__).resolve().parent


def _examples() -> Path:
    """The shipped examples, in whichever tree this file runs in: the package
    keeps them in `examples/`, the repository in `docs/publication`."""
    here = Path(__file__).resolve()
    for candidate in (here.parents[1] / "examples", here.parents[2] / "examples",
                      here.parents[2] / "docs" / "publication" / "engine-example"):
        if (candidate / "pump_tank_planning.yaml").is_file():
            return candidate
    raise AssertionError("no examples directory in this tree carries them")


EXAMPLES = _examples()
AT = datetime(2026, 9, 26, 12, 0)
CASES = {"severity": "warning", "consecutive_checks": 2}


def _two_list_copy(payload) -> list:
    """The copy one vertical carried: two of the four lists, and nothing else."""
    found = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("not_checked", "declines") and isinstance(value, list):
                    found.extend(item.get("reason") for item in value
                                 if isinstance(item, dict))
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return found


class TestTheIncident:

    def test_a_refusal_under_not_fitted_is_read(self):
        """The drift, as it was: an unpublished reason where the learn leg
        reports, which the two-list copy passes and this walker does not."""
        payload = {"model": {"proposed_transitions": {"not_fitted": [
            {"edge": "a->b", "reason": "a_name_nobody_published"}]}}}
        assert _two_list_copy(payload) == []
        assert declined_reasons(payload) == ["a_name_nobody_published"]
        assert unpublished_reasons(payload) == ["a_name_nobody_published"]


class TestEveryShapeIsRead:

    def test_records_and_flattened_reasons_at_any_depth(self):
        payload = {
            "not_checked": [{"axiom": "BOUNDEDNESS", "reason": "no_threshold"}],
            "hypothesis": {
                "not_checked": [{"reason": "cpt_missing", "query": "x"}],
                "candidates": [{"cause": "c", "declined": ["cpt_missing"]}]},
            "simulation": {"per_step": [{"declines": ["missing_dynamics"]}]},
            "case": {"stages": {"plan": [{"declined": ["no_objective"]}]}},
        }
        assert declined_reasons(payload) == [
            "no_threshold", "cpt_missing", "cpt_missing", "missing_dynamics",
            "no_objective"]
        assert unpublished_reasons(payload) == []

    def test_an_envelope_is_read_as_its_dict(self):
        session = api.EngineSession()
        session.load_model({"domain": {
            "id": "one", "name": "one unit", "entity_types": ["Unit"],
            "indicators": {"Unit": [{"name": "load", "type": "NUMERIC",
                                     "axioms": ["BOUNDEDNESS"]}]}}})
        session.add_entity("u-1", "Unit", {"load": 1.0})
        envelope = api.check(session)
        assert declined_reasons(envelope) == declined_reasons(envelope.to_dict())
        assert "no_threshold" in declined_reasons(envelope)

    def test_a_finding_is_not_a_decline(self):
        """A finding carries a `reason` too, and it is a sentence explaining
        the finding. Reading every record with a `reason` would count it."""
        payload = {"findings": [{"problem_type": "p", "reason": "why it fired"}]}
        assert declined_reasons(payload) == []


class TestThePublishedSet:

    def test_it_is_the_axiom_enum_and_every_discipline(self):
        expected = ({reason.value for reason in NotEvaluatedReason}
                    .union(*VOCABULARIES.values()))
        assert PUBLISHED_REASONS == expected

    def test_the_names_are_exported(self):
        for name in ("DECLINE_KEYS", "PUBLISHED_REASONS", "declined_reasons",
                     "unpublished_reasons"):
            assert name in subenvelope.__all__


# ---------------------------------------------------------------------------
# Every list the engine reports a decline under is one the walker reads.
# ---------------------------------------------------------------------------

def _pump_session():
    model = yaml.safe_load((EXAMPLES / "pump_tank_planning.yaml").read_text(
        encoding="utf-8"))
    model["domain"]["cases"] = dict(CASES)
    session = api.EngineSession()
    session.load_model(model)
    session.add_entity("pump1", "Pump", {"speed_rpm": 3000.0})
    session.add_entity("tank1", "Tank", {"level_pct": 50.0})
    session.add_entity("valve1", "Valve", {"open_pct": 0.0})
    session.add_relationship("pump1", "feeds", "tank1")
    session.add_relationship("valve1", "drains", "tank1")
    return session


def _feeder_session():
    model = yaml.safe_load((EXAMPLES / "substation_feeder.yaml").read_text(
        encoding="utf-8"))
    model["domain"]["cases"] = dict(CASES)
    session = api.EngineSession()
    session.load_model(model)
    for entity_id, kind, props in (
            ("sub-1", "Supply", {"voltage_kv": 11.0}),
            ("fdr-1", "Feeder", {"current_a": 300.0}),
            ("pnl-a", "Panel", {"voltage_v": 200.0}),
            ("pnl-b", "Panel", {"voltage_v": 201.0})):
        session.add_entity(entity_id, kind, props)
    session.add_relationship("sub-1", "powers", "fdr-1")
    session.add_relationship("fdr-1", "powers", "pnl-a")
    session.add_relationship("fdr-1", "powers", "pnl-b")
    return session


@pytest.fixture(scope="module")
def corpus():
    """What every verb answers on two shipped examples, decline paths
    included: the planning example for the simulation verbs and the learn leg,
    the causal example for the ranking and a case with a stage attached."""
    out = {}
    pump = _pump_session()
    for name, call in (
            ("describe", lambda: api.model_describe(pump)),
            ("check", lambda: api.check(pump)),
            ("gaps", lambda: api.gaps(pump)),
            ("project", lambda: api.project(pump)),
            ("rollout", lambda: api.rollout(pump, horizon_s=1800.0, step_s=300.0)),
            ("plan", lambda: api.plan(pump, horizon_s=1800.0, step_s=300.0)),
            ("entail", lambda: api.entail(pump)),
            ("discover", lambda: api.discover(pump)),
            ("infer", lambda: api.infer(pump, "tank1.level_pct")),
            ("hypothesize", lambda: api.hypothesize(pump, "tank1"))):
        out[f"pump/{name}"] = call().to_dict()
    with api.as_of(AT):
        out["pump/file_action"] = api.file_action(
            pump, {"template": "throttle_pump", "entity_id": "pump1",
                   "parameters": {"speed_rpm": 1500}},
            AT, "operator log", horizon_s=1800.0, step_s=300.0).to_dict()

    feeder = _feeder_session()
    api.check(feeder)
    ranking = api.hypothesize(feeder, "pnl-a")
    out["feeder/hypothesize"] = ranking.to_dict()
    case_id = api.open_case(feeder, "pnl-a", "voltage_v",
                            basis="panel low").to_dict()["case"]["case_id"]
    out["feeder/attach"] = api.attach_stage(
        feeder, case_id, "hypothesize", json.loads(json.dumps(ranking.to_dict()))
    ).to_dict()
    out["feeder/plan_attached"] = api.attach_stage(
        feeder, case_id, "plan", api.plan(feeder)).to_dict()
    # A stage that could not run at all: its verb answered an unavailable
    # envelope, with no leg for the stage and a sentence in `meta.reason`.
    out["feeder/unavailable_attached"] = api.attach_stage(
        feeder, case_id, "plan", api.plan(api.EngineSession())).to_dict()
    out["feeder/book"] = api.case_book(feeder).to_dict()
    return out


def _lists_of_records(node, found, where):
    """Every key whose value is a list holding a record with a text `reason`."""
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, list) and any(
                    isinstance(item, dict) and isinstance(item.get("reason"), str)
                    for item in value):
                found.setdefault(key, set()).add(where)
            _lists_of_records(value, found, where)
    elif isinstance(node, list):
        for item in node:
            _lists_of_records(item, found, where)


#: Keys whose records carry a `reason` that is not a decline. A finding's
#: `reason` is the sentence explaining why it fired.
NOT_DECLINES = {"findings"}


class TestNothingIsReportedWhereTheWalkerDoesNotLook:

    def test_every_list_of_reason_records_is_a_decline_key(self, corpus):
        found = {}
        for where, payload in corpus.items():
            _lists_of_records(payload, found, where)
        stray = {key: sorted(where) for key, where in found.items()
                 if key not in DECLINE_KEYS and key not in NOT_DECLINES}
        assert not stray, (
            f"records with a `reason` under keys the walker does not read: "
            f"{stray}; add the key to DECLINE_KEYS, or to NOT_DECLINES with why")

    def test_the_corpus_reaches_every_key_it_holds_the_walker_to(self, corpus):
        """Non-vacuity: each of the four keys actually carries a reason
        somewhere in what the verbs answered, so the check above is a check."""
        seen = set()

        def walk(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    if key in DECLINE_KEYS and isinstance(value, list) and value:
                        seen.add(key)
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        for payload in corpus.values():
            walk(payload)
        assert seen == set(DECLINE_KEYS), sorted(set(DECLINE_KEYS) - seen)

    def test_every_reason_the_verbs_gave_is_published(self, corpus):
        unpublished = {where: unpublished_reasons(payload)
                       for where, payload in corpus.items()
                       if unpublished_reasons(payload)}
        assert not unpublished, unpublished


#: Calls that pass a list of reasons through unchanged. `len` is not one: a
#: count of refusals is a number, and the key it is written under is a count.
_PASS_THROUGH = {"sorted", "list", "set", "tuple", "frozenset", "str"}


def _is_reason(expr) -> bool:
    """`d.reason`, `d.get("reason")`, or either passed through `str()` or an
    `or` with a fallback -- an expression whose value IS one reason."""
    if isinstance(expr, ast.Attribute):
        return expr.attr == "reason"
    if isinstance(expr, ast.BoolOp):
        return _is_reason(expr.values[0])
    if isinstance(expr, ast.Call):
        if (isinstance(expr.func, ast.Attribute) and expr.func.attr == "get"
                and expr.args and isinstance(expr.args[0], ast.Constant)):
            return expr.args[0].value == "reason"
        if isinstance(expr.func, ast.Name) and expr.func.id == "str" and expr.args:
            return _is_reason(expr.args[0])
    return False


def _is_reason_list(expr, reasoned) -> bool:
    """A list of refusals flattened to their names: a comprehension whose
    element is a reason, a literal of reasons, or a name built from either --
    through `sorted`, `list` and the like, never through a count."""
    if isinstance(expr, ast.Name):
        return expr.id in reasoned
    if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name):
        return (expr.func.id in _PASS_THROUGH and len(expr.args) == 1
                and _is_reason_list(expr.args[0], reasoned))
    if isinstance(expr, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
        return _is_reason(expr.elt)
    if isinstance(expr, (ast.List, ast.Tuple, ast.Set)):
        return bool(expr.elts) and all(_is_reason(e) for e in expr.elts)
    return False


def _is_record_list(expr) -> bool:
    """A list of records, each carrying its own `reason` key."""
    if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name):
        return (expr.func.id in _PASS_THROUGH and len(expr.args) == 1
                and _is_record_list(expr.args[0]))
    if isinstance(expr, (ast.ListComp, ast.GeneratorExp)) and isinstance(
            expr.elt, ast.Dict):
        return "reason" in {k.value for k in expr.elt.keys
                            if isinstance(k, ast.Constant)}
    return False


def _reasoned_names(function) -> set:
    """Names a function builds a list of reasons in, by assignment or by
    adding one reason at a time."""
    names = set()
    for _ in range(2):          # a name built from another built name
        for node in ast.walk(function):
            value = getattr(node, "value", None)
            targets = (node.targets if isinstance(node, ast.Assign) else
                       [node.target] if isinstance(node, ast.AnnAssign) else [])
            if value is not None and _is_reason_list(value, names):
                names |= {t.id for t in targets if isinstance(t, ast.Name)}
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("add", "append")
                    and isinstance(node.func.value, ast.Name)
                    and node.args and _is_reason(node.args[0])):
                names.add(node.func.value.id)
    return names


def _keys_reporting_reasons() -> dict:
    """Every key in the package's source that refusals are written under: a
    list of reasons, a name built from one, or a list of records each carrying
    its own `reason`."""
    found = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        if "tests" in path.parts or "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for function in [n for n in ast.walk(tree)
                         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            reasoned = _reasoned_names(function)
            for node in ast.walk(function):
                pairs = []
                if isinstance(node, ast.Dict):
                    pairs = [(k.value, v) for k, v in zip(node.keys, node.values)
                             if isinstance(k, ast.Constant) and isinstance(k.value, str)]
                elif isinstance(node, ast.Assign):
                    pairs = [(t.slice.value, node.value) for t in node.targets
                             if isinstance(t, ast.Subscript)
                             and isinstance(t.slice, ast.Constant)
                             and isinstance(t.slice.value, str)]
                for key, value in pairs:
                    if key != "reason" and (_is_reason_list(value, reasoned)
                                            or _is_record_list(value)):
                        found.setdefault(key, set()).add(
                            f"{path.relative_to(PACKAGE)}:{node.lineno}")
    return found


class TestTheSourceAgrees:

    def test_every_key_built_from_reasons_is_one_the_walker_reads(self):
        found = _keys_reporting_reasons()
        stray = {key: sorted(where) for key, where in found.items()
                 if key not in DECLINE_KEYS and key not in NOT_DECLINES}
        assert not stray, (
            f"the package writes refusals under keys the walker does not "
            f"read: {stray}")

    def test_the_scan_finds_the_keys_it_exists_to_find(self):
        """Non-vacuity for the scan: the flattened lists and the learn leg's
        records are all built in source, so the scan has to see them."""
        found = _keys_reporting_reasons()
        assert {"declines", "declined", "not_fitted"} <= set(found), sorted(found)
