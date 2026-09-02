"""One cell, one verdict: the declared path and the raw walk stopped disagreeing.

An internal ruling removed role inference from the indicator path and added a `missing_role`
decline. A second path -- `ConsistencyChecker.check_entity` -- kept walking every
entity property and classifying each by word-token, INCLUDING keys that are
declared indicators. So one cell produced both records in one envelope:

    FINDING impossible_value "foo_pct = 150.0 (percentage must be 0-100)"
    DECLINE missing_role "no role is declared. none could be inferred"

The decline said no inference was attempted, in the run where the finding proved
one was, and applying the percentage rule IS applying a role. `checked.invariants`
counted the cell once while two contradictory records referenced it.

THE COMMENT STATED A BOUNDARY THE CODE DID NOT IMPLEMENT. It scoped the surviving
guess to a raw key with `no IndicatorSpec and therefore nothing to declare a role
ON`. That is true of undeclared properties and was written about the whole walk.

SCOPE, AND IT IS NARROW ON PURPOSE. The exclusion covers keys the declared path
already dispatched CONSISTENCY for -- the overlap, and nothing else. An indicator
declaring only BOUNDEDNESS never had CONSISTENCY dispatched, so its key is still
walked; an undeclared property is untouched. That population is, still
open, and `test_the_exclusion_did_not_reach_past_the_overlap` below is the guard
that this fix did not quietly become the removal tried and reverted at a
cost of 32 reds.

PROBE HYGIENE, FROM A FAILURE IN THIS CLOSURE. The first check of the shipped
example's `pct` claim removed `role: percentage` from `level_pct_redundant` and
saw no change -- because that indicator ALSO declares a `consistency:` block,
which is the axiom's second way in, so the role path was never isolated. The
fixture instantiated a neighbour of the claim. Every case below that means to
exercise the role path declares CONSISTENCY and nothing else.
"""
from __future__ import annotations

import tempfile

import pytest

from arbiter_engine.api import EngineSession, check
from arbiter_engine.ontology.axioms.consistency import ConsistencyChecker
from arbiter_engine.interfaces import Entity

#: Names whose word-tokens the raw walk recognises, paired with names it does
#: not. Same quantity, same value; the only difference is the spelling.
TOKEN_NAMES = ["foo_pct", "foo_percent", "utilization_ratio", "error_count"]
PLAIN_NAMES = ["foo", "observed_generation", "reading"]


def _model(name, axioms="[CONSISTENCY]", role=None):
    role_line = f"        role: {role}\n" if role else ""
    return (
        "domain:\n  id: d\n  name: D\n  entity_types: [U]\n"
        "  relationship_types: [f]\n  indicators:\n    U:\n"
        f"      - name: {name}\n        type: NUMERIC\n{role_line}"
        f"        axioms: {axioms}\n        warning: 1\n        critical: 2\n")


def _run(name, axioms="[CONSISTENCY]", role=None, value=150.0, n=6):
    """Through the front door. A direct checker call would skip the dispatch
    that decides which of the two paths runs, which is the whole subject."""
    path = tempfile.mktemp(suffix=".yaml")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(_model(name, axioms, role))
    session = EngineSession()
    session.load_model(path)
    for i in range(n):
        session.add_entity(f"u{i}", "U", {name: value})
    return check(session).to_dict()


def _cells(envelope):
    """(entity, axiom) keys on each leg. The envelope strips evidence, so these
    five fields are what a consumer can actually join on."""
    found = {(f["entity_id"], f["axiom"]) for f in envelope.get("findings", [])}
    declined = {(d["entity_id"], d["axiom"])
                for d in envelope.get("not_checked", [])}
    return found, declined


class TestNoCellIsBothJudgedAndDeclined:
    """Acceptance 1. The claim is about the ENVELOPE, not about either path."""

    @pytest.mark.parametrize("name", TOKEN_NAMES + PLAIN_NAMES)
    def test_no_cell_appears_on_both_legs(self, name):
        found, declined = _cells(_run(name))
        assert not (found & declined), (
            f"{sorted(found & declined)} is reported as evaluated and as not "
            f"evaluated in one envelope")

    def test_the_pin_can_fail(self):
        """Their mutation rule, and it is not ceremony here: this assertion is
        an emptiness check, and an emptiness check over a set that is always
        empty for an unrelated reason passes forever. Feed the two legs a cell
        in common and the predicate must object."""
        found, declined = {("u0", "CONSISTENCY")}, {("u0", "CONSISTENCY")}
        assert found & declined, "the overlap predicate cannot detect an overlap"

    def test_the_declared_path_is_the_one_that_answers(self):
        """Not merely quiet -- the cell must still be ACCOUNTED for. Silence on
        both legs would satisfy the test above and lose the report."""
        envelope = _run("foo_pct")
        assert envelope["checked"]["invariants"] == 6
        assert {d["reason"] for d in envelope["not_checked"]} == {"missing_role"}
        assert envelope["findings"] == []


class TestTheOutcomeDoesNotDependOnTheSpelling:
    """Acceptance 2, scoped to the population covers."""

    @pytest.mark.parametrize("name", TOKEN_NAMES + PLAIN_NAMES)
    def test_every_name_declines_alike(self, name):
        envelope = _run(name)
        assert envelope["findings"] == []
        assert {d["reason"] for d in envelope["not_checked"]} == {"missing_role"}

    def test_a_declared_role_still_evaluates(self):
        """The remedy has to work, or the decline above is advice to nowhere."""
        envelope = _run("foo", role="percentage")
        assert len(envelope["findings"]) == 6
        assert envelope["not_checked"] == []


class TestTheDeclineTellsTheAuthorSomethingTrue:
    """The message is asserted by ACTING ON IT, not by matching its text.

    A text pin on this sentence is the defect this arc has already paid for
    twice: it goes red on the comment recording a removal, and it agrees with a
    stale string as happily as with a correct one. So take the remedy the engine
    names, apply it, and require the engine to agree -- and take the remedy it
    used to name, apply that, and require it NOT to work.
    """

    def _detail(self, name="foo"):
        declines = _run(name)["not_checked"]
        assert declines, "no decline to read a remedy out of"
        return declines[0]["detail"]

    def test_the_remedy_it_names_is_the_one_that_works(self):
        detail = self._detail()
        named = [r for r in ("percentage", "ratio", "count", "latency")
                 if f"'{r}'" in detail or f'"{r}"' in detail]
        assert named, f"the decline names no role to declare: {detail}"
        envelope = _run("foo", role=named[0])
        assert envelope["not_checked"] == [], (
            f"the decline told the author to declare {named[0]!r} and the "
            f"engine still declines after they did")

    def test_renaming_the_indicator_is_not_a_remedy(self):
        """The clause that outlived said an inference from the name had
        been attempted and missed, which invites exactly this move."""
        for name in TOKEN_NAMES:
            envelope = _run(name)
            assert {d["reason"] for d in envelope["not_checked"]} == {"missing_role"}, (
                f"renaming to {name!r} changed the decline, so the name is "
                f"still being read")
            # Asserted separately and deliberately: the decline set alone was
            # unchanged by the defect this CD fixes -- the raw walk ADDED a
            # finding rather than moving the decline -- so a check reading only
            # the decline leg would have passed throughout. The verdict a
            # reader acts on is both legs.
            assert envelope["findings"] == [], (
                f"renaming to {name!r} produced a finding, so the name still "
                f"selects a rule somewhere")


class TestTheShippedExampleTeachesTheCurrentEngine:
    """`water_tank.yaml` said that without `role:` the engine would infer the
    rule from the `pct` token. Asserted here as behaviour, on an indicator
    carrying the role path ALONE -- the shipped one also declares a
    `consistency:` block and cannot isolate the claim."""

    def test_a_pct_name_without_a_role_declines(self):
        envelope = _run("level_pct")
        assert envelope["findings"] == []
        assert {d["reason"] for d in envelope["not_checked"]} == {"missing_role"}


class TestTheWalkIsGone:
    """ excluded the overlap; an internal ruling removed the rest.

    This class previously pinned that the walk SURVIVED for keys the declared
    path had not judged -- the guard against quietly becoming the
    removal that had been tried and reverted. That removal has since been taken
    deliberately, sized first, so the guard is inverted rather than deleted: a
    walk that came back would be a regression against a decision, and nothing
    else in the suite would say so.

    What replaced it is a DECLARATION. `role:` plus CONSISTENCY on the
    indicator, which is checkable, tunable and counted in the denominator --
    none of which was true of the name.
    """

    def test_a_name_no_longer_selects_a_rule(self):
        """The undeclared property that used to fire by its spelling."""
        envelope = _run("foo", axioms="[BOUNDEDNESS]")
        session = EngineSession()
        path = tempfile.mktemp(suffix=".yaml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(_model("foo", "[BOUNDEDNESS]"))
        session.load_model(path)
        session.add_entity("u0", "U", {"foo": 1.0, "error_count": -3})
        out = check(session).to_dict()
        assert not any("error_count" in f["reason"] for f in out["findings"]), (
            "an undeclared property was judged by its name; the walk "
            "is back")

    def test_a_declared_role_is_what_judges_it_now(self):
        """The replacement has to work, or the removal cost coverage instead of
        moving it."""
        envelope = _run("error_count", axioms="[CONSISTENCY]", role="count",
                        value=-3.0)
        assert len(envelope["findings"]) == 6
        assert envelope["not_checked"] == []

    def test_the_checker_no_longer_exposes_the_walk(self):
        """Asserted on the object, not by grepping source -- a text search would
        go red on the comment recording the removal, which this arc has paid
        for."""
        assert not hasattr(ConsistencyChecker, "check_entity"), (
            "the raw-property walk is back on the checker")

    def test_every_finding_is_inside_the_denominator(self):
        """The reason the walk went, stated as a property of the envelope.

        Its findings ran outside the `relevant_axioms` loop, so
        `checked.invariants` never counted the cells they came from and a
        consumer subtracting findings from attempted got a negative
        contribution.
        """
        session = EngineSession()
        path = tempfile.mktemp(suffix=".yaml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(_model("error_count", "[CONSISTENCY]", "count"))
        session.load_model(path)
        for i in range(6):
            session.add_entity(f"u{i}", "U",
                               {"error_count": -3.0, "ready_ratio": 9.9,
                                "level_pct": 150.0})
        out = check(session).to_dict()
        attempted = out["checked"]["invariants"]
        assert len(out["findings"]) + len(out["not_checked"]) <= attempted, (
            f"{len(out['findings'])} findings and {len(out['not_checked'])} "
            f"declines against {attempted} attempted -- the envelope is "
            f"reporting on cells it never counted")


class TestBothLoadersReadTheDeclaredRole:
    """The defect the guess was masking, and the reason it stayed invisible.

    `settlement.yaml` declares `role: percentage` on `exposure_percent`. The
    engine-shaped loader read it; `OntologyLoader._parse_yaml_indicator` did
    not, so the spec came out with no role and the declared path declined. The
    raw walk then supplied the percentage rule from the `percent` token, and a
    closed-loop test covering that value passed -- on the spelling, not on the
    declaration, for as long as the field has existed.

    Nothing could go red for it. The pack was correct, the engine's own loader
    was correct, and the outcome was correct; only the REASON was wrong, and no
    surface reports a reason. It surfaced when an internal ruling removed the guess.
    """

    def test_the_second_loader_reads_role(self):
        from arbiter_engine.ontology.loader import OntologyLoader
        spec = OntologyLoader()._parse_yaml_indicator(
            {"name": "exposure_percent", "type": "NUMERIC",
             "role": "percentage", "axioms": ["CONSISTENCY"]},
            "TradingPosition")
        assert spec is not None
        assert spec.role == "percentage", (
            "the dict loader drops `role:`, so a pack that declares one gets an "
            "indicator that did not")

    def test_an_unknown_role_is_treated_as_absent_by_both(self):
        """The resolver's contract, not just the happy path: an unrecognised
        word must not become a role the engine silently ignores."""
        from arbiter_engine.ontology.loader import OntologyLoader
        spec = OntologyLoader()._parse_yaml_indicator(
            {"name": "q", "type": "NUMERIC", "role": "percentag",
             "axioms": ["CONSISTENCY"]}, "U")
        assert spec.role is None

    def test_the_two_loaders_agree(self):
        """Parity is the contract this module states for itself. A role read by
        one loader and dropped by the other is exactly the disagreement the
        parity claim is supposed to exclude."""
        import tempfile
        from arbiter_engine.ontology.loader import OntologyLoader
        from arbiter_engine.ontology.domain_loader import load_domain
        path = tempfile.mktemp(suffix=".yaml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(_model("q", "[CONSISTENCY]", "percentage"))
        engine_spec = load_domain(path).indicators["U"][0]
        dict_spec = OntologyLoader()._parse_yaml_indicator(
            {"name": "q", "type": "NUMERIC", "role": "percentage",
             "axioms": ["CONSISTENCY"]}, "U")
        assert engine_spec.role == dict_spec.role
