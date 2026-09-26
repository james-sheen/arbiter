"""`hypothesize` over MCP, answering exactly what the verb answers.

The verb shipped in 0.2.7 and no transport carried it, so an agent that could
`infer` a posterior could not ask what might explain the finding in front of
it -- the one question an operator has once a finding names an entity that is
wrong. It is a tool now, routed through the same dispatch every other tool
uses, and it answers byte for byte what a library caller gets.
"""

from __future__ import annotations

import json

from arbiter_engine.mcp.server import TOOL_SPECS, dispatch
from arbiter_engine import api

from test_a_finding_says_where_to_look_next import CRITICAL, _session


def test_it_is_a_registered_tool():
    spec = next(s for s in TOOL_SPECS if s["name"] == "hypothesize")
    assert spec["inputSchema"]["required"] == ["entity_id"]


def test_the_tool_answers_what_the_verb_answers():
    direct = api.hypothesize(_session(*CRITICAL), "pnl-a").to_dict()
    carried = dispatch(_session(*CRITICAL), "hypothesize", {"entity_id": "pnl-a"})
    assert json.dumps(carried, sort_keys=True, default=str) == json.dumps(
        direct, sort_keys=True, default=str)
    assert carried["hypothesis"]["candidates"][0]["cause"] == "fdr-1"


def test_an_entity_it_cannot_place_declines_rather_than_raising():
    carried = dispatch(_session(*CRITICAL), "hypothesize", {"entity_id": "nowhere"})
    assert carried["hypothesis"]["not_checked"], (
        "an unknown entity came back with nothing declined")
