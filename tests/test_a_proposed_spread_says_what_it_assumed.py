"""A proposed `gain_sigma:` reports what its own assumption is worth.

`_fit` computes the slope's standard error the ordinary way, which
assumes the residuals are independent. Neither fit path gives it that: both
difference the target's readings, so the residuals are an MA(1) whose lag-1
correlation measures near -0.5 EITHER WAY.

The correlation is therefore not the diagnostic, and this file was written
around the belief that it was. Measured over 200 trials at each of two noise
levels, a declared `gain: 0.02` recovered from 300 samples:

    path lag-1 autocorr ordinary se / empirical scatter
    step -0.49 1.03x
    exponential -0.49 5.17x

The same correlation, and one number right while the other is five times too
wide. What decides it is whether the REGRESSOR was differenced along with the
target. On the `step` path it was -- the fit is `dy = G dx + c` -- so the
correlation cancels out of the estimator and the ordinary standard error is
already right. On the `exponential` path the fit is `dy/alpha + y_{t-1} =
G x_t + c`, whose regressor is a LEVEL: the noise amplified by `1/alpha`
telescopes against a regressor that barely moves between samples, leaving an
estimator far more precise than its own residual scatter suggests.

WHAT IS REPORTED, AND WHY IT IS A FLAG RATHER THAN A CORRECTION. The exact
correction for an MA(1) error is the sandwich at lag 1, and it is NOT
ESTIMABLE on this data: the long-run variance of an MA(1) whose coefficient
sits near -1 is nearly zero, so the sample estimate came out non-positive in
81 of 200 trials -- two times in five, on the very path it exists for -- and
1.37x rather than 1.00x when it did not. A figure that silently falls back to
the number it was meant to replace, that often, is the default-nobody-can-see
shape this engine refuses everywhere else. (An earlier pass here reported
0.94x for it, which was an artefact of averaging the failed estimates in as
zeros.)

So the proposal carries the two things that ARE facts: the measured
correlation, and whether the standard error beside it can be read the way its
own docstring says -- which the engine knows from the declared response model
without estimating anything.

Interval coverage was 60/60 at both noise levels either way, so
`disagreement` under-triggers rather than over-triggers. The safe direction,
and the reason this is a reporting defect rather than a wrong verdict.
"""
from __future__ import annotations

import math
import pathlib
import tempfile
from datetime import datetime, timedelta

import numpy as np
import pytest

from arbiter_engine import api

T0 = datetime(2026, 9, 10, 12, 0, 0)
TAU, DT, GAIN, N = 600.0, 60.0, 0.02, 300
ALPHA = 1.0 - math.exp(-DT / TAU)

MODEL = """
domain:
  id: proposed_spread
  name: What a proposed spread assumed
  entity_types: [Pump, Tank]
  relationship_types: [feeds]
  indicators:
    Pump:
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 1e9}
    Tank:
      - {name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 1e9}
  relationship_rules:
    - type: feeds
      source_type: Pump
      target_type: Tank
      temporal: {propagation_delay_s: 0, time_constant_s: %(tau)s,
                 response_model: %(model)s}
      transition: {from: speed_rpm, to: level_pct, gain: 0.02,
                   source: datasheet, gain_sigma: estimate}
"""


def _fitted(*, response_model="exponential", tau=600.0, noise_sd=0.05,
            seed=0):
    """One proposal, over a source that wanders and a target that follows the
    declared dynamics exactly plus measurement noise."""
    rng = np.random.default_rng(seed)
    source = 1000.0 + np.cumsum(rng.normal(0, 20, N))
    target = np.zeros(N)
    target[0] = GAIN * source[0]
    if response_model == "exponential":
        for index in range(1, N):
            target[index] = target[index - 1] + ALPHA * (
                GAIN * source[index] - target[index - 1])
    else:
        target = GAIN * source
    observed = target + rng.normal(0, noise_sd, N)

    path = pathlib.Path(tempfile.mkdtemp()) / "model.yaml"
    path.write_text(MODEL % {"tau": tau, "model": response_model})
    session = api.EngineSession()
    session.load_model(str(path))
    stamps = [T0 - timedelta(seconds=(N - 1 - i) * DT) for i in range(N)]
    session.add_observations("pump1", "speed_rpm",
                             list(zip(stamps, map(float, source))))
    session.add_observations("tank1", "level_pct",
                             list(zip(stamps, map(float, observed))))
    session.add_entity("pump1", "Pump", {"speed_rpm": float(source[-1])})
    session.add_entity("tank1", "Tank", {"level_pct": float(observed[-1])})
    session.add_relationship("pump1", "feeds", "tank1")
    proposals = api.model_describe(session).to_dict()["model"][
        "proposed_transitions"]["fitted"]
    assert proposals, "the premise: this series fits"
    return proposals[0]


class TestThePremise:
    """If the fit stops recovering the declared gain, the number this file is
    about is not the number it says it is."""

    def test_the_declared_gain_comes_back(self):
        assert _fitted()["gain"] == pytest.approx(GAIN, abs=0.002)

    def test_and_a_spread_was_asked_for(self):
        assert _fitted()["gain_sigma_requested"] is True


class TestBothPathsCorrelateTheirResiduals:
    """The premise of the whole file, and the thing that makes the
    correlation useless as a warning on its own."""

    def test_a_lagged_fit_reports_it(self):
        proposal = _fitted(response_model="exponential", noise_sd=0.2)
        assert proposal["residual_autocorrelation"] < -0.2

    def test_and_so_does_a_step_fit(self):
        proposal = _fitted(response_model="step", tau=1.0, noise_sd=0.2)
        assert proposal["residual_autocorrelation"] < -0.2, (
            f"a `step` fit differences the target too, so its residuals "
            f"correlate exactly as much: "
            f"{proposal['residual_autocorrelation']}")


class TestTheFlagIsTheOneThatDiscriminates:

    def test_a_proposal_says_whether_its_standard_error_can_be_read(self):
        proposal = _fitted(response_model="exponential")
        assert "gain_sigma_assumes_independent_residuals" in proposal, (
            f"the proposal carries {sorted(proposal)} and nothing among them "
            f"says what the standard error beside `gain_sigma` is worth")

    def test_a_lagged_fit_says_the_assumption_does_not_hold(self):
        """The fit is `dy/alpha + y_{t-1} = G x_t + c`, whose regressor is a
        level: the noise amplified by `1/alpha` telescopes against a
        regressor that barely moves, and the estimator ends up five times
        more precise than its residual scatter suggests."""
        assert _fitted(response_model="exponential")[
            "gain_sigma_assumes_independent_residuals"] is False

    def test_a_step_fit_says_it_does(self):
        """Here the regressor is differenced along with the target, so the
        correlation cancels out of the estimator and the ordinary standard
        error was right all along -- which the autocorrelation, identical on
        both paths, could never have told anyone."""
        assert _fitted(response_model="step", tau=1.0)[
            "gain_sigma_assumes_independent_residuals"] is True


class TestTheNumbersThemselvesAreUnchanged:
    """This round reports; it decides nothing. The gain, the interval and the
    proposed spread are exactly what they were."""

    def test_the_gain_and_its_interval_still_bracket_the_declaration(self):
        proposal = _fitted()
        low, high = proposal["interval"]
        assert low <= GAIN <= high

    def test_the_proposed_spread_is_still_the_ordinary_standard_error(self):
        """Half the 95 % band over 1.96, which is what it has always been."""
        proposal = _fitted()
        low, high = proposal["interval"]
        assert proposal["gain_sigma"] == pytest.approx(
            (high - low) / (2.0 * 1.96), rel=1e-9)
