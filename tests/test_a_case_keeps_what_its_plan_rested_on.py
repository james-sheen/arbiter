"""A case keeps what its chosen plan reaches and the source its margin rests on.

an attached `plan` kept `best` and `objective` and dropped the rest,
so a case could say a plan was chosen and not why it was close: `decisive`, the
one source the chosen plan's margin rests on most, and `reaches`, the entities
downstream it moves, stayed on the envelope and never reached the record. No
test attached a plan stage through the transport either. Both now, over the
same JSON a client sends.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from arbiter_engine.mcp import server


def _examples() -> Path:
    """The shipped examples, in whichever tree this file runs in."""
    here = Path(__file__).resolve()
    for candidate in (here.parents[1] / "examples", here.parents[2] / "examples",
                      here.parents[2] / "docs" / "publication" / "engine-example"):
        if (candidate / "pump_tank_planning.yaml").is_file():
            return candidate
    raise AssertionError("no examples directory in this tree carries them")


def _call(session, name, **arguments):
    """One tool call as a client makes it: JSON in, JSON out."""
    return json.loads(json.dumps(
        server.dispatch(session, name, json.loads(json.dumps(arguments)))))


def test_a_plan_attached_over_the_transport_keeps_decisive_and_reaches():
    model = yaml.safe_load((_examples() / "pump_tank_planning.yaml").read_text())
    model["domain"]["cases"] = {"severity": "warning", "consecutive_checks": 2}
    session = server.start_session()
    _call(session, "load_model", model=model)
    for entity_id, entity_type, properties in (
            ("pump1", "Pump", {"speed_rpm": 3000.0}),
            ("tank1", "Tank", {"level_pct": 97.0}),
            ("valve1", "Valve", {"open_pct": 0.0})):
        _call(session, "add_entity", entity_id=entity_id,
              entity_type=entity_type, properties=properties)
    _call(session, "add_relationship", source_id="pump1",
          relation_type="feeds", target_id="tank1")
    _call(session, "add_relationship", source_id="valve1",
          relation_type="drains", target_id="tank1")
    _call(session, "check")
    case_id = _call(session, "open_case", entity_id="tank1",
                    indicator="level_pct")["case"]["case_id"]

    planned = _call(session, "plan")
    attached = _call(session, "attach_stage", case_id=case_id, stage="plan",
                     envelope=planned)
    assert attached["case"]["checked"]["stages_attached"] == 1

    [case] = [c for c in _call(session, "case_book")["cases"]["cases"]
              if c["case_id"] == case_id]
    [entry] = case["stages"]["plan"]
    leg = planned["plan"]
    chosen = next(c for c in leg["candidates"] if c["plan"] == leg["best"])
    reference = entry["reference"]
    assert (reference["best"], reference["objective"]) == (leg["best"], leg["objective"])
    assert reference["decisive"] is not None
    assert reference["decisive"] == chosen["decisive"]
    assert reference["reaches"], "the chosen plan reaches nothing to keep"
    assert reference["reaches"] == [{"entity": r["entity"], "hops": r["hops"]}
                                    for r in chosen["reaches"]]
