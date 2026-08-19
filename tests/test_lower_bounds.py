"""BOUNDEDNESS in both directions.

Issue #6 asked for lower bounds and was closed by DOCUMENTING that bounds are
upper-only. What that closure cost is not visible from inside this repository:
downstream, a consumer needing a floor feeds the engine `-rpm`, declares
`critical: -1000`, and then writes a translator, because the engine answers a
stalled fan with `rpm_neg exceeds critical threshold`.

So the tests here are about a floor being a first-class declaration — the value
is the value, the sentence says *below*, and the two directions have the same
capability rather than one having threshold-only and the other threshold-plus-
projection.

Runs against both trees; see this suite's conftest for why that matters.
"""

import pytest

from arbiter_engine.interfaces import IndicatorSpec
from arbiter_engine.ontology.domain_loader import (
    _FIELD_CONSUMERS, _KNOWN_INDICATOR_KEYS, _SHARED_FIELDS,
)
from arbiter_engine.types import Axiom, NotEvaluatedReason

from conftest import (
    ENTITY_ID, declines_for, findings_for, session_for,
)


#: A fan: stalls below 1000 rpm, warns below 2000, and must not run away above
#: 9000. Both pairs on one indicator, which is the shape a direction switch
#: cannot express and the reason this is two slots rather than one enum.
BANDED = {
    "name": "speed_rpm", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
    "lower_warning": 2000, "lower_critical": 1000,
    "warning": 9000, "critical": 10000, "window": "1h",
}
FLOOR_ONLY = {
    "name": "speed_rpm", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
    "lower_warning": 2000, "lower_critical": 1000, "window": "1h",
}


def _check(indicator: dict, value: float, series: list | None = None):
    session = session_for("BOUNDEDNESS", indicator)
    session.entities[ENTITY_ID].properties[indicator["name"]] = value
    if series:
        session.add_observations(ENTITY_ID, indicator["name"], series)
    from arbiter_engine.api import check
    return check(session)


def _types(envelope) -> list:
    return [f["problem_type"] for f in findings_for(envelope, "BOUNDEDNESS")]


class TestAFloorIsDeclarable:
    """The capability itself: a floor breach, from a positive reading."""

    @pytest.mark.parametrize("value,expected", [
        (800.0, "below_critical_threshold:speed_rpm"),
        (1000.0, "below_critical_threshold:speed_rpm"),
        (1500.0, "below_warning_threshold:speed_rpm"),
        (2000.0, "below_warning_threshold:speed_rpm"),
    ])
    def test_a_reading_at_or_under_the_floor_fires(self, value, expected):
        """`<=`, mirroring the ceiling arm's `>=`. A threshold names the edge of
        acceptable, not the first unacceptable value, and the two directions
        have to agree about that or a band is asymmetric at its own edges."""
        assert _types(_check(FLOOR_ONLY, value)) == [expected]

    def test_a_healthy_reading_fires_nothing_and_declines_nothing(self):
        """The other half of every finding test. A floor that fires on a
        healthy value is not a floor, and one that declines a value it just
        evaluated is the envelope contradicting itself."""
        envelope = _check(FLOOR_ONLY, 4000.0)
        assert _types(envelope) == []
        assert declines_for(envelope, "BOUNDEDNESS") == []

    def test_the_sentence_says_below(self):
        """The whole downstream cost of the workaround, in one string. A report
        layer renders this text; `exceeds` for a stalled fan is what forced a
        translator to exist."""
        finding = findings_for(_check(FLOOR_ONLY, 800.0), "BOUNDEDNESS")[0]
        assert "below" in finding["reason"]
        assert "exceed" not in finding["reason"]

    def test_the_value_is_not_negated(self):
        """The reading reported is the reading supplied.

        Under the workaround the finding carried `-800`, so every consumer had
        to know which indicators were negated in order to print one. Reading the
        evidence back is the test that the transform is gone rather than moved.
        """
        session = session_for("BOUNDEDNESS", FLOOR_ONLY)
        session.entities[ENTITY_ID].properties["speed_rpm"] = 800.0
        from arbiter_engine.api import attest, check
        check(session)
        evidence = attest(
            session, "below_critical_threshold:speed_rpm").to_dict()["evidence"][0]
        assert evidence["evidence"]["value"] == 800.0
        assert evidence["evidence"]["threshold"] == 1000.0
        assert evidence["evidence"]["bound"] == "lower"


class TestTheCeilingIsUnchanged:
    """A released path, pinned against the change that surrounds it.

    An internal ruling adds an arm to a checker that has shipped in six releases. The
    upper-bound tests are here rather than only in the pre-existing suite so
    that the file making the change is also the file that fails if it breaks
    the behaviour it was not supposed to touch.
    """

    @pytest.mark.parametrize("value,expected", [
        (12000.0, "threshold_exceeded:speed_rpm"),
        (9500.0, "threshold_warning:speed_rpm"),
    ])
    def test_the_upper_arm_still_fires_its_own_names(self, value, expected):
        assert _types(_check(BANDED, value)) == [expected]

    def test_the_upper_arm_still_says_exceeds(self):
        finding = findings_for(_check(BANDED, 12000.0), "BOUNDEDNESS")[0]
        assert "exceeds" in finding["reason"]

    def test_every_finding_states_which_bound_it_came_from(self):
        """`threshold_type` alone requires a reader to hold our naming
        convention; `bound` says it outright. Asserted across all four arms so
        the field cannot be added to the new ones and missed on the old."""
        for value in (12000.0, 9500.0, 1500.0, 800.0):
            finding = findings_for(_check(BANDED, value), "BOUNDEDNESS")[0]
            session = session_for("BOUNDEDNESS", BANDED)
            session.entities[ENTITY_ID].properties["speed_rpm"] = value
            from arbiter_engine.api import attest, check
            check(session)
            evidence = attest(
                session, finding["problem_type"]).to_dict()["evidence"][0]
            assert evidence["evidence"]["bound"] in ("upper", "lower")


class TestTheBand:
    """Both pairs on one indicator, which is why this is not `direction:`."""

    @pytest.mark.parametrize("value,expected", [
        (800.0, ["below_critical_threshold:speed_rpm"]),
        (1500.0, ["below_warning_threshold:speed_rpm"]),
        (5000.0, []),
        (9500.0, ["threshold_warning:speed_rpm"]),
        (12000.0, ["threshold_exceeded:speed_rpm"]),
    ])
    def test_one_indicator_holds_a_floor_and_a_ceiling(self, value, expected):
        assert _types(_check(BANDED, value)) == expected

    def test_a_breach_fires_once(self):
        """A reading cannot breach both directions — `_contradictory_band`
        refuses the only declaration that would allow it — so no arm needs the
        early return the upper-critical arm uses, and none of them double-fire.
        """
        for value in (800.0, 1500.0, 9500.0, 12000.0):
            assert len(_types(_check(BANDED, value))) == 1


class TestAContradictoryBandIsRefusedOnce:
    """A band admitting no healthy value is a model defect, not a finding.

    Left alone it fires on every reading forever, and the author's evidence
    points at the data. The engine says so once, in the decline channel, which
    is where a statement about the declaration belongs.
    """

    @pytest.mark.parametrize("indicator,phrase", [
        ({"lower_warning": 9000, "warning": 2000}, "at or above warning"),
        ({"lower_critical": 9000, "critical": 2000}, "at or above critical"),
        ({"lower_warning": 1000, "lower_critical": 5000}, "above lower_warning"),
        ({"warning": 90, "critical": 10}, "below warning"),
    ])
    def test_each_way_of_writing_one_is_named_separately(self, indicator, phrase):
        spec = {"name": "speed_rpm", "type": "NUMERIC",
                "axioms": ["BOUNDEDNESS"], "window": "1h", **indicator}
        envelope = _check(spec, 5000.0)
        records = declines_for(envelope, "BOUNDEDNESS")
        assert len(records) == 1
        assert records[0]["reason"] == NotEvaluatedReason.MISSING_CONFIG.value
        assert phrase in records[0]["detail"]
        assert _types(envelope) == [], (
            "a contradictory band produced a finding as well as a decline")

    def test_the_inverted_ceiling_case_predates_the_floor(self):
        """`critical` below `warning` was declarable before and was
        accepted silently. Refusing the floor's version and not the ceiling's
        would teach an author that the engine validates bands while leaving one
        spelling of the same mistake unchecked, which is a worse contract than
        validating neither.

        Measured across the shipped domains before this landed: 113 indicators
        declare both, and none of them is inverted, so this refusal costs the
        existing corpus nothing.
        """
        spec = {"name": "speed_rpm", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
                "warning": 90, "critical": 10, "window": "1h"}
        records = declines_for(_check(spec, 50.0), "BOUNDEDNESS")
        assert records and "can never be reported" in records[0]["detail"]


class TestTheProjectionArmPointsBothWays:
    """A rising quantity is warned about before it arrives; so is a falling one.

    Shipping the floor with only its threshold arm would have given the two
    directions unequal capability — invisible from any call site, and
    discoverable only by a consumer whose fan died between two clean reports.
    """

    def test_a_falling_series_is_projected_onto_the_floor(self):
        envelope = _check(
            {"name": "speed_rpm", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
             "lower_critical": 1000, "window": "1h"},
            3000.0, series=[5000, 4500, 4000, 3600, 3200, 3000])
        assert _types(envelope) == ["approaching_floor:speed_rpm"]

    def test_a_rising_series_is_still_projected_onto_the_ceiling(self):
        envelope = _check(
            {"name": "speed_rpm", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
             "critical": 10000, "window": "1h"},
            8000.0, series=[3000, 4200, 5400, 6300, 7200, 8000])
        assert _types(envelope) == ["approaching_limit:speed_rpm"]

    def test_a_reading_already_at_the_floor_is_not_also_projected_onto_it(self):
        """One breach, one finding. The threshold arm returns before the
        projection arm can add a second record for the same event."""
        envelope = _check(
            {"name": "speed_rpm", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
             "lower_critical": 1000, "window": "1h"},
            900.0, series=[5000, 4000, 3000, 2000, 1400, 900])
        assert _types(envelope) == ["below_critical_threshold:speed_rpm"]


class TestAFloorAloneIsAThreshold:
    """The decline condition had to widen in the same change.

    An indicator declaring only a floor would otherwise have fired a finding
    AND been declined as having no threshold, in one pass — the envelope
    disagreeing with itself about the evaluation it had just performed. This is
    the enumeration-blindness shape: a condition written against a closed set
    has to be revisited by whoever opens the set.
    """

    @pytest.mark.parametrize("declared", [
        {"lower_critical": 1000},
        {"lower_warning": 2000},
        {"lower_warning": 2000, "lower_critical": 1000},
    ])
    def test_a_floor_only_indicator_is_never_declined_as_thresholdless(self, declared):
        spec = {"name": "speed_rpm", "type": "NUMERIC",
                "axioms": ["BOUNDEDNESS"], "window": "1h", **declared}
        assert declines_for(_check(spec, 4000.0), "BOUNDEDNESS") == []

    def test_an_indicator_with_no_bound_at_all_still_declines(self):
        """The other half: widening the condition must not silence it."""
        spec = {"name": "speed_rpm", "type": "NUMERIC",
                "axioms": ["BOUNDEDNESS"], "window": "1h"}
        records = declines_for(_check(spec, 4000.0), "BOUNDEDNESS")
        assert len(records) == 1
        assert records[0]["reason"] == NotEvaluatedReason.NO_THRESHOLD.value


class TestZeroIsAFloor:
    def test_a_zero_floor_is_honoured(self):
        """The sentinel collision, in the new fields. `is not None`
        throughout, so a legitimate floor of 0.0 is a floor and not an
        absence — which for a quantity that must stay positive is the single
        most likely floor anyone writes."""
        spec = {"name": "speed_rpm", "type": "NUMERIC",
                "axioms": ["BOUNDEDNESS"], "lower_critical": 0.0, "window": "1h"}
        assert _types(_check(spec, 0.0)) == ["below_critical_threshold:speed_rpm"]
        assert _types(_check(spec, 5.0)) == []
        assert declines_for(_check(spec, 5.0), "BOUNDEDNESS") == []


class TestTheFieldIsDeclaredEverywhereItHasToBe:
    """The reporting surfaces are derived, so they only work if the field was
    classified. Asserted rather than assumed: an unclassified field is invisible
    to `unread_fields`, and a key absent from the schema list is reported as
    unknown on a model that spells it correctly."""

    @pytest.mark.parametrize("yaml_key", ["lower_warning", "lower_critical"])
    def test_the_key_is_in_the_schema(self, yaml_key):
        assert yaml_key in _KNOWN_INDICATOR_KEYS

    @pytest.mark.parametrize("field", [
        "lower_warning_threshold", "lower_critical_threshold"])
    def test_the_field_names_its_consuming_axiom(self, field):
        assert field not in _SHARED_FIELDS, (
            "the floor pair is read by BOUNDEDNESS alone; calling it shared "
            "means declaring one without BOUNDEDNESS is never reported")
        assert _FIELD_CONSUMERS[field] == (Axiom.BOUNDEDNESS,)

    def test_a_floor_without_boundedness_is_reported_as_unread(self):
        """One transform further out than the checker: the field can be read
        correctly and still be undeclarable in practice if nothing tells an
        author their floor is going nowhere."""
        session = session_for("BOUNDEDNESS", {
            "name": "speed_rpm", "type": "NUMERIC", "axioms": ["HOMEOSTASIS"],
            "lower_critical": 1000, "window": "1h"})
        from arbiter_engine.api import model_describe
        unread = model_describe(session).to_dict()["model"]["unread_fields"]
        assert [r["field"] for r in unread] == ["lower_critical"]
        assert unread[0]["read_by"] == ["BOUNDEDNESS"]

    def test_the_dataclass_carries_both_slots(self):
        spec = IndicatorSpec(uri="u", name="n")
        assert spec.lower_warning_threshold is None
        assert spec.lower_critical_threshold is None
