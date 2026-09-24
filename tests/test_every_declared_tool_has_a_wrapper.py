"""Every name in ``TOOL_SPECS`` has a wrapper, checked without the SDK.

THE GUARD THAT EXISTS ALREADY RUNS TOO LATE AND ON TOO FEW LANES.
`build_server()` raises `RuntimeError: TOOL_SPECS declares [...] with no wrapper
to register` at construction, which is the right behaviour and the right
message. But constructing the server needs the `mcp` SDK, so the only lane that
can reach it is the one installing the extra -- and every other lane SKIPS the
transport test and reports green.

That is not hypothetical. The four disciplines went in without wrappers once,
and `server.py` carries a comment about it. The world-model arc then did the
same thing with `rollout` and `plan`, and it shipped: 0.2.3 went to the index
with an MCP server that raised on construction for anyone who had the SDK
installed. Locally the suite was 1660 passed / 14 skipped; in CI it was 1668
passed / 5 skipped and red. The skip COUNT was the only local signal, and
nothing compares it across lanes.

SO THIS READS THE SOURCE INSTEAD OF IMPORTING IT. The wrapper table is a dict
literal inside `build_server`, so its keys are visible to the AST without the
function ever running and without the SDK being present. A name in `TOOL_SPECS`
and not in that dict fails here on EVERY lane, at collection speed.

WHY NOT JUST INSTALL THE SDK IN EVERY LANE. Because the dependency is optional
by decision -- the README's two-dependency claim is measured, and the transport
is behind an extra. A guard that requires the optional thing in order to check
the required thing has made it required in all but name.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

# THE ABSOLUTE IMPORT BELOW IS DOTTED, and that is not a style choice. This
# suite is derived: one file runs against two package roots, and the derivation
# recognises an absolute import by the DOT that follows the package name. An
# import written without that dot is carried across untouched and then names a
# package that does not exist on the other side -- measured, it refused a
# release build.
#
# -- the note that stood here said the same thing by naming the tool
# that performs the derivation and quoting a dotless import as the example.
# Neither survives the crossing: the tool is not in this tree, and the example
# is an absolute import, so it was substituted in place and the published
# sentence warned against an import it had itself just made valid-looking.
from arbiter_engine.mcp import server as _server
from arbiter_engine.mcp.server import TOOL_SPECS

SERVER = pathlib.Path(_server.__file__)

#: The dict whose keys are the wrappers. Named here so a rename of the local
#: variable fails loudly rather than silently emptying this test.
WRAPPER_TABLE = "wrappers"


def _wrapper_names() -> set:
    """Keys of the `wrappers = {...}` literal, read with the AST.

    Assigned inside `build_server`, so the walk is over the whole module rather
    than the module body -- and the assignment is found by TARGET NAME, not by
    position, because a literal found by position is one an edit above it
    silently redefines.
    """
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
            continue
        if not any(isinstance(t, ast.Name) and t.id == WRAPPER_TABLE
                   for t in node.targets):
            continue
        return {k.value for k in node.value.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    raise AssertionError(
        f"no `{WRAPPER_TABLE} = {{...}}` dict literal in {SERVER.name}; this "
        f"test reads that table and cannot see a renamed or restructured one")


def test_the_wrapper_table_is_readable():
    """Guards the guard. A resolver that returned an empty set would make the
    comparison below vacuously pass for a table that lost every entry."""
    names = _wrapper_names()
    assert len(names) >= 12, sorted(names)


def test_there_are_specs_to_check():
    assert len(TOOL_SPECS) >= 12


def test_every_declared_tool_has_a_wrapper():
    """The one that would have caught `rollout` and `plan` before the release."""
    declared = {spec["name"] for spec in TOOL_SPECS}
    missing = sorted(declared - _wrapper_names())
    assert not missing, (
        f"{missing} are in TOOL_SPECS with no entry in the wrapper table, so "
        f"the server would advertise a tool it cannot serve and `build_server` "
        f"would raise at construction -- but only on a lane that installs the "
        f"`mcp` extra")


def test_no_wrapper_is_registered_for_an_undeclared_tool():
    """The other direction. A wrapper with no spec is dead code that reads as
    a served tool, and `build_server` iterates TOOL_SPECS so it would never be
    registered at all."""
    stray = sorted(_wrapper_names() - {spec["name"] for spec in TOOL_SPECS})
    assert not stray, f"{stray} have wrappers and no TOOL_SPECS entry"


def test_the_two_new_verbs_are_among_them():
    """Named explicitly, because a set-comparison test stays green if BOTH
    sides lose a member together -- which is exactly how the pair went missing
    from the dict while remaining in `_HANDLERS`."""
    declared = {spec["name"] for spec in TOOL_SPECS}
    for verb in ("rollout", "plan"):
        assert verb in declared, f"{verb} left TOOL_SPECS"
        assert verb in _wrapper_names(), f"{verb} has no wrapper"
