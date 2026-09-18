"""A derived series can be empty two ways, and the decline has to say which.

MODELING.md has promised this since `align_tolerance` landed:

    Declare it too tightly and the operands are all present while the joined
    series is empty; the decline says how many points each operand had and how
    many survived, which is the only way to tell that apart from a feed that
    stopped.

`DerivedHistoryView.alignment()` computed exactly those figures and had no
caller anywhere in the package -- only its own unit test. So both cases
declined `insufficient_samples` with the same counts, and the sentence
described nothing. Measured before the fix: a 1s tolerance against operands 30s
apart, and an operand never fed at all, produced BYTE-IDENTICAL declines.

The two repairs are different and that is the whole point of telling them
apart: one is *widen `align_tolerance`*, the other is *fix the feed*. A reader
handed `n: 0` twice has no way to choose, and the more likely reading -- the
feed -- sends them looking for a fault in a collector that is working.

Same shape as finding I in 0.1.15, where the calendar was parsed, exported, and
never joined: a computed thing with no reader, promised in the documentation.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from arbiter_engine.api import EngineSession, check, project
from arbiter_engine.clock import as_of

NOW = datetime(2026, 9, 17, 12, 0)
TOLERANCE_S = 1.0
OFFSET_S = 30          # operands this far apart cannot pair within 1s


def _model(axioms):
    return {"domain": {
        "id": "rig", "name": "rig", "entity_types": ["Rig"],
        "indicators": {"Rig": [
            {"name": "inlet_c", "type": "NUMERIC", "axioms": [],
             "window": "2h"},
            {"name": "outlet_c", "type": "NUMERIC", "axioms": [],
             "window": "2h"},
            {"name": "drop_c", "type": "NUMERIC",
             "derived": "inlet_c - outlet_c", "align_tolerance": "1s",
             "axioms": axioms, "window": "2h",
             "homeostasis": {"setpoint": 0.0, "tolerance": 0.5},
             "dynamics": {"model": "local_level"},
             "horizon": "1h", "lookback": "2h"}]}}}


def _session(*, axioms, offset_s, feed_outlet=True, points=40):
    session = EngineSession()
    session.load_model(_model(axioms))
    session.add_entity("rig_1", "Rig", {})
    inlet = [(NOW - timedelta(minutes=points - i), 50.0 + i * 0.01)
             for i in range(points)]
    session.add_observations("rig_1", "inlet_c", inlet)
    if feed_outlet:
        session.add_observations("rig_1", "outlet_c", [
            (stamp + timedelta(seconds=offset_s), value - 0.2)
            for stamp, value in inlet])
    return session


def _starved(payload, key="not_checked"):
    for decline in payload.get(key, []):
        if decline.get("reason") == "insufficient_samples":
            return decline
    raise AssertionError(f"no insufficient_samples decline in {payload!r}")


class TestProjectSaysWhichOperandStarved:

    def _decline(self, **kw):
        session = _session(axioms=["HOMEOSTASIS"], **kw)
        with as_of(NOW):
            payload = project(session, horizon_s=3600.0).to_dict()
        return _starved(payload["projection"])

    def test_a_tight_tolerance_shows_both_operands_present(self):
        evidence = self._decline(offset_s=OFFSET_S)["evidence"]
        assert evidence["operands"] == {"inlet_c": 40, "outlet_c": 40}, (
            "both feeds delivered; the join is what came back empty")
        assert evidence["aligned"] == 0
        assert evidence["align_tolerance_s"] == TOLERANCE_S

    def test_a_stopped_feed_shows_the_operand_that_stopped(self):
        evidence = self._decline(offset_s=0, feed_outlet=False)["evidence"]
        assert evidence["operands"] == {"inlet_c": 40, "outlet_c": 0}, (
            "the second operand was never fed and the decline must name it")
        assert evidence["aligned"] == 0

    def test_the_two_cases_are_distinguishable(self):
        """The assertion the documentation actually makes. Stated against the
        whole evidence block rather than one key, because any future change
        that collapses them again should fail here."""
        tight = self._decline(offset_s=OFFSET_S)["evidence"]
        stopped = self._decline(offset_s=0, feed_outlet=False)["evidence"]
        assert tight != stopped, (
            "a too-tight `align_tolerance` and an operand feed that stopped "
            "produced identical declines; MODELING.md says this decline is "
            "'the only way to tell that apart'")

    def test_a_fed_property_carries_no_alignment(self):
        """Non-vacuity, and a bound on the change. A property nobody derives
        has no join, so inventing figures for it would be the same defect
        pointing the other way."""
        session = _session(axioms=["HOMEOSTASIS"], offset_s=0, points=2)
        with as_of(NOW):
            payload = project(session, horizon_s=3600.0).to_dict()
        for decline in payload["projection"].get("not_checked", []):
            if decline.get("property") == "inlet_c":
                assert "operands" not in (decline.get("evidence") or {})


class TestTheAxiomsSayItToo:
    """`project` is one reader of a starved series; the temporal axioms are
    four more, and they decline through `sampling_context`. Fixing only the
    projection side would leave `check` -- the verb almost everybody calls --
    still unable to tell the two apart.
    """

    def _decline(self, **kw):
        session = _session(axioms=["STABILITY"], **kw)
        with as_of(NOW):
            payload = check(session).to_dict()
        for decline in payload.get("not_checked", []):
            if (decline.get("indicator") == "drop_c"
                    and decline.get("reason") == "insufficient_samples"):
                return decline
        raise AssertionError("STABILITY did not decline insufficient_samples")

    def test_a_tight_tolerance_shows_both_operands_present(self):
        alignment = self._decline(offset_s=OFFSET_S)["alignment"]
        assert alignment["operands"] == {"inlet_c": 40, "outlet_c": 40}
        assert alignment["aligned"] == 0

    def test_a_stopped_feed_shows_the_operand_that_stopped(self):
        alignment = self._decline(offset_s=0, feed_outlet=False)["alignment"]
        assert alignment["operands"] == {"inlet_c": 40, "outlet_c": 0}

    def test_the_two_cases_are_distinguishable(self):
        tight = self._decline(offset_s=OFFSET_S)["alignment"]
        stopped = self._decline(offset_s=0, feed_outlet=False)["alignment"]
        assert tight != stopped


class TestWideningTheToleranceActuallyRepairsIt:
    """The remedy the figures point at has to work, or the decline is sending
    a reader somewhere that does not help. This is the half a test asserting
    only the decline's CONTENTS would miss."""

    def test_a_tolerance_that_spans_the_gap_joins_the_series(self):
        session = EngineSession()
        model = _model(["HOMEOSTASIS"])
        spec = model["domain"]["indicators"]["Rig"][2]
        spec["align_tolerance"] = "60s"
        session.load_model(model)
        session.add_entity("rig_1", "Rig", {})
        inlet = [(NOW - timedelta(minutes=40 - i), 50.0 + i * 0.01)
                 for i in range(40)]
        session.add_observations("rig_1", "inlet_c", inlet)
        session.add_observations("rig_1", "outlet_c", [
            (stamp + timedelta(seconds=OFFSET_S), value - 0.2)
            for stamp, value in inlet])
        with as_of(NOW):
            history = session.reading_history()
            joined = history.get_values("rig_1", "drop_c", timedelta(hours=2))
        assert len(joined) == 40, (
            f"widening `align_tolerance` past the {OFFSET_S}s gap should pair "
            f"every point; got {len(joined)}")
