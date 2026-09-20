"""`dynamics: {model: trend}` reports a FLAT median and a widening band.

Three documents said otherwise. The published spec said `trend`
"fits a straight line and extrapolates it"; the comment beside the return
said `q` "extrapolates the line across the horizon"; and an outside reading
reasoned from the word, predicted a ramp through a first-order lag, and had
to be refuted with a measurement. All three describe what the NAME suggests.

What `TrendCurve.fit` returns is a local-level `Fitted` whose `level` is the
fitted line AT THE LAST SAMPLE and whose `q` -- the variance the level gains
per second -- is the slope squared. `Fitted.forecast` holds `mean = level` at
every horizon and adds `q *horizon_s` to the variance. So the slope makes
the forecast WIDER and never higher, and a series that has been climbing is
reported as more uncertain rather than as certain to keep climbing.

That is the demotion `TrendCurve`'s own docstring argues for, carried through
to the arithmetic on purpose: extrapolating a fitted line states a direction
for a series that may have none. This file pins the arithmetic AND the
sentence, so the next reader who corrects the prose back toward the name has
to change a test that says why.
"""
from __future__ import annotations

import math
import pathlib
import random
from datetime import timedelta

import pytest

from arbiter_engine import api
from arbiter_engine.projection.projector import TrendCurve

N = 120
NOISE = 7.0


def _series(slope, noise=NOISE, seed=11):
    rng = random.Random(seed)
    now = api.now_utc()
    return [(now - timedelta(seconds=60 * (N - k)),
             1000.0 + slope * k + rng.gauss(0.0, noise))
            for k in range(N)]


def _fit(slope, **kw):
    fitted = TrendCurve().fit(_series(slope, **kw), {}, "m1.reading")
    assert not hasattr(fitted, "reason"), (
        f"the fit declined: {getattr(fitted, 'reason', None)}")
    return fitted


class TestTheMedianDoesNotMove:

    def test_every_horizon_reports_the_same_median(self):
        fitted = _fit(3.0)
        medians = [fitted.forecast(h).mean
                   for h in (600.0, 1800.0, 3600.0, 7200.0, 86400.0)]
        assert all(m == pytest.approx(medians[0], rel=1e-12)
                   for m in medians), (
            f"the medians move across horizons: {medians}. `trend` carries "
            f"its slope as process noise, so the median is the fitted line "
            f"at the LAST SAMPLE and stands still.")

    def test_the_median_is_the_line_at_the_last_sample(self):
        """Not the line extrapolated to the horizon, which is what the
        documents used to say -- and which for a 24-hour horizon on this
        series would be thousands of units away."""
        slope = 3.0
        fitted = _fit(slope)
        series = _series(slope)
        last = series[-1][1]
        assert fitted.forecast(86400.0).mean == pytest.approx(
            last, abs=4.0 * NOISE), (
            "the median has left the neighbourhood of the last reading")


class TestTheBandWidensWithTheSlope:

    def test_a_steeper_slope_widens_the_band_and_leaves_the_median(self):
        flat, steep = _fit(0.0), _fit(30.0)
        horizon = 3600.0
        assert steep.forecast(horizon).sigma > flat.forecast(horizon).sigma, (
            "a steeper fitted slope must make the forecast wider")
        assert steep.q > flat.q, "`q` is the slope squared"
        assert steep.forecast(horizon).mean == pytest.approx(
            steep.level), "the slope moved the median"

    def test_the_band_grows_with_the_horizon(self):
        fitted = _fit(3.0)
        widths = [fitted.forecast(h).sigma
                  for h in (600.0, 1800.0, 3600.0, 7200.0)]
        assert all(b > a for a, b in zip(widths, widths[1:])), (
            f"the band did not widen with the horizon: {widths}")

    def test_the_width_is_exactly_the_declared_arithmetic(self):
        fitted = _fit(3.0)
        horizon = 3600.0
        expected = math.sqrt(fitted.variance + fitted.q * horizon + fitted.r)
        assert fitted.forecast(horizon).sigma == pytest.approx(
            expected, rel=1e-12)


def _spec_text():
    """The guide this tree has, whitespace-collapsed.

    COLLAPSED because the first version of this file asserted the old
    sentence was absent and PASSED while the correction beside it quoted that
    sentence in full -- the quote happened to wrap across a newline, so the
    literal did not match. A test that a reflow can flip was pinning the line
    breaks, not the claim.

    BOTH TREES because the source keeps the publication spec and the SHIPPED
    package keeps `MODELING.md`, which is derived from it. Looking only for
    the spec made this guard skip in the built tree -- silently, and in the
    one lane whose guide a reader of the published package actually has.
    """
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / "MODELING.md",
                      here.parents[2] / "MODELING.md"):
        if candidate.exists():
            return " ".join(candidate.read_text().split())
    for parent in here.parents:
        candidate = parent / "docs" / "publication" / "domain-model-spec.md"
        if candidate.exists():
            return " ".join(candidate.read_text().split())
    return None


class TestTheDocumentsAgreeWithTheArithmetic:
    """The prose is the thing that was wrong, so the prose is pinned too."""

    def test_the_spec_does_not_claim_the_median_extrapolates(self):
        text = _spec_text()
        if text is None:
            pytest.skip("the publication spec is not in this tree")
        assert "fits a straight line and extrapolates it" not in text, (
            "the spec describes `trend` as extrapolating its median, which "
            "is what the name suggests and not what the model computes")

    def test_the_spec_says_which_way_the_slope_acts(self):
        text = _spec_text()
        if text is None:
            pytest.skip("the publication spec is not in this tree")
        assert "widens; it does not point" in text
