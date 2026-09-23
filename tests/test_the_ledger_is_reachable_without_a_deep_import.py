"""The one number that grades this engine, and how far away it was.

`calibration` scores this engine's own forecasts against a
parameter-free random walk. It rides on every envelope. And until this release
the only way to make it non-null was:

    session.ledger = SqlitePredictionLedger(path)

an attribute assigned from a module path the README itself calls importable and
unsupported. `EngineSession.__init__` took a `history` argument and not a
`ledger` one, though both are stores and both have a durable implementation
shipped beside the in-memory default. TWO outside reviews wrote the same
sentence about it, a round apart.

`EngineSession(ledger=...)` now takes it, and `SqlitePredictionLedger` is a
supported name. **The default is unchanged**, which is the part worth a test of
its own: a caller who passes nothing still gets an in-memory ledger, and a
one-shot process still reports every rate null -- correctly, because nothing in
that run matured. A promotion that quietly made calibration start working would
be a behaviour change wearing an ergonomics costume.

- THE TWO FACTS BELOW COST THREE ATTEMPTS EACH. The author burned
three probes discovering the grace window and an outside reviewer burned two;
both then reported it as *a thing a consumer discovers by trial*. They are in
the README now, and pinned here so the prose and the behaviour move together.
"""

from __future__ import annotations

import inspect
import os
import pathlib
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

from arbiter_engine.api import (
    EngineSession, InMemoryObservationHistory)
from arbiter_engine.residual.predict_vs_mirror import PredictionLedger
from arbiter_engine.residual.sqlite_ledger import SqlitePredictionLedger

NOW = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)


def _readme() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / "README.md",
                      here.parents[2] / "docs" / "publication" / "README-merged.md"):
        if candidate.is_file():
            return candidate
    raise AssertionError("no README found in this tree")


def _db() -> str:
    return os.path.join(tempfile.mkdtemp(), "ledger.db")


def _file_one(ledger, predicted_at, horizon_s=60.0):
    return ledger.record_value_prediction(
        entity_id="t", property_name="v", predicted_value=80.0,
        tolerance=5.0, horizon_s=horizon_s, predicted_at=predicted_at)


class TestTheSessionTakesALedger:

    def test_the_constructor_accepts_one(self):
        assert "ledger" in inspect.signature(EngineSession.__init__).parameters

    def test_passing_nothing_is_unchanged(self):
        """The load-bearing half. The old default was in-memory and it still
        is; a promotion that turned persistence on for everybody would change
        what `calibration` reports for every existing caller."""
        assert type(EngineSession().ledger) is PredictionLedger

    def test_what_is_passed_is_what_is_used(self):
        durable = SqlitePredictionLedger(_db())
        assert EngineSession(ledger=durable).ledger is durable

    def test_history_still_works_beside_it(self):
        """Two injectable stores, and adding the second must not have moved
        the first."""
        history = InMemoryObservationHistory()
        session = EngineSession(history=history, ledger=SqlitePredictionLedger(_db()))
        assert session.history is history


class TestItOutlivesTheProcess:
    """The reason a durable ledger exists at all. Run in a real subprocess,
    because *survives being assigned to a second object* is a weaker claim
    than *survives the interpreter exiting* and the weaker one is the easier
    thing to accidentally test."""

    def test_a_record_filed_by_a_process_that_exited_is_still_there(self):
        path = _db()
        module = SqlitePredictionLedger.__module__
        program = (
            f"from {module} import SqlitePredictionLedger\n"
            "from datetime import datetime, timezone\n"
            f"led = SqlitePredictionLedger({path!r})\n"
            "led.record_value_prediction(entity_id='t', property_name='v',\n"
            "    predicted_value=80.0, tolerance=5.0, horizon_s=60.0,\n"
            "    predicted_at=datetime(2026, 9, 23, 11, 50, tzinfo=timezone.utc))\n"
            "led.close()\n")
        env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path),
                   PYTHONDONTWRITEBYTECODE="1")
        done = subprocess.run([sys.executable, "-c", program],
                              capture_output=True, text=True, env=env)
        assert done.returncode == 0, done.stderr

        reopened = SqlitePredictionLedger(path)
        assert len(reopened.records()) == 1, (
            "the record did not survive the process that filed it")


class TestTheGradingWindow:
    """Both sides of both facts, because a one-sided version of
    either reads as *grading is broken*."""

    def test_the_default_grace_is_sixty_seconds(self):
        assert SqlitePredictionLedger(_db()).grace_s == 60.0

    @pytest.mark.parametrize("past_horizon,expected", [
        (30, None), (59, None), (61, "confirmed")])
    def test_nothing_is_graded_until_the_grace_window_closes(
            self, past_horizon, expected):
        ledger = SqlitePredictionLedger(_db())
        at = NOW - timedelta(seconds=60 + past_horizon)
        _file_one(ledger, at)
        history = InMemoryObservationHistory()
        history.add("t", "v", 79.0, at + timedelta(seconds=60))
        ledger.grade_matured(problems=[], observed_entity_ids={"t"},
                             now=NOW, histories=[history])
        assert ledger.records()[0].verdict == expected

    @pytest.mark.parametrize("read_at,expected", [
        (60, "falsified"), (200, "ungradeable")])
    def test_a_reading_outside_the_window_grades_nothing(self, read_at, expected):
        """Same wildly wrong value both times. Inside the window it falsifies;
        outside it, not having looked at the right instant is not evidence
        about what was there."""
        ledger = SqlitePredictionLedger(_db())
        at = NOW - timedelta(seconds=600)
        _file_one(ledger, at)
        history = InMemoryObservationHistory()
        history.add("t", "v", 999.0, at + timedelta(seconds=read_at))
        ledger.grade_matured(problems=[], observed_entity_ids={"t"},
                             now=NOW, histories=[history])
        assert ledger.records()[0].verdict == expected


class TestTheReadmeSaysAllOfIt:
    """The prose and the behaviour, held together. Each of these was written
    down because somebody lost time to not knowing it."""

    @pytest.mark.parametrize("claim", [
        "EngineSession(ledger=",
        "grace_s",
        "ungradeable",
    ])
    def test_the_readme_states_it(self, claim):
        assert claim in _readme().read_text(encoding="utf-8"), claim

    def test_the_readme_still_says_the_default_is_not_wired(self):
        """Two-sided against the promotion. The name is supported now; the
        ledger is still not wired in by default, and a README that stopped
        saying so would be advertising persistence nobody gets."""
        text = _readme().read_text(encoding="utf-8")
        assert "A prediction ledger wired in by default." in text
