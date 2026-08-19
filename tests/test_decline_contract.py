"""W1.1 — the decline contract, as one parameterized property.

    For every axiom checker, under every shape of absent or malformed data,
    the evaluation must FIND or DECLINE. It must never be silent.

Silence is the defect this engine exists to not commit. Its whole argument is
that an empty findings list means *nothing was wrong* only when the envelope
also says nothing was skipped, and the first issue filed against the published
package was exactly that: absent data producing a clean pass. That defect was
fixed, and until this file existed nothing in the engine's own tree could stop
it coming back -- the only tripwire was a downstream consumer's integration
suite, which is a strange place to keep an engine's regression protection.

The matrix deletes the category rather than the instance. A ninth axiom, or a
new way for data to be absent, is a new row or column here and every existing
cell keeps its meaning.

WHY THE DATA BREACHES
---------------------
Every cell supplies data the axiom cannot legitimately pass. That is
deliberate: it removes the third branch of the invariant ("or it genuinely
held"), so `no finding and no decline` can only mean silence. A predicate has
to discriminate -- one that passes on a healthy artifact AND on a broken one
is not evidence, and `assert findings or declines` against data an axiom could
legitimately clear would be precisely that.
"""

import pytest

from arbiter_engine.api import check
from arbiter_engine.types import (
    AXIOM_MINIMUMS, Axiom, NotEvaluatedReason,
)

from conftest import (
    BREACHING_VALUE, ENTITY_ID, INDICATOR_BY_AXIOM,
    declines_for, findings_for, session_for, unhealthy_series,
)


AXIOMS = [a.value for a in Axiom]


# --------------------------------------------------------------------------
# The absence shapes. Each takes a loaded session and leaves it in the named
# state; the two store shapes are one situation seen from either side, which
# is why they are separate rows rather than one "wrong store" row -- the
# engine holds two stores and every axiom reads exactly one of them, so which
# side you supplied decides which answer you get.
# --------------------------------------------------------------------------

def _shape_nothing_supplied(session, axiom):
    """The entity exists and neither store holds anything."""


def _shape_properties_only(session, axiom):
    """A current value on the entity; the observation history is empty."""
    session.entities[ENTITY_ID].properties[
        INDICATOR_BY_AXIOM[axiom]["name"]] = BREACHING_VALUE


def _shape_history_only(session, axiom):
    """A full history; the entity carries no current value."""
    name = INDICATOR_BY_AXIOM[axiom]["name"]
    session.add_observations(ENTITY_ID, name, unhealthy_series(axiom, 40))


def _shape_undeclared_name(session, axiom):
    """Both stores filled, under a name no indicator declares."""
    typo = INDICATOR_BY_AXIOM[axiom]["name"] + "_typo"
    session.entities[ENTITY_ID].properties[typo] = BREACHING_VALUE
    session.add_observations(ENTITY_ID, typo, unhealthy_series(axiom, 40))


def _shape_below_sample_floor(session, axiom):
    """One observation short of the floor this axiom declares for itself."""
    name = INDICATOR_BY_AXIOM[axiom]["name"]
    floor = AXIOM_MINIMUMS[axiom]
    session.entities[ENTITY_ID].properties[name] = BREACHING_VALUE
    if floor > 1:
        session.add_observations(ENTITY_ID, name, unhealthy_series(axiom, floor - 1))


ABSENCE_SHAPES = {
    "nothing_supplied": _shape_nothing_supplied,
    "properties_only": _shape_properties_only,
    "history_only": _shape_history_only,
    "undeclared_name": _shape_undeclared_name,
    "below_sample_floor": _shape_below_sample_floor,
}


class TestTheMatrixCoversWhatTheEngineDeclares:
    """The rows are pinned to the producer, not to this file.

    A transcribed set in an ENUMERATING position fails silently: a missing
    member of a parametrize list is not a red test, it is a test that never
    runs, and coverage looks complete. So the enumeration stays readable and
    an equality assertion is what goes red.
    """

    def test_every_declared_axiom_has_a_row(self):
        assert set(INDICATOR_BY_AXIOM) == {a.value for a in Axiom}, (
            "the matrix and the Axiom enum disagree; an axiom with no "
            "indicator declaration is an axiom this contract never tests")

    def test_every_axiom_has_a_declared_sample_floor(self):
        assert set(AXIOM_MINIMUMS) == {a.value for a in Axiom}

    def test_the_shape_list_is_not_silently_empty(self):
        assert len(ABSENCE_SHAPES) >= 5


@pytest.mark.parametrize("axiom", AXIOMS)
@pytest.mark.parametrize("shape", sorted(ABSENCE_SHAPES))
def test_absent_data_is_never_silent(axiom, shape):
    """The contract, one cell at a time."""
    session = session_for(axiom)
    ABSENCE_SHAPES[shape](session, axiom)

    envelope = check(session)
    findings = findings_for(envelope, axiom)
    declines = declines_for(envelope, axiom)

    assert findings or declines, (
        f"{axiom} under {shape}: the engine returned neither a finding nor a "
        f"decline. An empty findings list with nothing in not_checked reads as "
        f"health, and this data cannot be healthy.\n"
        f"  envelope: {envelope.to_dict()}")


@pytest.mark.parametrize("axiom", AXIOMS)
def test_every_decline_carries_a_reason_from_the_closed_set(axiom):
    """A decline naming a reason outside the enum is a misclassification.

    The reason vocabulary is deliberately closed and domain-agnostic. A member
    added to the enum and not emitted anywhere is harmless; a reason emitted
    that the enum does not contain means some caller is reading a string the
    engine promises is one of nine.
    """
    session = session_for(axiom)
    known = {r.value for r in NotEvaluatedReason}
    for shape in ABSENCE_SHAPES.values():
        session = session_for(axiom)
        shape(session, axiom)
        for record in check(session).to_dict()["not_checked"]:
            assert record["reason"] in known, (
                f"{record['reason']!r} is not in the declared decline "
                f"vocabulary {sorted(known)}")


class TestMalformedConfigDeclinesRatherThanCrashes:
    """The sixth absence shape: the declaration itself is broken.

    Not parameterized across all eight, because 'malformed' is only defined
    for the axioms carrying a required config block. Writing an eight-row
    parametrize here and letting six rows pass vacuously would report six
    passes that assert nothing, which is the shape of coverage this project
    keeps finding in its own work.
    """

    def test_conservation_without_input_property(self):
        broken = dict(INDICATOR_BY_AXIOM["CONSERVATION"])
        broken["conservation"] = {"output_properties": ["outflow_lps"]}
        session = session_for("CONSERVATION", indicator=broken)
        session.add_observations(ENTITY_ID, broken["name"], unhealthy_series("CONSERVATION", 40))

        envelope = check(session)
        declines = declines_for(envelope, "CONSERVATION")
        assert declines, "a CONSERVATION block with no input_property was silent"
        assert any(d["reason"] == NotEvaluatedReason.MISSING_CONFIG.value
                   for d in declines), (
            f"expected a missing_config decline, got "
            f"{[d['reason'] for d in declines]}")

    def test_monotonicity_without_a_direction(self):
        broken = dict(INDICATOR_BY_AXIOM["MONOTONICITY"])
        broken.pop("monotonicity", None)
        session = session_for("MONOTONICITY", indicator=broken)
        session.add_observations(ENTITY_ID, broken["name"], [5.0, 4.0, 3.0, 2.0, 1.0])

        envelope = check(session)
        assert (findings_for(envelope, "MONOTONICITY")
                or declines_for(envelope, "MONOTONICITY")), (
            "MONOTONICITY with no direction block was silent on a series that "
            "falls monotonically")

    def test_a_threshold_axiom_with_no_thresholds(self):
        broken = dict(INDICATOR_BY_AXIOM["BOUNDEDNESS"])
        broken.pop("warning", None)
        broken.pop("critical", None)
        session = session_for("BOUNDEDNESS", indicator=broken)
        session.entities[ENTITY_ID].properties[broken["name"]] = BREACHING_VALUE

        envelope = check(session)
        assert (findings_for(envelope, "BOUNDEDNESS")
                or declines_for(envelope, "BOUNDEDNESS")), (
            "BOUNDEDNESS with no bounds declared was silent")


class TestTheEnvelopeSaysWhenItCheckedNothing:
    """The boundary case the matrix cannot state: no entities at all.

    With nothing to evaluate there is nothing to decline, so the invariant
    above has no cell here -- and an envelope with no findings and no declines
    is exactly what a clean pass looks like. What keeps it honest is the
    `checked` summary: zero entities and zero invariants is the disclosure,
    and `is_fully_evaluated` is true only because the question was empty.
    """

    def test_an_empty_session_reports_that_it_checked_nothing(self):
        session = session_for("BOUNDEDNESS")
        session.entities.clear()
        payload = check(session).to_dict()
        assert payload["findings"] == []
        assert payload["not_checked"] == []
        assert payload["checked"]["entities"] == 0
        assert payload["checked"]["invariants"] == 0
