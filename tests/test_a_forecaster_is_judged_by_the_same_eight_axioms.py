"""Monitoring a forecaster needs no new mechanism -- but it does need both surfaces.

A MISCALIBRATED MODEL, A MODEL THAT SKIPS SUBJECTS, AND A MODEL THAT DELIVERS
LATE are the three shapes BOUNDEDNESS, CONSERVATION and RESPONSIVENESS already
judge. What was missing was never an axiom; it was a way to get the numbers
onto an entity. So this file is mostly about the feeding.

AND THE FEEDING IS WHERE THE DESIGN'S OWN EXAMPLE FALLS SHORT. Stamping the
figures as properties gets two of the three: those two axioms judge the current
value, and CONSERVATION reads the SERIES. Measured -- an entity carrying
`forecasts_expected: 3` and `forecasts_issued: 1` as properties alone declines
`insufficient_samples` and reports no imbalance, so a model skipping two thirds
of its subjects produced a clean envelope. Both surfaces are written, and the
test below is the one that would have caught it.

THE ENGINE NEVER NAMES THE TYPE. `ForecastModel` is a domain author's word and
appears nowhere in the package; `entity_type` is a required parameter.
"""

from __future__ import annotations

import pathlib
from datetime import datetime, timedelta

import pytest

from arbiter_engine.api import EngineSession, check
from arbiter_engine.clock import as_of
from arbiter_engine.forecast import (
    feed_model_figures, ingest_forecasts, model_figures)

T0 = datetime(2026, 9, 17, 10, 0)

MONITOR = [
    {"name": "coverage_90", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
     "window": "30d", "lower_warning": 0.85, "lower_critical": 0.80},
    {"name": "forecasts_issued", "type": "NUMERIC", "axioms": ["CONSERVATION"],
     "window": "30d", "conservation": {
         "input_property": "forecasts_expected",
         "output_properties": ["forecasts_issued"]}},
    {"name": "forecast_age_s", "type": "NUMERIC", "role": "latency",
     "axioms": ["RESPONSIVENESS"], "window": "30d",
     "warning": 120, "critical": 600},
]


def _session(models=("garch_v3",), accounts=3, expected_from=()):
    """`models:` is the ALLOW-LIST and `expected_from:` is the obligation, and
    this fixture keeps them apart because the engine did not.

    `forecasts_expected` used to be derived from `models:`, so every producer
    PERMITTED to send a forecast was charged with every subject. On the shipped
    margin-book example -- two permitted models, six accounts -- both were
    reported 50% and 83% short of a debt nobody had declared, at severity
    `high`. A fixture that passed one list for both would have kept that
    invisible, so `expected_from` defaults to nothing and every test about an
    obligation names one.
    """
    forecast = {"expected": True, "models": list(models)}
    if expected_from:
        forecast["expected_from"] = list(expected_from)
    session = EngineSession()
    session.load_model({"domain": {
        "id": "d", "name": "d", "entity_types": ["Acct", "ForecastModel"],
        "indicators": {
            "Acct": [{"name": "balance", "type": "NUMERIC",
                      "axioms": ["BOUNDEDNESS"], "window": "1h",
                      "critical": 1e9,
                      "forecast": forecast}],
            "ForecastModel": MONITOR}}})
    for n in range(accounts):
        session.add_entity(f"a{n}", "Acct", {"balance": 50.0})
    return session


def _forecast(session, model="garch_v3", entity="a0", minutes_ago=90,
              q=(10.0, 11.0, 12.0)):
    ingest_forecasts(session, [{
        "model_id": model, "entity_id": entity, "property": "balance",
        "horizon_s": 3600.0, "issued_at": T0 - timedelta(minutes=minutes_ago),
        "quantiles": {"q05": q[0], "q50": q[1], "q95": q[2]}}], at=T0)


def _grade(session, entity="a0", observed=900.0):
    session.history.add(entity, "balance", observed,
                        timestamp=T0 - timedelta(minutes=30))
    with as_of(T0):
        session.ledger.grade_matured(problems=[], observed_entity_ids={entity},
                                     histories=[session.history])


def _cycles(session, n=8):
    for index in range(n):
        with as_of(T0 - timedelta(seconds=30 * (n - 1 - index))):
            feed_model_figures(session, "ForecastModel")


def _about(envelope, entity_id):
    return sorted(f["problem_type"] for f in envelope["findings"]
                  if f["entity_id"] == entity_id)


# --- the three shapes --------------------------------------------------------

def test_a_miscalibrated_model_is_an_ordinary_finding():
    session = _session()
    _forecast(session)
    _grade(session)
    _cycles(session)
    with as_of(T0):
        assert "below_critical_threshold:coverage_90" in _about(
            check(session).to_dict(), "garch_v3")


def test_a_model_that_skips_its_subjects_is_an_ordinary_finding():
    """Three accounts owe a forecast from this model; it forecast one."""
    session = _session(accounts=3, expected_from=("garch_v3",))
    _forecast(session)
    _grade(session)
    _cycles(session)
    with as_of(T0):
        findings = check(session).to_dict()["findings"]
    violation = next(f for f in findings
                     if f["problem_type"] == "conservation_violation:forecasts_issued")
    assert "deficit" in violation["reason"]


def test_a_model_that_delivers_late_is_an_ordinary_finding():
    session = _session()
    _forecast(session, minutes_ago=90)
    _cycles(session)
    with as_of(T0):
        assert "response_time_critical:forecast_age_s" in _about(
            check(session).to_dict(), "garch_v3")


def test_a_healthy_model_is_silent():
    """The discriminator. Three axioms that fired on every forecaster would
    make all three tests above pass and mean nothing."""
    session = _session(accounts=1)
    _forecast(session, minutes_ago=1, q=(800.0, 900.0, 1000.0))
    _grade(session)
    _cycles(session)
    with as_of(T0):
        assert _about(check(session).to_dict(), "garch_v3") == []


# --- the surface the design's own example misses -----------------------------

def test_properties_alone_leave_conservation_blind():
    """THE MEASUREMENT BEHIND THE FEEDER. Stamping the figures as properties
    and stopping there is what the design's YAML implies, and it produces a
    clean envelope for a model supplying a third of what it owes."""
    session = _session()
    session.add_entity("garch_v3", "ForecastModel",
                       {"forecasts_expected": 3.0, "forecasts_issued": 1.0})
    with as_of(T0):
        envelope = check(session).to_dict()
    assert _about(envelope, "garch_v3") == []
    assert "insufficient_samples" in [d["reason"] for d in envelope["not_checked"]]


def test_the_feeder_writes_both_surfaces():
    session = _session()
    _forecast(session)
    with as_of(T0):
        feed_model_figures(session, "ForecastModel")
    assert session.entities["garch_v3"].properties["forecasts_issued"] == 1.0
    assert session.history.get_values(
        "garch_v3", "forecasts_issued", timedelta(days=30))


def test_feeding_twice_updates_rather_than_duplicates():
    session = _session()
    _forecast(session)
    with as_of(T0 - timedelta(minutes=1)):
        feed_model_figures(session, "ForecastModel")
    _forecast(session, entity="a1")
    with as_of(T0):
        feed_model_figures(session, "ForecastModel")
    assert session.entities["garch_v3"].properties["forecasts_issued"] == 2.0
    assert len(session.history.get_values(
        "garch_v3", "forecasts_issued", timedelta(days=30))) == 2


def test_each_cycle_files_one_reading_not_a_ladder():
    """A synthetic ladder would let a window-reading axiom answer about a
    history that never happened."""
    session = _session()
    _forecast(session)
    with as_of(T0):
        feed_model_figures(session, "ForecastModel")
    stamps = session.history.get_values("garch_v3", "forecasts_issued",
                                        timedelta(days=30))
    assert len(stamps) == 1
    assert stamps[0][0] == T0


# --- what the figures are ----------------------------------------------------

def _guide() -> str:
    """The modelling guide, from whichever copy this tree has."""
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / "MODELING.md",
                      here.parents[2] / "docs" / "publication"
                      / "domain-model-spec.md"):
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    raise AssertionError("no modelling guide found to check against")


def test_the_figures_are_named_as_the_guide_declares_them():
    """A reader pastes the YAML and it reads what this produces.

    THIS TEST USED TO ASSERT AGAINST ITSELF. It carried the five names as a set
    literal, so it pinned the monitor against a second copy of the fact typed
    into this file and never opened the document its own name refers to. The
    guide declared none of them for a release, `monitor.py` said in its
    docstring that it did, and this passed throughout -- which is what a check
    that answers the wrong question looks like from the outside.

    Every figure the monitor can produce is now read from the guide itself, so
    the two cannot drift apart without going red.
    """
    session = _session()
    _forecast(session)
    _grade(session)
    with as_of(T0):
        figures = model_figures(session)["garch_v3"]
    assert len(figures) >= 5, (
        f"the fixture produced only {sorted(figures)}, so this asserts about "
        f"almost nothing")
    guide = _guide()
    undeclared = sorted(name for name in figures if name not in guide)
    assert not undeclared, (
        f"the monitor produces {undeclared} and the modelling guide declares "
        f"no indicator by that name, so a reader pasting the guide's YAML gets "
        f"a model that cannot read what the engine writes")


def test_the_denominator_travels_with_the_rate():
    """A coverage of 1.0 from one record and from four thousand are different
    statements that the rate alone presents identically."""
    session = _session()
    _forecast(session)
    _grade(session)
    with as_of(T0):
        assert model_figures(session)["garch_v3"]["graded_n"] == 1.0


def test_a_model_never_graded_has_no_coverage_rather_than_zero():
    """A `coverage_90` of 0.0 reads as catastrophically miscalibrated, and
    BOUNDEDNESS would fire on it. Absent is absent."""
    session = _session()
    _forecast(session)
    with as_of(T0):
        figures = model_figures(session)["garch_v3"]
    assert "coverage_90" not in figures
    assert "pinball_loss" not in figures
    assert figures["forecasts_issued"] == 1.0


def test_the_age_is_of_the_most_recent_forecast():
    session = _session()
    _forecast(session, minutes_ago=90)
    _forecast(session, entity="a1", minutes_ago=5)
    with as_of(T0):
        assert model_figures(session)["garch_v3"]["forecast_age_s"] == 300.0


def test_expected_is_attributed_only_to_models_a_declaration_names():
    """`expected: true` on its own says a forecast is due and nothing about
    who owes it. Attributing it to whichever model happened to send one would
    invent an obligation and then report it met."""
    session = EngineSession()
    session.load_model({"domain": {
        "id": "d", "name": "d", "entity_types": ["Acct", "ForecastModel"],
        "indicators": {
            "Acct": [{"name": "balance", "type": "NUMERIC",
                      "axioms": ["BOUNDEDNESS"], "window": "1h",
                      "critical": 1e9, "forecast": {"expected": True}}],
            "ForecastModel": MONITOR}}})
    session.add_entity("a0", "Acct", {"balance": 50.0})
    _forecast(session)
    with as_of(T0):
        assert "forecasts_expected" not in model_figures(session)["garch_v3"]


def test_expected_counts_one_per_declared_subject():
    session = _session(accounts=5, expected_from=("garch_v3",))
    _forecast(session)
    with as_of(T0):
        assert model_figures(session)["garch_v3"]["forecasts_expected"] == 5.0


def test_being_permitted_to_forecast_is_not_owing_one():
    """THE FALSE FINDING THIS KEY EXISTS TO END.

    `models:` is an allow-list -- the guide says so on the line beside it, and
    an id outside it declines `model_unknown`. Deriving the obligation from it
    charged every permitted producer with every subject: on the shipped
    margin-book example both listed models were reported short of a debt
    nobody had declared, at severity `high`. A desk naming five permitted
    models would have had four delinquent by construction.

    A wrong finding is worse than a missing one, so without `expected_from:`
    the figure is ABSENT and the CONSERVATION declaration over it declines.
    """
    session = _session(models=("garch_v3", "lstm_v1"), accounts=5)
    _forecast(session)
    with as_of(T0):
        figures = model_figures(session)
    assert "forecasts_expected" not in figures["garch_v3"]


def test_an_obligation_reaches_only_the_model_it_names():
    """Two permitted, one obliged. The other is not silently charged."""
    session = _session(models=("garch_v3", "lstm_v1"), accounts=4,
                       expected_from=("garch_v3",))
    _forecast(session, model="garch_v3")
    _forecast(session, model="lstm_v1", entity="a1")
    with as_of(T0):
        figures = model_figures(session)
    assert figures["garch_v3"]["forecasts_expected"] == 4.0
    assert "forecasts_expected" not in figures["lstm_v1"]


def test_the_engines_own_records_are_not_monitored_as_producers():
    """`project` files a projection and a random walk. Monitoring those as
    forecasters put `baseline_rw` in the report with an age and a coverage
    rate -- the yardstick lined up on the grid it was measuring."""
    from arbiter_engine.api import project

    session = _session(accounts=1)
    base = T0 - timedelta(days=1)
    session.add_observations("a0", "balance", [
        (base + timedelta(minutes=7 * i), 50.0 + (i % 5)) for i in range(200)])
    session.model.indicators["Acct"][0].dynamics_config = {"model": "local_level"}
    with as_of(T0):
        project(session, horizon_s=3600.0)
        figures = model_figures(session)
    assert "baseline_rw" not in figures
    assert not [name for name in figures if ":" in name]


def test_two_models_are_two_subjects():
    session = _session(models=("garch_v3", "lstm_v1"), accounts=2,
                       expected_from=("garch_v3", "lstm_v1"))
    _forecast(session, model="garch_v3")
    _forecast(session, model="lstm_v1", entity="a1")
    _forecast(session, model="lstm_v1", entity="a0", minutes_ago=10)
    with as_of(T0):
        figures = model_figures(session)
    assert sorted(figures) == ["garch_v3", "lstm_v1"]
    assert figures["garch_v3"]["forecasts_expected"] == 2.0
    # PER MODEL, which the first version of this test never checked: it read
    # the model list and the expectation and left `forecasts_issued` free, so
    # a mutation counting every model's records for each of them passed.
    assert figures["garch_v3"]["forecasts_issued"] == 1.0
    assert figures["lstm_v1"]["forecasts_issued"] == 2.0


def test_a_declaration_that_names_models_without_expecting_one_counts_nothing():
    """`models:` says WHO would supply a forecast; `expected:` says one is
    due. A declaration with the first and not the second owes nothing, and
    counting it would report a deficit against an obligation nobody made."""
    session = EngineSession()
    session.load_model({"domain": {
        "id": "d", "name": "d", "entity_types": ["Acct", "ForecastModel"],
        "indicators": {
            "Acct": [{"name": "balance", "type": "NUMERIC",
                      "axioms": ["BOUNDEDNESS"], "window": "1h",
                      "critical": 1e9,
                      "forecast": {"models": ["garch_v3"]}}],
            "ForecastModel": MONITOR}}})
    session.add_entity("a0", "Acct", {"balance": 50.0})
    _forecast(session)
    with as_of(T0):
        assert "forecasts_expected" not in model_figures(session)["garch_v3"]


def test_the_kind_filter_is_now_a_live_path():
    """IT WAS DEFENCE UNTIL, AND THIS TEST SAID SO AND SAID WHY.

    The version here was named `..._is_defence_and_not_a_live_path`, reported
    that no test claimed to exercise the filter, and gave the measurement
    behind that: `record_distribution` was the only ledger method accepting a
    `model_id`, the walk already skipped records without one, so no record
    reachable through the public surface could be the wrong kind AND carry a
    model id. Deleting the filter changed nothing.

    It also named its own expiry -- *the filter stays, because a later method
    growing a `model_id` argument would reach it* -- and that is what happened.
    A rollout files its projections under `arbiter_engine:rollout` so the
    coupling stratum in `own_projections` knows whose forecasts it covers, and
    those are `kind == "value"` records carrying a model id. The filter now
    does work on every call.

    So the enumeration below changes rather than the filter, and the coverage
    it said was missing exists: `test_the_forecaster_report_does_not_adopt_them`
    in `test_the_engine_scores_its_own_declared_spread.py` files one and
    asserts the report does not list it. A test that predicted the conditions
    of its own failure is worth more than one that passed."""
    import inspect
    from arbiter_engine.forecast import monitor
    from arbiter_engine.residual import predict_vs_mirror

    assert 'r.kind == "distribution"' in inspect.getsource(monitor)
    accepting = sorted(
        name for name in dir(predict_vs_mirror.PredictionLedger)
        if name.startswith("record_")
        and "model_id" in inspect.signature(
            getattr(predict_vs_mirror.PredictionLedger, name)).parameters)
    assert accepting == ["record_distribution", "record_value_prediction"], (
        f"{accepting} -- a NEW filer growing a `model_id` makes the kind "
        f"filter matter for its records too. Give it live coverage rather "
        f"than widening this list on sight.")

    session = _session(accounts=1)
    _forecast(session)
    session.ledger.record_prediction(
        entity_id="a0", probability=0.5, horizon_s=3600.0,
        indicator="balance", predicted_at=T0 - timedelta(minutes=10))
    with as_of(T0):
        assert model_figures(session)["garch_v3"]["forecasts_issued"] == 1.0


def test_an_empty_ledger_produces_no_subjects():
    with as_of(T0):
        assert model_figures(_session()) == {}


# --- the domain-agnostic line -------------------------------------------------

def test_the_engine_does_not_name_the_entity_type():
    """`ForecastModel` is a domain author's word. Writing it into the package
    would put a domain word in a domain-free core -- the class three axioms
    were rewritten to remove."""
    from arbiter_engine.forecast import monitor
    import inspect
    assert "ForecastModel" not in inspect.getsource(monitor)


def test_the_caller_chooses_the_type():
    session = _session()
    _forecast(session)
    with as_of(T0):
        feed_model_figures(session, "WhateverICallIt")
    assert session.entities["garch_v3"].type == "WhateverICallIt"
