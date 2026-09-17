"""The clock has one provider, and moving it moves every window in the engine.

Replay and backtest both need the same thing: feed history once with real
timestamps, then ask the engine what it would have said at each step. Every
window, retention cut-off and grading deadline is anchored at ``now_utc()``, so
the whole of that requirement is *make ``now_utc`` answer a different question*.

WHY THESE ASSERTIONS GO THROUGH OTHER MODULES

Twenty-five modules bind ``now_utc`` at import with ``from ... import now_utc``.
A test that freezes the clock and then asks the clock module what time it is
proves nothing about any of them -- it exercises the one caller that was never
at risk. So the load-bearing assertions below read the clock through a module
that imported it the ordinary way, which is the only shape that can fail if the
seam is ever moved back to the name instead of the provider.

The last test is the one a module global would fail: a freeze must not reach a
thread that never asked for one.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest

from arbiter_engine.clock import (
    as_naive_utc, as_of, clock_is_frozen, now_utc,
)
from arbiter_engine.history.observation import InMemoryObservationHistory

FIXED = datetime(2026, 3, 4, 5, 6, 7)


def test_the_clock_reads_the_frozen_instant_inside_the_block():
    with as_of(FIXED):
        assert now_utc() == FIXED
    assert now_utc() != FIXED


def test_the_block_yields_the_instant_it_normalised():
    with as_of(FIXED) as yielded:
        assert yielded == FIXED


def test_an_aware_instant_is_converted_and_not_stripped():
    """The engine's whole clock convention in one assertion. Stripping keeps
    the local wall-clock reading and discards the zone that explains it, which
    moves the instant by the offset -- eight hours, here."""
    aware = datetime(2026, 3, 4, 5, 6, 7, tzinfo=timezone(timedelta(hours=8)))
    with as_of(aware):
        assert now_utc() == datetime(2026, 3, 3, 21, 6, 7)
        assert now_utc() == as_naive_utc(aware)


def test_a_nested_block_restores_the_outer_freeze_not_the_wall_clock():
    """A replay that steps a sub-window must come back to the step it was on.
    Restoring to the wall clock would end the replay silently, and every
    window after it would be measured against today."""
    inner = datetime(2020, 1, 1)
    with as_of(FIXED):
        with as_of(inner):
            assert now_utc() == inner
        assert now_utc() == FIXED


def test_the_freeze_is_reported_rather_than_inferred():
    assert not clock_is_frozen()
    with as_of(FIXED):
        assert clock_is_frozen()
    assert not clock_is_frozen()


def test_the_clock_is_restored_when_the_block_raises():
    with pytest.raises(RuntimeError):
        with as_of(FIXED):
            raise RuntimeError("boom")
    assert not clock_is_frozen()


# --- the assertions that matter: a consumer that imported by name ----------

def test_a_history_window_follows_the_injected_clock():
    """``get_values`` computes ``cutoff = now_utc() - window`` and imported
    ``now_utc`` by name. This is the claim the replay design rests on: the
    history needs NO change to follow the clock.

    Three readings an hour apart around the frozen instant. A one-hour window
    at that instant must see the two inside it and not the one two hours back.
    """
    history = InMemoryObservationHistory()
    for offset_h, value in ((-2, 10.0), (-0.5, 20.0), (-0.1, 30.0)):
        history.add("e1", "temp", value,
                    timestamp=FIXED + timedelta(hours=offset_h))
    with as_of(FIXED):
        inside = history.get_values("e1", "temp", timedelta(hours=1))
    assert sorted(value for _, value in inside) == [20.0, 30.0]


def test_the_same_window_sees_nothing_at_the_wall_clock():
    """The other half, and the one that fails if the freeze does not reach the
    history: the same readings are far in the past for a live caller, so an
    unfrozen window is empty. A test that only asserted the frozen case would
    pass against a history that ignored the clock and returned everything."""
    history = InMemoryObservationHistory()
    history.add("e1", "temp", 20.0, timestamp=FIXED - timedelta(minutes=30))
    assert history.get_values("e1", "temp", timedelta(hours=1)) == []
    with as_of(FIXED):
        frozen = history.get_values("e1", "temp", timedelta(hours=1))
    assert [value for _, value in frozen] == [20.0]


def test_a_freeze_does_not_reach_another_thread():
    """The reason the provider is a context variable and not a module global.

    This engine is imported by a long-lived server whose tools are called
    independently. Under a global, one caller replaying last Tuesday moves
    every concurrent caller's windows to last Tuesday -- and the symptom is a
    check declining ``insufficient_samples`` on a live feed, which reads
    exactly like a quiet channel.
    """
    seen = {}

    def read():
        seen["frozen"] = clock_is_frozen()
        seen["now"] = now_utc()

    with as_of(FIXED):
        worker = threading.Thread(target=read)
        worker.start()
        worker.join()
        assert now_utc() == FIXED

    assert seen["frozen"] is False
    assert seen["now"] != FIXED
