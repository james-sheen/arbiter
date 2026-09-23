"""The loader's RDF namespaces, and the graph that justifies them.

`ontology/loader.py` declares two namespaces on `example.org` and a
comment beside them said renaming would break the graph that declares those
prefixes. A second outside review measured that claim against the published
tree and found ZERO TTL files in it: the justification named a file the reader
could not open. That is a published sentence pointing at a tree the reader has
not got -- the class an earlier round closed -- committed in the round that
closed it, by the author of the fix.

THE FILE SHIPS NOW RATHER THAN THE SENTENCE BEING SOFTENED, because the
sentence was true and only its evidence was missing. This file is what makes it
checkable where a reader is standing.

AND IT WAS ALREADY DRIFTING WHEN IT ARRIVED. The graph declared SIX axioms
against the engine's eight; CONSERVATION and MONOTONICITY had never reached it.
Shipping it as it stood would have moved the drift into the published tree
rather than ending it, so the axiom set and every observation minimum below are
DERIVED from `AXIOM_MINIMUMS` -- the same table the original six were read
from. A ninth axiom cannot now reach the engine without reaching the graph.

THE ROUND TRIP RUNS ON A LANE, which it never did before. `rdf` is an
advertised extra, so `pip install arbiter-engine[rdf]` is a supported install,
and no lane installed it -- the whole RDF path executed nowhere. CI installs it
as of this round, for the same reason it installs `jsonschema`.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from arbiter_engine.types import Axiom, AXIOM_MINIMUMS

AXIOM_NS = "http://example.org/axiom#"


def _graph_path() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    for candidate in (
            here.parents[1] / "arbiter_engine" / "ontology" / "schemas"
            / "health_meta_ontology.ttl",
            here.parents[2] / "detection" / "ontology" / "schemas"
            / "health_meta_ontology.ttl"):
        if candidate.is_file():
            return candidate
    raise AssertionError("the meta-ontology is not in this tree")


def _loader_source() -> str:
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / "arbiter_engine" / "ontology" / "loader.py",
                      here.parents[2] / "detection" / "ontology" / "loader.py"):
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    raise AssertionError("no ontology loader found in this tree")


def _declared_prefixes() -> set:
    """`@prefix name: <uri> .` -- read as text, so this runs without rdflib.

    The claim under test is that two strings agree, and a parser is not needed
    to compare two strings. Keeping it textual means the check runs on the lane
    a reader has, not only on the one that installed an extra.
    """
    return set(re.findall(r"^@prefix\s+\w+:\s*<([^>]+)>\s*\.",
                          _graph_path().read_text(encoding="utf-8"), re.MULTILINE))


def _loader_namespaces() -> set:
    return set(re.findall(r'Namespace\(\s*"([^"]+)"\s*\)', _loader_source()))


class TestTheGraphIsHere:
    """The defect was its absence. These fail if it leaves again."""

    def test_the_meta_ontology_is_in_this_tree(self):
        assert _graph_path().is_file()

    def test_it_is_not_empty(self):
        """Guards the guard. A zero-byte file at the right path would satisfy
        every other assertion by declaring nothing to disagree with."""
        assert len(_graph_path().read_text(encoding="utf-8").splitlines()) > 50


class TestTheNamespacesAndTheGraphAgree:

    def test_the_parse_finds_prefixes(self):
        assert len(_declared_prefixes()) >= 4, sorted(_declared_prefixes())

    def test_every_namespace_the_loader_declares_is_declared_by_the_graph(self):
        """The sentence the comment makes, as an assertion. If a namespace in
        the loader is in no shipped graph, the justification for keeping its
        URI has gone -- which is exactly the state the review found."""
        orphans = _loader_namespaces() - _declared_prefixes()
        assert orphans == set(), (
            f"the loader declares namespaces no shipped graph uses: "
            f"{sorted(orphans)}")


class TestTheGraphDoesNotDriftFromTheEngine:
    """Derived from `AXIOM_MINIMUMS`, not restated. The file arrived two
    axioms behind and nothing could see it."""

    def _axiom_rows(self) -> dict:
        text = _graph_path().read_text(encoding="utf-8")
        rows = {}
        for block in re.findall(
                r"^axiom:(\w+)\s+a\s+axiom:Axiom\s*;(.*?)\.\s*$",
                text, re.MULTILINE | re.DOTALL):
            name, body = block
            minimum = re.search(r'minimumObservations\s+"(\d+)"', body)
            rows[name.upper()] = int(minimum.group(1)) if minimum else None
        return rows

    def test_the_block_parse_found_axioms(self):
        assert len(self._axiom_rows()) >= 6, self._axiom_rows()

    def test_the_graph_declares_every_axiom_the_engine_has(self):
        missing = {a.name for a in Axiom} - set(self._axiom_rows())
        assert missing == set(), (
            f"the engine has axioms the shipped graph has never heard of: "
            f"{sorted(missing)}")

    def test_the_graph_declares_no_axiom_the_engine_lacks(self):
        """Two-sided: a graph naming a ninth axiom teaches a reader a checker
        that does not exist."""
        extra = set(self._axiom_rows()) - {a.name for a in Axiom}
        assert extra == set(), sorted(extra)

    @pytest.mark.parametrize("axiom", list(Axiom), ids=lambda a: a.name)
    def test_each_minimum_is_the_engines_own(self, axiom):
        assert self._axiom_rows().get(axiom.name) == AXIOM_MINIMUMS[axiom], (
            f"{axiom.name}: the graph says "
            f"{self._axiom_rows().get(axiom.name)}, the engine says "
            f"{AXIOM_MINIMUMS[axiom]}")


class TestTheRdfPathActuallyRuns:
    """It ran on no lane until this round. `rdf` is an advertised extra, so a
    caller is invited to install exactly this path."""

    def test_the_loader_parses_the_shipped_graph(self):
        pytest.importorskip("rdflib", reason="the rdf extra is not installed")
        from arbiter_engine.ontology.loader import OntologyLoader
        loader = OntologyLoader()
        assert loader.load_meta_ontology(str(_graph_path())) is True
        assert loader.meta_loaded
        assert len(loader.graph) > 100, (
            f"the graph parsed to {len(loader.graph)} triples")

    def test_the_axioms_land_under_the_declared_namespace(self):
        """The round trip that matters: what comes back out carries the URI
        the loader declared going in."""
        pytest.importorskip("rdflib", reason="the rdf extra is not installed")
        from rdflib import RDF, Namespace
        from arbiter_engine.ontology.loader import OntologyLoader
        loader = OntologyLoader()
        loader.load_meta_ontology(str(_graph_path()))
        found = {str(s).rsplit("#", 1)[1].upper()
                 for s, _, _ in loader.graph.triples(
                     (None, RDF.type, Namespace(AXIOM_NS).Axiom))}
        assert found == {a.name for a in Axiom}, sorted(found)
