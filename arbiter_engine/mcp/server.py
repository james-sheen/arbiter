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
import sys
from typing import Any, Dict, List

from arbiter_engine.api import (
    EngineSession, attest, check, gaps, model_describe, traverse,
)
from arbiter_engine.envelope import Envelope, unavailable_envelope

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
    # the three feeders.
    #
    # The five above are the READ surface, and until now they were the whole
    # server: no tool loaded a model, no tool supplied an entity or an
    # observation, and `main()` took no model path. The protocol worked
    # perfectly and the session it served was permanently empty, so every tool
    # answered `no domain model loaded` forever and a custom launcher was
    # mandatory before the component could do anything at all.
    #
    # An agent cannot write a launcher. It has the tools it is given, which is
    # the whole premise of the transport, so a read-only surface over an
    # unfillable session is not a thin server — it is one that cannot reach its
    # own purpose.
    #
    # These mirror `EngineSession`'s feeders one for one rather than inventing
    # a shape: the session is the contract, and a transport that offered a
    # different vocabulary would be a second API to keep in step.
    {
        "name": "load_model",
        "description": (
            "Load a domain model from a YAML file path or an inline mapping. "
            "Call this before anything else — every other tool answers "
            "'no domain model loaded' until it succeeds."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "model": {"type": "object"},
            },
        },
    },
    {
        "name": "add_entity",
        "description": (
            "Register one entity and its current property values. Threshold "
            "axioms read these; the series axioms read observation history, "
            "which is a separate feed."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "entity_type": {"type": "string"},
                "properties": {"type": "object"},
                "name": {"type": "string"},
            },
            "required": ["entity_id", "entity_type"],
        },
    },
    {
        "name": "add_observations",
        "description": (
            "Feed a series for one entity property. Values are either bare "
            "readings spaced interval_seconds apart, or [timestamp, value] "
            "pairs. An unrecognised property name is accepted and reported by "
            "gaps as an unconsumed observation, never silently dropped."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "property_name": {"type": "string"},
                "values": {"type": "array"},
                "interval_seconds": {"type": "number"},
            },
            "required": ["entity_id", "property_name", "values"],
        },
    },
]

def _load_model(session: EngineSession, arguments: Dict[str, Any]) -> Envelope:
    """A feeder answering in the envelope every other tool answers in.

    Returning the model description on success is deliberate. An agent's next
    question after loading is always *what is in it*, and a bare acknowledgement
    would make the useful answer a second round trip — while a load that half
    worked (a file that parsed but declared no indicators) would look identical
    to one that worked.
    """
    source = arguments.get("path") or arguments.get("model")
    if source is None:
        return unavailable_envelope(
            "load_model needs `path` (a YAML file) or `model` (an inline "
            "mapping); neither was supplied")
    try:
        session.load_model(source)
    except Exception as exc:      # noqa: BLE001 — reported, never raised
        # A transport that raises gives the agent a stack trace it cannot act
        # on. The reason belongs in the envelope, which is the channel this
        # engine already uses to say why it could not do something.
        return unavailable_envelope(
            f"could not load the domain model: {type(exc).__name__}: {exc}")
    return model_describe(session)


def _add_entity(session: EngineSession, arguments: Dict[str, Any]) -> Envelope:
    session.add_entity(
        arguments["entity_id"], arguments["entity_type"],
        arguments.get("properties"), arguments.get("name", ""))
    return model_describe(session)


def _add_observations(session: EngineSession,
                      arguments: Dict[str, Any]) -> Envelope:
    """Feeds a series, then answers with `gaps`.

    `gaps` rather than a count, because it is the tool that reports
    `unconsumed_observations` — a property name nothing reads shows up in the
    reply to the call that fed it, rather than waiting for someone to ask.
    """
    values = arguments["values"]
    # JSON has no tuples, so a timestamped pair arrives as a two-element list
    # and the session's shape test already accepts that. Nothing to convert.
    session.add_observations(
        arguments["entity_id"], arguments["property_name"], values,
        float(arguments.get("interval_seconds", 60.0)))
    return gaps(session)


_HANDLERS = {
    "model_describe": lambda s, a: model_describe(s),
    "check": lambda s, a: check(s),
    "traverse": lambda s, a: traverse(
        s, a["start_nodes"], a.get("direction", "forward"),
        a.get("value_mode", "current"), a.get("max_hops", 4),
        a.get("overrides")),
    "gaps": lambda s, a: gaps(s, a.get("start_node")),
    "attest": lambda s, a: attest(s, a["problem_type"], a.get("entity_id")),
    "load_model": _load_model,
    "add_entity": _add_entity,
    "add_observations": _add_observations,
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

    async def load_model_tool(path: str | None = None,
                              model: Dict[str, Any] | None = None) -> str:
        return _emit("load_model", {"path": path, "model": model})

    async def add_entity_tool(entity_id: str, entity_type: str,
                              properties: Dict[str, Any] | None = None,
                              name: str = "") -> str:
        return _emit("add_entity", {
            "entity_id": entity_id, "entity_type": entity_type,
            "properties": properties, "name": name,
        })

    async def add_observations_tool(entity_id: str, property_name: str,
                                    values: List[Any],
                                    interval_seconds: float = 60.0) -> str:
        return _emit("add_observations", {
            "entity_id": entity_id, "property_name": property_name,
            "values": values, "interval_seconds": interval_seconds,
        })

    # derived from TOOL_SPECS rather than listed again.
    #
    # This was a hand-written tuple of five pairs beside a hand-written list of
    # five specs, which is an enumeration that gates work and cannot fail on a
    # member it lacks: a tool added to TOOL_SPECS and forgotten here registers
    # nothing, and the server starts clean. `dispatch` is already keyed off
    # `_HANDLERS`, so the wrappers are the only place a name could go missing —
    # and now the loop reads the spec list, so a spec without a wrapper raises
    # at construction instead of vanishing.
    wrappers = {
        "model_describe": model_describe_tool,
        "check": check_tool,
        "traverse": traverse_tool,
        "gaps": gaps_tool,
        "attest": attest_tool,
        "load_model": load_model_tool,
        "add_entity": add_entity_tool,
        "add_observations": add_observations_tool,
    }
    missing = {spec["name"] for spec in TOOL_SPECS} - set(wrappers)
    if missing:
        raise RuntimeError(
            f"TOOL_SPECS declares {sorted(missing)} with no wrapper to "
            f"register; the server would advertise a tool it cannot serve")
    for spec in TOOL_SPECS:
        name = spec["name"]
        server.add_tool(wrappers[name], name=name,
                        description=spec["description"])

    return server


def main(argv: List[str] | None = None) -> int:
    """``--model`` pre-loads a domain before the first tool call.

    The `load_model` tool makes the server usable without this; the argument
    makes it usable the way MCP servers are actually deployed. A client config
    names a command and its arguments once, and every session that command
    starts is expected to come up ready — an agent should not have to know the
    operator's file layout, and a stdio server has no other channel to learn
    it.

    A bad path fails HERE, with the reason on stderr and a non-zero exit, rather
    than starting a server whose every tool answers `no domain model loaded`.
    That silence is exactly the shape this engine exists to refuse, and a
    launcher is the one place it cannot be reported through the envelope.
    """
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(
        prog="arbiter-mcp",
        description="Serve the arbiter engine over MCP (stdio).")
    parser.add_argument(
        "--model", metavar="PATH",
        help="domain model YAML to load at startup; tools can also load one")
    args = parser.parse_args(argv)

    session = EngineSession()
    if args.model:
        try:
            session.load_model(args.model)
        except Exception as exc:      # noqa: BLE001 — reported, then refused
            print(f"arbiter-mcp: could not load {args.model}: "
                  f"{type(exc).__name__}: {exc}", file=sys.stderr)
            return 2

    asyncio.run(build_server(session).run_stdio_async())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
