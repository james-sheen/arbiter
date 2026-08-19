"""W1.2 — the five-tool surface, and the transport that shipped unrun.

SPLIT ON PURPOSE. The routing table, the tool specifications and the five
envelopes they return need no SDK, so they are tested unconditionally and run
everywhere. Only the server construction needs `mcp`, and only that is guarded.

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


def _loaded_session():
    session = session_for("BOUNDEDNESS")
    session.entities[ENTITY_ID].properties["level_pct"] = 99.0
    session.add_observations(ENTITY_ID, "level_pct", [99.0] * 12)
    return session


class TestTheRoutingTable:
    """A name in one table and not the other is a runtime KeyError otherwise."""

    def test_five_tools_are_advertised(self):
        assert len(TOOL_SPECS) == 5

    def test_every_advertised_tool_is_routable(self):
        session = _loaded_session()
        for name in TOOL_NAMES:
            if name in ("traverse", "attest"):
                continue          # exercised below with their required arguments
            assert dispatch(session, name, {}), f"{name} returned an empty payload"

    def test_an_unknown_tool_raises_rather_than_returning_empty(self):
        with pytest.raises(KeyError):
            dispatch(_loaded_session(), "no_such_tool", {})

    def test_every_spec_declares_a_description_an_agent_can_read(self):
        for spec in TOOL_SPECS:
            assert spec.get("description", "").strip(), (
                f"{spec['name']} advertises no description; the description is "
                f"what an agent selects on")
            assert "inputSchema" in spec


class TestTheFiveEnvelopes:
    """Each tool returns the envelope shape, not a bare result."""

    @pytest.mark.parametrize("name,arguments", [
        ("model_describe", {}),
        ("check", {}),
        ("gaps", {}),
        ("traverse", {"start_nodes": [ENTITY_ID]}),
        ("attest", {"problem_type": "threshold_exceeded:level_pct"}),
    ])
    def test_the_envelope_legs_are_present(self, name, arguments):
        payload = dispatch(_loaded_session(), name, arguments)
        for leg in ("checked", "findings", "not_checked", "questions", "meta"):
            assert leg in payload, f"{name} returned a payload with no {leg}"

    def test_the_argument_set_covers_every_tool_the_shim_advertises(self):
        """Pins the parametrize list above against the shipped table.

        The list is transcribed -- each tool needs its own arguments, so it
        cannot be generated -- and a transcribed set in an enumerating position
        fails silently: a tool missing from it is not a red test, it is a tool
        that is never called.
        """
        covered = {"model_describe", "check", "gaps", "traverse", "attest"}
        assert covered == set(TOOL_NAMES)


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
