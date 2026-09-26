"""`extends:`: a subtype declares only what it adds.

The factory example declares one cell's three stations as three types, and two
of their indicators -- the cycle time and the parts counter -- are written out
three times, identically. With `extends:` they are written once on `Station`,
each station keeps only what is its own, and the findings are the same finding
for finding. Where a subtype changes PART of an inherited band into a band that
contradicts itself, the model says `inheritance_conflict` rather than choosing a
side; a parent nobody declared and a cycle are refused at load.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml

from arbiter_engine import api
from arbiter_engine.ontology.domain_loader import (
    MalformedDomainModelError, load_domain)
from arbiter_engine.subenvelope import VOCABULARIES

AT = datetime(2026, 9, 26, 12, 0)
STATIONS = ("Station__ST_01", "Station__ST_02", "Station__ST_03")
SHARED = ("cycle_time_s", "parts_out")


def _example() -> dict:
    here = Path(__file__).resolve()
    for candidate in (here.parents[1] / "examples", here.parents[2] / "examples",
                      here.parents[2] / "docs" / "publication" / "engine-example"):
        if (candidate / "factory_line.yaml").is_file():
            return yaml.safe_load((candidate / "factory_line.yaml").read_text())
    raise AssertionError("no examples directory in this tree carries it")


def _rewritten(original: dict) -> dict:
    """The same cell, with the shared indicators declared once on `Station`."""
    model = copy.deepcopy(original)
    domain = model["domain"]
    indicators = domain["indicators"]
    parent = [copy.deepcopy(e) for e in indicators["Station__ST_01"]
              if e["name"] in SHARED]
    for station in STATIONS:
        own = []
        for entry in indicators[station]:
            inherited = next((p for p in parent if p["name"] == entry["name"]), None)
            if inherited is None:
                own.append(entry)
                continue
            extra = {k: v for k, v in entry.items() if inherited.get(k) != v}
            if extra:                       # ST_02 adds a consistency check
                own.append({"name": entry["name"], **extra})
        indicators[station] = own
    indicators["Station"] = parent
    domain["entity_types"] = [
        {"name": t, "extends": "Station"} if t in STATIONS else t
        for t in domain["entity_types"]] + ["Station"]
    return model


def _session(model: dict) -> api.EngineSession:
    """One cell, fed a morning that breaks something at every station."""
    session = api.EngineSession()
    session.load_model(model)
    with api.as_of(AT):
        session.add_entity("press", "Press__PR_01",
                           {"die_temp_c": 250.0, "tonnage_kn": 1500.0,
                            "stroke_count": 900.0})
        session.add_entity("st1", "Station__ST_01",
                           {"cycle_time_s": 71.0, "parts_out": 480.0,
                            "weld_current_a": 210.0})
        session.add_entity("st2", "Station__ST_02",
                           {"cycle_time_s": 61.0, "parts_in": 520.0,
                            "parts_out": 500.0, "parts_out_mes": 470.0,
                            "scrap_count": 12.0, "parts_in_per_interval": 10.0,
                            "parts_out_per_interval": 7.0,
                            "scrap_count_per_interval": 1.0})
        session.add_entity("st3", "Station__ST_03",
                           {"cycle_time_s": 58.0, "parts_out": 300.0,
                            "reject_pct": 4.0})
        for source, target in (("press", "st1"), ("st1", "st2"), ("st2", "st3")):
            session.add_relationship(source, "feeds", target)
        minutes = [AT - timedelta(minutes=59 - i) for i in range(60)]
        series = {
            ("st1", "cycle_time_s"): [60.0 + (i % 3) * 0.5 for i in range(50)]
                                     + [70.0 + i for i in range(10)],
            ("st1", "parts_out"): [float(i * 8) for i in range(55)]
                                  + [430.0, 440.0, 450.0, 460.0, 480.0],
            ("st2", "parts_out"): [float(i * 8) for i in range(60)],
            ("st2", "parts_out_mes"): [float(i * 7) for i in range(60)],
            ("st3", "parts_out"): [float(i * 5) for i in range(60)],
            ("st3", "cycle_time_s"): [58.0 + (i % 4) * 0.25 for i in range(60)],
        }
        for (entity_id, prop), values in series.items():
            session.add_observations(entity_id, prop, list(zip(minutes, values)))
    return session


def _outcome(model: dict):
    with api.as_of(AT):
        envelope = api.check(_session(model)).to_dict()
    findings = sorted((f["entity_id"], f.get("type") or f.get("problem_type"),
                       f.get("severity")) for f in envelope["findings"])
    declines = sorted((d.get("entity_id"), d.get("indicator"), d.get("axiom"),
                       d.get("reason")) for d in envelope["not_checked"])
    return findings, declines, envelope["checked"]["invariants"]


class TestDeclaredOnceTheSameFindings:

    def test_the_rewritten_cell_finds_exactly_what_the_original_does(self):
        original = _example()
        before, after = _outcome(original), _outcome(_rewritten(original))
        assert before[0], "the morning was meant to break something"
        assert before == after

    def test_the_rewrite_really_declares_them_once(self):
        rewritten = _rewritten(_example())["domain"]["indicators"]
        for station in STATIONS:
            assert "cycle_time_s" not in {e["name"] for e in rewritten[station]}
        assert [e for e in rewritten["Station__ST_02"] if e["name"] == "parts_out"] \
            == [{"name": "parts_out",
                 "consistency": {"agrees_with": ["parts_out_mes"], "tolerance": 0.01}}]

    def test_the_subtype_carries_the_parents_indicators_and_its_own(self):
        model = load_domain(_rewritten(_example()))
        names = [s.name for s in model.indicators["Station__ST_02"]]
        assert names[:2] == list(SHARED) and "parts_in" in names
        merged = next(s for s in model.indicators["Station__ST_02"] if s.name == "parts_out")
        assert merged.consistency_config and merged.monotonicity_config
        assert model.lineage("Station__ST_02") == ("Station__ST_02", "Station")
        assert model.extends["Station__ST_03"] == "Station"


def _conflicted():
    return {"domain": {
        "id": "c", "name": "c",
        "entity_types": ["Tank", {"name": "SmallTank", "extends": "Tank"}],
        "indicators": {
            "Tank": [{"name": "level", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
                      "warning": 80, "critical": 95}],
            "SmallTank": [{"name": "level", "warning": 97}],
        },
    }}


class TestAContradictionIsNamedNotResolved:

    def test_the_loader_records_it(self):
        conflict, = load_domain(_conflicted()).inheritance_conflicts
        assert (conflict["entity_type"], conflict["indicator"],
                conflict["extends"]) == ("SmallTank", "level", "Tank")

    def test_model_describe_lists_it_as_unreachable(self):
        session = api.EngineSession()
        session.load_model(_conflicted())
        rows = api.model_describe(session).to_dict()["model"]["unreachable_declarations"]
        assert {"entity_type": "SmallTank", "indicator": "level",
                "reason": "inheritance_conflict"}.items() <= next(
                    r for r in rows if r.get("reason")).items()

    def test_entail_declines_it_by_name(self):
        session = api.EngineSession()
        session.load_model(_conflicted())
        session.add_entity("t1", "SmallTank", {"level": 50.0})
        declines = api.entail(session).to_dict()["entailment"]["not_checked"]
        assert "inheritance_conflict" in {d["reason"] for d in declines}
        assert "inheritance_conflict" in VOCABULARIES["entailment"]

    def test_the_band_is_still_refused_at_every_check(self):
        session = api.EngineSession()
        session.load_model(_conflicted())
        session.add_entity("t1", "SmallTank", {"level": 96.0})
        declines = api.check(session).to_dict()["not_checked"]
        assert ("level", "BOUNDEDNESS", "missing_config") in {
            (d["indicator"], d["axiom"], d["reason"]) for d in declines}

    def test_a_whole_band_redeclared_is_not_a_conflict(self):
        model = _conflicted()
        model["domain"]["indicators"]["SmallTank"] = [
            {"name": "level", "warning": 97, "critical": 99}]
        assert load_domain(model).inheritance_conflicts == []


class TestAHierarchyThatCannotResolveIsRefused:

    @pytest.mark.parametrize("types, words", [
        (["A", {"name": "B", "extends": "Z"}], "does not declare"),
        ([{"name": "A", "extends": "B"}, {"name": "B", "extends": "A"}], "cycle"),
        ([{"name": "A", "extends": "A"}], "cycle"),
        ([{"name": "A", "parent": "B"}, "B"], "`name` and `extends`"),
        ([{"extends": "B"}, "B"], "`name` and `extends`"),
        (["B", {"name": "A", "extends": 3}], "names one declared"),
    ])
    def test_at_load(self, types, words):
        with pytest.raises(MalformedDomainModelError, match=words):
            load_domain({"domain": {"id": "h", "name": "h", "entity_types": types}})


class TestTemplatesReachTheSubtype:

    def test_a_parent_template_acts_on_a_subtype_entity(self):
        model = {"domain": {
            "id": "p", "name": "p",
            "entity_types": ["Pump", {"name": "BoosterPump", "extends": "Pump"}],
            "indicators": {"Pump": [{"name": "speed_rpm", "type": "NUMERIC",
                                     "axioms": ["BOUNDEDNESS"], "critical": 4000}]},
            "action_templates": [{
                "name": "throttle", "applies_to": "Pump",
                "parameters_schema": {"speed_rpm": {"entity_property": "speed_rpm"}},
                "effect": "set", "source": "runbook"}],
        }}
        session = api.EngineSession()
        session.load_model(model)
        session.add_entity("b1", "BoosterPump", {"speed_rpm": 3000.0})
        payload = api.rollout(session, actions=[{
            "template": "throttle", "entity_id": "b1",
            "parameters": {"speed_rpm": 1500}}], horizon_s=120, step_s=60).to_dict()
        assert payload["simulation"]["checked"]["actions_refused"] == 0
        assert payload["simulation"]["per_step"][0]["values"]["b1"]["speed_rpm"] == 1500.0

    def test_model_describe_says_who_extends_whom(self):
        session = api.EngineSession()
        session.load_model(_rewritten(_example()))
        extends = api.model_describe(session).to_dict()["model"]["extends"]
        assert extends == {station: "Station" for station in STATIONS}
