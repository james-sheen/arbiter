""" (Phase 1 of phased adoption) — Monte Carlo
probabilistic prediction layer over the SIMULATE substrate.

Per decision (phased adoption: Phase 1 Monte Carlo → Phase 2
Bayesian → Phase 3 LLM-counterfactual), this module supplies Phase 1.

Architecture: a sampling-based probability estimator over a
DigitalTwinTopology snapshot. The estimator runs N randomized
mutations + simulation calls and aggregates outcome frequencies as
probability estimates with binomial-standard-error confidence
bands.

Design choices:
- **Caller-supplied simulation callable**. The predictor is NOT
  hard-wired to any specific detection / RCA / action-planning
  pathway — callers supply `simulation_step(snapshot, rng) ->
  Dict[outcome_name, bool]` and decide what one "sample" means.
  This keeps the predictor reusable across the BP Digital-Twin
  pillars: "Predicts" via outcome-of-problem estimation,
  "Acts proactively" via P(action_clears_problem) estimation,
  cross-domain propagation via posterior-shape inputs.
- **Deterministic given seed**. Same `(snapshot, simulation_step,
  seed, n_samples)` produces the same outcome distributions. The
   trade-off table calls this out as a load-bearing property
  for calibration validation.
- **Sample count is a tunable, not an architectural commitment**.
  Default N=100, min N=10 (fast smoke), max N=10000 (high-confidence
  verdicts). The N=100 default matches decision's stated
  sample count.

Per phase ordering: this Phase 1 supplies the calibration
baseline that Phase 2 Bayesian re-anchors against, and the
numeric grounding that Phase 3 LLM-counterfactual requires.

Per read-only-by-design contract — never mutates inputs.
"""

from __future__ import annotations

import copy
import logging
import math
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# Module-level constants (load-bearing decision)
_DEFAULT_SAMPLE_COUNT = 100
_MIN_SAMPLE_COUNT = 10
_MAX_SAMPLE_COUNT = 10000

# Per decision: this is the threshold downstream consumers
# (ACTIVE-mode auto-approval) read from `P(action_clears_problem)`.
# Surfaced here for inspection + tests; the actual ACTIVE-mode policy
# owns the decision of whether to use it.
ACTIVE_MODE_AUTO_APPROVE_THRESHOLD = 0.85


@dataclass
class MonteCarloOutcomeDistribution:
    """Per-outcome probability estimate from N Monte Carlo
    samples over a DigitalTwinTopology snapshot.

    Output shape designed so downstream consumers (acceptance
    gate, ACTIVE-mode policy, cross-domain propagation)
    can read the estimate without re-running the sampler:

    - ``estimated_probability``: empirical frequency = samples_observed
      sample_count.
    - ``std_error``: binomial standard error sqrt(p*(1-p)/n).
    - ``confidence_interval_95``: normal-approximation 95% CI [low, high]
      clipped to [0, 1].
    - ``samples_observed``: raw count for callers that want the
      conjugate-prior input (Phase 2 Bayesian).
    """
    outcome_name: str
    estimated_probability: float  # 0..1 inclusive
    sample_count: int
    samples_observed: int
    seed: Optional[int] = None

    @property
    def std_error(self) -> float:
        """Binomial standard error of the proportion estimate."""
        if self.sample_count <= 0:
            return 0.0
        p = self.estimated_probability
        return math.sqrt(p * (1.0 - p) / self.sample_count)

    @property
    def confidence_interval_95(self) -> Tuple[float, float]:
        """Normal-approximation 95% CI clipped to [0, 1]."""
        # 1.96 is the standard normal z-score at 97.5th percentile
        margin = 1.96 * self.std_error
        low = max(0.0, self.estimated_probability - margin)
        high = min(1.0, self.estimated_probability + margin)
        return (low, high)

    @property
    def meets_active_mode_threshold(self) -> bool:
        """True iff the lower bound of the 95% CI meets or exceeds
        the ACTIVE-mode auto-approve threshold (reads this
        for its routing decision)."""
        return self.confidence_interval_95[0] >= ACTIVE_MODE_AUTO_APPROVE_THRESHOLD

    def to_dict(self) -> Dict[str, Any]:
        low, high = self.confidence_interval_95
        return {
            "outcome_name": self.outcome_name,
            "estimated_probability": self.estimated_probability,
            "sample_count": self.sample_count,
            "samples_observed": self.samples_observed,
            "std_error": self.std_error,
            "confidence_interval_95": [low, high],
            "meets_active_mode_threshold": self.meets_active_mode_threshold,
            "seed": self.seed,
        }


@dataclass
class MonteCarloPredictionRequest:
    """Request shape for a Monte Carlo prediction over a
    DigitalTwinTopology snapshot. The snapshot itself is not stored
    on this dataclass to keep the request shape JSON-serializable
    over the HTTP endpoint (follow-up); callers pass the
    snapshot separately to ``MonteCarloPredictor.predict``.
    """
    outcome_names: List[str]
    n_samples: int = _DEFAULT_SAMPLE_COUNT
    seed: Optional[int] = None

    def __post_init__(self):
        if not self.outcome_names:
            raise ValueError(
                "MonteCarloPredictionRequest: outcome_names "
                "must be a non-empty list of outcome string names"
            )


class MonteCarloPredictor:
    """ — sample-based probability estimator over a
    DigitalTwinTopology snapshot.

    Caller-supplied simulation: ``predict(snapshot, simulation_step,
    request)`` runs ``request.n_samples`` calls of
    ``simulation_step(snapshot, rng)`` (each returning a
    ``Dict[outcome_name, bool]``) and aggregates the per-outcome
    frequencies as ``MonteCarloOutcomeDistribution`` records.

    Caller examples (not implemented here per the
    caller-supplied-simulation design choice):
    - "Probabilistic detection on a snapshot": simulation_step is
      "randomly mutate K threshold values within [warn, critical]
      and re-run axiom detection; return {problem_persists: True
      iff axiom fires}".
    - "Probabilistic action-clears-problem": simulation_step is
      "apply candidate action to snapshot; re-run detection;
      return {action_clears_problem: True iff axiom no longer
      fires}".

    Per Phase 1 sample-count semantics: N=100 default;
    N=10..N=10000 valid; values outside the range raise
    ValueError. The clamping is intentional — silent clamping
    would hide miscalibrated callers.
    """

    def __init__(self, seed: Optional[int] = None):
        """Initialize with optional seed for deterministic sampling.

        When ``seed`` is None, the predictor uses an
        unseeded ``random.Random`` (system entropy). The seed (or
        None) is recorded on every emitted
        ``MonteCarloOutcomeDistribution`` for reproducibility.
        """
        self._seed = seed
        self._rng_factory = (
            (lambda: random.Random(seed))
            if seed is not None
            else random.Random
        )

    def predict(
        self,
        snapshot: Any,  # DigitalTwinTopology — Any to avoid hard import dependency
        simulation_step: Callable[[Any, random.Random], Dict[str, bool]],
        request: MonteCarloPredictionRequest,
        max_perturbation_seconds: Optional[float] = None,
    ) -> Dict[str, MonteCarloOutcomeDistribution]:
        """Run N Monte Carlo samples; return per-outcome distributions.

        Args:
            snapshot: a DigitalTwinTopology snapshot (or any opaque
                object the simulation_step understands).
            simulation_step: callable ``(snapshot, rng) -> Dict[str,
                bool]``. Returns a dict mapping each outcome_name
                to True/False for this sample.
            request: ``MonteCarloPredictionRequest`` carrying
                outcome_names, n_samples, seed.
            max_perturbation_seconds: — optional
                wall-clock budget cap. When set, sampling aborts
                early once cumulative elapsed time exceeds the
                budget; returned distributions report the partial
                sample count (NOT the original request.n_samples).
                A WARN log names the truncation. Default None =
                no budget (full sample run). When ≤ 0, no sampling
                at all (returns empty-sample-count distributions).
                Per cost-budget concern: N=100..1000
                deep-copies + per-sample LayeredDetector re-runs
                can dominate the budget; this knob lets operators
                cap runaway runs.

        Returns:
            Dict mapping each ``outcome_name`` in
            ``request.outcome_names`` to a
            ``MonteCarloOutcomeDistribution`` with empirical
            probability estimate, sample count, std error, and 95%
            CI. When budget is exceeded, sample_count reflects the
            ACTUAL samples run (< request.n_samples).

        Raises:
            ValueError: if ``request.n_samples`` is outside
                [_MIN_SAMPLE_COUNT, _MAX_SAMPLE_COUNT].
        """
        n = request.n_samples
        if n < _MIN_SAMPLE_COUNT:
            raise ValueError(
                f"MonteCarloPredictor.predict: n_samples="
                f"{n} below minimum {_MIN_SAMPLE_COUNT}. Below "
                f"this floor, binomial CI is too wide for any "
                f"useful decision."
            )
        if n > _MAX_SAMPLE_COUNT:
            raise ValueError(
                f"MonteCarloPredictor.predict: n_samples="
                f"{n} exceeds maximum {_MAX_SAMPLE_COUNT}. Above "
                f"this ceiling, sampling cost dominates and Phase 2 "
                f"analytic posterior is the right tool."
            )

        # Use request seed if provided, else this predictor's seed,
        # else system entropy.
        effective_seed = (
            request.seed if request.seed is not None
            else self._seed
        )
        rng = (
            random.Random(effective_seed)
            if effective_seed is not None
            else random.Random()
        )

        # — wall-clock cost-budget tracking. Start
        # timer when the loop begins so it doesn't penalize setup time.
        import time as _time
        start_time = _time.perf_counter()
        budget_exhausted_at: Optional[int] = None

        # Counters per outcome
        counters: Dict[str, int] = {name: 0 for name in request.outcome_names}

        # Actual samples run (may be < n if budget exhausted early)
        actual_n = 0

        for i in range(n):
            # check budget BEFORE running the next sample so
            # we don't pay for an unbounded N+1 sample after the budget
            # is already exhausted.
            if max_perturbation_seconds is not None and max_perturbation_seconds <= 0:
                # Special case: 0 or negative budget = no samples
                budget_exhausted_at = 0
                break
            if (
                max_perturbation_seconds is not None
                and _time.perf_counter() - start_time >= max_perturbation_seconds
            ):
                budget_exhausted_at = i
                break

            try:
                sample_outcomes = simulation_step(snapshot, rng)
            except Exception as e:
                # Per defensive-execute pattern (archetype):
                # surface programming errors loudly, soft-skip others.
                if isinstance(e, (AttributeError, KeyError, TypeError, NameError)):
                    logger.error(
                        f"simulation_step raised programming error "
                        f"{type(e).__name__}: {e} — aborting sample run"
                    )
                    raise
                logger.warning(
                    f"simulation_step raised {type(e).__name__}: "
                    f"{e} — sample treated as no-outcome-fired"
                )
                actual_n += 1
                continue

            for name in request.outcome_names:
                # Missing keys treated as False (outcome did not fire)
                if sample_outcomes.get(name, False):
                    counters[name] += 1
            actual_n += 1

        # emit WARN naming the truncation when budget exhausted.
        if budget_exhausted_at is not None:
            elapsed = _time.perf_counter() - start_time
            logger.warning(
                "MonteCarloPredictor.predict: wall-clock budget "
                "%.2fs exhausted after %d/%d samples (elapsed=%.2fs). "
                "Returning partial distributions; consider increasing "
                "max_perturbation_seconds OR reducing per-sample cost "
                "(e.g. lighter detection_callable / smaller snapshot).",
                max_perturbation_seconds, actual_n, n, elapsed,
            )

        # Build output distributions. When budget exhausted with 0
        # actual samples, the sample_count must be at least 1 to avoid
        # division-by-zero; report 0 explicitly + estimated_probability=0.
        effective_n = max(actual_n, 1)
        results: Dict[str, MonteCarloOutcomeDistribution] = {}
        for name in request.outcome_names:
            observed = counters[name]
            results[name] = MonteCarloOutcomeDistribution(
                outcome_name=name,
                estimated_probability=(observed / effective_n) if actual_n > 0 else 0.0,
                sample_count=actual_n,
                samples_observed=observed,
                seed=effective_seed,
            )

        return results


# ===========================================================================
# — Threshold-perturbation simulation_step factory
# ===========================================================================


def make_threshold_perturbation_simulation_step(
    perturbation_strategy: Callable[
        [Dict[str, float], random.Random], Dict[str, float]
    ],
    detection_step: Callable[
        [Dict[str, float]], Dict[str, Any]
    ],
    outcome_extractors: Dict[str, Callable[[Dict[str, Any]], bool]],
) -> Callable[[Any, random.Random], Dict[str, bool]]:
    """factory producing a Monte Carlo
    ``simulation_step`` closure that perturbs threshold values per
    sample and re-runs detection.

    Per off-ramp 4 (variance-reduction techniques): the
    perturbation_strategy is caller-supplied so different sampling
    schemes (uniform / beta / stratified / antithetic / control
    variates) can be swapped without changing the predictor or the
    factory shape. Same caller-supplied-simulation pattern as
     MonteCarloPredictor.predict.

    Per Phase 1 contract: deterministic given seed. The
    closure passes the rng into perturbation_strategy verbatim,
    preserving the calibration-reproducibility load-bearing
    property.

    Args:
        perturbation_strategy: callable
            ``(baseline_thresholds: Dict[name, value], rng: random.Random)
            -> Dict[name, perturbed_value]``. Returns a fresh dict per
            call; the snapshot itself is NOT mutated (the closure
            passes the perturbed thresholds to detection_step which
            decides how to use them).
        detection_step: callable
            ``(perturbed_thresholds: Dict[name, value]) -> Dict[Any, Any]``.
            Re-runs detection logic against the perturbed thresholds
            (the snapshot proper stays frozen; the caller is
            responsible for materializing the perturbation effect).
            Output is an opaque detection-result dict that
            ``outcome_extractors`` interpret.
        outcome_extractors: callable per outcome_name
            ``Dict[outcome_name, (detection_result) -> bool]``. Each
            extractor inspects the detection_result and reports
            whether that outcome fired for the sample.

    Returns:
        A ``simulation_step(snapshot, rng) -> Dict[outcome_name, bool]``
        closure consumable by ``MonteCarloPredictor.predict``. The
        closure ignores ``snapshot`` (perturbation operates on
        baseline_thresholds extracted by detection_step's
        implementation, not on the snapshot directly).

    Note on snapshot deep-copy: the v1 factory deliberately does NOT
    deep-copy the snapshot per sample. Snapshot mutation is the
    caller's concern via detection_step. This avoids the 10-100x
    snapshot-copy overhead that would dominate the N=100..1000
    sample budget. If a future caller requires snapshot-level
    perturbation (mutate node properties + re-run detection), they
    supply a detection_step that handles the copy internally — the
    factory's contract is per-sample isolation, not snapshot copy
    semantics.
    """
    def step(snapshot: Any, rng: random.Random) -> Dict[str, bool]:
        # The caller's detection_step is responsible for accessing
        # the snapshot if needed (via closure or explicit parameter).
        # The factory only enforces the per-sample perturbation +
        # outcome-extraction sequence.
        baseline: Dict[str, float] = {}  # Empty default; detection_step may inject
        perturbed = perturbation_strategy(baseline, rng)
        detection_result = detection_step(perturbed)
        outcomes: Dict[str, bool] = {}
        for name, extractor in outcome_extractors.items():
            try:
                outcomes[name] = bool(extractor(detection_result))
            except Exception as e:
                # Per archetype: programming errors raise;
                # extraction errors log + treat outcome as False
                if isinstance(e, (AttributeError, KeyError, TypeError, NameError)):
                    raise
                logger.warning(
                    f"outcome_extractor for {name!r} raised "
                    f"{type(e).__name__}: {e} — outcome treated as False"
                )
                outcomes[name] = False
        return outcomes

    return step


def uniform_threshold_perturbation_strategy(
    baseline_thresholds: Dict[str, float],
    bounds: Dict[str, tuple],
) -> Callable[[Dict[str, float], random.Random], Dict[str, float]]:
    """ — uniform-sampling perturbation strategy
    factory.

    Returns a perturbation_strategy callable suitable for
    ``make_threshold_perturbation_simulation_step``. Each threshold
    is perturbed by uniform-sampling within
    ``bounds[threshold_name] = (low, high)`` per sample. Thresholds
    without bounds entries pass through unchanged.

    Args:
        baseline_thresholds: ignored at factory-build time; the
            returned closure ignores the parameter passed by the
            simulation_step factory (it relies on the captured
            ``baseline_thresholds``/``bounds`` closure).
        bounds: ``Dict[threshold_name, (low, high)]`` mapping each
            threshold to its uniform-sampling range.

    Returns:
        A callable ``(baseline, rng) -> perturbed``.
    """
    captured_baseline = dict(baseline_thresholds)
    captured_bounds = dict(bounds)

    def strategy(
        _baseline_runtime: Dict[str, float],  # unused — captured at factory time
        rng: random.Random,
    ) -> Dict[str, float]:
        result: Dict[str, float] = {}
        for name, baseline_value in captured_baseline.items():
            if name in captured_bounds:
                low, high = captured_bounds[name]
                result[name] = rng.uniform(low, high)
            else:
                result[name] = baseline_value
        return result

    return strategy



# ============================================================
# — real axiom-threshold perturbation v2 substrate
# ============================================================

# Per substrate-only scope (the established pattern sub-split of full
#): 3 pure-helper functions ship today — deepcopy_snapshot()
# + extract_axiom_thresholds_from_domain_config() +
# make_real_perturbation_simulation_step_v2() — composing the
# substrate that v2 perturbation needs. The runtime LayeredDetector
# re-run integration + calibration test against synthetic chaos
# snapshot are deferred to (filed at this CD's closure).
#
# the v1 stub (uniform_threshold_perturbation_strategy +
# make_threshold_perturbation_simulation_step) stays as the default
# in-place strategy; v2 is the deep-copy + per-axiom variant
# operators opt into via the new factory.

# Module-level cost-budget knob — scope item #4.
# N=100..1000 deep-copies dominate the sample budget at v2; the
# caller MAY abort early via _MAX_PERTURBATION_SECONDS_DEFAULT or
# the per-call `max_perturbation_seconds` kwarg to predict() (added
# at for runtime callers). For substrate scope, the constant is
# surfaced for tests + future runtime callers.
_MAX_PERTURBATION_SECONDS_DEFAULT = 30.0


def deepcopy_snapshot(snapshot: Any) -> Any:
    """ (substrate) — deep-copy a DigitalTwinTopology
    snapshot for per-sample isolation.

    Per scope item #1: per-sample snapshot deep-copy is
    REQUIRED so threshold injection doesn't leak across samples.
    The v1 factory deliberately skipped deep-copy because
    its perturbation operates on a derived thresholds-dict, not the
    snapshot itself; v2 mutates per-entity property values inside
    the snapshot copy + re-runs detection against the mutated copy.

    Uses `copy.deepcopy` — recursive Python deep-copy. For very large
    snapshots (>10k entities off-ramp #4 trigger condition),
    operators MAY swap this for a custom shallow-clone helper at
     runtime time; substrate stays naive.

    Args:
        snapshot: A DigitalTwinTopology (or any object supporting
            `copy.deepcopy`). Duck-typed.

    Returns:
        A deep-copy of the snapshot. The original is untouched read-only-by-design contract.
    """
    return copy.deepcopy(snapshot)


def extract_axiom_thresholds_from_domain_config(
    domain_config: Any,
) -> Dict[Tuple[str, str, str], Tuple[Optional[float], Optional[float]]]:
    """ (substrate) — extract per-(entity_type,
    indicator, axiom) [warning, critical] threshold tuples from a
    DomainConfig.

    Per scope item #2: pull current threshold values from
    DomainConfig.indicators + axiom_parameters so the perturbation
    strategy has a baseline range to mutate within.

    YAML shape consumed:
        indicators:
          EntityType:
            - name: indicator_name
              type: NUMERIC | STATE
              axioms: [BOUNDEDNESS, HOMEOSTASIS,...]
              warning: <number> # optional
              critical: <number> # optional
              plausible_range: [<low>, <high>] # optional

    For each (entity_type, indicator, axiom) triple where the axiom
    is enabled for the indicator AND a warning/critical value is
    declared, emit a tuple. Missing warning/critical → None for
    that slot; the perturbation strategy decides how to handle the
    missing bound (typically: skip the perturbation for that triple).

    Args:
        domain_config: A DomainConfig. Duck-typed — accepts any
            object with an ``indicators: Dict[entity_type, List[indicator_dict]]``
            attribute.

    Returns:
        Dict mapping ``(entity_type, indicator_name, axiom_name) ->
        (warning, critical)``. Both values are Optional[float] —
        None when the indicator dict lacks that threshold key.
    """
    result: Dict[Tuple[str, str, str], Tuple[Optional[float], Optional[float]]] = {}
    indicators_by_type = getattr(domain_config, "indicators", {}) or {}

    for entity_type, indicator_list in indicators_by_type.items():
        if not isinstance(indicator_list, list):
            continue
        for ind in indicator_list:
            if not isinstance(ind, dict):
                continue
            name = ind.get("name")
            if not name:
                continue
            axioms = ind.get("axioms") or []
            warn_val = ind.get("warning")
            crit_val = ind.get("critical")
            for axiom in axioms:
                if not isinstance(axiom, str):
                    axiom = str(axiom)
                # Coerce to Optional[float] (or leave None)
                warn_f = float(warn_val) if isinstance(warn_val, (int, float)) else None
                crit_f = float(crit_val) if isinstance(crit_val, (int, float)) else None
                result[(str(entity_type), str(name), axiom)] = (warn_f, crit_f)

    return result


def make_real_perturbation_simulation_step_v2(
    domain_config: Any,
    perturbation_strategy: Callable[
        [Dict[Tuple[str, str, str], Tuple[Optional[float], Optional[float]]],
         random.Random],
        Dict[Tuple[str, str, str], Tuple[Optional[float], Optional[float]]],
    ],
    detection_callable: Callable[[Any, Dict[Tuple[str, str, str], Tuple[Optional[float], Optional[float]]]], Dict[str, Any]],
    outcome_extractors: Dict[str, Callable[[Dict[str, Any]], bool]],
) -> Callable[[Any, random.Random], Dict[str, bool]]:
    """ (substrate) — factory producing a v2 Monte Carlo
    ``simulation_step`` that deep-copies the snapshot + injects
    perturbed thresholds per sample + runs caller-supplied detection.

    Per scope items #1-3: deep-copy + threshold extraction +
    detection re-run per sample.

    Substrate-only scope: ``detection_callable`` is caller-supplied
    (preserves caller-supplied-simulation pattern).
    Runtime wiring of LayeredDetector.detect_problems lands.

    Args:
        domain_config: A DomainConfig — passed to
            ``extract_axiom_thresholds_from_domain_config`` at factory
            time to capture the baseline thresholds. Caller is
            responsible for ensuring the domain_config matches the
            snapshot's domain at runtime.
        perturbation_strategy: callable ``(baseline_thresholds,
            rng) -> perturbed_thresholds``. Operates on the dict
            shape returned by ``extract_axiom_thresholds_from_domain_config``.
            Returns a fresh dict per call. Caller-supplied so v2 can
            swap uniform / beta / stratified sampling strategies
            (off-ramp #4).
        detection_callable: callable ``(snapshot_copy,
            perturbed_thresholds) -> detection_result``. Runs detection
            against the deep-copied + threshold-injected snapshot.
            Substrate scope: caller-supplied (caller decides whether
            to inject thresholds onto snapshot entities or pass them
            as a sidecar parameter to a detector).
        outcome_extractors: callable per outcome_name
            ``Dict[outcome_name, (detection_result) -> bool]``.
            Each extractor inspects detection_result and reports
            whether the outcome fired for the sample.

    Returns:
        A ``simulation_step(snapshot, rng) -> Dict[outcome_name, bool]``
        closure consumable by ``MonteCarloPredictor.predict``. The
        closure deep-copies the snapshot per sample.

    Per read-only-by-design — the closure does NOT mutate
    the original snapshot; per-sample work happens on the deep-copy.
    """
    # Capture baseline thresholds at factory time (one extraction
    # amortized over N samples).
    baseline_thresholds = extract_axiom_thresholds_from_domain_config(domain_config)

    def step(snapshot: Any, rng: random.Random) -> Dict[str, bool]:
        # scope #1: per-sample deep-copy.
        snapshot_copy = deepcopy_snapshot(snapshot)

        # scope #2: extract baseline + perturb per sample.
        # Perturbation strategy returns a fresh dict (per-call rng-driven).
        perturbed = perturbation_strategy(baseline_thresholds, rng)

        # scope #3: detection re-run on the perturbed copy.
        detection_result = detection_callable(snapshot_copy, perturbed)

        outcomes: Dict[str, bool] = {}
        for name, extractor in outcome_extractors.items():
            try:
                outcomes[name] = bool(extractor(detection_result))
            except Exception as e:
                if isinstance(e, (AttributeError, KeyError, TypeError, NameError)):
                    raise
                logger.warning(
                    f"outcome_extractor for {name!r} raised "
                    f"{type(e).__name__}: {e} — outcome treated as False"
                )
                outcomes[name] = False
        return outcomes

    return step


# ===========================================================================
# — Reference detection_callable factory for v2 substrate.
#
# ships the deep-copy + threshold-extraction substrate (sync,
# caller-supplied detection_callable). wires a reference
# `detection_callable` builder that operators can use to plug a real
# `LayeredDetector` into the v2 perturbation factory. Substrate-only
# scope — the helper builds an `entities/graph/history`
# extractor + LayeredDetector instantiator + outcome dict; operators
# wire it into the v2 factory via `make_real_perturbation_simulation_step_v2`.
#
# Async-vs-sync bridge: LayeredDetector.detect_all is async, but
# MonteCarloPredictor.predict expects a sync simulation_step. The
# reference callable runs detect_all via asyncio.run() (constructs
# its own event loop per call). For inside-event-loop callers, the
# `make_layered_detector_runtime_callable_async` variant is also
# exposed; operators choose based on calling context.
# ===========================================================================


def build_detection_outcome_dict(problems: List[Any]) -> Dict[str, Any]:
    """pure helper that converts a list of Problem objects
    into the scope #1 outcome dict shape:
    ``{"problem_persists": bool, "problem_count": int, "fired_axioms": set}``.

    Used inside detection_callable implementations to standardize the
    return shape. Operators implementing custom detection_callables
    should adopt this helper so outcome_extractors work consistently.

    Args:
        problems: A list of detection Problem-like objects. Each may
            have a ``.axiom`` attribute (string name) or a ``.axiom_type``
            attribute (legacy); defensive getattr handles both.

    Returns:
        Dict with the 3 standard outcome fields. `fired_axioms` is a
        set of stringified axiom names; empty when no problems carry
        an axiom attribute.
    """
    count = len(problems) if problems else 0
    fired: set = set()
    for p in problems or []:
        axiom = getattr(p, "axiom", None) or getattr(p, "axiom_type", None)
        if axiom is not None:
            axiom_name = getattr(axiom, "value", None) or str(axiom)
            fired.add(axiom_name)
    return {
        "problem_persists": count > 0,
        "problem_count": count,
        "fired_axioms": fired,
    }


def make_layered_detector_runtime_callable(
    layered_detector_factory: Callable[..., Any],
    snapshot_to_inputs: Callable[[Any], Tuple[Any, Any, Any]],
    *,
    threshold_injector: Optional[
        Callable[
            [Any, Dict[Tuple[str, str, str], Tuple[Optional[float], Optional[float]]]],
            None,
        ]
    ] = None,
) -> Callable[[Any, Dict[Tuple[str, str, str], Tuple[Optional[float], Optional[float]]]], Dict[str, Any]]:
    """ (substrate) — build a sync detection_callable
    compatible with the v2 perturbation factory.

    Wires `LayeredDetector.detect_all` into the
    ``detection_callable(snapshot_copy, perturbed_thresholds) -> dict``
    contract that the `make_real_perturbation_simulation_step_v2`
    expects. The async detect_all call is bridged to sync via
    asyncio.run() — fine for the MonteCarloPredictor.predict() loop
    which is itself sync.

    Per scope #1 — threshold injection is operator-supplied via
    the optional `threshold_injector` callable. The injector decides
    HOW to apply the perturbed thresholds (mutate snapshot entity
    properties OR construct an AxiomParameters override). When None,
    thresholds are ignored (detection runs against the unperturbed
    snapshot_copy — useful for sanity-checking the wiring before
    plugging real injection).

    Args:
        layered_detector_factory: callable ``() -> LayeredDetector``
            (or any duck-typed equivalent). Called once per sample to
            get a fresh detector. Operators wanting per-sample
            AxiomParameters overrides return a new detector with the
            override applied here.
        snapshot_to_inputs: callable ``(snapshot_copy) -> (entities,
            graph, history)`` — extracts the 3-tuple that detect_all
            expects from a DigitalTwinTopology snapshot (or any opaque
            snapshot the operator manages).
        threshold_injector: optional callable ``(snapshot_copy,
            perturbed_thresholds) -> None`` — mutates snapshot_copy
            in place with the perturbed thresholds. When None,
            thresholds are passed but unused (substrate-scope safe
            default).

    Returns:
        A sync ``detection_callable(snapshot_copy, perturbed_thresholds)
        -> Dict[str, Any]`` compatible with
        ``make_real_perturbation_simulation_step_v2``.
    """
    import asyncio as _asyncio

    def detection_callable(
        snapshot_copy: Any,
        perturbed_thresholds: Dict[
            Tuple[str, str, str], Tuple[Optional[float], Optional[float]]
        ],
    ) -> Dict[str, Any]:
        if threshold_injector is not None:
            threshold_injector(snapshot_copy, perturbed_thresholds)
        detector = layered_detector_factory()
        entities, graph, history = snapshot_to_inputs(snapshot_copy)
        # asyncio.run() always creates a new event loop — safe for the
        # sync MonteCarloPredictor.predict() loop. Inside-event-loop
        # callers use the _async variant below.
        result = _asyncio.run(detector.detect_all(entities, graph, history))
        problems = getattr(result, "problems", None) or []
        return build_detection_outcome_dict(problems)

    return detection_callable


async def make_layered_detector_runtime_callable_async(
    layered_detector_factory: Callable[..., Any],
    snapshot_to_inputs: Callable[[Any], Tuple[Any, Any, Any]],
    snapshot_copy: Any,
    perturbed_thresholds: Dict[
        Tuple[str, str, str], Tuple[Optional[float], Optional[float]]
    ],
    threshold_injector: Optional[
        Callable[
            [Any, Dict[Tuple[str, str, str], Tuple[Optional[float], Optional[float]]]],
            None,
        ]
    ] = None,
) -> Dict[str, Any]:
    """async variant of the reference detection_callable.

    For inside-event-loop callers (e.g. FastAPI route handlers) that
    cannot use asyncio.run() because an event loop is already active.
    Operators wrap this in a sync shim if integrating with the sync
    MonteCarloPredictor.predict() loop via a thread executor.

    Same arg semantics as ``make_layered_detector_runtime_callable``
    except this is the direct-invoke variant (no closure).
    """
    if threshold_injector is not None:
        threshold_injector(snapshot_copy, perturbed_thresholds)
    detector = layered_detector_factory()
    entities, graph, history = snapshot_to_inputs(snapshot_copy)
    result = await detector.detect_all(entities, graph, history)
    problems = getattr(result, "problems", None) or []
    return build_detection_outcome_dict(problems)


# ===========================================================================
# — Canonical AxiomParameters threshold_injector.
#
# ships the v2 substrate hook (`threshold_injector: Optional[Callable]`)
# on the reference detection_callable factory; lands the canonical
# injector mapping the `Dict[(entity_type, indicator, axiom),
# Tuple[warn, critical]]` shape onto a concrete target.
#
# Architectural choice: option (b) scope #1 — snapshot
# entity-property mutation under a sentinel key
# ``__cd508_axiom_thresholds__``. Rationale:
# - Preserves AxiomParameters dataclass shape (option (a) would require
# N-field schema extension; high-surface change rippling through every
# axiom checker that reads global params).
# - Per-(entity_type, indicator, axiom) granularity preserved at the
# per-entity level (each entity carries its own perturbed thresholds).
# - Per-sample isolation guaranteed via the `deepcopy_snapshot` —
# the mutation happens on the snapshot_copy, NEVER the original.
# - Sentinel key under entity.properties avoids polluting the
# ``axiom_thresholds`` namespace (which downstream might use for
# non-perturbation purposes).
#
# the established pattern substrate scope: ships the injector helper + factory.
# Axiom-checker-level integration (each axiom reads from the sentinel
# key before falling back to AxiomParameters) deferred to.
# Until lands, the override is set on entities but NOT consumed —
# operators wire a custom LayeredDetector that pre-reads the sentinel
# at detect_all time OR the work updates each axiom checker.
# ===========================================================================


# the sentinel key and its resolver moved to
# `arbiter_engine/axiom_thresholds.py`. Six axiom checkers import the resolver and
# none of them have anything to do with Monte Carlo; keeping it here meant the
# predictor could not be removed from the engine extraction without taking the
# checkers with it. Re-exported so existing import sites keep working.
from ..axiom_thresholds import (  # noqa: E402,F401
    CD508_ENTITY_PROPERTY_KEY,
    resolve_axiom_threshold,
)


def inject_thresholds_via_entity_properties(
    snapshot_copy: Any,
    perturbed_thresholds: Dict[
        Tuple[str, str, str], Tuple[Optional[float], Optional[float]]
    ],
) -> None:
    """ (option b) — canonical threshold_injector.

    Mutates ``snapshot_copy.nodes[id].entity.properties`` in place, adding
    or updating the ``__cd508_axiom_thresholds__`` sentinel key with a
    per-(indicator, axiom) → (warn, critical) dict. Only entities whose
    entity-type appears in ``perturbed_thresholds`` are touched.

    Per + invoked PER SAMPLE inside the v2 perturbation
    factory's detection_callable. Per-sample isolation guaranteed via
    the ``deepcopy_snapshot`` — the mutation happens on the snapshot
    copy, NEVER on the original snapshot.

    Args:
        snapshot_copy: A deep-copied DigitalTwinTopology (or duck-typed
            equivalent with ``.nodes`` dict-keyed by entity-id +
            ``.entity.properties`` dict). The copy is mutated in place.
        perturbed_thresholds: The dict shape from the
            ``extract_axiom_thresholds_from_domain_config`` (or a
            perturbed variant). Keys are ``(entity_type, indicator,
            axiom)`` tuples; values are ``(warn, critical)`` Tuples
            where either bound may be None (axiom-not-applicable).

    Returns:
        None. Mutation is in-place on snapshot_copy.

    previously behavior: the override is RECORDED on the entity but
    NOT yet consumed by axiom checkers — they still read from the
    global AxiomParameters. This makes a single-checker-at-a-time
    rollout: each axiom checker that adopts the override-first pattern
    becomes calibration-aware independently.
    """
    if not perturbed_thresholds:
        return

    nodes = getattr(snapshot_copy, "nodes", None) or {}
    if not nodes:
        return

    # Group perturbed_thresholds by entity_type for O(N nodes × M types) lookup
    # rather than O(N × all-keys) on every node.
    by_entity_type: Dict[str, Dict[Tuple[str, str], Tuple[Optional[float], Optional[float]]]] = {}
    for (etype, indicator, axiom), (warn, critical) in perturbed_thresholds.items():
        by_entity_type.setdefault(etype, {})[(indicator, axiom)] = (warn, critical)

    for node in nodes.values():
        entity = getattr(node, "entity", None)
        if entity is None:
            continue
        # Real Entity uses ``.type``; test fixtures may use ``.entity_type``.
        node_etype = (
            getattr(entity, "type", None)
            or getattr(entity, "entity_type", None)
        )
        if not node_etype or node_etype not in by_entity_type:
            continue

        # Ensure properties dict exists (defensive — production Entity
        # always has it; some test fixtures might not).
        props = getattr(entity, "properties", None)
        if props is None:
            try:
                entity.properties = {}
                props = entity.properties
            except (AttributeError, TypeError):
                # Read-only or frozen entity — skip silently per per-sample
                # error-tolerance pattern. Override won't be applied to
                # this entity but other entities can still be perturbed.
                logger.warning(
                    "inject_thresholds_via_entity_properties: "
                    "entity %r has no settable .properties dict — skipping",
                    getattr(entity, "id", "<unknown>"),
                )
                continue

        # Update under the sentinel key. Existing dict (from a prior
        # sample on a non-deep-copied snapshot, or from operator
        # pre-population) is REPLACED, not merged — per-sample isolation
        # contract requires the dict to reflect only THIS sample's
        # perturbed values.
        props[CD508_ENTITY_PROPERTY_KEY] = dict(by_entity_type[node_etype])


def make_entity_properties_threshold_injector() -> Callable[
    [Any, Dict[Tuple[str, str, str], Tuple[Optional[float], Optional[float]]]],
    None,
]:
    """convenience factory returning the canonical threshold_injector
    suitable for `make_layered_detector_runtime_callable`'s `threshold_injector`
    kwarg.

    Stateless factory — returns the pure-function form for parity with
    the injector signature. previously operators integrating with
    a real LayeredDetector pass this as:

        make_layered_detector_runtime_callable(layered_detector_factory=lambda: my_detector,
            snapshot_to_inputs=my_extractor,
            threshold_injector=make_entity_properties_threshold_injector())

    Once lands the axiom-checker-level integration, the override
    dict written by this injector becomes load-bearing for calibration
    validation.
    """
    return inject_thresholds_via_entity_properties


# ===========================================================================
# — Shared override-precedence resolver for axiom checkers.
#
# Each axiom-checker that integrates override (scope items
# #1/#2/#3) calls this helper at every threshold read-site. Precedence:
# 1. entity.properties["__cd508_axiom_thresholds__"][(indicator, axiom)]
# — per-sample perturbed override from injector
# 2. axiom_param_value — global AxiomParameters fallback
#
# Bound selector — each tuple is (warn, critical); callers pass which side
# they want via the `bound` arg: "warn" / "critical" / "both" (returns the
# full tuple for callers that need both).
#
# the established pattern substrate scope for this helper ships as the SHARED
# entry point that all 3 axiom-checkers will use. Per-checker integration
# (read-site changes in ConstraintEngine / UnifiedAxiomReasoner /
# StatisticalAnomalyDetector) ships in as a multi-file rollout.
# ===========================================================================

