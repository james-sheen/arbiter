"""Released behaviours the shipped suite could not demonstrate.

Found by differencing what each test lane EXECUTES over the release
manifest, rather than by reading test names: six behaviours in reachable modules
were exercised only by a lane that does not ship. A consumer running the shipped
suite green had no way to check any of them.

THE SHARPEST IS `expected_direction: decreasing`. It is a declared, documented
model option, and only the increasing arm was ever run here -- so the direction a
reader declares is the one the package could not show working.

WHY THESE AND NOT THE REST. The other unexercised lines live in modules nothing
reaches from the eleven exports, where a shipped pin would put a green check
beside something a consumer still cannot call. Those are recorded instead. Every
behaviour below sits on a path the supported surface reaches.
"""
from __future__ import annotations

import tempfile
import textwrap

import pytest

from arbiter_engine.api import EngineSession, check
from arbiter_engine.ontology.domain_loader import (
    NotADomainModelError, is_domain_model, load_domain)

MODEL = """
    domain:
      id: d
      name: D
      entity_types: [Meter]
      relationship_types: [f]
      indicators:
        Meter:
          - name: remaining
            type: NUMERIC
            axioms: [MONOTONICITY]
            window: 24h
            monotonicity:
              expected_direction: decreasing
              allow_reset: false
    """


def _session(model: str = MODEL):
    path = tempfile.mktemp(suffix=".yaml")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(textwrap.dedent(model))
    session = EngineSession()
    session.load_model(path)
    return session


def _reversals(direction, series):
    """Problem types from a MONOTONICITY run, for one declared direction.

    Only reversal findings are asserted on. Observations fed without timestamps
    land near-simultaneously, so `monotonicity_rate` fires on EVERY series here
    including the monotone ones -- an artefact of the fixture, not of the axiom,
    and asserting `findings == []` would be asserting the artefact.
    """
    session = _session(MODEL.replace("decreasing", direction))
    session.add_entity("m1", "Meter", {"remaining": series[-1]})
    session.add_observations("m1", "remaining", series)
    envelope = check(session).to_dict()
    return ([f["problem_type"] for f in envelope["findings"]
             if "reversal" in f["problem_type"]],
            [r["reason"] for r in envelope["not_checked"]
             if r["axiom"] == "MONOTONICITY"])


def _not_the_rate_arm(declined):
    """Reasons other than the rate arm's.

    MONOTONICITY's rate arm declines `no_threshold` when no rate is
    declared, and none of the models here declares one. These tests are about
    `expected_direction`, so the assertion is narrowed to their subject rather
    than deleted -- and narrowed by NAMING the excluded reason, so a second
    unexpected decline still fails.
    """
    return [r for r in declined if r != "no_threshold"]


class TestMonotonicityDecreasing:
    """`expected_direction: decreasing` -- declared, documented, and until now
    never exercised by a test a consumer of the package could run."""

    def test_a_monotone_decline_raises_no_reversal(self):
        found, declined = _reversals("decreasing", [60, 50, 40, 30, 20, 10])
        assert found == [], found
        assert _not_the_rate_arm(declined) == [], (
            f"the axiom declined rather than running: {declined}")

    def test_rises_in_a_decreasing_series_are_reversals(self):
        """The behaviour the direction exists for."""
        found, declined = _reversals("decreasing", [60, 50, 80, 40, 70, 30, 65, 20])
        assert found, "a decreasing indicator did not report repeated rises"
        assert _not_the_rate_arm(declined) == []

    def test_one_rise_is_under_the_declarable_tolerance(self):
        """Not a gap: the tolerance is a declared number and defaults above one.
        Pinned so a later change to that default is visible here rather than as a
        surprise in the arm nobody runs."""
        found, _ = _reversals("decreasing", [60, 50, 40, 55, 30, 20])
        assert found == [], found

    @pytest.mark.parametrize("series,mirrored", [
        ([10, 20, 5, 30, 8, 40, 9, 50], [50, 40, 55, 30, 52, 20, 51, 10]),
    ])
    def test_the_two_directions_behave_alike_on_mirrored_series(self, series, mirrored):
        """The invariant worth having. A sibling axiom was once silent on one
        input shape while seven others declined, and only a comparison across
        the pair could see it -- the same shape one axiom over."""
        up, up_declined = _reversals("increasing", series)
        down, down_declined = _reversals("decreasing", mirrored)
        assert bool(up) == bool(down), (
            f"increasing reported {up} and decreasing reported {down} on "
            f"mirrored series; the directions have diverged")
        assert up_declined == down_declined, (
            f"the directions decline differently on mirrored series: "
            f"{up_declined} vs {down_declined}")
        assert _not_the_rate_arm(up_declined) == []


class TestUnconsumedObservationsEdges:
    def test_no_model_gives_an_empty_report_rather_than_raising(self):
        session = EngineSession()
        assert session.unconsumed_observations() == []

    def test_observations_for_an_entity_never_added_say_so(self):
        """`unknown_entity` is a reason a bridge author can meet, and the
        vocabulary document tells them to expect it."""
        session = _session()
        session.add_observations("ghost", "remaining", [1, 2, 3])
        reasons = {r["reason"] for r in session.unconsumed_observations()}
        assert "unknown_entity" in reasons, reasons


class TestIsDomainModel:
    """Both arms. It exists so a directory scan needs no exceptions, which is
    only true if the False arm actually catches what a scan meets."""

    def test_a_real_model_is_accepted(self):
        assert is_domain_model(textwrap.dedent(MODEL)) is True

    @pytest.mark.parametrize("source", [
        "no-such-file.yaml",          # a short string is read as a path
        "domain: [not, a, mapping]",  # parses, wrong shape
        "{{{ not yaml",               # malformed
    ])
    def test_what_a_scan_meets_is_refused_without_raising(self, source):
        assert is_domain_model(source) is False

    def test_a_companion_file_is_named_as_such_rather_than_crashing(self):
        """The refusal a constraints companion gets. It has to be a distinct
        exception, because a scan tells it apart from a broken file."""
        with pytest.raises(NotADomainModelError) as caught:
            load_domain("domain: some-other-domain\nconstraints: []\n")
        assert "not a mapping" in str(caught.value)

class TestTheAcceptedValuesOfTwoDocumentedFields:
    """`direction:` and `flow:` are documented model fields, and the shipped
    suite exercised only their REJECTION paths -- the branch that warns on a
    typo. What a correct declaration does was never run here, which is the
    stranger gap of the two: the published worked example declares `flow: in`
    and `flow: out` on its own tank.
    """

    @pytest.mark.parametrize("declared,expected", [
        ("UPPER", "UPPER"), ("lower", "LOWER"),
        ("bidirectional", "BIDIRECTIONAL"),
    ])
    def test_a_valid_direction_survives_loading(self, declared, expected):
        from arbiter_engine.ontology.domain_loader import (
            resolve_direction)
        assert resolve_direction(declared) == expected

    def test_an_absent_direction_defaults_rather_than_failing(self):
        from arbiter_engine.ontology.domain_loader import (
            resolve_direction)
        assert resolve_direction(None) == "BIDIRECTIONAL"
        assert resolve_direction("") == "BIDIRECTIONAL"

    def test_an_unknown_direction_falls_back_without_raising(self):
        """The arm that WAS covered, kept beside the others so the pair reads as
        one behaviour rather than two half-tested ones."""
        from arbiter_engine.ontology.domain_loader import (
            resolve_direction)
        assert resolve_direction("sideways") == "BIDIRECTIONAL"

    @pytest.mark.parametrize("declared", ["in", "out", " IN ", "Out"])
    def test_a_valid_flow_survives_loading(self, declared):
        from arbiter_engine.ontology.domain_loader import (
            _resolve_flow_direction as resolve_flow)
        assert resolve_flow(declared) == declared.strip().lower()

    def test_an_unknown_flow_is_treated_as_absent_not_coerced(self):
        """`inbound` must NOT become `in`. Coercing by prefix would be the same
        inference the engine removed one layer up, and the author would believe
        they had declared something exact."""
        from arbiter_engine.ontology.domain_loader import (
            _resolve_flow_direction as resolve_flow)
        assert resolve_flow("inbound") is None
        assert resolve_flow(None) is None
