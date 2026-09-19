"""The learner fits the quantity the model declares, not a per-sample slope.

`Transition.gain` IS A STEADY-STATE GAIN. MODELING.md says so and
`TwinEdge.response_fraction` supplies the time course separately. The learner
read one temporal field, `propagation_delay_s`, then regressed the first
differences of the two series against each other -- and never read
`response_model` or `time_constant_s` at all.

Those two estimands coincide only when the response is instantaneous. On a
first-order edge the discrete update is

    y_t - y_{t-1} = alpha *(G *x_t + c - y_{t-1}), alpha = 1 - exp(-dt/tau)

so the change in the target tracks the ERROR, not the change in the source,
and a slope of `dy` on `dx` returns a fraction of `G` of order `alpha`.

Measured before the fix, on the fixture below -- a series generated through
the edge's own declared response at `tau = 600 s` sampled every 60 s, with a
declared gain of 0.02: the learner fitted 0.00234, filed a `disagreement`, and
attached a remedy telling the author the data put the gain elsewhere. Following
that remedy would have replaced a correct datasheet number with one eight
times too small. The declaration is correctly left untouched; the REPORT was
wrong, and a wrong report with a confident interval is worse than none.

WHY THE SUITE COULD NOT SEE IT. The shipped learner fixture declares
`time_constant_s: 1, response_model: step` and generates the target as an
instantaneous multiple of the source -- the single regime where the
differenced slope IS the steady-state gain.

THE SERIES HERE IS GENERATED FROM THE DECLARED CURVE, NOT FROM THE FIT. The
generator below applies `1 - exp(-dt/tau)` written out in full rather than
calling the engine, because a fixture built by the code under test cannot
falsify it.
"""
from __future__ import annotations

import math
import random
from datetime import timedelta

import pytest

from arbiter_engine import api

MODEL = """
domain:
  id: estimand
  name: A coupling with a declared time course
  entity_types: [Pump, Tank]
  relationship_types: [feeds]
  indicators:
    Pump:
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}
    Tank:
      - {name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}
  relationship_rules:
    - type: feeds
      source_type: Pump
      target_type: Tank
      temporal: {propagation_delay_s: 0, time_constant_s: %(tau)s,
                 response_model: %(model)s}
      transition: {from: speed_rpm, to: level_pct, gain: %(gain)s,
                   source: datasheet}
"""

DECLARED_GAIN = 0.02
INTERVAL_S = 60.0
SAMPLES = 400
BASE_SPEED = 1000.0
BASE_LEVEL = 50.0


def _session(tmp_path, tau, model, name, gain=DECLARED_GAIN):
    path = tmp_path / f"{name}.yaml"
    path.write_text(MODEL % {"tau": tau, "model": model, "gain": gain})
    session = api.EngineSession()
    session.load_model(str(path))
    session.add_entity("pump1", "Pump", {"speed_rpm": BASE_SPEED})
    session.add_entity("tank1", "Tank", {"level_pct": BASE_LEVEL})
    session.add_relationship("pump1", "feeds", "tank1")
    return session


def _feed_lagged_series(session, tau, gain=DECLARED_GAIN, seed=7):
    """A series the declared model would actually produce.

    The target relaxes toward `BASE_LEVEL + gain * (speed - BASE_SPEED)` with
    the declared time constant, which is what `response_model: exponential`
    means sampled on a grid.
    """
    rng = random.Random(seed)
    alpha = 1.0 - math.exp(-INTERVAL_S / float(tau))
    speed, level = BASE_SPEED, BASE_LEVEL
    now = api.now_utc()
    for k in range(SAMPLES):
        speed += rng.uniform(-50.0, 50.0)
        level += alpha * (
            (BASE_LEVEL + gain * (speed - BASE_SPEED)) - level)
        when = now - timedelta(seconds=INTERVAL_S * (SAMPLES - k))
        session.add_observations("pump1", "speed_rpm", [(when, speed)])
        session.add_observations("tank1", "level_pct", [(when, level)])
    return session


def _proposed(session):
    return api.model_describe(session).to_dict()[
        "model"]["proposed_transitions"]


class TestACorrectDeclarationIsNotContradicted:

    @pytest.mark.parametrize("tau", [600.0, 300.0, 60.0])
    def test_a_series_generated_through_the_declared_response_agrees(
            self, tmp_path, tau):
        session = _feed_lagged_series(
            _session(tmp_path, tau, "exponential", f"tau{int(tau)}"), tau)
        assert _proposed(session)["disagreements"] == [], (
            f"at tau={tau}s the declared gain generated this series through "
            f"the declared response model, and the learner reported it as "
            f"contradicted")

    def test_the_fitted_number_is_the_declared_quantity(self, tmp_path):
        session = _feed_lagged_series(
            _session(tmp_path, 600.0, "exponential", "recover"), 600.0)
        fitted = _proposed(session)["fitted"]
        assert len(fitted) == 1
        assert fitted[0]["gain"] == pytest.approx(DECLARED_GAIN, rel=1e-3), (
            f"the fit returned {fitted[0]['gain']} for a steady-state gain of "
            f"{DECLARED_GAIN}; a per-sample slope would land near "
            f"{DECLARED_GAIN * (1 - math.exp(-INTERVAL_S / 600.0)):.5f}")

    def test_the_proposal_names_the_response_model_it_fitted_through(
            self, tmp_path):
        session = _feed_lagged_series(
            _session(tmp_path, 600.0, "exponential", "named"), 600.0)
        assert _proposed(session)["fitted"][0][
            "response_model"] == "exponential", (
            "two different computations produce the `gain` key, and a reader "
            "comparing one against a datasheet must know which ran")


class TestAWrongDeclarationIsStillContradicted:
    """Guard: a fit that agrees with everything has stopped being a check."""

    def test_a_gain_the_data_excludes_is_still_reported(self, tmp_path):
        # Declared 0.05; the series is generated at 0.02.
        session = _feed_lagged_series(
            _session(tmp_path, 600.0, "exponential", "wrong", gain=0.05),
            600.0, gain=DECLARED_GAIN)
        disagreements = _proposed(session)["disagreements"]
        assert len(disagreements) == 1
        assert disagreements[0]["declared_gain"] == pytest.approx(0.05)
        assert disagreements[0]["fitted_gain"] == pytest.approx(
            DECLARED_GAIN, rel=1e-2)

    def test_the_declaration_is_still_never_edited(self, tmp_path):
        """A proposal, not a repair -- unchanged by this fix."""
        path = tmp_path / "untouched.yaml"
        session = _feed_lagged_series(
            _session(tmp_path, 600.0, "exponential", "untouched", gain=0.05),
            600.0, gain=DECLARED_GAIN)
        before = path.read_text()
        _proposed(session)
        assert path.read_text() == before


class TestAnUnsupportedResponseModelIsRefusedNotGuessed:
    """LINEAR and LOGARITHMIC are not first-order lags, so no transform makes
    the declared gain a least-squares slope. A number produced under the wrong
    model is precisely the defect this file exists for, so it is declined."""

    @pytest.mark.parametrize("model", ["linear", "logarithmic"])
    def test_it_declines_by_name(self, tmp_path, model):
        session = _feed_lagged_series(
            _session(tmp_path, 600.0, model, f"unsup{model}"), 600.0)
        proposed = _proposed(session)
        assert proposed["fitted"] == []
        reasons = {entry["reason"] for entry in proposed["not_fitted"]}
        assert "response_model_unsupported" in reasons
        assert proposed["disagreements"] == [], (
            "refusing to fit must not also file a contradiction")

    def test_a_step_edge_is_still_fitted(self, tmp_path):
        """The regime the original fit assumed keeps working."""
        session = _session(tmp_path, 1.0, "step", "stepwise")
        rng = random.Random(11)
        speed = BASE_SPEED
        now = api.now_utc()
        for k in range(SAMPLES):
            speed += rng.uniform(-50.0, 50.0)
            level = BASE_LEVEL + DECLARED_GAIN * (speed - BASE_SPEED)
            when = now - timedelta(seconds=INTERVAL_S * (SAMPLES - k))
            session.add_observations("pump1", "speed_rpm", [(when, speed)])
            session.add_observations("tank1", "level_pct", [(when, level)])
        fitted = _proposed(session)["fitted"]
        assert len(fitted) == 1
        assert fitted[0]["gain"] == pytest.approx(DECLARED_GAIN, rel=1e-6)
        assert fitted[0]["response_model"] == "step"
