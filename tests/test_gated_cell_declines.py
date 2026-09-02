"""A gated cell and a clean cell must not produce the same envelope.

A check gated on a declared property -- evaluate this only if the entity carries
that -- was counted in `checked.invariants` and appeared in no row. So it was
byte-identical to a cell that evaluated and found nothing: counted, no finding,
no decline. Measured on the way in, 20 healthy entities beside 5 gated ones made
`attempted - findings - declines` read 25, and no reader can tell twenty healthy
cells from twenty gated ones. The count was never a fallback.

THE WORDING IS THE DECISION, and it was ruled on from outside. The engine knows a
gate fired and which declaration gated it. It does not know whether the gate was
INTENDED -- a deliberate exemption and a mistake look identical here -- so a
reason asserting `chose not to` would claim knowledge the engine does not have.
Intentionality belongs to whoever holds the scan. `precondition_unmet` states the
precondition and stops.

WHAT THIS FILE REFUSES TO DO. Asserting only that the new row appears would pass
on an engine that emitted it for every cell, which is the same defect inverted.
Every test here compares the GATED entity against the CLEAN one in the same run.
"""
from __future__ import annotations

import tempfile
import textwrap

import pytest

from arbiter_engine.api import EngineSession, check
from arbiter_engine.types import NotEvaluatedReason

#: Indented, and dedented at use. A triple-quoted literal closing at column 0
#: trips the published tree's dedent check, which cannot tell a stray
#: column-zero line inside a string from a docstring that lost its indent.
MODEL = """
    domain:
      id: d
      name: D
      entity_types: [Svc, Pod]
      relationship_types: [routes]
      indicators:
        Svc:
          - name: routes_pods
            type: RELATIONSHIP
            axioms: [CONNECTIVITY]
            target_type: Pod
            relation_type: routes
            min_cardinality: 1
            required_property: selector
    """


def _run(svc_props):
    """One clean Svc plus the Svcs under test, in a single run.

    The clean one is always present: the claim is about two cells DIFFERING, and
    a run containing only gated cells cannot make it.
    """
    path = tempfile.mktemp(suffix=".yaml")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(textwrap.dedent(MODEL))
    session = EngineSession()
    session.load_model(path)
    session.add_entity("pod1", "Pod", {})
    session.add_entity("svc-clean", "Svc", {"selector": {"app": "x"}})
    # THE RELATIONSHIP IS LOAD-BEARING AND WAS MISSING IN THE FIRST DRAFT.
    # Without it `svc-clean` fails its cardinality check, so the two entities
    # differ by a FINDING and the headline test below passes on an engine that
    # emits no decline at all -- it went green against the un-fixed gate. A
    # clean cell has to be genuinely clean or the comparison is with something
    # else. (Argument order is `(source, relation_type, target)`; the first
    # attempt passed the target as the relation type and produced exactly the
    # unhealthy service this note is about.)
    session.add_relationship("svc-clean", "routes", "pod1")
    for name, props in svc_props.items():
        session.add_entity(name, "Svc", props)
    return check(session).to_dict()


def _rows(envelope, entity_id):
    """Everything the envelope says about one entity, both legs."""
    return (
        sorted((f["axiom"], f["problem_type"]) for f in envelope["findings"]
               if f["entity_id"] == entity_id),
        sorted((n["axiom"], n["reason"]) for n in envelope["not_checked"]
               if n["entity_id"] == entity_id),
    )


class TestTheTwoCellsDiffer:
    def test_a_gated_cell_and_a_clean_cell_are_distinguishable(self):
        env = _run({"svc-gated": {"selector": {}}})
        clean, gated = _rows(env, "svc-clean"), _rows(env, "svc-gated")
        assert clean == ([], []), (
            f"the clean cell is not clean, so this comparison is not the one "
            f"the CD is about: {clean}")
        assert clean != gated, (
            "a gated cell and a clean cell produced identical envelope rows, "
            "which is the entire defect this CD exists for")

    def test_the_gated_cell_is_on_the_decline_leg(self):
        env = _run({"svc-gated": {"selector": {}}})
        _, declines = _rows(env, "svc-gated")
        assert ("CONNECTIVITY", NotEvaluatedReason.PRECONDITION_UNMET.value) in declines

    def test_the_clean_cell_is_not(self):
        """The half that fails if the engine declines for everybody."""
        env = _run({"svc-gated": {"selector": {}}})
        _, declines = _rows(env, "svc-clean")
        assert NotEvaluatedReason.PRECONDITION_UNMET.value not in {r for _, r in declines}, (
            "the clean cell also declined, so the new row says nothing")

    def test_the_cell_is_still_counted(self):
        """Option (b) was to stop counting it. That was rejected: the skip would
        become invisible, which is the same defect one level down. The
        denominator keeps the cell and the decline explains it."""
        env = _run({"svc-gated": {"selector": {}}})
        assert env["checked"]["invariants"] > 0
        _, declines = _rows(env, "svc-gated")
        assert declines, "the cell is counted and unexplained again"


class TestTheReasonDoesNotClaimIntent:
    """Asserted as behaviour, not by reading the sentence.

    If the engine could tell a deliberate exemption from an accident it would be
    entitled to say so. It cannot, and the proof is that both shapes arrive here
    indistinguishable: a Service declaring an empty selector on purpose, and one
    that never got the key at all, are the same fact to this check.
    """

    def test_deliberate_and_accidental_gates_are_reported_alike(self):
        env = _run({
            "svc-empty": {"selector": {}},      # the case, on purpose
            "svc-absent": {},                   # the key never arrived
        })
        assert _rows(env, "svc-empty") == _rows(env, "svc-absent"), (
            "the engine reported two states it cannot tell apart differently, "
            "which is it claiming knowledge it does not have")

    def test_an_unresolvable_gate_is_a_different_reason(self):
        """The neighbouring claim, kept separate on purpose. A name no entity of
        the type carries is a TYPO, and that one the engine can see -- it is
        `missing_property` and put it there. Collapsing the two would
        undo that closure."""
        env = _run({"svc-only": {}})
        # Nothing carries `selector` now except svc-clean, so remove that leg by
        # asking a run where the clean entity is the only carrier.
        _, declines = _rows(env, "svc-only")
        reasons = {r for _, r in declines}
        assert NotEvaluatedReason.PRECONDITION_UNMET.value in reasons
        assert NotEvaluatedReason.MISSING_PROPERTY.value not in reasons


class TestTheVocabularyGrew:
    def test_the_reason_is_in_the_closed_set(self):
        assert NotEvaluatedReason.PRECONDITION_UNMET.value == "precondition_unmet"

    def test_it_is_the_twelfth(self):
        """The count is asserted because the README states one, and two records
        of a number drift. `test_decline_vocabulary_cd1658` holds the README to
        this enum; this holds the enum to the closure that grew it."""
        assert len(list(NotEvaluatedReason)) == 12
