"""The third stratum: which entity types a forecaster is actually good at.

A POOLED SCORE CANNOT ANSWER THE ONLY QUESTION WORTH ASKING of a forecaster,
which is whether to keep using it. `by_model` splits producers and
`by_horizon` splits the distance ahead; the third split the design named is by
what is being forecast, and a model that is well calibrated on one entity type
and useless on another is a single number describing neither.

THE LEDGER CANNOT DERIVE IT. It holds an entity id and has never held a model.
Reading a type out of an id's shape is the name-heuristic class this package
has removed from three axioms, so the type is STATED by whoever files -- both
callers have the entity in hand at that moment, and the fact is free there and
unrecoverable afterwards.

WHICH LEAVES A DENOMINATOR PROBLEM, and it is the one this module's own
docstring calls worse than no figure. If some records carry a type and some do
not, a rate over the ones that do is a rate over an unstated subset. So the
count it does NOT cover is reported beside it.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from arbiter_engine.api import EngineSession
from arbiter_engine.clock import as_of
from arbiter_engine.forecast import ingest_forecasts

T0 = datetime(2026, 9, 17, 10, 0)


def _session():
    session = EngineSession()
    session.load_model({"domain": {
        "id": "d", "name": "d", "entity_types": ["Acct", "Desk"],
        "indicators": {
            "Acct": [{"name": "balance", "type": "NUMERIC",
                      "axioms": ["BOUNDEDNESS"], "window": "1h"}],
            "Desk": [{"name": "balance", "type": "NUMERIC",
                      "axioms": ["BOUNDEDNESS"], "window": "1h"}]}}})
    session.add_entity("acct_7", "Acct", {"balance": 100.0})
    session.add_entity("desk_1", "Desk", {"balance": 100.0})
    return session


#: ISSUED SO THAT IT MATURES AT `T0`, which is where the mirror observation
#: goes. The first version issued two hours back with a one-hour horizon, so
#: every record matured an hour before the observation that was meant to grade
#: it and came back `ungradeable` with no scores -- an empty stratum that
#: looked exactly like the stratum not working.
ISSUED = T0 - timedelta(hours=1)


def _forecast(entity_id, *, model="garch_v3", q=(90.0, 100.0, 110.0),
              horizon=3600.0, issued=None):
    return {"model_id": model, "entity_id": entity_id, "property": "balance",
            "horizon_s": horizon, "issued_at": issued or ISSUED,
            "quantiles": {"q05": q[0], "q50": q[1], "q95": q[2]}}


def _graded(session, outcomes):
    """File the mirror observations and grade, so records carry scores."""
    for entity_id, value in outcomes.items():
        session.history.add(entity_id, "balance", value, timestamp=T0)
    with as_of(T0 + timedelta(minutes=1)):
        # The full signature: grading reads the PROBLEM stream for the other
        # record kinds and the OBSERVATION stream for these. Calling it with
        # `histories=` alone was my fixture's error, not the ledger's -- and it
        # failed loudly, which is the right way for a wrong call to fail.
        session.ledger.grade_matured(
            problems=[], observed_entity_ids=set(outcomes),
            histories=[session.history])
    return session.ledger.calibration()


# --- the stratum ------------------------------------------------------------

def test_a_forecaster_is_scored_per_entity_type():
    session = _session()
    ingest_forecasts(session, [_forecast("acct_7"), _forecast("desk_1")],
                     at=ISSUED)
    figures = _graded(session, {"acct_7": 100.0, "desk_1": 100.0})
    assert sorted(figures["by_entity_type"]) == ["Acct", "Desk"]
    assert figures["by_entity_type"]["Acct"]["n"] == 1
    assert figures["by_entity_type"]["Desk"]["n"] == 1


def test_the_split_can_disagree_with_the_pooled_figure():
    """The reason the stratum exists. One model, two types: inside the interval
    on one and far outside on the other. Pooled, it looks half-right; split, it
    says which half."""
    session = _session()
    ingest_forecasts(session, [_forecast("acct_7"), _forecast("desk_1")],
                     at=ISSUED)
    figures = _graded(session, {"acct_7": 100.0, "desk_1": 10_000.0})
    assert figures["coverage_90"] == 0.5
    assert figures["by_entity_type"]["Acct"]["coverage_90"] == 1.0
    assert figures["by_entity_type"]["Desk"]["coverage_90"] == 0.0


def test_every_bucket_carries_its_own_count():
    """`coverage_90` over four records and over four thousand are different
    statements, and a rate without its denominator is the shape the top-level
    envelope exists to refuse."""
    session = _session()
    batch = [_forecast("acct_7") for _ in range(3)] + [_forecast("desk_1")]
    ingest_forecasts(session, batch, at=ISSUED)
    figures = _graded(session, {"acct_7": 100.0, "desk_1": 100.0})
    assert figures["by_entity_type"]["Acct"]["n"] == 3
    assert figures["by_entity_type"]["Desk"]["n"] == 1


def test_the_three_strata_agree_on_the_population_they_split():
    session = _session()
    ingest_forecasts(session, [_forecast("acct_7"), _forecast("desk_1")],
                     at=ISSUED)
    figures = _graded(session, {"acct_7": 100.0, "desk_1": 100.0})
    total = figures["coverage_90_n"]
    for stratum in ("by_model", "by_horizon", "by_entity_type"):
        assert sum(b["n"] for b in figures[stratum].values()) == total, stratum


# --- what it will not guess --------------------------------------------------

def test_a_record_filed_without_a_type_is_counted_and_not_attributed():
    """The honest half. The ledger is a released surface with callers that do
    not state a type, and inventing one for them would put a made-up label in a
    calibration table."""
    session = _session()
    session.ledger.record_distribution(
        entity_id="acct_7", property_name="balance",
        quantiles={"q05": 90.0, "q50": 100.0, "q95": 110.0},
        horizon_s=3600.0, model_id="legacy", predicted_at=ISSUED)
    figures = _graded(session, {"acct_7": 100.0})
    assert figures["by_entity_type"] == {}
    assert figures["entity_type_unattributed_n"] == 1


def test_a_mixed_population_reports_the_part_the_stratum_does_not_cover():
    """Without this count, `by_entity_type` would read as covering everything
    while describing a subset nobody stated -- which this module's own
    docstring calls worse than no figure at all."""
    session = _session()
    ingest_forecasts(session, [_forecast("acct_7")], at=ISSUED)
    session.ledger.record_distribution(
        entity_id="desk_1", property_name="balance",
        quantiles={"q05": 90.0, "q50": 100.0, "q95": 110.0},
        horizon_s=3600.0, model_id="legacy", predicted_at=ISSUED)
    figures = _graded(session, {"acct_7": 100.0, "desk_1": 100.0})
    assert figures["coverage_90_n"] == 2
    assert sum(b["n"] for b in figures["by_entity_type"].values()) == 1
    assert figures["entity_type_unattributed_n"] == 1


def test_the_unattributed_count_is_not_a_bucket_in_the_stratum():
    """A key named for the absence collides the first time somebody declares an
    entity type with that name."""
    session = _session()
    session.ledger.record_distribution(
        entity_id="acct_7", property_name="balance",
        quantiles={"q05": 90.0, "q50": 100.0, "q95": 110.0},
        horizon_s=3600.0, model_id="legacy", predicted_at=ISSUED)
    figures = _graded(session, {"acct_7": 100.0})
    assert "unattributed" not in figures["by_entity_type"]
    assert "unknown" not in figures["by_entity_type"]


def test_an_empty_ledger_reports_no_stratum_rather_than_a_zero():
    """A zero would read as *perfectly calibrated* for a model never graded."""
    figures = EngineSession().ledger.calibration()
    assert figures["by_entity_type"] == {}
    assert figures["entity_type_unattributed_n"] == 0
    assert figures["coverage_90"] is None


# --- where the type comes from ----------------------------------------------

def test_the_ingest_feeder_states_the_type_it_already_resolved():
    """It looked the entity up two statements earlier to check the forecast
    against the model; the fact is free there and gone afterwards."""
    session = _session()
    ingest_forecasts(session, [_forecast("acct_7")], at=ISSUED)
    assert session.ledger.records()[0].entity_type == "Acct"


def test_a_type_is_never_read_out_of_an_entity_id():
    """The discriminator for the claim above: an id that LOOKS like a type is
    still not one, and a ledger that guessed would report a type this model
    does not declare."""
    session = _session()
    session.add_entity("Desk/desk_2", "Acct", {"balance": 100.0})
    ingest_forecasts(session, [_forecast("Desk/desk_2")],
                     at=ISSUED)
    assert session.ledger.records()[0].entity_type == "Acct"


def test_the_projection_runner_states_it_too():
    """The engine's own projector is the other caller, and a stratum that only
    covered outside forecasters would compare them on different footings."""
    from arbiter_engine.projection import runner
    import inspect
    source = inspect.getsource(runner)
    assert "entity_type=entity.type" in source
