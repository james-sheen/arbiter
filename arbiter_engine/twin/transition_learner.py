"""Fitting a declared coupling's magnitude, as a proposal the engine will not adopt.

`propagation/weight_learner.py` learns
P(target problem | source problem) — a
REACHABILITY model, which is what `ImpactEstimator` needs and is not a
transition. A transition needs a GAIN: how much the target moves per unit of
the source. This fits that, and hands back a proposal.

THE PAIR IS ALWAYS DECLARED; ONLY THE NUMBER IS EVER LEARNED. Searching for
couplings — pairing every numeric property on one entity with every numeric
property on another and keeping what correlates — is the inference this
package spent several releases removing from `role:`, from flow direction and
from `agrees_with:`. It would find a gain between a pump's lifetime run-hours
counter and a tank's level, because over any window where the pump ran, both
rise. So the author writes `gain: estimate` to say *these two are coupled and
I do not know by how much*, and the engine answers only that question.

NOTHING HERE PROMOTES ITSELF. IT LIVES IN `twin/` RATHER THAN BESIDE `weight_learner.py` IN
`propagation/`, and the closure decided that rather than taste. `propagation/`
is not a seed directory -- its files ride into the published cut because
`twin/builder.py` imports them -- so a learner placed there would have been
reachable only from `api.py`, which the manifest test reports as an entry
point pulling in a subtree. That is a scope change, not a file move. It is
transition machinery, it sits beside the rollout and the planner that read the
same `TwinEdge.transitions`, and the dependency graph is what says so.

`causal/discovery.py` sets the governance precedent and states it plainly: it proposes edges, reports
`pairs_untested`, declines `faithfulness_unverifiable` on every run, and
nothing it produces enters the model without an author. A fitted gain is a
`LearnedTransition` with an `n` and an interval; it moves no value until it is
adopted, and where a gain IS declared and the data contradict it, the engine
reports the disagreement and does not edit the declaration. A tool that
rewrites its own input is not reporting on a system, it is one.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..causal.discovery import MINIMUM_PAIRED_SAMPLES
from ..causal.leadlag import align

__all__ = ["LearnedTransition", "TransitionRefusal", "learn_transitions",
           "MINIMUM_PAIRED_SAMPLES"]

#: DELIBERATELY THE SAME NUMBER AS `discovery.py`, imported rather than
#: restated. Both answer *are there enough paired samples to defend a fit*,
#: and two constants meaning one thing is how a floor comes to be 120 in one
#: module and 100 in the next with nothing saying which is the rule.

#: How far back to read. Wide, because the floor above is about SAMPLE COUNT
#: and a window that silently truncated the series would make the floor mean
#: something else.
_LOOKBACK = timedelta(days=3650)


@dataclass
class LearnedTransition:
    """A fitted gain. A PROPOSAL, never an edit."""
    edge: str
    relation_type: str
    from_property: str
    to_property: str
    gain: float
    intercept: float
    n: int
    r_squared: float
    ci_low: float
    ci_high: float
    declared_gain: Optional[float] = None
    source: str = "learned"

    @property
    def contradicts_declaration(self) -> bool:
        """True when a gain IS declared and the interval excludes it.

        The interval, not the point estimate: a fitted 0.021 against a
        declared 0.020 is agreement, and calling it a contradiction would make
        this finding fire on every edge anyone ever measured.
        """
        if self.declared_gain is None:
            return False
        return not (self.ci_low <= self.declared_gain <= self.ci_high)


@dataclass
class TransitionRefusal:
    """A gain this run would not fit, and why."""
    reason: str
    location: str
    detail: str = ""


def _series(history: Any, entity_id: str, property_name: str
            ) -> List[Tuple[Any, float]]:
    try:
        return list(history.get_values(entity_id, property_name, _LOOKBACK))
    except Exception:  # noqa: BLE001 - a store that cannot answer is a refusal
        return []


def _fit(x: np.ndarray, y: np.ndarray
         ) -> Tuple[float, float, float, float, float]:
    """Least squares `y = gain*x + intercept`, with a 95% band on the slope.

    The band is the normal approximation, matching
    `MonteCarloOutcomeDistribution.confidence_interval_95` rather than
    introducing a t-distribution and a second convention. `scipy` is not a
    dependency of this package and a slope interval does not justify becoming
    one.
    """
    n = len(x)
    x_mean, y_mean = float(np.mean(x)), float(np.mean(y))
    sxx = float(np.sum((x - x_mean) ** 2))
    if sxx <= 0.0:
        return 0.0, y_mean, 0.0, 0.0, 0.0
    gain = float(np.sum((x - x_mean) * (y - y_mean)) / sxx)
    intercept = y_mean - gain * x_mean
    residuals = y - (gain * x + intercept)
    sse = float(np.sum(residuals ** 2))
    sst = float(np.sum((y - y_mean) ** 2))
    r_squared = 1.0 - sse / sst if sst > 0 else 0.0
    if n > 2:
        standard_error = math.sqrt(max(sse / (n - 2), 0.0) / sxx)
    else:
        standard_error = 0.0
    margin = 1.96 * standard_error
    return gain, intercept, r_squared, gain - margin, gain + margin


def learn_transitions(session: Any, topology: Any,
                      floor: int = MINIMUM_PAIRED_SAMPLES
                      ) -> Tuple[List[LearnedTransition],
                                 List[TransitionRefusal]]:
    """Fit every DECLARED coupling from the session's observations."""
    proposals: List[LearnedTransition] = []
    refusals: List[TransitionRefusal] = []
    history = session.reading_history()

    edges = [e for bucket in getattr(topology, "edges", {}).values()
             for e in bucket]
    for edge in edges:
        for transition in getattr(edge, "transitions", []) or []:
            label = f"{edge.source_id}->{edge.target_id}"
            source = _series(history, edge.source_id,
                             transition.from_property)
            target = _series(history, edge.target_id, transition.to_property)
            if not source or not target:
                refusals.append(TransitionRefusal(
                    "insufficient_samples", label,
                    f"no observations for "
                    f"{edge.source_id}.{transition.from_property}"
                    if not source else
                    f"no observations for "
                    f"{edge.target_id}.{transition.to_property}"))
                continue

            delay = float(getattr(edge, "propagation_delay_s", 0.0) or 0.0)
            shifted = [(when + timedelta(seconds=delay), value)
                       for when, value in source]
            a, b = align(shifted, target)

            if len(a) == 0 and len(source) >= 2 and len(target) >= 2:
                # THE DELAY DOES NOT LAND ON THE SAMPLING GRID, and this is
                # NOT `insufficient_samples`. `align` intersects on exact
                # timestamps, so a declared 90-second delay against a series
                # sampled every 60 seconds pairs nothing however long the
                # series is. Reporting a sample shortage would send the author
                # to collect more data, which cannot help -- a decline whose
                # remedy does not work is worse than no decline.
                refusals.append(TransitionRefusal(
                    "delay_off_grid", label,
                    f"the declared propagation delay of {delay:g}s does not "
                    f"land on the sampling grid of these two series, so no "
                    f"pair of readings can be aligned. Feed the series on a "
                    f"grid the delay divides, or declare a delay that is a "
                    f"multiple of the sampling interval."))
                continue

            # THE COUPLING IS BETWEEN CHANGES, so the fit is on first
            # differences. Regressing levels would report a gain between any
            # two quantities that happen to drift together.
            if len(a) < 2:
                refusals.append(TransitionRefusal(
                    "insufficient_samples", label,
                    f"{len(a)} aligned readings, and a change needs at least "
                    f"two"))
                continue
            dx, dy = np.diff(a), np.diff(b)
            n = int(len(dx))
            if n < floor:
                refusals.append(TransitionRefusal(
                    "insufficient_samples", label,
                    f"{n} paired changes for "
                    f"{transition.from_property} -> {transition.to_property}, "
                    f"and this engine will not fit a gain below {floor}. The "
                    f"floor is the one `causal/discovery.py` uses, for the "
                    f"same reason: a slope on a handful of points is a number "
                    f"nobody can defend."))
                continue
            if float(np.sum((dx - float(np.mean(dx))) ** 2)) <= 0.0:
                refusals.append(TransitionRefusal(
                    "unidentifiable_parameter", label,
                    f"{edge.source_id}.{transition.from_property} never "
                    f"changes across these readings, so no gain can be "
                    f"measured from it at any sample count"))
                continue

            gain, intercept, r_squared, low, high = _fit(dx, dy)
            proposals.append(LearnedTransition(
                edge=label, relation_type=edge.relation_type,
                from_property=transition.from_property,
                to_property=transition.to_property,
                gain=gain, intercept=intercept, n=n, r_squared=r_squared,
                ci_low=low, ci_high=high,
                declared_gain=(None if transition.estimated
                               else transition.gain),
            ))
    return proposals, refusals
