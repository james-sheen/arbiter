"""The walk stamped that it approximated, and never how much that cost.

A value two hops out is charged each edge's own step response against
a source that is already lagged, so it develops as the PRODUCT of two curves
where the declared dynamics imply their CONVOLUTION. The walk has stamped
`series_edges_compose_by_product` since -- which names the assumption
and stops there. **A trajectory produced by an approximation is a number, and
the size of the approximation is its predicate**, which is the rule
`checked.invariants` exists to enforce one level out.

WHY THE STAMP STOOD. `MODELING.md` argues, correctly, that the
partial-fraction form for distinct time constants cancels catastrophically as
two of them approach each other, so a robust version needs a near-equality
tolerance -- a number nobody declared, and therefore not this engine's to
pick. **That argument is about the FORMULATION, not the convolution.**
Measured at `t=900`, `tau1=600`, sweeping `tau2` down onto it:

    tau2 - tau1 partial fraction divided difference
    1 0.441756579002 0.441756579002
    1e-9 0.442178596519 0.442174599629
    1e-13 0.625000000000 0.442174599629
    0 ZeroDivisionError 0.442174599629

The right-hand column meets `1 - (1 + t/tau)exp(-t/tau)` exactly at equality.
`expm1` is built for this, and the only branch is `x != 0.0` -- an exact float
comparison, not a tolerance.

 THEN CLOSED IT. Having established that the exact form is available
and stable, the walk composes two exponential stages exactly and stamps
`series_edges_composed_exactly`. **The three pins below that asserted the
approximation was still in force were inverted deliberately** -- they had done
their job, which was to hold the measurement apart from the fix until the fix
was ruled on.

WHAT THIS FILE PINS
  - the two-hop trajectory IS the convolution, to float precision;
  - the row records the composition that was AVOIDED, so an author learns how
    much of a multi-hop transient depends on the composition being exact;
  - `exact` matches the closed form derived independently here;
  - the error is SIGNED, and the sign is the point -- the product LEADS, so a
    breach two hops out is predicted early;
  - the divergence vanishes at steady state, which is where the engine has
    always said the composition is exact;
  - a chain with NO closed form is stamped and NOT quantified, because a
    figure covering only the stages it could solve would describe a chain
    nobody declared;
  - one hop is neither stamped nor quantified.
"""
from __future__ import annotations

import math

import pytest

from arbiter_engine import api
from arbiter_engine.twin.actions import ActionInstance
from arbiter_engine.twin.topology import TwinEdge

TAU, STEP_S, HORIZON_S = 600.0, 300.0, 3600.0
STEP = 100.0

MODEL = """
domain:
  id: cascade
  name: Two lags in series
  entity_types: [A, B, C]
  relationship_types: [drives]
  indicators:
    A: [{name: x, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9, window: 30m}]
    B: [{name: y, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9, window: 30m}]
    C: [{name: z, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9, window: 30m}]
  relationship_rules:
    - type: drives
      source_type: A
      target_type: B
      temporal: {propagation_delay_s: 0, time_constant_s: 600,
                 response_model: exponential}
      transition: {from: x, to: y, gain: 1.0, gain_sigma: 0.01, source: datasheet}
    - type: drives
      source_type: B
      target_type: C
      temporal: {propagation_delay_s: 0, time_constant_s: 600,
                 response_model: %(second)s}
      transition: {from: y, to: z, gain: 1.0, gain_sigma: 0.01, source: datasheet}
  action_templates:
    - name: step_x
      applies_to: A
      parameters_schema: {x: {type: number, entity_property: x, candidates: [100]}}
      effect: set
      settle_s: 1
      source: runbook
"""


def _sim(tmp_path, name, second="exponential", hops=2):
    path = tmp_path / f"{name}.yaml"
    path.write_text(MODEL % {"second": second})
    session = api.EngineSession()
    session.load_model(str(path))
    for eid, typ, prop in (("a", "A", "x"), ("b", "B", "y"), ("c", "C", "z")):
        session.add_entity(eid, typ, {prop: 0.0})
        session.add_observations(eid, prop, [0.0] * 20)
    session.add_relationship("a", "drives", "b")
    if hops == 2:
        session.add_relationship("b", "drives", "c")
    act = [ActionInstance(template="step_x", entity_id="a",
                          parameters={"x": STEP}, at_s=0)]
    return api.rollout(session, actions=act, horizon_s=HORIZON_S,
                       step_s=STEP_S).to_dict()["simulation"]


def _exact(t):
    """Two equal first-order lags in series, unit step. Derived here, not
    imported, so the guard and the engine cannot agree by sharing a bug."""
    return 1.0 - (1.0 + t / TAU) * math.exp(-t / TAU)


class TestTheTrajectoryIsNowTheConvolution:
    """The inverted pins: what used to hold the product in place."""

    def test_the_two_hop_value_is_the_exact_convolution(self, tmp_path):
        sim = _sim(tmp_path, "exactnow")
        for step in sim["per_step"]:
            assert step["values"]["c"]["z"] == pytest.approx(
                STEP * _exact(step["at_s"]), abs=1e-9)

    def test_it_is_no_longer_the_product(self, tmp_path):
        """The old answer led by up to 0.161 per unit. If this ever passes as
        equality again, the correction has been lost."""
        sim = _sim(tmp_path, "notproduct")
        worst = max(
            abs(s["values"]["c"]["z"] - STEP * (1.0 - math.exp(-s["at_s"] / TAU)) ** 2)
            for s in sim["per_step"])
        assert worst > 10.0

    def test_the_stamp_says_exact_not_approximate(self, tmp_path):
        sim = _sim(tmp_path, "stamped")
        assert "series_edges_composed_exactly" in sim["assumptions"]
        assert "series_edges_compose_by_product" not in sim["assumptions"]


class TestTheRowsSayWhatTheApproximationCost:

    def test_one_row_per_step(self, tmp_path):
        sim = _sim(tmp_path, "rows")
        assert len(sim["series_errors"]) == len(sim["per_step"]) > 0
        assert sim["checked"]["series_chains_quantified"] == 1

    def test_the_row_records_the_composition_that_was_avoided(self, tmp_path):
        """ inverted this. `exact` is now what the walk USED and
        `product` is the counterfactual -- so the trajectory is read back
        against `exact`, and `product` is held to the curve the walk would
        have followed without the correction."""
        sim = _sim(tmp_path, "faithful")
        by_t = {s["at_s"]: s["values"]["c"]["z"] for s in sim["per_step"]}
        for row in sim["series_errors"]:
            # The envelope rounds fractions to 9 dp, as the ledger's scores
            # do, so a value scaled by the step carries that rounding out to
            # `STEP * 1e-9`.
            assert by_t[row["at_s"]] == pytest.approx(
                STEP * row["exact"], abs=STEP * 1e-9)
            t = row["at_s"]
            assert row["product"] == pytest.approx(
                (1.0 - math.exp(-t / TAU)) ** 2, abs=1e-9)

    def test_exact_matches_the_independent_closed_form(self, tmp_path):
        sim = _sim(tmp_path, "exact")
        for row in sim["series_errors"]:
            assert row["exact"] == pytest.approx(_exact(row["at_s"]), abs=1e-9)

    def test_the_error_is_signed_and_the_product_leads(self, tmp_path):
        """The sign is the point: a breach two hops out is predicted EARLY."""
        sim = _sim(tmp_path, "signed")
        for row in sim["series_errors"]:
            # Three independently rounded 9 dp figures, so the residual is
            # bounded by their rounding and not by the arithmetic.
            assert row["error"] == pytest.approx(
                row["product"] - row["exact"], abs=2.5e-9)
            assert row["error"] > 0.0

    def test_the_divergence_peaks_mid_transient(self, tmp_path):
        """Pinned as a SHAPE, not as a figure: the peak instant moves with
        any change to the declared time constants."""
        sim = _sim(tmp_path, "peak")
        errors = [r["error"] for r in sim["series_errors"]]
        assert max(errors) > errors[0]
        assert max(errors) > errors[-1]

    def test_it_vanishes_at_steady_state(self, tmp_path):
        """Where the engine has always said the composition is exact."""
        sim = _sim(tmp_path, "steady")
        assert sim["series_errors"][-1]["error"] < 0.02

    def test_a_row_names_the_chain_it_describes(self, tmp_path):
        sim = _sim(tmp_path, "named")
        row = sim["series_errors"][0]
        assert row["entity_id"] == "c" and row["indicator"] == "z"
        assert row["stages"] == [[TAU, 0.0], [TAU, 0.0]]


class TestAnUnsolvableChainIsStampedAndNotQuantified:
    """A figure covering only the stages it could solve would describe a
    chain nobody declared."""

    @pytest.mark.parametrize("second", ["linear", "logarithmic"])
    def test_a_non_exponential_stage_refuses_the_figure(self, tmp_path, second):
        sim = _sim(tmp_path, f"mixed_{second}", second=second)
        assert "series_edges_compose_by_product" in sim["assumptions"]
        assert not sim.get("series_errors")
        assert "series_chains_quantified" not in sim["checked"]

    def test_one_hop_is_neither_stamped_nor_quantified(self, tmp_path):
        sim = _sim(tmp_path, "single", hops=1)
        assert "series_edges_compose_by_product" not in sim["assumptions"]
        assert not sim.get("series_errors")


class TestTheCascadeFormIsStableWhereTheNaiveOneIsNot:
    """The measurement that makes the whole leg legitimate."""

    @staticmethod
    def _naive(t, tau1, tau2):
        a, b = 1.0 / tau1, 1.0 / tau2
        return 1.0 - (b * math.exp(-a * t) - a * math.exp(-b * t)) / (b - a)

    @pytest.mark.parametrize("eps", [1e-6, 1e-9, 1e-12, 0.0])
    def test_it_meets_the_equal_tau_limit_all_the_way_down(self, eps):
        got = TwinEdge.cascade_fraction(((TAU, 0.0), (TAU + eps, 0.0)), 900.0)
        assert got == pytest.approx(_exact(900.0), abs=1e-9)

    def test_it_converges_rather_than_jumping(self):
        """Separated from the equality check because at `1e-3` the two time
        constants genuinely DIFFER: the cascade is right to disagree with the
        equal-tau form there, by 4.2e-7. What matters is that closing the gap
        closes the difference, smoothly, with no threshold in between."""
        target = _exact(900.0)
        gaps = [abs(TwinEdge.cascade_fraction(
            ((TAU, 0.0), (TAU + e, 0.0)), 900.0) - target)
            for e in (1e-3, 1e-4, 1e-5, 1e-6)]
        assert gaps == sorted(gaps, reverse=True)
        assert gaps[0] < 1e-5

    def test_the_naive_form_is_the_one_that_fails(self):
        """Pins the REASON this is not simply the textbook formula. If this
        ever passes, the argument in `MODELING.md` has changed and this leg's
        justification needs re-reading."""
        assert self._naive(900.0, TAU, TAU + 1.0) == pytest.approx(
            _exact(900.0), abs=1e-3)
        assert abs(self._naive(900.0, TAU, TAU + 1e-13)
                   - _exact(900.0)) > 1e-3
        with pytest.raises(ZeroDivisionError):
            self._naive(900.0, TAU, TAU)

    def test_it_refuses_every_chain_it_cannot_solve(self):
        assert TwinEdge.cascade_fraction(((TAU, 0.0),), 900.0) is None
        assert TwinEdge.cascade_fraction((), 900.0) is None
        assert TwinEdge.cascade_fraction(
            ((TAU, 0.0), (TAU, 0.0), (TAU, 0.0)), 900.0) is None
        assert TwinEdge.cascade_fraction(((TAU, 0.0), None), 900.0) is None

    def test_dead_time_delays_the_whole_cascade(self):
        assert TwinEdge.cascade_fraction(((TAU, 100.0), (TAU, 100.0)),
                                         150.0) == 0.0

    def test_it_reaches_unity_at_steady_state(self):
        assert TwinEdge.cascade_fraction(((TAU, 0.0), (TAU, 0.0)),
                                         1e7) == pytest.approx(1.0, abs=1e-12)
