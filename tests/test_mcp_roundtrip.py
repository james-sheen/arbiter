"""W1.2 — the tool surface, and the transport that shipped unrun.

SPLIT ON PURPOSE. The routing table, the tool specifications and the envelopes
they return need no SDK, so they are tested unconditionally and run everywhere.
Only the server construction needs `mcp`, and only that is guarded.

An internal ruling added three FEEDERS. Before them this surface was read-only over a
session nothing could fill: no tool loaded a model, no tool supplied an entity
or an observation, and `main()` took no model path — so the protocol worked
perfectly and every tool answered `no domain model loaded` forever. An agent
cannot write the launcher that was the only way in; it has the tools it is
given, which is the premise of the transport.

The distinction is the point. This shim once registered its handlers with
decorators the 2.x SDK does not have, so it raised on the first line of
registration and had never been run -- and nothing caught it, because the whole
module was behind an import that was always absent. A skip that swallows an
entire component is not coverage; it is a component with no tests wearing the
same green as one that has them. Everything that can be tested without the
dependency now is, and the guarded part names what is missing rather than
disappearing quietly.
"""

import pytest

from arbiter_engine.mcp.server import (
    TOOL_SPECS, dispatch,
)

from conftest import ENTITY_ID, session_for


TOOL_NAMES = [spec["name"] for spec in TOOL_SPECS]


#: The smallest thing `load_model` can accept, for the envelope-shape walk.
_MINIMAL_MODEL = {
    "domain": {
        "id": "minimal", "name": "minimal",
        "entity_types": ["Unit"], "relationship_types": [],
        "indicators": {"Unit": [
            {"name": "level_pct", "type": "NUMERIC",
             "axioms": ["BOUNDEDNESS"], "critical": 95},
        ]},
    }
}


def _loaded_session():
    session = session_for("BOUNDEDNESS")
    session.entities[ENTITY_ID].properties["level_pct"] = 99.0
    session.add_observations(ENTITY_ID, "level_pct", [99.0] * 12)
    return session


#: One argument per tool, used by every walk in this file. Pinned against
#: TOOL_SPECS by set equality below.
ARGUMENTS = {
    "model_describe": {},
    "check": {},
    "gaps": {},
    "traverse": {"start_nodes": [ENTITY_ID]},
    "attest": {"problem_type": "threshold_exceeded:level_pct"},
    "load_model": {"model": _MINIMAL_MODEL},
    "add_entity": {"entity_id": "x", "entity_type": "Unit"},
    "add_observations": {"entity_id": ENTITY_ID,
                         "property_name": "level_pct",
                         "values": [1.0, 2.0]},
}


class TestTheRoutingTable:
    """A name in one table and not the other is a runtime KeyError otherwise."""

    def test_the_surface_is_reads_plus_feeders(self):
        """Named rather than counted.

        This asserted `len(TOOL_SPECS) == 5`, which is a bare count: it says
        nothing about WHICH tools, goes red on any change including a correct
        one, and is satisfied by the wrong five. The claim worth pinning is
        that the surface can be both read AND filled — a read-only surface over
        an unfillable session is what an internal ruling closed, and a count cannot tell
        you it came back.
        """
        reads = {"model_describe", "check", "traverse", "gaps", "attest"}
        feeders = {"load_model", "add_entity", "add_observations"}
        assert reads | feeders == set(TOOL_NAMES)

    @pytest.mark.parametrize("name", TOOL_NAMES)
    def test_every_advertised_tool_is_routable(self, name):
        """One argument table, shared with the envelope walk below.

        This used to call every tool with `{}` and skip the two that need
        arguments, which meant the skip list was a second transcription beside
        the argument list — and the three feeders all require arguments,
        so they would each have had to be remembered in two places. One table,
        pinned once.
        """
        assert dispatch(_loaded_session(), name, ARGUMENTS[name]), (
            f"{name} returned an empty payload")

    def test_an_unknown_tool_raises_rather_than_returning_empty(self):
        with pytest.raises(KeyError):
            dispatch(_loaded_session(), "no_such_tool", {})

    def test_every_spec_declares_a_description_an_agent_can_read(self):
        for spec in TOOL_SPECS:
            assert spec.get("description", "").strip(), (
                f"{spec['name']} advertises no description; the description is "
                f"what an agent selects on")
            assert "inputSchema" in spec


class TestTheEnvelopes:
    """Each tool returns the envelope shape, not a bare result."""

    @pytest.mark.parametrize("name", TOOL_NAMES)
    def test_the_envelope_legs_are_present(self, name):
        payload = dispatch(_loaded_session(), name, ARGUMENTS[name])
        for leg in ("checked", "findings", "not_checked", "questions", "meta"):
            assert leg in payload, f"{name} returned a payload with no {leg}"

    def test_the_argument_set_covers_every_tool_the_shim_advertises(self):
        """Pins ARGUMENTS against the shipped table, by EQUALITY both ways.

        The table is transcribed -- each tool needs its own arguments, so it
        cannot be generated -- and a transcribed set in an enumerating position
        fails silently: a tool missing from it is not a red test, it is a tool
        that is never called. Containment one way would not see an entry for a
        tool that no longer exists either.
        """
        assert set(ARGUMENTS) == set(TOOL_NAMES)


class TestTheTransport:
    """Needs the SDK. Skipped with its reason named, and CI installs the extra
    so this is not the component that is green everywhere and run nowhere."""

    def test_the_server_constructs_against_the_installed_sdk(self):
        pytest.importorskip(
            "mcp",
            reason="the `mcp` extra is not installed; `pip install "
                   "arbiter-engine[mcp]` runs this. The routing table above "
                   "is covered either way -- this pins only the SDK binding, "
                   "which is the part that once shipped never having run.")
        from arbiter_engine.mcp.server import build_server

        server = build_server(_loaded_session())
        assert server is not None
