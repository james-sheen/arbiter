"""The entity types a check applies to are DECLARED, and declared once.

Four axiom checks carried a hardcoded list of Kubernetes entity types and
refused anything outside it. The same scope was already declared in the domain
file's ``domain_checks`` entry and already enforced by the wrapper the platform
builds from that declaration, so the literal was a second copy -- and a domain
naming a type the literal omitted was accepted at load, bound, wrapped, called,
and silently returned nothing.

Assertions here are OUTCOMES -- which problems an entity receives -- not "the
literal was deleted". A test pinning the absence of a line passes the day
somebody writes the same refusal a different way.

Four of the eight checks the Kubernetes domain file declares never carried a
literal. They are the control group, and they are what showed the other four's to
be redundant rather than load-bearing.

THE TWO MIRRORS THAT ASSERT AGAINST THAT DOMAIN FILE ARE NOT HERE. A domain file
is a caller's configuration and is not part of this distribution, so a test
reading one could not run for an installing reader. They live beside this file in
the repository that owns the domain file. What is here is what is true of this
package: the checkers decide nothing by comparing an entity type to a literal.
"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from arbiter_engine import api as _anchor
from arbiter_engine.history.observation import InMemoryObservationHistory
from arbiter_engine.interfaces import Entity
from arbiter_engine.ontology.axioms.homeostasis import HomeostasisChecker
from arbiter_engine.ontology.axioms.responsiveness import ResponsivenessChecker

#: Asked of the package that was actually imported, so this resolves in the host
#: tree and in the published one without knowing which it is in. Counting
#: directories up from this file names a path that exists in only one of them --
#: measured, twice, on the day this was written.
AXIOMS = Path(_anchor.__file__).resolve().parent / "ontology" / "axioms"

#: The type each check used to demand, and a type it used to refuse. The refused
#: one is deliberately a name that means something else in another domain: an
#: OPC-UA `Node` is not a Kubernetes Node, and the point of the fix is that the
#: DECLARATION decides which it is, not a list buried in the checker.
ACCEPTED, REFUSED = "Pod", "Node"


def _history(entity_id="e1", prop=None, series=()):
    h = InMemoryObservationHistory()
    now = datetime.now(timezone.utc)
    for offset, value in series:
        h.add(entity_id, prop, value, now - timedelta(minutes=offset))
    return h


def _entity(entity_type, **props):
    return Entity(id="e1", type=entity_type, name="e1", properties=props)


def _slow_startup(entity_type):
    created = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    e = _entity(entity_type, phase="Pending", createdAt=created)
    return ResponsivenessChecker().check_slow_startup(e, startup_timeout_seconds=60.0)


def _health_probe(entity_type):
    e = _entity(entity_type, livenessProbeFailures=9)
    return ResponsivenessChecker().check_health_probe_failures(
        e, _history(), failure_threshold=3)


def _replica_mismatch(entity_type):
    e = _entity(entity_type, replicas=5, readyReplicas=1, availableReplicas=1)
    return HomeostasisChecker().check_replica_mismatch(e)


def _oscillating(entity_type):
    e = _entity(entity_type, restartCount=40)
    h = _history(prop="restartCount", series=((30, 0.0), (1, 40.0)))
    return HomeostasisChecker().check_oscillating_recovery(
        e, h, max_recovery_attempts=5)


PROBES = {
    "check_slow_startup": _slow_startup,
    "check_health_probe_failures": _health_probe,
    "check_replica_mismatch": _replica_mismatch,
    "check_oscillating_recovery": _oscillating,
}

#: The type each of the four used to demand. `Pod` for three of them;
#: `check_replica_mismatch` demanded a workload type instead.
FORMERLY_ACCEPTED = {
    "check_slow_startup": "Pod",
    "check_health_probe_failures": "Pod",
    "check_replica_mismatch": "Deployment",
    "check_oscillating_recovery": "Pod",
}


@pytest.mark.parametrize("check", sorted(PROBES))
def test_the_probe_is_not_measuring_nothing(check):
    """The mutation assert. Every case below compares a refused type against an
    accepted one, and if the accepted one produces nothing the comparison is
    between two empty lists and proves whatever you want."""
    found = PROBES[check](FORMERLY_ACCEPTED[check])
    assert found, (
        f"{check} produced no finding for {FORMERLY_ACCEPTED[check]}, the type "
        f"it has always accepted. This probe cannot detect the regression it "
        f"exists to detect")


@pytest.mark.parametrize("check", sorted(PROBES))
def test_a_type_the_literal_omitted_is_no_longer_refused(check):
    """The finding itself, as an outcome.

    Identical properties, only the entity type changed. Before the
    refused type produced nothing while the accepted one produced a finding,
    and nothing anywhere said why.
    """
    found = PROBES[check](REFUSED)
    assert found, (
        f"{check} still returns nothing for an entity typed {REFUSED!r} that "
        f"carries every property the check reads. The scope belongs to the "
        f"domain file's `entity_types`, not to a literal inside the checker")


def _type_literal_comparisons(path: Path):
    """Comparisons of something named `*type` against a string constant.

    By PARSE. A word search for `Pod` reads the docstrings that explain the
    boundary, and this repository has a gate that reads the AST for exactly
    that reason. The shape is described rather than spelled: a checker whose
    own source spells the pattern it hunts gets counted as an instance of it.
    """
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Compare):
            continue
        left = node.left
        name = (left.attr if isinstance(left, ast.Attribute)
                else left.id if isinstance(left, ast.Name) else None)
        if not name or not name.lower().endswith("type"):
            continue
        for comparator in node.comparators:
            if isinstance(comparator, ast.Constant) and isinstance(comparator.value, str):
                found.append((node.lineno, comparator.value))
            elif isinstance(comparator, (ast.Tuple, ast.List, ast.Set)):
                literals = [e.value for e in comparator.elts
                            if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                if literals:
                    found.append((node.lineno, literals))
    return found


@pytest.mark.parametrize("module", ["homeostasis.py", "responsiveness.py"])
def test_the_checkers_decide_nothing_by_comparing_an_entity_type_to_a_literal(module):
    path = AXIOMS / module
    assert path.is_file(), f"{module} moved; this test is now measuring nothing"
    found = _type_literal_comparisons(path)
    assert not found, (
        f"{module} compares an entity type against a literal at {found}. That "
        f"is a checker deciding by the entity's type, which is deciding by the "
        f"domain -- and the gate that hunts domain branches cannot see this "
        f"one: its predicate is a domain IDENTIFIER against a constant, and "
        f"this is a TYPE against a constant")



