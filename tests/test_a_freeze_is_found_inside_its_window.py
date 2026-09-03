"""`expect_variation` answers *has this ever moved*, and the window is the lever.

The modelling guide said *a reading that never moves is a dead probe
rather than a very steady system*, and a plant reads that as **tell me when a
sensor freezes**. The check reads the observations inside the indicator's
`window:`, so a series that varied and then went flat still contains variation
and the axiom stays quiet until every varying sample has aged out. A probe that
died twenty minutes into an hour-long window is not reported for forty more.

The guide now says so, and says the remedy: narrow the window. **This file is
why the guide is allowed to say it.** Both halves of that advice are behaviour --
that a narrower window finds the freeze, and that too narrow a one declines
`insufficient_samples` instead of answering -- and a behaviour stated in a
document with nothing running against it is the second copy of a fact that this
project keeps watching drift.

Found from outside, by an independent bridge whose fault injector flattened only
the tail of a corpus and produced a fault leg that was green having tested
nothing.
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import io
import random

import pytest

from arbiter_engine.api import EngineSession, check

NOW = _dt.datetime.now(_dt.timezone.utc)
CADENCE_S = 60.0

MODEL = """
domain:
  id: freeze-window-probe
  name: Freeze window probe
  entity_types: [Sensor]
  indicators:
    Sensor:
      - name: weld_current_a
        type: NUMERIC
        axioms: [STABILITY]
        expect_variation: true
{window}"""


def _series(varied: int, flat: int, seed: int = 3):
    """`varied` noisy samples, then `flat` identical ones. A probe that died."""
    rng = random.Random(seed)
    return [8500.0 + rng.gauss(0, 380.0) for _ in range(varied)] + [8500.0] * flat


def _run(values, window: str | None = None) -> dict:
    block = f"        window: {window}\n" if window else ""
    session = EngineSession()
    with contextlib.redirect_stderr(io.StringIO()):
        session.load_model(MODEL.format(window=block))
        session.add_entity("s1", "Sensor",
                           properties={"weld_current_a": values[-1]})
        n = len(values)
        session.add_observations("s1", "weld_current_a", [
            (NOW - _dt.timedelta(seconds=CADENCE_S * (n - 1 - i)), v)
            for i, v in enumerate(values)])
        return check(session).to_dict()


def _fired(envelope) -> bool:
    return any(f["problem_type"].startswith("frozen_series")
               for f in envelope["findings"])


def _reasons(envelope):
    return [d["reason"] for d in envelope["not_checked"]]


class TestAFreezeIsInvisibleWhileTheWindowStillHoldsMovement:
    def test_a_series_flat_throughout_is_found(self):
        """The case the guide's sentence plainly covers, and the only one the
        arm found before anybody asked about the others."""
        assert _fired(_run([8500.0] * 50))

    @pytest.mark.parametrize("flat", [5, 10, 20, 30, 40, 45, 49])
    def test_a_series_that_varied_and_then_stopped_is_not(self, flat):
        """One varying sample left in the window is enough to keep it quiet, and
        that holds right up to the last one."""
        assert not _fired(_run(_series(50 - flat, flat)))


class TestTheWindowIsTheLever:
    """Fifty samples at a minute apart: thirty that varied, then twenty flat.
    A probe that died twenty minutes ago."""

    SERIES = staticmethod(lambda: _series(30, 20))

    def test_no_window_declared_stays_quiet(self):
        assert not _fired(_run(self.SERIES()))

    @pytest.mark.parametrize("window", ["10m", "15m"])
    def test_a_window_inside_the_flat_run_finds_it(self, window):
        envelope = _run(self.SERIES(), window)
        assert _fired(envelope), (
            f"window {window} covers only flat samples and the freeze was not "
            f"reported; the guide's remedy does not work")
        assert _reasons(envelope) == []

    @pytest.mark.parametrize("window", ["30m", "1h"])
    def test_a_window_that_still_reaches_the_movement_does_not(self, window):
        assert not _fired(_run(self.SERIES(), window))

    def test_too_narrow_declines_rather_than_answering(self):
        """The floor under the lever, and the half a reader would meet second.
        Narrowing past the sample floor does not make the check sharper, it
        stops it running -- and it says so rather than passing."""
        envelope = _run(self.SERIES(), "5m")
        assert not _fired(envelope)
        assert _reasons(envelope) == ["insufficient_samples"]

    def test_the_window_and_the_cadence_are_a_pair(self):
        """The same span is usable or not depending on how often you collect.
        Five minutes holds five samples at a minute apart and thirty at ten
        seconds apart, and only one of those clears the floor."""
        fast = _series(30, 20)
        session = EngineSession()
        with contextlib.redirect_stderr(io.StringIO()):
            session.load_model(MODEL.format(window="        window: 5m\n"))
            session.add_entity("s1", "Sensor",
                               properties={"weld_current_a": fast[-1]})
            n = len(fast)
            session.add_observations("s1", "weld_current_a", [
                (NOW - _dt.timedelta(seconds=10.0 * (n - 1 - i)), v)
                for i, v in enumerate(fast)])
            envelope = check(session).to_dict()
        assert _reasons(envelope) == [], (
            "at a ten-second cadence a five-minute window holds thirty samples "
            "and should evaluate; it declined, so the pairing advice is wrong")
