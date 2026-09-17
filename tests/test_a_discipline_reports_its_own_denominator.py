"""A sub-envelope refuses to be built without the things that make it readable.

The top-level envelope's contract cannot carry a discipline's work: every
decline record it holds requires one of eight axioms, and a projection that
could not fit a model has no axiom to name. Given only that record shape, a
discipline could report a refusal ONLY by inventing an axiom for it -- which is
the name-derived judgement this engine has spent releases removing.

So a discipline reports in the same four-leg shape one level down. These tests
pin the four ways that shape can be filled in wrongly, and every one of them is
a failure that would otherwise be silent:

- a denominator that counts nothing, which makes every decline uninterpretable;
- a reason outside the closed set, which makes the set stop being evidence;
- a scope key that collides with the record's own fields, which rewrites the
  stated reason on the way out and cannot raise, because a dict update never
  does;
- a source that says something went wrong without saying what.

All four are constructor errors rather than serialiser errors, deliberately: a
sub-envelope that cannot be built is a bug its author sees, while one that
serialises into something unclassifiable is a bug its consumer sees.
"""

from __future__ import annotations

import pytest

from arbiter_engine.interfaces import Problem
from arbiter_engine.subenvelope import (
    VOCABULARIES, Decline, SubEnvelope,
)
from arbiter_engine.types import Axiom, Severity


def _sub(**kw):
    base = dict(kind="projection", checked={"series_seen": 1})
    base.update(kw)
    return SubEnvelope(**base)


# --- the denominator -------------------------------------------------------

def test_a_discipline_must_report_a_denominator():
    with pytest.raises(ValueError, match="denominator"):
        _sub(checked={})


def test_a_denominator_that_counts_nothing_is_refused():
    """`checked` may carry non-count entries -- which method answered is not a
    number -- but it cannot be made of them. Eight declined out of `exact_ve`
    is not a statement."""
    with pytest.raises(ValueError, match="counts nothing"):
        _sub(checked={"method": "exact_ve"})


def test_counts_and_metadata_coexist():
    sub = _sub(checked={"queries": 1, "answered": 0, "method": "exact_ve"})
    assert sub.to_dict()["checked"]["method"] == "exact_ve"


def test_a_boolean_is_not_a_count():
    """`True` is an `int` in this language, and a flag read as a denominator
    would satisfy the check above while counting nothing."""
    with pytest.raises(ValueError, match="counts nothing"):
        _sub(checked={"converged": True})


# --- the closed vocabulary -------------------------------------------------

def test_a_reason_outside_the_vocabulary_is_refused():
    with pytest.raises(ValueError, match="outside the vocabulary"):
        _sub(not_checked=[Decline("the_dog_ate_it", {"entity_id": "e1"})])


def test_each_discipline_keeps_its_own_set():
    """`cpt_missing` is a real reason -- for inference. Accepting it in a
    projection would let either discipline absorb the other's refusals, and a
    closed enum that accepts anything is not evidence about anything."""
    assert "cpt_missing" in VOCABULARIES["inference"]
    with pytest.raises(ValueError, match="outside the vocabulary"):
        _sub(not_checked=[Decline("cpt_missing", {"entity_id": "e1"})])


def test_every_discipline_can_report_an_internal_error():
    """A discipline that raises where it could have declined converts one
    unanswerable cell into an unanswerable pass."""
    for kind in VOCABULARIES:
        assert "internal_error" in VOCABULARIES[kind]


def test_an_unknown_discipline_names_the_known_ones():
    with pytest.raises(ValueError, match="unknown discipline"):
        _sub(kind="astrology")


# --- the scope collision ---------------------------------------------------

def test_a_scope_key_cannot_overwrite_the_stated_reason():
    """The serialiser flattens `scope` beside `reason`. Without this guard a
    scope entry called `reason` wins the dict update and the record goes out
    stating a reason it was not declined for -- with nothing raised, because a
    dict update is not an error."""
    with pytest.raises(ValueError, match="overwrite"):
        Decline("model_missing", {"reason": "something else"})


def test_the_other_written_keys_are_protected_too():
    for key in ("detail", "evidence"):
        with pytest.raises(ValueError, match="overwrite"):
            Decline("model_missing", {key: "x"})


def test_a_declines_scope_survives_serialisation():
    out = Decline("insufficient_samples", {"entity_id": "e1", "property": "temp"},
                  detail="3 of 5", evidence={"n": 3, "required": 5}).to_dict()
    assert out == {
        "reason": "insufficient_samples",
        "entity_id": "e1",
        "property": "temp",
        "detail": "3 of 5",
        "evidence": {"n": 3, "required": 5},
    }


# --- source and reason -----------------------------------------------------

def test_a_source_that_is_not_live_must_say_why():
    with pytest.raises(ValueError, match="carries no reason"):
        _sub(source="unavailable")


def test_an_unknown_source_is_refused():
    with pytest.raises(ValueError, match="source must be one of"):
        _sub(source="probably_fine")


def test_an_unavailable_sub_envelope_carries_its_reason_into_meta():
    sub = _sub(source="unavailable", reason="no history supplied")
    assert sub.to_dict()["meta"] == {
        "source": "unavailable", "reason": "no history supplied"}


# --- the shape --------------------------------------------------------------

def test_the_four_legs_are_always_present():
    out = _sub().to_dict()
    assert set(out) == {"checked", "findings", "not_checked", "questions", "meta"}


def test_a_discipline_finding_carries_its_evidence():
    """Top-level findings do not carry evidence and these do. A discipline's
    finding is a claim built from a computation the reader did not watch -- a
    posterior, a breach probability, a lead-lag -- and the numbers behind it
    are the only way to tell a measurement from an assertion."""
    problem = Problem(
        id="p1", entity_id="e1", entity_type="Thing", entity_name="e1",
        problem_type="projected_breach:level_pct", severity=Severity.WARNING,
        axiom=Axiom.BOUNDEDNESS, reason="P(breach) = 0.31",
        evidence={"p_breach": 0.31, "model": "local_level"},
    )
    finding = _sub(findings=[problem]).to_dict()["findings"][0]
    assert finding["evidence"] == {"p_breach": 0.31, "model": "local_level"}
    assert finding["problem_type"] == "projected_breach:level_pct"


def test_no_declines_is_not_health():
    """Named after the envelope's property of the same name and meaning the
    same thing: an absence of refusals, not an absence of problems."""
    assert _sub().is_fully_evaluated is True
    assert _sub(not_checked=[Decline("no_threshold", {"entity_id": "e"})]
                ).is_fully_evaluated is False
