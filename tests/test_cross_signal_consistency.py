"""CONSISTENCY compares two readings that should agree.

Issue #4 established that the shipped CONSISTENCY is single-value plausibility:
it asks whether a number is possible on its own terms, and would behave
identically if every other indicator on the entity were deleted. The axiom NAME
had been reserved for redundant-signal agreement in eleven places across the
use-case catalogue and in the example's own comment; the capability was not
behind it, and the documented remedy was *compute the difference in your adapter
and give the engine that*.

This is the capability going behind the name. The tests here are about the two
rules being genuinely independent — a redundant pair usually carries no `role:`
at all — and about a declared peer that is missing being a decline rather than
silence, which is the same argument issue #1 made about everything else.

Runs against both trees; see this suite's conftest for why that matters.
"""

import pytest

from arbiter_engine.api import check, model_describe
from arbiter_engine.ontology.axioms import roles
from arbiter_engine.types import Axiom, NotEvaluatedReason

from conftest import ENTITY_ID, declines_for, session_for


#: Two level sensors on one tank. Carries `role: percentage` as well, so the
#: single-value rule and the cross-signal rule are both live on one indicator —
#: which is the case most likely to have them interfere.
REDUNDANT_PCT = {
    "name": "level_pct", "type": "NUMERIC", "role": "percentage",
    "axioms": ["CONSISTENCY"], "window": "15m",
    "consistency": {"agrees_with": ["level_pct_redundant"], "tolerance": 0.02},
}

#: Two thermocouples. NO role, and none inferrable — `temp_c` tokenises to
#: nothing this engine knows. The commonest shape of a redundant pair, and the
#: one that would be unreachable if the cross-signal rule were role-gated.
REDUNDANT_TEMP = {
    "name": "temp_c", "type": "NUMERIC", "axioms": ["CONSISTENCY"],
    "window": "15m",
    "consistency": {"agrees_with": ["temp_c_b"], "tolerance_absolute": 1.5},
}


def _run(indicator: dict, properties: dict):
    session = session_for("CONSISTENCY", indicator)
    session.entities[ENTITY_ID].properties.update(properties)
    return session, check(session)


def _types(envelope) -> list:
    return [f["problem_type"] for f in envelope.to_dict()["findings"]]


class TestTwoReadingsThatShouldAgree:
    def test_a_pair_inside_tolerance_is_clean(self):
        _, envelope = _run(
            REDUNDANT_PCT, {"level_pct": 50.0, "level_pct_redundant": 50.5})
        assert _types(envelope) == []
        assert declines_for(envelope, "CONSISTENCY") == []

    def test_a_pair_outside_tolerance_is_a_finding(self):
        _, envelope = _run(
            REDUNDANT_PCT, {"level_pct": 50.0, "level_pct_redundant": 62.0})
        assert _types(envelope) == ["redundant_disagreement:level_pct"]

    def test_the_finding_names_both_readings(self):
        """A disagreement between two sensors is not actionable without both
        numbers — the operator's next question is always *which one is lying*,
        and an engine that reports only the one it was iterating cannot be
        asked."""
        session, envelope = _run(
            REDUNDANT_PCT, {"level_pct": 50.0, "level_pct_redundant": 62.0})
        from arbiter_engine.api import attest
        evidence = attest(
            session,
            "redundant_disagreement:level_pct").to_dict()["evidence"][0]["evidence"]
        assert evidence["value"] == 50.0
        assert evidence["peer_value"] == 62.0
        assert evidence["peer"] == "level_pct_redundant"
        assert evidence["tolerance"] == 0.02

    @pytest.mark.parametrize("kind,config,near,far", [
        ("relative", {"tolerance": 0.02}, 50.5, 62.0),
        ("absolute", {"tolerance_absolute": 1.5}, 51.0, 55.0),
    ])
    def test_both_tolerance_kinds_discriminate(self, kind, config, near, far):
        """Each kind must be quiet on the near pair and loud on the far one.
        A tolerance that fires on everything and one that fires on nothing are
        both unfalsifiable, and only testing one side cannot tell them apart."""
        spec = dict(REDUNDANT_PCT)
        spec["consistency"] = {"agrees_with": ["level_pct_redundant"], **config}
        _, quiet = _run(spec, {"level_pct": 50.0, "level_pct_redundant": near})
        _, loud = _run(spec, {"level_pct": 50.0, "level_pct_redundant": far})
        assert _types(quiet) == []
        assert _types(loud) == ["redundant_disagreement:level_pct"]

    def test_agreement_is_symmetric(self):
        """`a agrees with b` has to mean what `b agrees with a` means.

        The tolerance is relative to the LARGER magnitude for this reason: a
        denominator taken from whichever reading the model happened to name
        first would make the verdict depend on which side of the pair carries
        the block, and a model may reasonably declare it on either or both.
        """
        forward = {"name": "temp_c", "type": "NUMERIC", "axioms": ["CONSISTENCY"],
                   "consistency": {"agrees_with": ["temp_c_b"], "tolerance": 0.05}}
        backward = {"name": "temp_c_b", "type": "NUMERIC", "axioms": ["CONSISTENCY"],
                    "consistency": {"agrees_with": ["temp_c"], "tolerance": 0.05}}
        readings = {"temp_c": 40.0, "temp_c_b": 44.0}
        _, one = _run(forward, readings)
        _, other = _run(backward, readings)
        assert len(_types(one)) == len(_types(other)) == 1

    def test_two_zeroes_agree(self):
        """The relative measure is a division, and both readings at zero make
        it 0/0. Answering anything but *these agree* would accuse a pair of
        sensors that match exactly."""
        spec = dict(REDUNDANT_PCT)
        spec["consistency"] = {"agrees_with": ["level_pct_redundant"],
                               "tolerance": 0.02}
        _, envelope = _run(spec, {"level_pct": 0.0, "level_pct_redundant": 0.0})
        assert _types(envelope) == []
        assert declines_for(envelope, "CONSISTENCY") == []


class TestTheRuleDoesNotNeedARole:
    """A redundant pair usually carries no role, and requiring one would make
    the commonest case of this capability unreachable."""

    def test_a_roleless_pair_is_evaluated(self):
        _, envelope = _run(REDUNDANT_TEMP, {"temp_c": 40.0, "temp_c_b": 44.0})
        assert _types(envelope) == ["redundant_disagreement:temp_c"]

    def test_a_roleless_pair_is_not_declined_as_inapplicable(self):
        _, envelope = _run(REDUNDANT_TEMP, {"temp_c": 40.0, "temp_c_b": 40.5})
        assert declines_for(envelope, "CONSISTENCY") == []

    def test_the_model_does_not_report_it_as_unreachable(self):
        """One transform out from the checker, and the more important half.

        `unreachable_axioms` reads the same `applies()` the checker gates on.
        Teaching only the checker would leave `model_describe` telling an author
        that a declaration which fires every cycle can never fire — a false
        entry in the honesty leg, which is worse than a missing capability
        because it is the report a reader trusts to be exhaustive.
        """
        session, _ = _run(REDUNDANT_TEMP, {"temp_c": 40.0, "temp_c_b": 44.0})
        model = model_describe(session).to_dict()["model"]
        assert model["unreachable_declarations"] == []
        assert model["indicators"]["Unit"][0]["unreachable_axioms"] == []

    def test_a_roleless_indicator_with_no_block_is_still_unreachable(self):
        """The other half. Opening a second door must not prop the first one
        open: an indicator with neither a role nor a block still cannot be
        evaluated by CONSISTENCY, and the report has to keep saying so."""
        bare = {"name": "temp_c", "type": "NUMERIC", "axioms": ["CONSISTENCY"],
                "window": "15m"}
        session, envelope = _run(bare, {"temp_c": 40.0})
        model = model_describe(session).to_dict()["model"]
        assert model["unreachable_declarations"] != []
        records = declines_for(envelope, "CONSISTENCY")
        # split this arm off NOT_APPLICABLE: a roleless indicator is a
        # MISSING DECLARATION, not an inapplicable axiom. The remedy the loader
        # already prints (declare a `role:`) is what makes the two different.
        assert records[0]["reason"] == NotEvaluatedReason.MISSING_ROLE.value

    def test_the_inapplicable_decline_offers_the_second_remedy(self):
        """A decline naming only the role remedy tells half the truth now.
        Which remedy an author wants depends on which question they meant to
        ask, so the sentence offers both."""
        bare = {"name": "temp_c", "type": "NUMERIC", "axioms": ["CONSISTENCY"],
                "window": "15m"}
        _, envelope = _run(bare, {"temp_c": 40.0})
        detail = declines_for(envelope, "CONSISTENCY")[0]["detail"]
        assert "role:" in detail
        assert "agrees_with" in detail


class TestAMissingPeerIsADecline:
    """The absent-data argument, applied to the input this rule needs.

    A peer that is declared and not supplied is exactly the shape issue #1 was
    about: the check cannot run, and saying nothing makes that byte-identical
    to the sensors agreeing.
    """

    def test_an_absent_peer_declines(self):
        _, envelope = _run(REDUNDANT_PCT, {"level_pct": 50.0})
        records = declines_for(envelope, "CONSISTENCY")
        assert len(records) == 1
        assert records[0]["reason"] == NotEvaluatedReason.MISSING_PROPERTY.value
        assert "level_pct_redundant" in records[0]["detail"]

    def test_a_non_numeric_peer_declines(self):
        _, envelope = _run(
            REDUNDANT_PCT, {"level_pct": 50.0, "level_pct_redundant": "n/a"})
        records = declines_for(envelope, "CONSISTENCY")
        assert len(records) == 1
        assert records[0]["reason"] == NotEvaluatedReason.MISSING_PROPERTY.value

    def test_one_missing_peer_is_reported_even_when_another_compared(self):
        """`two of three agreed` is not an answer about the third."""
        spec = dict(REDUNDANT_PCT)
        spec["consistency"] = {
            "agrees_with": ["level_pct_redundant", "level_pct_third"],
            "tolerance": 0.02,
        }
        _, envelope = _run(
            spec, {"level_pct": 50.0, "level_pct_redundant": 62.0})
        assert _types(envelope) == ["redundant_disagreement:level_pct"]
        records = declines_for(envelope, "CONSISTENCY")
        assert len(records) == 1
        assert "level_pct_third" in records[0]["detail"]


class TestTheSingleValueRulesAreUntouched:
    """A released path, pinned inside the change that surrounds it."""

    @pytest.mark.parametrize("role,value", [
        ("percentage", 140.0), ("count", -3.0), ("ratio", 4.0)])
    def test_the_plausibility_rules_still_fire(self, role, value):
        spec = {"name": "reading", "type": "NUMERIC", "role": role,
                "axioms": ["CONSISTENCY"], "window": "15m"}
        _, envelope = _run(spec, {"reading": value})
        assert _types(envelope) == ["impossible_value"]

    def test_the_more_urgent_finding_wins_when_both_rules_fire(self):
        """The reasoner reports ONE finding (entity, property).

        This test asserted that both survive, because they are independent
        questions and an operator plausibly wants both facts. They do not: a
        reading of 140% is impossible AND disagrees with its twin, and
        `_deduplicate_axiom_problems` keeps the more urgent one. The engine is
        right about its own contract here — that rule predates this capability
        by a long way and exists so one underlying fault does not produce five
        alerts — and the premise above was the test author's.

        Pinned as it actually behaves, rather than left as an aspiration in a
        docstring. What the collapse costs when both findings come from the
        SAME axiom is real and is: the loser's evidence is
        dropped with no `additional_axioms` chain, because that chain only has
        something to record when the axioms differ.
        """
        _, envelope = _run(
            REDUNDANT_PCT, {"level_pct": 140.0, "level_pct_redundant": 50.0})
        assert _types(envelope) == ["impossible_value"]

    def test_a_plausible_reading_still_reports_its_disagreement(self):
        """The case that matters, and the one the dedup does not touch: two
        sensors that are each individually plausible and do not match. If the
        collapse above reached this, the capability would be unreachable
        wherever it is most useful."""
        _, envelope = _run(
            REDUNDANT_PCT, {"level_pct": 50.0, "level_pct_redundant": 62.0})
        assert _types(envelope) == ["redundant_disagreement:level_pct"]


class TestABareStringPeerIsOnePeer:
    def test_a_peer_written_without_brackets_does_not_iterate_its_letters(self):
        """The failure, in the newest list-valued field. `agrees_with:
        level_pct_redundant` is the likeliest way to write this block wrong,
        and left alone it looks for eighteen properties named after single
        letters and declines all of them."""
        spec = dict(REDUNDANT_PCT)
        spec["consistency"] = {"agrees_with": "level_pct_redundant",
                               "tolerance": 0.02}
        _, envelope = _run(spec, {"level_pct": 50.0, "level_pct_redundant": 62.0})
        assert _types(envelope) == ["redundant_disagreement:level_pct"]
        assert declines_for(envelope, "CONSISTENCY") == []


class TestTheBlockIsDeclaredEverywhereItHasToBe:
    def test_the_yaml_key_is_in_the_schema(self):
        from arbiter_engine.ontology.domain_loader import (
            _KNOWN_INDICATOR_KEYS,
        )
        assert "consistency" in _KNOWN_INDICATOR_KEYS

    def test_the_field_names_its_consuming_axiom(self):
        from arbiter_engine.ontology.domain_loader import (
            _FIELD_CONSUMERS,
        )
        assert _FIELD_CONSUMERS["consistency_config"] == (Axiom.CONSISTENCY,)

    def test_a_block_without_consistency_declared_is_reported_as_unread(self):
        spec = {"name": "temp_c", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
                "critical": 90, "window": "15m",
                "consistency": {"agrees_with": ["temp_c_b"]}}
        session, _ = _run(spec, {"temp_c": 40.0})
        unread = model_describe(session).to_dict()["model"]["unread_fields"]
        assert [r["field"] for r in unread] == ["consistency"]

    def test_the_gate_helper_reads_the_block(self):
        """`has_cross_signal_rule` is what both the checker and the
        reachability report consult, so it is the single place the answer
        lives — the same argument `AXIOM_ROLES` makes one line above it."""
        class _Spec:
            consistency_config = {"agrees_with": ["x"]}
        assert roles.has_cross_signal_rule(_Spec()) is True

        class _Empty:
            consistency_config = {"agrees_with": []}
        assert roles.has_cross_signal_rule(_Empty()) is False

        class _None:
            consistency_config = None
        assert roles.has_cross_signal_rule(_None()) is False
