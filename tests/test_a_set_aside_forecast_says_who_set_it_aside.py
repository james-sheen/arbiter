"""A shadow pass that checked nothing says why, and whose records they were.

`source=` NAMES WHO IS NOT A PRODUCER. A record carrying one is kept out of
`received`, out of the producer figures, and out of the shadow axiom pass --
correctly, because that pass exists to put the eight axioms over a forecast
somebody ELSE sent, and the engine's own projections are already judged against
the same declared lines by `run_projection`.

THE EXCLUSION WAS THE ONE SILENT SKIP IN `shadow_entities`. Every other filed a
decline, and the function's docstring says why: *a forecast that went nowhere is
exactly what the ingest report exists to surface, and this is the second place
it can happen.* A record with no median declines `missing_property`; a subject
the session cannot place declines `precondition_unmet`; a record with a source
returned nothing at all. So a batch whose every record carried one produced
`checked {entities: 0}` beside `not_checked []` -- a zero denominator with
nothing saying why, which a reader cannot tell from a clean run.

WHY THIS IS NOT HYPOTHETICAL. `arbiter-world-model-design-note.md` Sec. 6.2
instructs a bridge to call `ingest_forecasts` "with a `source=` naming the
producer" -- the exact inversion -- and its Sec. 6.3 then advertises the shadow
pass as the reason to route a learned model through this engine. A bridge
following both would switch the second off with the first and read back an
envelope indistinguishable from a clean one.

ONE DECLINE, COUNTED AND NAMED, on the `budget_exhausted` precedent. The engine
stamps its own projections every cycle, so a per-record decline would bury the
interesting case under them -- and the count alone is not enough either, which
`test_the_count_alone_would_not_have_been_enough` measures rather than asserts.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from arbiter_engine.api import (
    EngineSession, as_of, check, ingest_forecasts)

T0 = datetime(2026, 9, 18, 10, 0)
ISSUED = T0 - timedelta(minutes=30)

REASON = "not_a_producers_submission"

BOOK = {"domain": {
    "id": "d", "name": "d", "entity_types": ["Book"],
    "indicators": {"Book": [
        {"name": "nav", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
         "window": "1h", "critical": 1e9},
        # `role: count` is what makes a forecast of -3 IMPOSSIBLE rather than
        # merely low, so the shadow pass has something to find when it runs.
        {"name": "positions", "type": "NUMERIC", "role": "count",
         "axioms": ["CONSISTENCY"], "window": "1h"}]}}}


def _session():
    session = EngineSession()
    session.load_model(BOOK)
    session.add_entity("b1", "Book", {"nav": 100.0, "positions": 4.0})
    # HISTORY, BECAUSE THE BASELINE NEEDS A SERIES TO FIT ON. Without it the
    # random walk declines `too_little_history`, nothing of the engine's is
    # filed, and the two tests below measuring *the count alone is not enough*
    # would pass vacuously -- there would be no second population to confuse
    # the count with. The floor is what `_file_baseline` needs, not a number
    # chosen here.
    for index in range(12):
        when = T0 - timedelta(minutes=(12 - index) * 5)
        session.add_observations("b1", "nav", [(when, 96.0 + index * 0.4)])
        session.add_observations("b1", "positions", [(when, 4.0)])
    return session


def _records():
    return [
        {"model_id": "m", "entity_id": "b1", "property": "nav",
         "horizon_s": 3600.0, "issued_at": ISSUED,
         "quantiles": {"q05": 80.0, "q50": 90.0, "q95": 100.0}},
        {"model_id": "m", "entity_id": "b1", "property": "positions",
         "horizon_s": 3600.0, "issued_at": ISSUED,
         "quantiles": {"q05": -5.0, "q50": -3.0, "q95": -1.0}},
    ]


def _shadow(source):
    session = _session()
    with as_of(T0):
        ingest_forecasts(session, _records(), at=T0, source=source)
        return check(session).to_dict()["shadow"]


def _declines(shadow, reason=REASON):
    return [d for d in shadow["not_checked"] if d["reason"] == reason]


# --- the two halves, measured side by side ------------------------------------

def test_an_unstamped_batch_is_checked():
    """The control. Without it the test below measures nothing: a shadow pass
    that finds nothing on BOTH paths is a broken fixture, not a defect."""
    shadow = _shadow(None)
    assert shadow["checked"]["entities"] == 1
    assert "forecast_impossible_value" in [f["problem_type"]
                                           for f in shadow["findings"]]


def test_a_stamped_batch_is_not_checked():
    """Correct, and the reason the decline below has to exist."""
    shadow = _shadow("a_reference")
    assert shadow["checked"]["entities"] == 0
    assert shadow["findings"] == []


def test_a_stamped_batch_declines_rather_than_going_quiet():
    assert _declines(_shadow("a_reference"))


def test_a_run_that_set_nothing_aside_does_not_decline_this():
    """The decline is about records that were SET ASIDE, so a run with none
    must not carry it -- otherwise the reason is noise on every envelope that
    holds a forecast, and a reader learns to skip it.

    THE FIXTURE HAS NO HISTORY, and that is the whole of how *nothing set
    aside* is reached: the random walk needs a series to fit on, so with none
    it declines `too_little_history` and the engine files nothing of its own.
    An unstamped batch over a session WITH history still sets the engine's own
    baselines aside and still declines -- see the test below, which is the
    same mechanism seen from the other side.
    """
    session = EngineSession()
    session.load_model(BOOK)
    session.add_entity("b1", "Book", {"nav": 100.0, "positions": 4.0})
    with as_of(T0):
        ingest_forecasts(session, _records(), at=T0, source=None)
        shadow = check(session).to_dict()["shadow"]

    assert shadow["checked"]["entities"] == 1, "the batch must have been checked"
    assert not _declines(shadow)


# --- what the decline has to carry to be useful -------------------------------

def test_the_decline_names_the_sources_it_set_aside():
    decline = _declines(_shadow("a_reference"))[0]
    assert "a_reference" in decline["sources"]


def test_the_decline_carries_a_count():
    decline = _declines(_shadow("a_reference"))[0]
    assert isinstance(decline["records"], int)
    assert decline["records"] >= len(_records())


def test_the_count_alone_would_not_have_been_enough():
    """MEASURED, not asserted. Filing two stamped records sets aside FOUR --
    the engine fits a random walk beside each one and stamps its own -- so a
    reader told only a total sees a number larger than anything it sent and
    concludes the engine is discussing itself. The source NAMES are what make
    this a diagnosis."""
    decline = _declines(_shadow("a_reference"))[0]
    assert decline["records"] > len(_records())
    assert sorted(decline["sources"]) == ["a_reference", "engine"]


def test_the_engines_own_projections_are_named_too():
    """A session that stamps nothing of its own still sets aside the baselines
    the engine filed, and says so rather than counting them invisibly."""
    session = _session()
    with as_of(T0):
        ingest_forecasts(session, _records(), at=T0, source=None)
        shadow = check(session).to_dict()["shadow"]

    declines = _declines(shadow)
    assert declines, shadow["not_checked"]
    assert declines[0]["sources"] == ["engine"]


# --- the vocabulary it belongs to ---------------------------------------------

def test_the_reason_is_in_the_shadow_vocabulary():
    """A decline whose reason is outside its discipline's closed set cannot be
    built at all -- `SubEnvelope.__post_init__` refuses it -- so this asserts
    the registration rather than trusting that the call above worked."""
    from arbiter_engine.subenvelope import VOCABULARIES
    assert REASON in VOCABULARIES["shadow"]


def test_it_is_not_in_any_other_vocabulary():
    """The sets are separate on purpose. A reason that leaked into another
    discipline's vocabulary would let that discipline accept a refusal it
    cannot produce, which is how a closed enum stops being evidence."""
    from arbiter_engine.subenvelope import VOCABULARIES
    carriers = [name for name, members in VOCABULARIES.items()
                if REASON in members]
    assert carriers == ["shadow"]
