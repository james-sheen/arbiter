"""A sampled probability carries its exact interval, and a certain one its point.

The Monte Carlo predictor's 95% interval was the normal approximation,
p +/- 1.96*sqrt(p(1-p)/n) clipped to [0, 1]. It collapses at the ends: when every
sample shows the outcome the standard error is 0, so sixty clears of sixty read
[1.0, 1.0], where the 95% lower bound is 0.940. Near a floor it was too generous:
at 56 of 60 it read 0.870, above the 0.85 an `active` gate checks, where the exact
bound is 0.838. The gate compares that lower bound with a policy's floor, so it
approved what the bound it names would refuse.

The interval is exact (Clopper-Pearson) now. Its defining property is pinned
rather than its formula: over every count, it covers the true probability at
least 95% of the time. The normal approximation fails that, and a test says so,
or the property would pass anything.

The planner reads the same interval for `clearance_probability`. A candidate whose
transitions are deterministic samples one constant -- nothing about it was
uncertain -- so it reports its point, as it did; a candidate sampled from a
declared spread reports the exact interval of its count, which no longer looks
like the deterministic one when nothing cleared.
"""
from __future__ import annotations

import math
import pathlib
import tempfile
from pathlib import Path

import pytest

from arbiter_engine import api
from arbiter_engine.twin.monte_carlo_predictor import (
    ACTIVE_MODE_AUTO_APPROVE_THRESHOLD, MonteCarloOutcomeDistribution,
    exact_interval)

#: `scipy.stats.beta.ppf` at 0.025 and 0.975, recorded. scipy is not a
#: dependency of this package: it was used to check, not to compute.
RECORDED = {
    (1, 10): (0.0025285785444617848, 0.4450161170281954),
    (9, 10): (0.5549838829718047, 0.9974714214555382),
    (2, 100): (0.0024313368239425423, 0.07038393247107011),
    (30, 100): (0.21240642048953667, 0.3998146761798041),
    (43, 100): (0.331391016631383, 0.5328662616751536),
    (56, 60): (0.838013244802271, 0.9815382224241185),
    (58, 60): (0.8847189555807483, 0.9959373753579065),
    (59, 60): (0.910600949942513, 0.999578125547658),
}
P_GRID = (0.001, 0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99, 0.999)


def _mass(k, n, p):
    return math.exp(math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
                    + k * math.log(p) + (n - k) * math.log1p(-p))


def _coverage(intervals, n, p):
    """The chance, at probability `p`, that the interval drawn covers `p`."""
    return sum(_mass(k, n, p) for k, (low, high) in enumerate(intervals)
               if low <= p <= high)


def _normal_approximation(k, n):
    p = k / n
    margin = 1.96 * math.sqrt(p * (1 - p) / n)
    return max(0.0, p - margin), min(1.0, p + margin)


class TestTheInterval:

    @pytest.mark.parametrize("k, n", sorted(RECORDED))
    def test_it_agrees_with_the_beta_quantiles(self, k, n):
        assert exact_interval(k, n) == pytest.approx(RECORDED[(k, n)], abs=1e-9)

    @pytest.mark.parametrize("n", [1, 10, 60, 1000])
    def test_at_the_ends_it_has_a_closed_form(self, n):
        edge = 0.025 ** (1 / n)
        assert exact_interval(n, n) == pytest.approx((edge, 1.0), abs=1e-12)
        assert exact_interval(0, n) == pytest.approx((0.0, 1 - edge), abs=1e-12)

    def test_no_sample_is_no_information(self):
        assert exact_interval(0, 0) == (0.0, 1.0)

    @pytest.mark.parametrize("n", [10, 60, 100])
    def test_it_covers_the_truth_at_least_ninety_five_times_in_a_hundred(self, n):
        intervals = [exact_interval(k, n) for k in range(n + 1)]
        short = {p: _coverage(intervals, n, p) for p in P_GRID}
        assert min(short.values()) >= 0.95 - 1e-12, short

    def test_the_normal_approximation_does_not(self):
        # The control: a property every interval met would test nothing. At
        # p = 0.99 and sixty samples, all sixty clear more than half the time,
        # and the approximation's [1.0, 1.0] then excludes the truth.
        intervals = [_normal_approximation(k, 60) for k in range(61)]
        assert _coverage(intervals, 60, 0.99) < 0.5


class TestTheGate:

    def _sixty(self, observed):
        return MonteCarloOutcomeDistribution(
            outcome_name="action_clears_problem",
            estimated_probability=observed / 60, sample_count=60,
            samples_observed=observed)

    def test_sixty_of_sixty_is_0_940_not_1(self):
        low, high = self._sixty(60).confidence_interval_95
        assert high == 1.0 and low == pytest.approx(0.025 ** (1 / 60), abs=1e-12)
        assert self._sixty(60).meets_active_mode_threshold

    def test_fifty_six_of_sixty_no_longer_meets_the_floor(self):
        # The approximation read 0.870 here, over the 0.85 floor.
        assert _normal_approximation(56, 60)[0] > ACTIVE_MODE_AUTO_APPROVE_THRESHOLD
        assert self._sixty(56).confidence_interval_95[0] < ACTIVE_MODE_AUTO_APPROVE_THRESHOLD
        assert not self._sixty(56).meets_active_mode_threshold

    def test_sixty_samples_cannot_show_more_than_0_940(self):
        # What a floor of 0.95 or 0.99 now means at sixty samples: out of reach.
        assert exact_interval(60, 60)[0] < 0.95


def _examples_dir() -> pathlib.Path:
    """Whichever copy this tree has: the built package ships `examples/` at its
    root, the source tree keeps them under the publication docs. Never an
    absolute path -- one names a directory that exists only where this file was
    written, and this file ships."""
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / "examples",
                      here.parents[2] / "docs" / "publication"
                      / "engine-example"):
        if candidate.is_dir() and list(candidate.glob("*.yaml")):
            return candidate
    raise AssertionError("no examples directory found in this tree")


SAMPLES = 100   # the planner's default; `api.plan` does not take another


@pytest.fixture(scope="module")
def candidates():
    """The pump-tank example asked for `clearance_probability`, at a tank level
    where one plan holds every kind of candidate: certain, sampled and always
    clear, sampled and sometimes, sampled and never."""
    text = (_examples_dir() / "pump_tank_dynamics.yaml").read_text().replace(
        "  planning:\n    objective: expected_findings",
        "  planning:\n    objective: clearance_probability\n"
        "    min_severity: warning")
    path = Path(tempfile.mkdtemp()) / "clearance.yaml"
    path.write_text(text)
    session = api.EngineSession()
    session.load_model(str(path))
    session.add_entity("pump1", "Pump", {"speed_rpm": 1000.0})
    session.add_entity("tank1", "Tank", {"level_pct": 50.0})
    session.add_relationship("pump1", "feeds", "tank1")
    return api.plan(session, horizon_s=3600.0,
                    step_s=300.0).to_dict()["plan"]["candidates"]


class TestThePlannersInterval:

    def _sampled(self, candidates):
        return [c for c in candidates if "declared_gain_spread_sampled" in c["assumptions"]]

    def test_the_premise_every_kind_is_here(self, candidates):
        sampled = {c["objective"] for c in self._sampled(candidates)}
        assert 1.0 in sampled and 0.0 in sampled and sampled - {0.0, 1.0}, sampled
        assert any("deterministic_transitions" in c["assumptions"] for c in candidates)

    def test_a_certain_candidate_reports_its_point(self, candidates):
        for c in candidates:
            if "deterministic_transitions" in c["assumptions"]:
                assert c["interval"] == [c["objective"], c["objective"]]

    def test_a_sampled_candidate_reports_the_exact_interval_of_its_count(self, candidates):
        for c in self._sampled(candidates):
            observed = round(c["objective"] * SAMPLES)
            assert c["interval"] == pytest.approx(
                list(exact_interval(observed, SAMPLES)), abs=1e-12)

    def test_sampled_and_never_clear_is_not_certain_and_never_clear(self, candidates):
        never = [c for c in self._sampled(candidates) if c["objective"] == 0.0]
        assert never and all(c["interval"][1] > 0.03 for c in never)
