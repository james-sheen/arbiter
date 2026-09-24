"""Importing this package must not drag in an optional dependency.

`rdflib` is an optional extra. Nothing on the default path -- reading
a YAML domain model, running a session, asking for a judgment -- wants an RDF
graph, and the loader has carried a no-rdflib branch since precisely
because its absence is the SUPPORTED state rather than a degraded one. So a
user who never installs the extra should never pay for it, and a user who does
install it should not pay for it until they ask for a graph.

They paid for it anyway, in both trees and through four separate doors, because
`ontology/loader.py` imported rdflib at module scope and the reasoner imports
the loader. Measured before the fix: 50 rdflib modules on a bare import of the
package.

WHY THIS FILE EXISTS RATHER THAN A COMMENT SAYING SO. The previous guard
against this lived outside the published suite and asserted that `rdflib` was
absent from `sys.modules` -- which is true for free on any machine where the
extra is NOT INSTALLED. It had therefore passed its whole life without once
testing the thing it named, and the comment that described the problem named
the guard by a filename a reader of the published tree cannot open.

So: the outcome test below asks for the extra FIRST and skips when it is
genuinely unavailable, rather than passing vacuously; the mechanism test reads
the loader as text and runs everywhere, extra or not; and the third test is the
other side -- rdflib must still WORK when a graph is actually wanted, or
deleting RDF support altogether would satisfy the first two.
"""

from __future__ import annotations

import ast
import os
import pathlib
import subprocess
import sys

import pytest

# Rewritten to the published package name by build-engine.sh, which is what
# makes this file dual-runnable: it names the orchestrator's copy here and the
# published one there, and the claim is the same claim in both.
PACKAGE = "arbiter_engine"

OPTIONAL_EXTRA = "rdflib"


def _tree_root() -> pathlib.Path:
    """The directory to put on `PYTHONPATH` so `PACKAGE` imports.

    Derived by walking up rather than counting parents, because this file sits
    at `tests/engine/` in the source repository and at `tests/` in the derived
    one -- two different depths for one claim. The walk asks the question that
    actually matters (from where is this package importable?) instead of
    encoding an answer that is right in exactly one tree.
    """
    top = PACKAGE.split(".")[0]
    for parent in pathlib.Path(__file__).resolve().parents:
        if (parent / top).is_dir():
            return parent
    raise AssertionError(f"no directory above this file contains {top}/")


def _loader_source() -> str:
    root = _tree_root()
    path = root.joinpath(*PACKAGE.split(".")) / "ontology" / "loader.py"
    assert path.is_file(), f"no ontology loader at {path}"
    return path.read_text(encoding="utf-8")


def _import_probe(statement: str) -> set:
    """Run `statement` in a FRESH interpreter; report the modules it pulled.

    A subprocess and not an import here, because this test process has already
    imported most of the tree and `sys.modules` cannot be un-rung. `sys
    .executable` rather than a bare `python3`: the previous guard hardcoded the
    latter and could not run anywhere the interpreter is not on a default PATH,
    which is how it reached a remote runner and failed for a reason that had
    nothing to do with its subject.
    """
    code = (f"import sys\n{statement}\n"
            "print(chr(10).join(m for m in sys.modules))")
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(_tree_root()),
             "PYTHONDONTWRITEBYTECODE": "1"},
    )
    # Assert on the exit code before reading stdout: an empty module list from a
    # crashed interpreter satisfies every assertion below for the wrong reason.
    assert result.returncode == 0, (
        f"probe failed: {statement}\n{result.stderr[-2000:]}")
    return {m.split(".")[0] for m in result.stdout.split()}


class TestTheOutcome:
    """What a user observes. Needs the extra installed to mean anything, and
    says so out loud instead of passing when it is missing."""

    @pytest.fixture(autouse=True)
    def _the_extra_must_be_here(self):
        pytest.importorskip(
            OPTIONAL_EXTRA,
            reason=f"{OPTIONAL_EXTRA} is not installed, so this process cannot "
                   f"tell a package that does not import it from one that "
                   f"cannot")

    @pytest.mark.parametrize("door", [
        f"import {PACKAGE}",
        f"from {PACKAGE} import UnifiedAxiomReasoner",
        f"from {PACKAGE}.ontology.domain_loader import DomainModel",
        f"from {PACKAGE}.api import EngineSession",
    ])
    def test_no_door_into_this_package_pulls_the_extra(self, door):
        """Four doors, because the fix that shipped before this one closed
        two of them while its commit message claimed the whole surface. Each
        name here is exported by BOTH trees -- a door that exists on only one
        side cannot test a claim made about both."""
        assert OPTIONAL_EXTRA not in _import_probe(door), (
            f"`{door}` pulled {OPTIONAL_EXTRA}")


class TestTheMechanism:
    """Read the module rather than the outcome, so this half runs on a lane
    with no extra installed and still has a subject."""

    def test_the_loader_does_not_import_the_extra_at_module_scope(self):
        tree = ast.parse(_loader_source())
        offenders = []
        for node in tree.body:          # module scope ONLY, not nested bodies
            if isinstance(node, ast.Import):
                offenders += [a.name for a in node.names
                              if a.name.split(".")[0] == OPTIONAL_EXTRA]
            elif isinstance(node, ast.ImportFrom):
                if (node.module or "").split(".")[0] == OPTIONAL_EXTRA:
                    offenders.append(node.module)
            elif isinstance(node, ast.Try):
                # The shape this defect shipped in: a try/except ImportError
                # around a module-scope import reads as careful handling of an
                # optional dependency and costs exactly as much as a bare one.
                for stmt in ast.walk(node):
                    if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                        name = (getattr(stmt, "module", None)
                                or stmt.names[0].name)
                        if name.split(".")[0] == OPTIONAL_EXTRA:
                            offenders.append(f"{name} (inside a module-scope try)")
        assert not offenders, (
            f"loader.py imports {offenders} at module scope; every import of "
            f"this package pays for it")


class TestTheOtherSide:
    """If the first two tests were the whole guard, deleting RDF support would
    satisfy them. This is what stops that reading."""

    def test_the_extra_is_still_used_when_a_graph_is_actually_wanted(self):
        pytest.importorskip(OPTIONAL_EXTRA)
        from importlib import import_module
        loader_module = import_module(f"{PACKAGE}.ontology.loader")
        loader = loader_module.OntologyLoader()
        assert loader.graph is not None, (
            "constructing a loader with the extra installed left no graph; "
            "the import is lazy, not gone")
        assert loader_module.HAS_RDFLIB is True

    def test_the_loader_still_declares_the_namespaces_it_had(self):
        """They moved with the import. Pinned because a lazy binding is an easy
        place to drop a constant nobody reads on the default path."""
        pytest.importorskip(OPTIONAL_EXTRA)
        from importlib import import_module
        loader_module = import_module(f"{PACKAGE}.ontology.loader")
        loader_module.OntologyLoader()          # triggers the lazy bind
        assert str(loader_module.HEALTH) == "http://example.org/health#"
        assert str(loader_module.AXIOM) == "http://example.org/axiom#"
