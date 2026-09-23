"""Which RDF namespaces this engine may declare, pinned.

`ontology/loader.py` declared three namespace constants and one of
them ended in the short name of a single vertical's platform -- a domain noun
inside a component this project requires to carry none, shipped in every wheel
since the first, and reachable through an extra the package advertises.

THE MEASUREMENT THAT DECIDED THE FIX, and it is the reason this is a deletion
rather than a rename: no graph anywhere in the project declared that URI. The
engine's own meta-ontology declares two prefixes and not that one; the
platform's Kubernetes ontology declares a different URI entirely, on another
host. The lookup tried it first against every graph and fell through every
time, so removing it changes no behaviour in either tree -- which is a stronger
claim than *it looked wrong*, and the one worth having.

WHY A PIN AND NOT A WORD LIST. The domain-agnostic gate this project already
runs deliberately carries no vocabulary: it detects an identifier compared
against a constant, and says so, because a word-level filter reads prose ABOUT
a domain as the domain. That gate was right not to fire here -- a constant is
not a branch -- and extending it with a noun list would give it the weakness it
was designed without. So this file pins the SET instead, which needs no
vocabulary at all: two members, named, and a third of any spelling fails.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

#: The two the meta-ontology actually declares. `AXIOM` is read nowhere in the
#: source -- measured, not assumed -- and stays because the prefix is real; it
#: is an unused constant rather than a false one, and removing it is a separate
#: question from the one this file answers.
DECLARED = frozenset({
    "http://example.org/health#",
    "http://example.org/axiom#",
})


def _loader_source() -> str:
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / "arbiter_engine" / "ontology" / "loader.py",
                      here.parents[2] / "detection" / "ontology" / "loader.py"):
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    raise AssertionError("no ontology loader found in this tree")


def _namespace_uris(source: str) -> set:
    """Every `Namespace("...")` argument, by parsing rather than grepping.

    A comment mentioning a URI is prose about the code; a call is the code.
    The distinction is load-bearing here, because the comment recording this
    fix has to be able to describe what it removed."""
    found = set()
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "Namespace"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            found.add(node.args[0].value)
    return found


class TestTheNamespaceSetIsExactlyWhatWasRuled:

    def test_the_parse_finds_namespaces_to_judge(self):
        """Guards the guard. An AST walk that matched nothing -- a renamed
        import, a moved file -- would make every assertion below a green
        measuring an empty set."""
        assert len(_namespace_uris(_loader_source())) >= 2

    def test_no_namespace_beyond_the_two_declared(self):
        extra = _namespace_uris(_loader_source()) - DECLARED
        assert extra == set(), (
            f"the loader declares a namespace nothing ruled on: {sorted(extra)}")

    def test_both_declared_namespaces_are_still_there(self):
        """The other side of the pin. Removing one would also be a change
        nobody ruled on, and a one-sided test cannot see it."""
        missing = DECLARED - _namespace_uris(_loader_source())
        assert missing == set(), f"a declared namespace went missing: {sorted(missing)}"

    def test_a_comment_cannot_satisfy_this_test(self):
        """The fix's own comment describes what it removed. If this check read
        text rather than syntax, that comment would fail it -- which is the
        trap this project has filed twice under a different name."""
        assert _namespace_uris('# Namespace("http://example.org/anything#")\n') == set()


class TestTheLookupUsesOnlyWhatIsDeclared:

    def test_every_namespace_the_lookup_iterates_is_a_declared_name(self):
        """The defect was not the constant; it was the constant being TRIED.
        A namespace could be declared, unused and harmless -- one is. This
        pins the other half: the entity-class lookup may iterate only names
        this module declares, so a future addition cannot reach past them."""
        tree = ast.parse(_loader_source())
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        target = [f for f in ast.walk(tree)
                  if isinstance(f, ast.FunctionDef) and f.name == "_get_entity_class"]
        assert target, "_get_entity_class is gone; this pin now guards nothing"
        iterated = {n.id for node in ast.walk(target[0])
                    if isinstance(node, ast.List)
                    for n in node.elts if isinstance(n, ast.Name)}
        assert iterated, "the lookup iterates no namespace list at all"
        assert iterated <= names, sorted(iterated - names)
        assert len(iterated) <= len(DECLARED), (
            f"the lookup iterates {len(iterated)} namespaces and only "
            f"{len(DECLARED)} are declared")
