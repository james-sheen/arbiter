"""The ingestion boundary takes real timestamps, and normalises zones.

`add_observations` accepted uniform-interval batches only: a list of readings,
spaced `interval_seconds` apart, ending now. That is the shape a test has. Real
telemetry is timestamped snapshots — the scrape takes as long as it takes, gaps
exist, and back-filling a batch is normal — and reconstructing it as a ladder
ending at *now* moves every reading. The axioms that read a window then answer
about a series nobody supplied.

The second half is the zone. This engine stores naive UTC and says so; what it
did not have was a caller-facing place to hand it an aware datetime. Converting
at this boundary is what lets every comparison downstream assume naive-UTC on
both sides without checking — and the alternative, stripping the zone, was
measured producing three verdicts for one instant.

Runs against both trees; see this suite's conftest for why that matters.
"""

from datetime import datetime, timedelta, timezone

import pytest

from arbiter_engine.api import EngineSession
from arbiter_engine.clock import now_utc

FIXED = datetime(2026, 8, 19, 12, 0, 0)
PLUS_EIGHT = timezone(timedelta(hours=8))
MINUS_FIVE = timezone(timedelta(hours=-5))


def _stored(session: EngineSession, entity: str, prop: str) -> list:
    """The (timestamp, value) pairs the history actually holds."""
    return list(session.history._history[(entity, prop)])


class TestTheBareShapeIsUnchanged:
    """A released signature, pinned inside the change that widens it."""

    def test_a_list_of_readings_still_loads(self):
        session = EngineSession()
        session.add_observations("e", "p", [1.0, 2.0, 3.0])
        assert [v for _, v in _stored(session, "e", "p")] == [1.0, 2.0, 3.0]

    def test_the_interval_still_spaces_them(self):
        session = EngineSession()
        session.add_observations("e", "p", [1.0, 2.0, 3.0], interval_seconds=30)
        stamps = [t for t, _ in _stored(session, "e", "p")]
        assert (stamps[1] - stamps[0]).total_seconds() == 30
        assert (stamps[2] - stamps[1]).total_seconds() == 30

    def test_an_empty_series_is_a_no_op(self):
        session = EngineSession()
        session.add_observations("e", "p", [])
        assert ("e", "p") not in session.history._history


class TestTimestampedSamples:
    def test_a_pair_series_keeps_the_supplied_instants(self):
        """The point of the whole item. A collector's timestamps survive
        instead of being replaced by a ladder ending now."""
        session = EngineSession()
        samples = [(FIXED - timedelta(seconds=i * 37), float(i)) for i in range(4)]
        session.add_observations("e", "p", samples)
        assert sorted(t for t, _ in _stored(session, "e", "p")) == sorted(
            when for when, _ in samples)

    def test_irregular_spacing_survives(self):
        """A uniform ladder cannot represent a gap, and a gap is the normal
        state of a real scrape. If this were re-spaced, a window-reading axiom
        would count samples that were never in the window."""
        session = EngineSession()
        offsets = [0, 5, 400, 405, 410]
        session.add_observations("e", "p", [
            (FIXED - timedelta(seconds=o), 1.0) for o in offsets])
        stamps = sorted(t for t, _ in _stored(session, "e", "p"))
        gaps = [(b - a).total_seconds() for a, b in zip(stamps, stamps[1:])]
        assert 395 in gaps, "the gap was re-spaced away"

    def test_posix_timestamps_are_accepted(self):
        """A collector that speaks JSON has a float, not a datetime, and
        making it construct one is friction at the boundary least able to
        afford it."""
        session = EngineSession()
        epoch = datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        session.add_observations("e", "p", [(epoch, 1.0)])
        assert _stored(session, "e", "p")[0][0] == FIXED


class TestZonesAreConvertedNotStripped:
    """One instant, three spellings, one stored value.

    Stripping the zone keeps the local wall-clock reading and discards the fact
    that explains it. Measured before the clock module existed: the same
    instant written as `Z`, `+08:00` and `-05:00` produced a finding, no
    finding at all, and a finding at twice the severity.
    """

    @pytest.mark.parametrize("zone", [timezone.utc, PLUS_EIGHT, MINUS_FIVE])
    def test_every_spelling_of_one_instant_stores_the_same_value(self, zone):
        instant = datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc)
        session = EngineSession()
        session.add_observations("e", "p", [(instant.astimezone(zone), 1.0)])
        assert _stored(session, "e", "p")[0][0] == FIXED

    def test_what_is_stored_is_naive(self):
        """Every comparison downstream assumes naive-UTC on both sides without
        checking. An aware value reaching the store would raise a TypeError
        deep in an axiom, which is the failure this boundary exists to
        prevent."""
        session = EngineSession()
        session.add_observations(
            "e", "p", [(datetime(2026, 8, 19, 12, tzinfo=PLUS_EIGHT), 1.0)])
        assert _stored(session, "e", "p")[0][0].tzinfo is None

    def test_a_naive_value_passes_through_unchanged(self):
        """Guessing that a naive value meant local time would silently move
        instants that are correct today."""
        session = EngineSession()
        session.add_observations("e", "p", [(FIXED, 1.0)])
        assert _stored(session, "e", "p")[0][0] == FIXED


class TestTheShapesAreNotGuessedBetween:
    def test_a_mixed_series_raises(self):
        """A list whose first element is a pair and whose fifth is a float is
        a caller bug. Reading the pair as a value would put a tuple into the
        history for an axiom to trip over three layers down, which is the
        expensive way to find out."""
        session = EngineSession()
        with pytest.raises(ValueError, match="mix of bare readings"):
            session.add_observations("e", "p", [(FIXED, 1.0), 2.0])

    def test_a_two_element_vector_is_not_read_as_a_pair(self):
        """`[[1, 2], [3, 4]]` means two readings of a vector. The pair rule is
        SHAPE plus a plausible date, not `any sequence of length two` — an
        unbounded rule would silently reinterpret a caller's data."""
        from arbiter_engine.api import _is_timestamped
        assert _is_timestamped([1, 2]) is False
        assert _is_timestamped([1755604800.0, 2.0]) is True

    def test_a_short_string_is_not_a_pair(self):
        """A string has a length and is indexable, so a two-character reading
        would otherwise unpack."""
        from arbiter_engine.api import _is_timestamped
        assert _is_timestamped("ok") is False

    def test_a_bool_is_not_a_timestamp(self):
        """`True` is an `int` in Python and compares greater than nothing
        useful; excluded explicitly so a `(flag, value)` pair is not read as a
        date."""
        from arbiter_engine.api import _is_timestamped
        assert _is_timestamped([True, 1.0]) is False


class TestTheAxiomsSeeTheRealWindow:
    """One transform out. The store holding the right instants only matters if
    a window-reading axiom then answers about them."""

    def test_samples_outside_the_window_are_not_counted(self):
        """The defect this closes, end to end. Under the ladder every sample
        landed inside a one-hour window whatever its real age; a batch
        back-filled from yesterday would have been evaluated as if it were
        current."""
        session = EngineSession()
        now = now_utc()
        session.add_observations("e", "p", [
            (now - timedelta(days=1, seconds=i * 60), 1.0) for i in range(10)])
        recent = session.history.get_values("e", "p", timedelta(hours=1))
        assert recent == [], (
            "day-old samples were counted as inside a one-hour window")

    def test_samples_inside_the_window_are_counted(self):
        """The other half — a window that excludes everything is not a window.
        """
        session = EngineSession()
        now = now_utc()
        session.add_observations("e", "p", [
            (now - timedelta(seconds=i * 60), 1.0) for i in range(10)])
        assert len(session.history.get_values("e", "p", timedelta(hours=1))) == 10
