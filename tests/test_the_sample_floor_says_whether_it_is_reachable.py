"""A sample-floor decline that says whether the floor can ever be met.

`observations 0 of 10` reads as *collect more data*, and on a series sampled
sparser than the window it is permanently wrong: no amount of further collection
puts ten samples inside thirty minutes at one an hour. Two axioms already said so
-- HOMEOSTASIS and MONOTONICITY carried the window, the total and the interval --
and two declined with the bare counts, so the same starved input produced an
interpretable answer or an uninterpretable one depending on which axiom reached
it first.

**The scope of this was measured, and it was smaller than the ask claimed.**
RESPONSIVENESS was listed as attaching nothing; it declines `missing_property`,
where a sampling interval would be a fact about a property that has no value.
MONOTONICITY was listed as missing the interval; it attaches one as soon as two
observations exist, and the probe that said otherwise had fed none. What was
actually missing was CONSERVATION and STABILITY.

Each axiom counts against a DIFFERENT window -- STABILITY reads the indicator's
`window:`, CONSERVATION its own accounting window, HOMEOSTASIS a baseline in days
-- so the fix is not one field filled from one source. A window copied from the
wrong place would be a precise wrong number, which is worse than the silence it
replaced.
"""
from __future__ import annotations

import pytest

yaml = pytest.importorskip("yaml")

from arbiter_engine.api import EngineSession, check  # noqa: E402


def _declines(model, feeds, axiom):
    session = EngineSession()
    session.load_model(yaml.safe_dump(model))
    session.add_entity("t", "T", {k: v for k, (v, _) in feeds.items()}, "t")
    for name, (value, interval) in feeds.items():
        session.add_observations("t", name, [value] * 4, interval_seconds=interval)
    return [d for d in check(session).to_dict()["not_checked"]
            if d.get("axiom") == axiom and d.get("reason") == "insufficient_samples"]


STABILITY_MODEL = {"domain": {
    "id": "reach", "name": "reach", "entity_types": ["T"],
    "relationship_types": ["r"],
    "indicators": {"T": [{"name": "v", "type": "NUMERIC", "axioms": ["STABILITY"],
                          "window": "30m", "expect_variation": True}]}}}

CONSERVATION_MODEL = {"domain": {
    "id": "reach", "name": "reach", "entity_types": ["T"],
    "relationship_types": ["r"],
    "indicators": {"T": [
        {"name": "i", "type": "NUMERIC", "axioms": ["CONSERVATION"], "flow": "in",
         "conservation": {"input_property": "i", "output_properties": ["o"]}},
        {"name": "o", "type": "NUMERIC", "flow": "out"}]}}}


class TestStabilitySaysWhetherTheFloorFits:
    def test_a_cadence_wider_than_the_window_is_named_unreachable(self):
        found = _declines(STABILITY_MODEL, {"v": (1.0, 3600.0)}, "STABILITY")
        assert len(found) == 1, "the decline this file is about did not occur"
        assert found[0]["floor_unreachable_at_this_rate"] is True
        assert found[0]["window_seconds"] == 1800.0
        assert found[0]["sampling_interval_seconds"] == 3600.0

    def test_a_cadence_that_fits_is_not_named_unreachable(self):
        """The control. Without it, a check that marked everything unreachable
        would pass the test above."""
        found = _declines(STABILITY_MODEL, {"v": (1.0, 60.0)}, "STABILITY")
        assert len(found) == 1
        assert not found[0].get("floor_unreachable_at_this_rate", False)
        assert found[0]["sampling_interval_seconds"] == 60.0

    def test_the_remedy_names_both_ways_out(self):
        found = _declines(STABILITY_MODEL, {"v": (1.0, 3600.0)}, "STABILITY")
        remedy = str(found[0].get("remedy", ""))
        assert "sample more often" in remedy and "widen the window" in remedy


class TestConservationCountsAgainstItsOwnWindow:
    def test_the_window_reported_is_the_accounting_window(self):
        """CONSERVATION does not read the indicator's `window:`; it has its own.
        Reporting the indicator's would be a precise wrong answer."""
        found = _declines(CONSERVATION_MODEL,
                          {"i": (1.0, 3600.0), "o": (1.0, 3600.0)}, "CONSERVATION")
        assert len(found) == 1
        assert found[0]["window_seconds"] == 300.0
        assert found[0]["sampling_interval_seconds"] == 3600.0

    def test_a_floor_of_one_is_never_unreachable(self):
        """Arithmetic, asserted because it is the case most likely to be wrong
        by copy-paste: spanning one sample takes no time, so no cadence can make
        a floor of one impossible. It is simply not observed yet."""
        found = _declines(CONSERVATION_MODEL,
                          {"i": (1.0, 3600.0), "o": (1.0, 3600.0)}, "CONSERVATION")
        assert found[0]["required"] == 1
        assert not found[0].get("floor_unreachable_at_this_rate", False)


class TestItNeverAssertsWhatItHasNotComputed:
    def test_without_an_interval_there_is_no_verdict(self):
        """A single observation yields no interval, and the claim *this can
        never be met* must not be made from an unknown rate."""
        session = EngineSession()
        session.load_model(yaml.safe_dump(STABILITY_MODEL))
        session.add_entity("t", "T", {"v": 1.0}, "t")
        session.add_observations("t", "v", [1.0], interval_seconds=3600.0)
        found = [d for d in check(session).to_dict()["not_checked"]
                 if d.get("axiom") == "STABILITY"
                 and d.get("reason") == "insufficient_samples"]
        assert len(found) == 1
        assert "sampling_interval_seconds" not in found[0]
        assert not found[0].get("floor_unreachable_at_this_rate", False)


class TestTheHelperSeesAStateSeries:
    def test_a_state_history_yields_a_total_rather_than_a_zero(self):
        """`sampling_context` reads numeric values first. A STATE series is
        stored apart from them, so without the fallback the state arm of
        STABILITY would report `total_observations: 0` about a property with a
        full history -- a wrong number where none was the honest answer."""
        from datetime import datetime, timedelta, timezone

        from arbiter_engine.interfaces import (
            Observation, sampling_context,
        )
        from arbiter_engine.history.observation import (
            InMemoryObservationHistory,
        )
        history = InMemoryObservationHistory()
        # Timezone-aware, and not a style choice: `utcnow()` is deprecated from
        # 3.12 and this suite runs with warnings as errors, so it passed on the
        # one interpreter it was written against and failed on the other two the
        # matrix runs. The sibling tests already build timestamps this way.
        base = datetime.now(timezone.utc) - timedelta(hours=3)
        for i in range(4):
            history.add_observation(Observation(
                entity_id="e1", entity_type="T", property_name="phase",
                property_type="state", value="Running",
                timestamp=base + timedelta(minutes=30 * i)))
        assert len(history.get_states("e1", "phase", timedelta(hours=4))) == 4, (
            "the fixture recorded no states, so what follows would be asserting "
            "about an empty history rather than about the fallback")
        context = sampling_context(history, "e1", "phase", timedelta(minutes=30))
        assert context["total_observations"] == 4
        assert context["sampling_interval_seconds"] == 1800.0
