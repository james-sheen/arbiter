"""The five worked examples, loaded and RUN — because nothing was doing that.

NO TEST OPENED ANY OF THEM. Five files ship as the documentation of how to
write a model, and the suite mentioned two of them in prose and read none. That
is how two high-severity defects sat in one release behind a green run:

  - `project` could not resolve `margin_book.yaml`'s `lower_critical:
    {from_property: margin_requirement}`, so the flagship example could never
    report a projected breach;
  - the same example declares `models: [garch_v3, lstm_v1]`, and running
    `project` then `check` declined `model_unknown` for the engine's own two
    records and counted them as the forecast an outside producer owed.

Every unit test around them passed. They called the internal functions
directly, and each of these defects lives in the COMPOSITION -- which is
exactly what an example is a specimen of.

WHY THE EXAMPLES AND NOT A FIXTURE. A fixture written beside the code under
test tracks the code; these files are a promise to a reader who pastes them.
`margin_book.yaml` is the one that exercises the forecast path end to end, so
it gets the whole walk. The other four are loaded and proofread, which is the
claim they make.
"""

from __future__ import annotations

import pathlib
from datetime import datetime, timedelta

import pytest

from arbiter_engine.api import (
    EngineSession, check, model_describe, plan, project, rollout)
from arbiter_engine.clock import as_of
from arbiter_engine.forecast import ingest_forecasts

T0 = datetime(2026, 9, 17, 9, 35)


def _examples_dir() -> pathlib.Path:
    """Whichever copy this tree has: the built package ships `examples/` at its
    root, the source tree keeps them under the publication docs."""
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / "examples",
                      here.parents[2] / "docs" / "publication"
                      / "engine-example"):
        if candidate.is_dir() and list(candidate.glob("*.yaml")):
            return candidate
    raise AssertionError("no examples directory found in this tree")


EXAMPLES = sorted(p.name for p in _examples_dir().glob("*.yaml"))


def _loaded(name: str) -> EngineSession:
    session = EngineSession()
    session.load_model(_examples_dir().joinpath(name).read_text(encoding="utf-8"))
    return session


def test_there_are_examples_to_check():
    """Guards the guard. A resolver that found an empty directory would make
    every parametrised test below vacuous, and a suite of zero tests is the
    same green as a suite that passed."""
    assert len(EXAMPLES) >= 5, EXAMPLES


@pytest.mark.parametrize("name", EXAMPLES)
class TestEachExampleIsAModelTheEngineCanRead:

    def test_it_loads(self, name):
        assert _loaded(name).model is not None

    def test_nothing_it_declares_is_unreachable(self, name):
        """A declaration that provably cannot fire is a check the reader
        believes they asked for. In a file whose job is to teach, it teaches
        the wrong thing."""
        session = _loaded(name)
        block = model_describe(session).to_dict()["model"]
        assert block["unreachable_declarations"] == []

    def test_nothing_it_declares_was_dropped(self, name):
        session = _loaded(name)
        block = model_describe(session).to_dict()["model"]
        assert block["dropped_declarations"] == []

    def test_every_declared_entity_type_carries_indicators(self, name):
        session = _loaded(name)
        declared = set(session.model.entity_types)
        described = set(session.model.indicators)
        assert declared - described == set(), (
            f"{name} declares entity types with no indicators: "
            f"{sorted(declared - described)}")


# =====================================================================
# `margin_book.yaml` end to end -- the example that exercises the forecast
# path, walked the way its own comments say a reader would walk it.
# =====================================================================


def _random_walk(*, step: float, last: float, n: int = 300):
    """A deterministic local-level series ending at `last`.

    Its own generator rather than `random`, so the series is a property of
    this file and not of whichever interpreter runs it: a fixture whose values
    move with the Python version is a fixture that will fail somewhere nobody
    can reproduce. Shifted at the end so the distance to the floor -- the one
    number the assertion depends on -- is stated here rather than discovered.
    """
    out, level, state = [], 0.0, 20260917
    for _ in range(n):
        state = (1103515245 * state + 12345) % 2147483648
        level += step * ((state / 2147483648.0) - 0.5) * 2.0
        out.append(level)
    shift = last - out[-1]
    return [value + shift for value in out]

MARGIN_BOOK = "margin_book.yaml"
REQUIREMENT = 818_640.0


def _margin_session() -> EngineSession:
    session = _loaded(MARGIN_BOOK)
    session.add_entity("acct_01", "Account", {
        "margin_balance": 1_203_684.35,
        "margin_requirement": REQUIREMENT,
        "margin_call_amount_usd": 0.0,
    })
    base = T0 - timedelta(days=2)
    session.add_observations("acct_01", "margin_balance", [
        (base + timedelta(minutes=7 * i), 1_200_000.0 + (i % 13) * 900.0)
        for i in range(300)])
    session.add_observations("acct_01", "margin_requirement",
                             [(base + timedelta(minutes=7 * i), REQUIREMENT)
                              for i in range(300)])
    return session


def _projection(session):
    with as_of(T0):
        payload = project(session, horizon_s=3600.0).to_dict()
    return payload.get("projection", payload)


class TestTheFlagshipExampleCanReportABreach:

    def test_project_resolves_its_per_instance_floor(self):
        """The example declares `lower_critical: {from_property:
        margin_requirement}`. A reader who declares that and runs `project`
        must not be told no line was declared."""
        declines = _projection(_margin_session())["not_checked"]
        offending = [d for d in declines
                     if d["reason"] == "no_threshold"
                     and d.get("property") == "margin_balance"]
        assert offending == [], offending

    def test_a_balance_sitting_over_its_floor_is_reported(self):
        """The whole point of the declaration, end to end.

        The balance is ABOVE its requirement right now, so nothing has
        happened yet and the top-level axioms say so. What the example
        promises is that the engine will still report the hour ahead, against
        a floor read off this account rather than off the book -- and until
        the resolver reached `project` it could not, for any account, ever."""
        session = _loaded(MARGIN_BOOK)
        series = _random_walk(step=2500.0, last=REQUIREMENT + 1500.0)
        session.add_entity("acct_02", "Account", {
            "margin_balance": series[-1], "margin_requirement": REQUIREMENT})
        base = T0 - timedelta(days=2)
        session.add_observations("acct_02", "margin_balance", [
            (base + timedelta(minutes=7 * i), value)
            for i, value in enumerate(series)])
        assert series[-1] > REQUIREMENT, "this account has not breached yet"

        leg = _projection(session)
        found = [f.get("problem_type") or f.get("type")
                 for f in leg.get("findings", [])]
        assert any(str(name).startswith("projected_breach") for name in found), (
            f"no projected breach; declines were "
            f"{[d['reason'] for d in leg['not_checked']]}")


class TestTheFlagshipExampleTellsItsOwnForecastsApart:

    def test_projecting_does_not_satisfy_the_declared_expectation(self):
        """`forecast: {expected: true}` says an OUTSIDE forecaster owes one.
        The engine's own projection must not fill that slot."""
        session = _margin_session()
        with as_of(T0):
            project(session, horizon_s=3600.0)
            leg = check(session).to_dict()["forecasts"]
        assert leg["checked"]["received"] == 0
        assert any(d["reason"] == "forecast_missing"
                   for d in leg["not_checked"])

    def test_the_declared_model_list_does_not_refuse_the_engine(self):
        """The example declares `models: [garch_v3, lstm_v1]`."""
        session = _margin_session()
        with as_of(T0):
            project(session, horizon_s=3600.0)
            leg = check(session).to_dict()["forecasts"]
        assert not [d for d in leg["not_checked"]
                    if d["reason"] == "model_unknown"]

    def test_a_forecast_from_a_declared_producer_is_accepted_and_scored(self):
        session = _margin_session()
        with as_of(T0):
            report = ingest_forecasts(session, [{
                "model_id": "garch_v3", "entity_id": "acct_01",
                "property": "margin_balance", "horizon_s": 3600.0,
                "issued_at": T0 - timedelta(minutes=5),
                "quantiles": {"q05": 1_100_000.0, "q50": 1_200_000.0,
                              "q95": 1_300_000.0}}], at=T0)
            leg = check(session).to_dict()["forecasts"]
        assert report["filed"] == 1
        assert report["baselines"] == 1, "no yardstick was filed beside it"
        assert leg["checked"]["received"] == 1
        assert not [d for d in leg["not_checked"]
                    if d["reason"] in ("model_unknown", "forecast_missing")]

    def test_the_shadow_leg_reaches_the_reader(self):
        """The example declares `dynamics.report_above`, so the breach
        probability is decidable and the shadow leg should carry a denominator
        rather than a refusal."""
        session = _margin_session()
        with as_of(T0):
            ingest_forecasts(session, [{
                "model_id": "lstm_v1", "entity_id": "acct_01",
                "property": "margin_balance", "horizon_s": 3600.0,
                "issued_at": T0 - timedelta(minutes=5),
                "quantiles": {"q05": 1_100_000.0, "q50": 1_200_000.0,
                              "q95": 1_300_000.0}}], at=T0)
            shadow = check(session).to_dict()["shadow"]
        assert shadow["checked"]["entities"] == 1
        assert not [d for d in shadow["not_checked"]
                    if d["reason"] in ("no_threshold", "no_report_probability")]


class TestTheExampleFeedsNothingThatGoesUnread:

    def test_no_property_it_names_is_reported_undeclared(self):
        """An example that trips the engine's own unread-input report is
        teaching a reader to write a model the engine complains about."""
        session = _margin_session()
        with as_of(T0):
            envelope = check(session).to_dict()
        assert envelope["unread_properties"] == []


class TestTheDynamicsExampleRunsTheSimulationVerbs:
    """`pump_tank_dynamics.yaml` is the example that declares a
    `transition:`, an `action_templates:` block and a `planning:` objective.

    Before it, not one shipped example declared any of the three, so the whole
    simulation surface 0.2.3 added was undocumented by specimen: a reader who
    wanted to try `rollout` or `plan` had to write a model first, from prose.
    An example nothing runs is a claim; this runs it.
    """

    NAME = "pump_tank_dynamics.yaml"

    def _session(self, level_pct=92.0, speed_rpm=3000.0):
        session = _loaded(self.NAME)
        session.add_entity("pump1", "Pump", {"speed_rpm": speed_rpm})
        session.add_entity("tank1", "Tank", {"level_pct": level_pct})
        session.add_relationship("pump1", "feeds", "tank1")
        return session

    def test_it_ships(self):
        assert self.NAME in EXAMPLES

    def test_the_declared_response_is_walked_not_jumped(self):
        """The reason this example exists: a delay and a lag, not a step."""
        from arbiter_engine.twin.actions import ActionInstance
        per_step = rollout(
            self._session(),
            actions=[ActionInstance("throttle_pump", "pump1",
                                    {"speed_rpm": 800.0}, 0.0)],
            horizon_s=3600.0, step_s=60.0).to_dict()["simulation"]["per_step"]
        levels = [s["values"]["tank1"]["level_pct"] for s in per_step]
        assert levels[0] == pytest.approx(92.0), (
            "the declared 120s delay means nothing moves in the first minute")
        assert levels[-1] < 55.0, "the response never developed"
        # Strictly monotone once it starts: a jump would show as one change
        # followed by a flat line.
        moving = [a - b for a, b in zip(levels[2:], levels[1:-1])]
        assert sum(1 for d in moving if abs(d) > 1e-9) > 10, (
            "the level moved in only a handful of steps, which is a jump "
            "rather than the declared first-order response")

    def test_plan_ranks_its_declared_candidates(self):
        payload = plan(self._session(), horizon_s=1800.0,
                       step_s=60.0).to_dict()["plan"]
        assert payload["ranked"] is True
        assert len(payload["candidates"]) >= 5, "four settings and do_nothing"
        assert len({c["objective"] for c in payload["candidates"]}) > 1, (
            "every candidate scored the same, so the declared dynamics did "
            "not reach the ranking")
        assert not [d for d in payload["not_checked"]
                    if d["reason"] in ("no_objective", "no_candidates")]

    def test_model_describe_sees_the_declared_coupling(self):
        model = model_describe(self._session()).to_dict()["model"]
        assert model["proposed_transitions"]["checked"]["couplings_seen"] == 1
        assert model["transitions"]["declared"], (
            "the example declares a transition and `model_describe` does not "
            "list it")

    def test_the_example_itself_reports_no_unread_input(self):
        assert check(self._session()).to_dict()["unread_properties"] == []
