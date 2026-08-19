"""hunting on a period the shipped STABILITY arm cannot see.

The oscillation detector is period-2 BY CONSTRUCTION: each value close to the
one two back, far from the one before. A controller hunting on a four-, six- or
eight-sample period scores exactly zero there and the series reads as maximally
stable. The project's own analysis reached that conclusion and correctly called
the silence not-a-defect — a detector answering the question it was built to
answer — while calling slow hunting genuinely pathological.

This is the opt-in second question. Declared rather than inferred, for the
reason `expect_variation` is: a day/night thermal swing, a duty-cycled
compressor and a batch process are all correctly periodic, and a checker
deciding otherwise would be carrying domain behaviour.

Runs against both trees; see this suite's conftest for why that matters.
"""

import math

import pytest

from arbiter_engine.api import attest, check, model_describe
from arbiter_engine.types import Axiom

from conftest import ENTITY_ID, declines_for, session_for

SAMPLES = 40
ON = {"detect_slow_oscillation": True}


def _sine(period: int, amplitude: float = 300.0, mean: float = 3000.0) -> list:
    return [mean + amplitude * math.sin(2 * math.pi * i / period)
            for i in range(SAMPLES)]


def _indicator(config: dict | None = None) -> dict:
    spec = {"name": "speed_rpm", "type": "NUMERIC", "axioms": ["STABILITY"],
            "window": "1h"}
    if config is not None:
        spec["stability"] = config
    return spec


def _run(series: list, config: dict | None = None):
    spec = _indicator(config)
    session = session_for("STABILITY", spec)
    session.entities[ENTITY_ID].properties["speed_rpm"] = series[-1]
    session.add_observations(ENTITY_ID, "speed_rpm", series)
    return session, check(session)


def _types(envelope) -> list:
    return [f["problem_type"] for f in envelope.to_dict()["findings"]]


class TestTheSlowPeriodsAreCaught:
    @pytest.mark.parametrize("period", [4, 6, 8, 10])
    def test_a_declared_slow_cycle_fires(self, period):
        _, envelope = _run(_sine(period), ON)
        assert _types(envelope) == ["slow_oscillation:speed_rpm"]

    def test_the_finding_states_the_period_it_measured(self):
        """The evidence has to be checkable against the operator's own graph.
        `crossed its mean ten times in forty samples, so the period is about
        eight` is a sentence they can verify; a dominant periodogram bin is
        not, which is why this counts crossings rather than running an FFT."""
        session, _ = _run(_sine(8), ON)
        evidence = attest(
            session, "slow_oscillation:speed_rpm").to_dict()["evidence"][0]
        measured = evidence["evidence"]["estimated_period_samples"]
        assert 6 <= measured <= 10, measured
        assert evidence["evidence"]["mean_crossings"] >= 4
        assert evidence["evidence"]["observations"] == SAMPLES

    def test_the_reason_names_why_the_other_arm_missed_it(self):
        _, envelope = _run(_sine(8), ON)
        finding = envelope.to_dict()["findings"][0]
        assert "period-2" in finding["reason"]


class TestItIsOptIn:
    def test_an_undeclared_cycle_is_silent(self):
        """Every model written before this field keeps its behaviour. A
        periodic series is not a fault until a domain says it is."""
        _, envelope = _run(_sine(8), None)
        assert _types(envelope) == []

    def test_declaring_false_is_the_same_as_not_declaring(self):
        _, envelope = _run(_sine(8), {"detect_slow_oscillation": False})
        assert _types(envelope) == []

    def test_the_block_is_reported_when_stability_is_not_declared(self):
        """One transform out. A block nothing reads has to say so, or an author
        believes they enabled a check they did not."""
        spec = _indicator(ON)
        spec["axioms"] = ["BOUNDEDNESS"]
        spec["critical"] = 9000
        session = session_for("STABILITY", spec)
        unread = model_describe(session).to_dict()["model"]["unread_fields"]
        assert [r["field"] for r in unread] == ["stability"]
        assert unread[0]["read_by"] == ["STABILITY"]


class TestItDoesNotFireOnThingsThatAreNotCycles:
    """A detector that fires on everything is not a detector. Each of these is
    a shape an operator would be angry to be paged about."""

    def test_a_monotone_ramp_is_not_a_cycle(self):
        _, envelope = _run([3000 + 5 * i for i in range(SAMPLES)], ON)
        assert _types(envelope) == []

    def test_a_flat_series_is_not_a_cycle(self):
        _, envelope = _run([3000.0] * SAMPLES, ON)
        assert _types(envelope) == []

    def test_noise_below_the_amplitude_gate_is_not_a_cycle(self):
        """A 0.07% swing crosses its mean constantly and means nothing. The
        gate is RELATIVE so one declaration works for a temperature in Kelvin
        and a ratio in [0, 1] — the same reasoning BOUNDEDNESS's relative slope
        minimum carries."""
        _, envelope = _run(_sine(8, amplitude=2.0), ON)
        assert _types(envelope) == []

    def test_the_amplitude_gate_is_configurable_and_discriminates(self):
        series = _sine(8, amplitude=60.0)        # 2% of 3000
        _, loud = _run(series, {**ON, "min_amplitude": 0.01})
        _, quiet = _run(series, {**ON, "min_amplitude": 0.10})
        assert _types(loud) == ["slow_oscillation:speed_rpm"]
        assert _types(quiet) == []

    def test_the_crossing_gate_is_configurable_and_discriminates(self):
        series = _sine(8)
        _, loud = _run(series, {**ON, "min_crossings": 4})
        _, quiet = _run(series, {**ON, "min_crossings": 50})
        assert _types(loud) == ["slow_oscillation:speed_rpm"]
        assert _types(quiet) == []


class TestTheTwoArmsDoNotOverlap:
    """The fixture here swings between 1000 and 3000 rather than +/-300 around
    3000, and that is not cosmetic.

    The fast arm normalises its distances by the largest absolute value in the
    triple and requires consecutive readings to differ by `delta` = 0.3. A
    +/-10% swing around a mean of 3000 therefore does not reach it — so a first
    cut of these two tests asserted the fast arm was silent AND that it fired,
    and the second went red. The engine was right; the fixture was not
    oscillating by the fast arm's definition.

    Worth stating because it is a real property of that arm rather than a
    quirk of this file: a signal hunting around a large mean needs a swing of
    more than 30% of its own magnitude before period-2 detection sees it, which
    is one more reason the slow arm reads the whole window and gates on a
    relative amplitude of its own.
    """

    SERIES = [1000.0 if i % 2 else 3000.0 for i in range(SAMPLES)]

    def test_a_period_two_signal_is_left_to_the_arm_that_owns_it(self):
        """One signal, one finding. The boundary is principled rather than a
        suppression: below three samples per period this IS the fast case, and
        the existing arm reports it."""
        _, envelope = _run(self.SERIES, ON)
        assert "slow_oscillation:speed_rpm" not in _types(envelope)

    def test_the_fast_arm_still_reports_period_two(self):
        """The other half — the boundary must not silence both."""
        _, envelope = _run(self.SERIES, ON)
        assert _types(envelope) == ["stability_oscillation:speed_rpm"]


class TestItReadsTheWholeWindow:
    def test_a_slow_cycle_is_visible_beyond_the_fast_arms_truncation(self):
        """The defect found by running it: the fast arm truncates to
        `stability_window_size` samples because its question is about the last
        few readings, and the slow arm handed the same ten sees at most one
        cycle of a period-8 signal. It ran, on the right data, and could not
        have fired for any input.

        Pinned by supplying a series far longer than that truncation, which is
        the only shape that tells the two apart.
        """
        from arbiter_engine.types import AxiomParameters
        assert SAMPLES > AxiomParameters().stability_window_size * 2, (
            "the fixture no longer spans more than the fast arm's window, so "
            "this test would pass under the truncation it exists to catch")
        _, envelope = _run(_sine(8), ON)
        assert _types(envelope) == ["slow_oscillation:speed_rpm"]

    def test_too_short_a_series_is_silent_rather_than_declined(self):
        """A second decline for one evaluation breaks the denominator the
        envelope rests on — the oscillation arm has already declined on a
        starved input. Same ruling `_check_frozen_series` carries."""
        session = session_for("STABILITY", _indicator(ON))
        session.entities[ENTITY_ID].properties["speed_rpm"] = 3000.0
        session.add_observations(ENTITY_ID, "speed_rpm", [3000.0, 3100.0])
        envelope = check(session)
        assert len(declines_for(envelope, "STABILITY")) == 1


class TestTheBlockIsDeclaredEverywhereItHasToBe:
    def test_the_yaml_key_is_in_the_schema(self):
        from arbiter_engine.ontology.domain_loader import (
            _KNOWN_INDICATOR_KEYS,
        )
        assert "stability" in _KNOWN_INDICATOR_KEYS

    def test_the_field_names_its_consuming_axiom(self):
        from arbiter_engine.ontology.domain_loader import (
            _FIELD_CONSUMERS,
        )
        assert _FIELD_CONSUMERS["stability_config"] == (Axiom.STABILITY,)
