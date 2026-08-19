"""W1.2 — the verified probes, pinned.

Every case below was run against the released package before it was written
down, and each pins a behaviour that shipped broken at least once or that a
consumer had to discover by experiment. The distinction from
`test_decline_contract.py` is deliberate: that file states one invariant over a
generated matrix, this one pins particular measured answers. An invariant tells
you the class is closed; a pin tells you the number did not move.

Nothing here is written from a docstring. Where a figure appears -- a floor, a
severity, a payload location -- it came off a run.
"""

import pytest

from arbiter_engine.api import (
    EngineSession, check, model_describe,
)
from arbiter_engine.types import (
    AXIOM_MINIMUMS, Axiom, NotEvaluatedReason,
)

from conftest import (
    BREACHING_VALUE, ENTITY_ID, ENTITY_TYPE, INDICATOR_BY_AXIOM,
    declines_for, model_for, session_for, unhealthy_series,
)


def _reasons(envelope) -> set:
    return {n["reason"] for n in envelope.to_dict()["not_checked"]}


def _problem_types(envelope) -> list:
    return [f["problem_type"] for f in envelope.to_dict()["findings"]]


# =========================================================================
# The original repro set: absent data must not read as health.
# =========================================================================

class TestTheAbsentDataReproSet:
    """P1-P5, the shapes the first issue against the published package used.

    P1 is the boundary the others are not: with no entities there is nothing
    to decline, so the envelope is legitimately empty and the `checked`
    summary is what carries the disclosure. The other four all hold data in
    some form, and each must produce a verdict or a named refusal.
    """

    def test_p1_no_entities_reports_zero_checked_rather_than_zero_problems(self):
        session = EngineSession()
        session.load_model(model_for("BOUNDEDNESS"))
        payload = check(session).to_dict()
        assert payload["findings"] == []
        assert payload["checked"] == {"invariants": 0, "entities": 0}

    def test_p2_entities_with_no_data_decline_rather_than_pass(self):
        session = session_for("STABILITY")
        envelope = check(session)
        assert _problem_types(envelope) == []
        assert NotEvaluatedReason.INSUFFICIENT_SAMPLES.value in _reasons(envelope)

    def test_p3_a_value_in_properties_is_read_by_a_threshold_axiom(self):
        session = session_for("BOUNDEDNESS")
        session.entities[ENTITY_ID].properties["level_pct"] = 99.0
        assert "threshold_exceeded:level_pct" in _problem_types(check(session))

    def test_p4_a_value_in_the_wrong_store_says_so(self):
        """The decline that used to read `missing_property` for data the
        caller had already supplied -- to the other store."""
        session = session_for("BOUNDEDNESS")
        session.add_observations(ENTITY_ID, "level_pct", [99.0] * 40)
        declines = declines_for(check(session), "BOUNDEDNESS")
        assert declines, "history-only data produced no BOUNDEDNESS decline"
        assert NotEvaluatedReason.NO_CURRENT_VALUE.value in {
            d["reason"] for d in declines}, (
            "a threshold axiom holding sixty observations and no current value "
            "must not report the value as missing; that directs a caller to "
            "supply what they already supplied")

    def test_p5_a_misspelled_property_is_reported_as_unconsumed(self):
        session = session_for("BOUNDEDNESS")
        session.add_observations(ENTITY_ID, "levl_pct", [99.0] * 30)
        unconsumed = session.unconsumed_observations()
        assert len(unconsumed) == 1
        record = unconsumed[0]
        assert record["property"] == "levl_pct"
        assert record["observations"] == 30
        assert record["reason"] == "undeclared_property"
        assert record["entity_type"] == ENTITY_TYPE

    def test_p5b_the_engine_does_not_guess_the_intended_name(self):
        """A nearest-match suggestion would be a domain heuristic wearing a
        helpful face. It reports what was fed; deciding what was meant is the
        reader's."""
        session = session_for("BOUNDEDNESS")
        session.add_observations(ENTITY_ID, "levl_pct", [99.0] * 30)
        record = session.unconsumed_observations()[0]
        assert "level_pct" not in str(record.values()), (
            "the unconsumed report named the declared indicator, which reads "
            "as a suggestion the engine deliberately does not make")


# =========================================================================
# The sample floor.
# =========================================================================

class TestTheSampleFloorIsTheDeclaredOne:
    """Crossing the declared floor must remove the insufficient_samples decline.

    Stated over all eight and derived from `AXIOM_MINIMUMS`, rather than as one
    hand-written 9/10 pair. The floors differ by an order of magnitude between
    axioms (1 to 30), so a pin on one of them says nothing about the other
    seven, and the table is exactly the sort of number that drifts from the
    code that reads it -- it did once already, when three copies of it existed
    and two had drifted apart.

    The claim is one-directional on purpose. BELOW the floor an axiom may still
    answer, and four of them do: threshold axioms read the entity's current
    value and need no history at all, so `insufficient_samples` was never their
    gate. What the floor promises is the other direction -- that at or above
    it, sample count is no longer the reason you got nothing.
    """

    @pytest.mark.parametrize("axiom", [a.value for a in Axiom])
    def test_at_the_floor_sample_count_is_no_longer_the_obstacle(self, axiom):
        floor = AXIOM_MINIMUMS[axiom]
        session = session_for(axiom)
        name = INDICATOR_BY_AXIOM[axiom]["name"]
        session.entities[ENTITY_ID].properties[name] = BREACHING_VALUE
        session.add_observations(ENTITY_ID, name, unhealthy_series(axiom, floor))

        stalled = [d for d in declines_for(check(session), axiom)
                   if d["reason"] == NotEvaluatedReason.INSUFFICIENT_SAMPLES.value]
        assert not stalled, (
            f"{axiom} declares a floor of {floor} and still reported "
            f"insufficient_samples with exactly {floor} observations")

    @pytest.mark.parametrize("axiom", [a.value for a in Axiom])
    def test_below_the_floor_it_declines_or_answers_from_the_current_value(
            self, axiom):
        floor = AXIOM_MINIMUMS[axiom]
        if floor < 2:
            pytest.skip(f"{axiom} declares a floor of {floor}; there is no "
                        f"below-the-floor case to construct")
        session = session_for(axiom)
        name = INDICATOR_BY_AXIOM[axiom]["name"]
        session.entities[ENTITY_ID].properties[name] = BREACHING_VALUE
        session.add_observations(ENTITY_ID, name, unhealthy_series(axiom, floor - 1))

        envelope = check(session)
        assert _problem_types(envelope) or declines_for(envelope, axiom), (
            f"{axiom} one sample short of its floor was silent")

    def test_the_stability_boundary_including_the_sample_between(self):
        """The specific pin, with 9 characterized rather than left open.

        A stuck sensor reporting one constant value is the case a consumer
        raised: eight samples declined, ten fired, and nobody had measured
        nine. It declines -- the boundary is the floor itself, not one either
        side of it.
        """
        outcomes = {}
        for n in (8, 9, 10):
            session = session_for("STABILITY")
            session.add_observations(ENTITY_ID, "speed_rpm", [1500.0] * n)
            envelope = check(session)
            outcomes[n] = (
                _problem_types(envelope),
                {d["reason"] for d in declines_for(envelope, "STABILITY")},
            )

        assert outcomes[8] == ([], {NotEvaluatedReason.INSUFFICIENT_SAMPLES.value})
        assert outcomes[9] == ([], {NotEvaluatedReason.INSUFFICIENT_SAMPLES.value})
        assert outcomes[10] == (["frozen_series:speed_rpm"], set())
        assert AXIOM_MINIMUMS["STABILITY"] == 10, (
            "the pin above is written against a floor of 10; the table moved")


# =========================================================================
# The documented lower-bound path.
# =========================================================================

class TestTheNegationWorkaroundBehavesAsDocumented:
    """Thresholds are upper bounds only, so a lower bound is expressed by
    negating the value and mirroring the thresholds.

    Pinned because it is the documented path today, and a consumer needing a
    lower bound has to build it. It is also worth pinning that the finding text
    comes out inverted: a fan running too SLOW is reported as `rpm_neg`
    exceeding a threshold, which every consumer then translates back at the
    report layer. That is a real cost of the workaround, and writing it down
    here is what makes it visible rather than folklore.
    """

    LOWER_BOUND = {"name": "rpm_neg", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
                   "warning": -1000, "critical": -500, "window": "1h"}

    def _at(self, rpm):
        session = EngineSession()
        session.load_model(model_for("BOUNDEDNESS", indicator=self.LOWER_BOUND))
        session.add_entity(ENTITY_ID, ENTITY_TYPE, properties={"rpm_neg": -float(rpm)})
        return check(session)

    def test_a_healthy_fan_is_silent(self):
        assert _problem_types(self._at(1500)) == []

    def test_below_the_lower_warning_fires_warning(self):
        envelope = self._at(900)
        assert _problem_types(envelope) == ["threshold_warning:rpm_neg"]
        assert envelope.to_dict()["findings"][0]["severity"] == "warning"

    def test_below_the_lower_critical_fires_critical(self):
        envelope = self._at(400)
        assert _problem_types(envelope) == ["threshold_exceeded:rpm_neg"]
        assert envelope.to_dict()["findings"][0]["severity"] == "critical"

    def test_the_finding_names_the_transform_not_the_quantity(self):
        """The wart, pinned deliberately. If direction-aware bounds ever land,
        this test is the one that should change, and it should change loudly."""
        assert "rpm_neg" in _problem_types(self._at(400))[0]


# =========================================================================
# CONSERVATION.
# =========================================================================

class TestConservation:

    SPEC = {"Unit": [
        {"name": "inflow_lps", "type": "NUMERIC", "axioms": ["CONSERVATION"],
         "window": "15m",
         "conservation": {"input_property": "inflow_lps",
                          "output_properties": ["outflow_lps"],
                          "loss_margin": 0.05}},
        {"name": "outflow_lps", "type": "NUMERIC", "axioms": []},
    ]}

    def _session(self, inflow, outflow, spec=None):
        session = EngineSession()
        session.load_model({"domain": {
            "id": "conservation", "name": "conservation",
            "entity_types": [ENTITY_TYPE], "relationship_types": [],
            "indicators": spec or self.SPEC}})
        session.add_entity(ENTITY_ID, ENTITY_TYPE,
                           properties={"inflow_lps": inflow, "outflow_lps": outflow})
        session.add_observations(ENTITY_ID, "inflow_lps", [inflow] * 10)
        session.add_observations(ENTITY_ID, "outflow_lps", [outflow] * 10)
        return session

    def test_a_deficit_past_the_loss_margin_fires(self):
        """8 in, 5 out: a 37.5 % deficit against a 5 % margin."""
        envelope = check(self._session(8.0, 5.0))
        assert "conservation_violation:inflow_lps" in _problem_types(envelope)
        assert envelope.to_dict()["findings"][0]["severity"] == "high"

    def test_a_deficit_inside_the_loss_margin_is_clean(self):
        """10 in, 9.8 out: 2 %, and the margin permits 5 %."""
        envelope = check(self._session(10.0, 9.8))
        assert _problem_types(envelope) == []
        assert declines_for(envelope, "CONSERVATION") == []

    def test_a_block_without_input_property_declines_missing_config(self):
        broken = {"Unit": [dict(self.SPEC["Unit"][0],
                                conservation={"output_properties": ["outflow_lps"]}),
                           self.SPEC["Unit"][1]]}
        declines = declines_for(check(self._session(8.0, 5.0, spec=broken)),
                                "CONSERVATION")
        assert {d["reason"] for d in declines} == {
            NotEvaluatedReason.MISSING_CONFIG.value}


# =========================================================================
# Where things live in the describe payload.
# =========================================================================

class TestTheDescribePayloadLocations:
    """This nesting moved once between releases, silently, and a consumer had
    to write a tolerant reader. Pin both locations, and pin them as a pair:
    the two reports answer opposite questions and sit at different depths, so
    reading one at the other's level returns None, which reads as *this build
    does not support it* rather than *you looked in the wrong place*.
    """

    def _payload(self):
        session = session_for("BOUNDEDNESS")
        session.add_observations(ENTITY_ID, "levl_pct", [1.0] * 3)
        return model_describe(session).to_dict()

    def test_unconsumed_observations_is_at_the_top_level(self):
        payload = self._payload()
        assert "unconsumed_observations" in payload
        assert payload["unconsumed_observations"], "the misspelled series vanished"

    def test_unread_fields_is_under_model_and_not_at_the_top_level(self):
        payload = self._payload()
        assert "unread_fields" in payload["model"]
        assert "unread_fields" not in payload

    def test_unreachable_declarations_is_under_model(self):
        assert "unreachable_declarations" in self._payload()["model"]

    def test_the_top_level_keys_are_the_envelope_plus_the_two_reports(self):
        """An equality assertion, not containment. Containment cannot see an
        extra key, and an envelope that grew a leg silently is the thing this
        class exists to catch."""
        assert set(self._payload()) == {
            "checked", "findings", "not_checked", "questions", "meta",
            "model", "unconsumed_observations",
        }
