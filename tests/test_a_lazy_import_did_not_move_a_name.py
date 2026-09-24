"""Making an import lazy must not change what a name resolves to.

The RDF names on `ontology/loader.py` are not a supported surface, and
that is the argument for being careful with them rather than the argument for
not bothering: nobody is watching, so nothing else would have noticed.

WHAT WENT WRONG. When the rdflib import was deferred, the names it binds were
given `None` placeholders at module scope so the module's own code would not
raise `NameError`. That worked for this module and broke the names for everyone
else, in three separate ways, all measured against the previous release:

  - `...ontology.loader import HEALTH` takes a COPY of the binding at
    import time. It stayed `None` in the caller's namespace permanently, no
    matter what was loaded afterwards. Before, it was the namespace.
  - WITHOUT the extra, seven names that had correctly raised `ImportError`
    began answering `None`. A name that does not exist started existing, as
    nothing. (SEVEN, and this sentence said six until an outside round counted
    the tuple below and found the prose beside it disagreeing. The count is
    checked against that tuple now -- see the last test in this file -- because
    a file whose subject is *a fix must not move a name* had a number in its own
    docstring that nothing held.)
  - `HAS_RDFLIB` answered `None` in BOTH states -- not a bool -- so a caller
    writing `if HAS_RDFLIB:` took the wrong branch with rdflib INSTALLED.

THE FIX IS THE SAME MECHANISM THAT WAS RULED OUT ONE ROUND EARLIER, doing the
job it can do. A module `__getattr__` does not serve a bare global lookup inside
a function of that module -- which is why `_rdflib_ready()` exists -- but
`from X import Y` IS attribute access on the module object, so it does serve
that. Both are needed; neither replaces the other.

THE TABLE BELOW IS THE PREVIOUS RELEASE'S BEHAVIOUR, measured in all four
combinations and reproduced here as the specification.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import textwrap

import pytest

# -- DERIVED, not written down. This used to be a string literal naming
# the source package, which the build substitutes in place: correct in effect,
# and indistinguishable to a checker from the prose leaks that substitution
# destroys. Reading it off an imported module's `__package__` puts the only
# mention of the name on an import line, where the rewrite is meant to act, and
# makes the value a derivation rather than a second copy of it.
from arbiter_engine import types as _anchor

PACKAGE = _anchor.__package__
LOADER = f"{PACKAGE}.ontology.loader"
EXTRA = "rdflib"

#: Undefined without the extra, so asking raises. Inherited from the module as
#: it stood before the import became lazy, not chosen here.
ABSENT_WITHOUT_EXTRA = ("Literal", "RDF", "RDFS", "OWL", "XSD", "HEALTH", "AXIOM")
#: Bound to None without the extra. The same inheritance, the other half of it.
NONE_WITHOUT_EXTRA = ("Graph", "Namespace", "URIRef")


def _tree_root() -> pathlib.Path:
    top = PACKAGE.split(".")[0]
    for parent in pathlib.Path(__file__).resolve().parents:
        if (parent / top).is_dir():
            return parent
    raise AssertionError(f"no directory above this file contains {top}/")


def _run(code: str, without_extra: pathlib.Path | None = None):
    """Run `code` in a fresh interpreter, optionally with the extra hidden.

    A subprocess because this process has already imported the tree and a
    binding taken at import time cannot be retaken. The extra is hidden with a
    stub module that RAISES on import rather than by uninstalling anything --
    the same shape the real absence has, and reversible.
    """
    path = str(_tree_root())
    if without_extra is not None:
        (without_extra / f"{EXTRA}.py").write_text(
            f'raise ImportError("{EXTRA} is not installed")\n', encoding="utf-8")
        path = f"{without_extra}{os.pathsep}{path}"
    return subprocess.run(
        [sys.executable, "-B", "-c", textwrap.dedent(code)],
        capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": path, "PYTHONDONTWRITEBYTECODE": "1"})


class TestWithTheExtraInstalled:

    @pytest.fixture(autouse=True)
    def _need_the_extra(self):
        pytest.importorskip(EXTRA, reason=f"{EXTRA} is not installed")

    def test_a_from_import_gets_the_real_object_and_not_a_placeholder(self):
        """The defect this file exists for. `None` here is a silently wrong
        value that never becomes right, because the caller holds a copy."""
        r = _run(f"""
            from {LOADER} import HEALTH, AXIOM, Graph, Literal
            assert HEALTH is not None and str(HEALTH).endswith("health#"), HEALTH
            assert AXIOM is not None and str(AXIOM).endswith("axiom#"), AXIOM
            assert Graph is not None and isinstance(Graph, type), Graph
            assert Literal is not None, Literal
            print("ok")
        """)
        assert r.returncode == 0, r.stderr[-1500:]

    def test_the_status_flag_is_a_bool_and_is_true(self):
        """`if HAS_RDFLIB:` is the obvious thing to write against this module.
        `None` reads as False with the extra installed, which is the wrong
        branch and a silent one."""
        r = _run(f"""
            from {LOADER} import HAS_RDFLIB
            assert HAS_RDFLIB is True, repr(HAS_RDFLIB)
            print("ok")
        """)
        assert r.returncode == 0, r.stderr[-1500:]

    def test_reading_a_name_does_not_require_having_used_the_loader_first(self):
        r = _run(f"""
            import {LOADER} as L
            assert str(L.HEALTH).endswith("health#"), L.HEALTH
            print("ok")
        """)
        assert r.returncode == 0, r.stderr[-1500:]


class TestWithoutTheExtra:
    """Runs WHETHER OR NOT the extra is installed here, because the absence is
    simulated rather than found. That is the point: the no-extra half of this
    contract had never been exercised on any lane that had rdflib."""

    def test_a_name_that_needs_the_extra_raises_rather_than_answering_none(
            self, tmp_path):
        names = ", ".join(ABSENT_WITHOUT_EXTRA)
        r = _run(f"""
            import {LOADER} as L
            for name in {ABSENT_WITHOUT_EXTRA!r}:
                try:
                    getattr(L, name)
                except AttributeError as e:
                    assert "{EXTRA}" in str(e), (name, str(e))
                else:
                    raise AssertionError(name + " answered instead of raising")
            print("ok")
        """, without_extra=tmp_path)
        assert r.returncode == 0, f"names: {names}\n{r.stderr[-1500:]}"

    def test_a_from_import_of_one_of_them_is_an_import_error(self, tmp_path):
        """What `from X import Y` turns an AttributeError into, and what the
        previous release did."""
        r = _run(f"""
            try:
                from {LOADER} import HEALTH
            except ImportError:
                print("ok")
            else:
                raise AssertionError("HEALTH imported without the extra")
        """, without_extra=tmp_path)
        assert r.returncode == 0, r.stderr[-1500:]

    def test_the_three_that_were_none_are_still_none(self, tmp_path):
        """Inherited asymmetry, pinned so it cannot be tidied away by accident.
        Tidying it is a change to a published surface and belongs in a release
        note, not in a refactor."""
        r = _run(f"""
            import {LOADER} as L
            for name in {NONE_WITHOUT_EXTRA!r}:
                assert getattr(L, name) is None, (name, getattr(L, name))
            print("ok")
        """, without_extra=tmp_path)
        assert r.returncode == 0, r.stderr[-1500:]

    def test_the_status_flag_is_false_and_not_none(self, tmp_path):
        r = _run(f"""
            from {LOADER} import HAS_RDFLIB
            assert HAS_RDFLIB is False, repr(HAS_RDFLIB)
            print("ok")
        """, without_extra=tmp_path)
        assert r.returncode == 0, r.stderr[-1500:]

    def test_the_loader_still_works_without_the_extra(self, tmp_path):
        """The names raising must not mean the module is broken: the built-in
        path is the SUPPORTED default and has to keep answering."""
        r = _run(f"""
            from {LOADER} import OntologyLoader
            loader = OntologyLoader()
            assert loader.graph is None
            assert loader.get_indicators("Pod") == []
            print("ok")
        """, without_extra=tmp_path)
        assert r.returncode == 0, r.stderr[-1500:]


class TestTheLazinessIsStillReal:
    """Restoring the names must not be done by importing eagerly again. This is
    the cross-check that keeps the two fixes from undoing each other."""

    def test_importing_the_loader_module_does_not_pull_the_extra(self):
        pytest.importorskip(EXTRA, reason=f"{EXTRA} is not installed")
        r = _run(f"""
            import sys
            import {LOADER}
            pulled = [m for m in sys.modules if m.split(".")[0] == "{EXTRA}"]
            assert not pulled, len(pulled)
            print("ok")
        """)
        assert r.returncode == 0, r.stderr[-1500:]

    def test_an_unknown_attribute_still_raises_a_plain_attribute_error(self):
        """The hook must not swallow a typo into the rdflib branch."""
        r = _run(f"""
            import {LOADER} as L
            try:
                L.no_such_name_at_all
            except AttributeError as e:
                assert "no attribute" in str(e), str(e)
                print("ok")
            else:
                raise AssertionError("a missing name resolved")
        """)
        assert r.returncode == 0, r.stderr[-1500:]


class TestThisFileHoldsItsOwnDocstring:
    """The smallest thing this round found, and the one with the shortest route
    from prose to proof: the counts above are stated in English and defined in
    Python four lines apart, and they disagreed."""

    def test_the_docstring_count_matches_the_tuple_it_describes(self):
        import re
        words = {w: i for i, w in enumerate(
            "zero one two three four five six seven eight nine ten".split())}
        doc = __doc__ or ""
        said = re.search(r"\b(" + "|".join(words) + r"|\d+)\s+names that had",
                         doc, re.I)
        assert said, "the docstring no longer states a count; drop this test too"
        raw = said.group(1).lower()
        stated = words.get(raw, None)
        if stated is None:
            stated = int(raw)
        assert stated == len(ABSENT_WITHOUT_EXTRA), (
            f"the docstring says {raw} and ABSENT_WITHOUT_EXTRA holds "
            f"{len(ABSENT_WITHOUT_EXTRA)}")

    def test_the_two_groups_account_for_every_name_the_module_exposes(self):
        """Two-sided: the counts can also drift by a name leaving the module
        entirely, which the test above would not see."""
        from importlib import import_module
        loader = import_module(LOADER)
        exposed = set(loader._RDFLIB_NAMES) | {"HAS_RDFLIB"}
        described = set(ABSENT_WITHOUT_EXTRA) | set(NONE_WITHOUT_EXTRA) | {"HAS_RDFLIB"}
        assert described == exposed, (
            f"described but not exposed: {described - exposed}; "
            f"exposed but not described: {exposed - described}")
