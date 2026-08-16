"""The MCP transport shim.

Deliberately thin. All five tools live in :mod:`arbiter_engine.api`
as plain functions over the engine (moved there, because they are
engine API rather than transport); this module only registers them with the SDK and
serialises the envelope. Everything worth testing is testable without
importing ``mcp`` at all, which is why the tool tests need no protocol
round-trip.

The SDK import is **lazy**, inside :func:`build_server`. Importing this module
must not require ``mcp`` to be installed — the engine is the dependency, the
transport is not (the scope ruling holds the platform,; the server
holds neither).

Run with:

    python3 -m arbiter_engine.mcp.server

(Inside the orchestrator repo the same module runs at its in-repo path, from
the repo parent on the path. That path is deliberately not spelled out here.)

This module now SHIPS -- the public-API ruling decided the surface is a
permanent public contract -- so its own docstring is public text. It previously gave only
the in-repo invocation, with an absolute operator path in front of it: a private
package name and a private filesystem path, both in a docstring, where the
build's stray scan cannot see them because that scan matches import STATEMENTS
and this is prose. Name what a reader actually has, and nothing else.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from arbiter_engine.api import (
    EngineSession, attest, check, gaps, model_describe, traverse,
)

#: The five primitives, in the order that an internal ruling lists them. Each entry is the
#: name, a one-line description for the client, and the JSON-Schema input.
TOOL_SPECS: List[Dict[str, Any]] = [
    {
        "name": "model_describe",
        "description": (
            "What domain model is loaded: entity types, indicators, and the "
            "axioms each indicator DECLARES. Call this before reasoning — it "
            "is the vocabulary, and an entity type absent from it does not "
            "exist in this model. Declared is not the same as evaluated."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "check",
        "description": (
            "Evaluate the declared invariants over the supplied observations. "
            "Returns findings AND what could not be evaluated, with reasons — "
            "an empty findings list with a populated not_checked list means "
            "nothing was measured, not that nothing is wrong."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "traverse",
        "description": (
            "Walk the entity graph. One primitive subsumes root-cause "
            "(direction=reverse), impact (forward), and what-if "
            "(value_mode=hypothetical with overrides)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "start_nodes": {"type": "array", "items": {"type": "string"}},
                "direction": {
                    "type": "string",
                    "enum": ["forward", "reverse", "bidirectional"],
                },
                # An internal ruling fed PROJECTED (2026-08-04), so the enum offers it.
                # It was withheld while the mode was inert; advertising a
                # capability nothing implements is the shape, and so
                # is leaving a withholding note whose stated reason has since
                # been resolved.
                "value_mode": {
                    "type": "string",
                    "enum": ["current", "hypothetical", "projected"],
                },
                "max_hops": {"type": "integer"},
                "overrides": {"type": "object"},
            },
            "required": ["start_nodes"],
        },
    },
    {
        "name": "gaps",
        "description": (
            "What the model is missing, as priority-ranked questions. This is "
            "what the engine needs to know next in order to answer better."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"start_node": {"type": "string"}},
        },
    },
    {
        "name": "attest",
        "description": (
            "The evidence behind a finding: which axiom, which threshold, how "
            "many observations. Engine-side evidence only."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "problem_type": {"type": "string"},
                "entity_id": {"type": "string"},
            },
            "required": ["problem_type"],
        },
    },
]

_HANDLERS = {
    "model_describe": lambda s, a: model_describe(s),
    "check": lambda s, a: check(s),
    "traverse": lambda s, a: traverse(
        s, a["start_nodes"], a.get("direction", "forward"),
        a.get("value_mode", "current"), a.get("max_hops", 4),
        a.get("overrides")),
    "gaps": lambda s, a: gaps(s, a.get("start_node")),
    "attest": lambda s, a: attest(s, a["problem_type"], a.get("entity_id")),
}


def dispatch(session: EngineSession, name: str,
             arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Route one tool call and return the envelope as a dict.

    Kept separate from the SDK registration so the routing table itself is
    testable — a name present in TOOL_SPECS but missing from _HANDLERS is the
    kind of gap that otherwise surfaces only at runtime.
    """
    handler = _HANDLERS.get(name)
    if handler is None:
        raise KeyError(f"unknown tool: {name}")
    return handler(session, arguments or {}).to_dict()


def build_server(session: EngineSession | None = None):
    """Construct the MCP server. Imports the SDK lazily.

    this targets ``mcp.server.MCPServer``, the high-level class in
    the 2.x SDK, which derives each tool's input schema from the wrapper's
    signature. The first version registered handlers with
    ``@server.list_tools()`` / ``@server.call_tool()`` on the low-level
    ``Server``; those decorators do not exist in 2.x, so **it raised
    ``AttributeError`` on the first line of registration and had never once
    been run.** Nothing caught it because the SDK cannot be installed in this
    repo's environment, so the shim had no test at all — see the module note
    below.

    The wrappers are deliberately trivial: each one calls :func:`dispatch`,
    which stays the single routing table and stays testable without the SDK.
    ``TOOL_SPECS`` remains the source of the descriptions, because those are
    what an agent actually reads.
    """
    from mcp.server import MCPServer  # noqa: PLC0415 — deliberate lazy import

    state = session or EngineSession()
    server = MCPServer("arbiter-engine")
    spec_by_name = {spec["name"]: spec for spec in TOOL_SPECS}

    def _emit(name: str, arguments: Dict[str, Any]) -> str:
        return json.dumps(dispatch(state, name, arguments), indent=2)

    async def model_describe_tool() -> str:
        return _emit("model_describe", {})

    async def check_tool() -> str:
        return _emit("check", {})

    async def traverse_tool(
        start_nodes: List[str],
        direction: str = "forward",
        value_mode: str = "current",
        max_hops: int = 4,
        overrides: Dict[str, Any] | None = None,
    ) -> str:
        return _emit("traverse", {
            "start_nodes": start_nodes, "direction": direction,
            "value_mode": value_mode, "max_hops": max_hops,
            "overrides": overrides,
        })

    async def gaps_tool(start_node: str | None = None) -> str:
        return _emit("gaps", {"start_node": start_node})

    async def attest_tool(problem_type: str,
                          entity_id: str | None = None) -> str:
        return _emit("attest", {"problem_type": problem_type,
                                "entity_id": entity_id})

    for name, fn in (
        ("model_describe", model_describe_tool),
        ("check", check_tool),
        ("traverse", traverse_tool),
        ("gaps", gaps_tool),
        ("attest", attest_tool),
    ):
        server.add_tool(fn, name=name,
                        description=spec_by_name[name]["description"])

    return server


def main() -> int:
    import asyncio

    asyncio.run(build_server().run_stdio_async())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
