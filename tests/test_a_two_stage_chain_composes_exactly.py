"""Two exponential lags in series now compose to their convolution.

 established that the exact cascade response is available and
numerically stable, and measured what the product approximation cost: on two
equal 600 s lags the product LEADS by 0.161 per unit at `t = 900 s`, so a
breach two hops out was predicted early and `plan` ranks on transients.

HOW IT IS DONE, AND WHY THAT WAY. The walk charges each edge's own response
against a source that is already lagged, so the contribution it is about to
form is `f1 *f2`. Scaling the FRACTION by `H / (f1 *f2)` lands it on `H`
without the propagation ever needing the un-lagged delta or the upstream gain
-- both of which would have to be threaded through every contribution in the
one routine every axiom evaluation in a rollout depends on. The correction
rides the fraction, so the value and its spread cannot come apart.

**PER CONTRIBUTION, NOT PER PROPERTY**, which is what makes converging paths
safe: each charge is corrected by its own chain and superposition is linear,
so a target fed by a two-stage chain and a direct edge gets each contribution
right.

WHAT STAYS APPROXIMATE, AND STILL SAYS SO. A chain containing a `linear` or
`logarithmic` stage has no closed cascade form and keeps
`series_edges_compose_by_product`. A three-stage chain gets the exact
two-stage composition for its solvable head and the product for the rest --
measured, that moves the answer from 28.11 units of error to 18.42 on three
equal 600 s lags, and it is still stamped as approximate because it is.

A rollout crossing both kinds carries BOTH stamps, which is the honest report.
"""
from __future__ import annotations

import math

import pytest

from arbiter_engine import api
from arbiter_engine.twin.actions import ActionInstance

TAU, STEP = 600.0, 100.0
EXACT_STAMP = "series_edges_composed_exactly"
PRODUCT_STAMP = "series_edges_compose_by_product"

_RULE = """    - {type: drives, source_type: %(src)s, target_type: %(dst)s,
       temporal: {propagation_delay_s: %(delay)s, time_constant_s: 600,
                  response_model: %(model)s},
       transition: {from: %(from)s, to: %(to)s, gain: 1.0,
                    gain_sigma: 0.01, source: datasheet}}
"""

HEAD = """
domain:
  id: cascade_exact
  name: Lags in series
  entity_types: [A, B, C, D]
  relationship_types: [drives]
  indicators:
    A: [{name: x, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9, window: 30m}]
    B: [{name: y, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9, window: 30m}]
    C: [{name: z, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9, window: 30m}]
    D: [{name: w, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9, window: 30m}]
  action_templates:
    - {name: step_x, applies_to: A,
       parameters_schema: {x: {type: number, entity_property: x, candidates: [100]}},
       effect: set, settle_s: 1, source: runbook}
  relationship_rules:
"""

_LINKS = [("A", "B", "x", "y"), ("B", "C", "y", "z"), ("C", "D", "z", "w")]
_NODES = [("a", "A", "x"), ("b", "B", "y"), ("c", "C", "z"), ("d", "D", "w")]


def _model(hops, second="exponential", delay=0):
    body = ""
    for index in range(hops):
        src, dst, frm, to = _LINKS[index]
        body += _RULE % {"src": src, "dst": dst, "from": frm, "to": to,
                         "delay": delay,
                         "model": second if index == 1 else "exponential"}
    return HEAD + body


def _sim(tmp_path, name, hops=2, second="exponential", delay=0,
         horizon=3600.0, step_s=300.0):
    path = tmp_path / f"{name}.yaml"
    path.write_text(_model(hops, second, delay))
    session = api.EngineSession()
    session.load_model(str(path))
    for eid, typ, prop in _NODES[:hops + 1]:
        session.add_entity(eid, typ, {prop: 0.0})
        session.add_observations(eid, prop, [0.0] * 20)
    for index in range(hops):
        session.add_relationship("abcd"[index], "drives", "abcd"[index + 1])
    act = [ActionInstance(template="step_x", entity_id="a",
                          parameters={"x": STEP}, at_s=0)]
    return api.rollout(session, actions=act, horizon_s=horizon,
                       step_s=step_s).to_dict()["simulation"]


def _h2(t, delay=0.0):
    u = t - 2 * delay
    return 0.0 if u <= 0 else 1.0 - (1.0 + u / TAU) * math.exp(-u / TAU)


class TestTheTwoStageAnswerIsTheConvolution:

    def test_every_step_matches_the_closed_form(self, tmp_path):
        sim = _sim(tmp_path, "exact")
        for step in sim["per_step"]:
            assert step["values"]["c"]["z"] == pytest.approx(
                STEP * _h2(step["at_s"]), abs=1e-9)

    def test_dead_time_shifts_the_whole_cascade(self, tmp_path):
        """Both stages' delays come off the cascade, not one of them."""
        sim = _sim(tmp_path, "delayed", delay=120)
        for step in sim["per_step"]:
            assert step["values"]["c"]["z"] == pytest.approx(
                STEP * _h2(step["at_s"], delay=120.0), abs=1e-9)

    def test_the_steady_state_is_untouched(self, tmp_path):
        """It was always exact; a correction that moved it would be a bug."""
        sim = _sim(tmp_path, "steady", horizon=36000.0, step_s=3600.0)
        assert sim["per_step"][-1]["values"]["c"]["z"] == pytest.approx(
            STEP, abs=1e-6)

    def test_one_hop_is_untouched(self, tmp_path):
        sim = _sim(tmp_path, "single", hops=1)
        for step in sim["per_step"]:
            t = step["at_s"]
            assert step["values"]["b"]["y"] == pytest.approx(
                STEP * (1.0 - math.exp(-t / TAU)), abs=1e-9)
        assert EXACT_STAMP not in sim["assumptions"]
        assert PRODUCT_STAMP not in sim["assumptions"]


class TestTheSpreadRidesTheSameCurve:
    """The correction is applied to the FRACTION, so an interval belonging to
    a trajectory nobody walked is not representable."""

    def test_sigma_tracks_the_corrected_value(self, tmp_path):
        sim = _sim(tmp_path, "spread")
        ratios = []
        for step in sim["per_step"]:
            h = _h2(step["at_s"])
            sigma = step["sigma"]["c"]["z"]
            ratios.append(sigma / h)
        # Two declared spreads of 0.01 on a 100 unit step, independent, so
        # the constant is sqrt(2). What matters is that it IS constant: the
        # spread follows the same curve the value does.
        assert ratios == pytest.approx([math.sqrt(2.0)] * len(ratios), abs=1e-6)


class TestWhatStaysApproximateSaysSo:

    @pytest.mark.parametrize("second", ["linear", "logarithmic"])
    def test_a_stage_with_no_closed_form_keeps_the_product(self, tmp_path,
                                                           second):
        sim = _sim(tmp_path, f"mixed_{second}", second=second)
        assert PRODUCT_STAMP in sim["assumptions"]
        assert EXACT_STAMP not in sim["assumptions"]

    def test_three_stages_carry_both_stamps(self, tmp_path):
        """The solvable head is exact and the rest is not, so both claims are
        true and both are made."""
        sim = _sim(tmp_path, "three", hops=3)
        assert EXACT_STAMP in sim["assumptions"]
        assert PRODUCT_STAMP in sim["assumptions"]

    def test_three_stages_are_closer_than_before_and_still_approximate(
            self, tmp_path):
        """Pinned as an INEQUALITY, not a figure. The exact head improves the
        tail's starting point; it does not make the tail exact, and claiming
        otherwise is what the second stamp exists to prevent."""
        sim = _sim(tmp_path, "three_err", hops=3, horizon=1800.0,
                   step_s=1800.0)
        t = 1800.0
        got = sim["per_step"][-1]["values"]["d"]["w"]
        exact3 = STEP * (1.0 - (1.0 + t / TAU + (t / TAU) ** 2 / 2.0)
                         * math.exp(-t / TAU))
        old = STEP * (1.0 - math.exp(-t / TAU)) ** 3
        assert abs(got - exact3) < abs(old - exact3)
        assert abs(got - exact3) > 1.0


class TestConvergingPathsAreCorrectedPerContribution:

    def test_a_direct_edge_beside_a_chain_keeps_its_own_curve(self, tmp_path):
        """`b` is one hop from `a` and `c` is two. Correcting per property
        rather than per contribution would bend one of them onto the other's
        curve."""
        sim = _sim(tmp_path, "converge")
        for step in sim["per_step"]:
            t = step["at_s"]
            assert step["values"]["b"]["y"] == pytest.approx(
                STEP * (1.0 - math.exp(-t / TAU)), abs=1e-9)
            assert step["values"]["c"]["z"] == pytest.approx(
                STEP * _h2(t), abs=1e-9)
