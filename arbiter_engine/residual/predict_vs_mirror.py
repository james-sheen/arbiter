""" (Track-A A-7) — PREDICT-vs-MIRROR residual: the prediction ledger.

The document's central engine (dt.md 5.4.2): a prediction recorded at
traversal time, graded against the mirrored world at horizon maturity.
This is the **D4 traversal-aperture** — sibling apertures already exist and
are deliberately not duplicated: `PlanOutcomeRecorder` covers the
plan-aperture and `OutcomeFeedbackLoop` action-calibration; #15 of
the 22-corpus (an explicit recorded prediction, falsified the next day) is
the exhibit neither of those could see.

v0 grades IMPACT predictions (`DownstreamImpact`: entity X impacted with
probability p within delay d, emitted by every forward traversal):

- **CONFIRMED** — a problem arrived on the predicted entity inside the
  window (graded eagerly; no emission — a confirmed prediction is quiet).
- **FALSIFIED** — the window closed, the entity WAS observed, no problem
  came: the model said impact-HERE and reality stayed quiet. Emitted as a
  ``prediction_residual:impact_missing`` problem into the D2 gate
where it routes as the fourth residual source
  (``prediction``), classifies structural by default, and is subject to
  the same restart / labeled-intervention excuses as every other row.
- **UNGRADEABLE** — the entity was not observed in the window: the
  not-looking silence. Per the three-silences discipline (dt.md 8.5) it is
  recorded, never graded, and never emitted.

Gate-off semantics follow the PlanOutcomeRecorder precedent (``DT_PREDICT_VS_MIRROR_ENABLED`` default OFF): the module-level singleton
record/grade paths are no-ops with zero memory accumulation; the
``PredictionLedger`` class itself is a pure library. Ring cap via
``DT_PREDICTION_LEDGER_RING_CAP`` (default 1000). Value-level predictions
(``ProjectedValue`` vs observed property) SHIPPED and are no longer a
follow-up: ``record_value_prediction`` and ``record_projected_values`` file
them and ``grade_matured`` scores ``kind == "value"`` against the mirror
reading.

THE LOOP CLOSED ONE WAY at -- a rollout files its per-step values
here and ``check`` grades them -- and what it files became scoreable rather
than only judgeable at a value carrying a declared spread states that
spread as quantiles, so ``own_projections`` can ask whether the engine's own
intervals are honest and not merely whether the world landed inside them. What
is still open is the OTHER direction: the transition learner reads nothing
back.
"""

from __future__ import annotations

import os
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from ..clock import as_naive_utc, now_utc

from typing import Any, Deque, Dict, Iterable, List, Optional, Sequence, Set, Tuple

GRADE_CONFIRMED: str = "confirmed"
GRADE_FALSIFIED: str = "falsified"
GRADE_UNGRADEABLE: str = "ungradeable"

PREDICTION_RESIDUAL_TYPE: str = "prediction_residual:impact_missing"

_DEFAULT_RING_CAP: int = 1000
_DEFAULT_GRACE_S: float = 60.0
# falsified-emission severity: probability-weighted — a confident prediction
# that missed is a louder model-wrong signal than a long-shot that missed.
_HIGH_PROBABILITY: float = 0.5


def predict_vs_mirror_enabled() -> bool:
    """The gate — default OFF."""
    return os.environ.get(
        "DT_PREDICT_VS_MIRROR_ENABLED", ""
    ).strip().lower() in ("1", "true", "yes")


@dataclass
class PredictionRecord:
    """One traversal-time prediction awaiting its mirror."""

    prediction_id: str
    traversal_id: str
    entity_id: str
    kind: str                       # "impact" | "stated" | "value" | "distribution"
    probability: float
    horizon_s: float
    severity: str
    predicted_at: datetime
    hop_distance: int = 0
    path: Tuple[str, ...] = ()
    # (#15 exercise): optional indicator scope. Entity-granular
    # confirmation reads any in-window problem on the entity as a hit —
    # which is exactly the Day-9 conflation corpus #15 exposed (two
    # signals decoupling on ONE entity). A scoped record confirms only
    # on a problem carrying the same indicator.
    indicator: Optional[str] = None
    # (value-kind v1): a value prediction grades against the
    # OBSERVATION stream, not the problem stream — predicted value vs the
    # observation closest to the horizon, within a caller-owned tolerance
    # (never guessed; the no-name-heuristics discipline).
    value: Optional[float] = None
    tolerance: Optional[float] = None
    # Distribution-kind: the forecast itself, as declared quantiles, plus the
    # producer that issued it. A point prediction answers "what"; a
    # distribution answers "what, and how sure" -- and only the second can be
    # scored for CALIBRATION rather than for accuracy. `model_id` is what makes
    # the strata in `calibration()` possible: without it every producer's
    # scores are pooled, and a pooled score cannot say which model to stop
    # using.
    quantiles: Optional[Dict[str, float]] = None
    model_id: Optional[str] = None
    # The third stratum, SUPPLIED BY THE CALLER and never derived. This ledger
    # holds an entity id and has never held a model, so the only way to get a
    # type out of an id here would be to read the id's shape -- which is the
    # name-heuristic class this package has removed from three axioms. Both
    # callers have the entity in hand when they file, so the fact is free at
    # the one moment it is known and unrecoverable afterwards.
    entity_type: Optional[str] = None
    #:. The couplings that drove this value, each `relation:from->to`.
    #: A rollout supplies them; anything else filing a value leaves them
    #: empty, and an empty tuple means UNATTRIBUTED rather than *belongs to
    #: everyone* -- which is what a per-coupling confirm rate used to assume.
    couplings: Tuple[str, ...] = ()
    # WHO ISSUED IT. Supplied by the caller on the same argument as
    # `entity_type` above: they know it when they file and nothing can recover
    # it afterwards.
    #
    # NOT TWO PARTIES ANY MORE. This said "the engine's own projector, or
    # somebody outside", which was true while `SOURCE_ENGINE` was the only
    # non-`None` value anyone set. 0.1.17 gave `ingest_forecasts` a `source=`
    # and the predicate everything reads became `source is None`, so the field
    # is now free-form and the only distinction it draws is *submitted by a
    # producer* against *filed by somebody who is not one*. A caller running a
    # reference forecaster beside the desk's stamps its own value, and
    # `checked.caller_references` counts those apart from the engine's.
    #
    # It is here because the alternative was matching on the id. `project`
    # files under `<model>:<source>` and its reference under `baseline_rw`, and
    # the `forecasts` leg was reading every distribution record as a producer's
    # submission -- so a model declaring `models: [garch_v3]` declined
    # `model_unknown` for the engine's OWN projection, and the leg counted it
    # as the forecast an outside producer owed. An expectation nobody met read
    # as met. Telling the two apart by the shape of a string is the
    # name-heuristic class this package has removed from three axioms; a field
    # the filer sets is the same fact, stated once, by whoever knows it.
    #
    # `None` means outside, because that is what every caller predating this
    # field was.
    source: Optional[str] = None
    # Set at grading for distribution records: per-level pinball loss, the
    # 90%-interval hit, and the CRPS approximation built from them.
    scores: Optional[Dict[str, Any]] = None
    verdict: Optional[str] = None   # confirmed | falsified | ungradeable
    graded_at: Optional[datetime] = None


@dataclass
class PredictionResidualProblem:
    """Duck-types the Problem surface DiscrepancyAggregator reads."""

    id: str
    entity_id: str
    entity_type: str
    problem_type: str
    severity: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""


def _problem_ts(problem: Any) -> Optional[datetime]:
    for attr in ("detected_at", "created_at", "first_seen", "timestamp"):
        value = getattr(problem, attr, None)
        if isinstance(value, datetime):
            return value
    return None


def _problem_indicator(problem: Any) -> Optional[str]:
    """Mirror of the aggregator's indicator derivation: evidence first,
    then the problem_type suffix."""
    ev = getattr(problem, "evidence", None) or {}
    if isinstance(ev, dict) and ev.get("indicator"):
        return str(ev["indicator"])
    ptype = str(getattr(problem, "problem_type", "") or "")
    if ":" in ptype:
        return ptype.split(":", 1)[1] or None
    return None


#: The two levels a distribution record must carry. Chosen because the central
#: 90% interval is what `coverage_90` scores, and a record that cannot be
#: coverage-scored cannot be calibration-scored at all -- which would make it a
#: point prediction wearing a distribution's name.
_REQUIRED_LEVELS: Tuple[str, str] = ("q05", "q95")


def quantile_level(key: str) -> float:
    """``q05`` -> 0.05, ``q50`` -> 0.5, ``q975`` -> 0.975.

    The digits after ``q`` ARE the fractional part, which is the only reading
    under which ``q05`` and ``q5`` can both be written and mean what their
    authors meant. Levels of 0 and 1 are refused: a 0th or 100th percentile is
    unbounded for every distribution the engine will be handed, so a number
    there is a placeholder rather than a forecast.
    """
    text = str(key).strip().lower()
    if not text.startswith("q") or not text[1:].isdigit():
        raise ValueError(
            f"quantile key {key!r} is not `q` followed by digits (q05, q50, q95)")
    level = float("0." + text[1:])
    if not 0.0 < level < 1.0:
        raise ValueError(f"quantile level from {key!r} is {level}, not strictly in (0, 1)")
    return level


def pinball_loss(level: float, predicted: float, observed: float) -> float:
    """The proper scoring rule for one quantile. Lower is better, 0 is exact.

    Asymmetric by design: at the 5th percentile, being too HIGH is penalised
    nineteen times as hard as being too low, because a 5th-percentile forecast
    that the outcome routinely falls below is not a 5th percentile.
    """
    delta = observed - predicted
    return delta * level if delta >= 0 else -delta * (1.0 - level)


#: Half-width of the central 90% interval of a normal, in standard deviations.
#: The level is fixed by `_REQUIRED_LEVELS` -- q05 and q95 ARE the central 90%
#: -- so this is derived from that pair rather than chosen beside it. It is
#: NOT 1.96: that is the 95% half-width and it is what a value record's
#: `tolerance` carries. Both describe one declared spread at two levels, and a
#: record filed from that spread carries both.
NORMAL_90_HALF_WIDTH: float = 1.6448536269514722


def _validated_quantiles(quantiles: Dict[str, float]) -> Dict[str, float]:
    """Every rule a set of quantiles must satisfy to be scoreable, once.

    These checks were written for `record_distribution`, and the
    engine's own projections now file quantiles too. Two copies of a
    validation rule is how two callers come to disagree about what a valid
    forecast is, so there is one.
    """
    if not quantiles:
        raise ValueError("a distribution prediction requires quantiles")
    levels = {}
    for key, value in quantiles.items():
        levels[key] = quantile_level(key)          # raises on a malformed key
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(
                f"quantile {key!r} is {value!r}, which is not a number")
    # `q10` and `q100` both read as 0.1 under the rule above, and so do
    # `q1` and `q10`. Two keys at one level are not a crash -- they are two
    # scores for one quantile, silently double-weighting it in the mean
    # that becomes CRPS. Refused, naming both spellings, because the caller
    # meant one of them and the ledger cannot tell which.
    collisions: Dict[float, List[str]] = {}
    for key, level in levels.items():
        collisions.setdefault(level, []).append(key)
    duplicated = {lvl: sorted(keys) for lvl, keys in collisions.items()
                  if len(keys) > 1}
    if duplicated:
        raise ValueError(
            f"two quantile keys name one level: {duplicated}. The digits "
            f"after `q` are the fractional part, so `q1`, `q10` and `q100` "
            f"are all 0.1")
    missing = [k for k in _REQUIRED_LEVELS if k not in quantiles]
    if missing:
        raise ValueError(
            f"a distribution prediction requires {list(_REQUIRED_LEVELS)}; "
            f"missing {missing}. A forecast with no stated interval cannot "
            f"be scored for coverage, and an unscoreable record would be "
            f"counted in a calibration figure it never contributed to"
        )
    # Monotonicity is a property of quantiles, not a convention: if the
    # 95th percentile sits below the 5th, the producer has mislabelled its
    # own output and every score computed from it would be meaningless.
    ordered = sorted(levels.items(), key=lambda kv: kv[1])
    for (lo_key, _), (hi_key, _) in zip(ordered, ordered[1:]):
        if quantiles[hi_key] < quantiles[lo_key]:
            raise ValueError(
                f"quantiles are not monotone: {hi_key}={quantiles[hi_key]} "
                f"< {lo_key}={quantiles[lo_key]}")
    return {str(k): float(v) for k, v in quantiles.items()}


def normal_quantiles(value: float, sigma: float) -> Dict[str, float]:
    """The central 90% of a declared normal, as the levels a score needs.

    NOTHING IS ASSUMED HERE THAT WAS NOT ASSUMED ALREADY. A declared
    `gain_sigma:` is a standard deviation, and a value record's tolerance has
    been read off it as `1.96 *sigma` since; this states the same
    spread at the level `coverage_90` scores. The normality is the author's,
    carried forward -- not a distribution the ledger invented, which is what
    `forecast/contract.py` refuses to do on a producer's behalf.
    """
    half = NORMAL_90_HALF_WIDTH * float(sigma)
    return {"q05": float(value) - half,
            "q50": float(value),
            "q95": float(value) + half}


def _score_quantiles(quantiles: Dict[str, float], observed: float,
                     observed_at: datetime,
                     model_id: Optional[str]) -> Dict[str, Any]:
    """Pinball, the CRPS approximation and the 90% hit, for one graded record.

    Shared by the producer aperture and the engine's own, because a
    score the engine computes about itself under a second implementation is
    not comparable with the one it computes about a producer -- and being
    comparable is the whole reason to compute it.
    """
    losses = {key: pinball_loss(quantile_level(key), value, observed)
              for key, value in quantiles.items()}
    lo, hi = quantiles[_REQUIRED_LEVELS[0]], quantiles[_REQUIRED_LEVELS[1]]
    return {
        "observed": observed,
        "observed_at": observed_at.isoformat(),
        "pinball": {k: round(v, 9) for k, v in losses.items()},
        "pinball_mean": round(sum(losses.values()) / len(losses), 9),
        # CRPS for a distribution given by quantiles is approximated by
        # twice the mean pinball loss over its levels. It is named
        # `_approx` because the equality is exact only in the limit of
        # densely and evenly spaced levels, and three levels are neither.
        "crps_approx": round(2.0 * sum(losses.values()) / len(losses), 9),
        "covered_90": lo <= observed <= hi,
        "interval": [lo, hi],
        "model_id": model_id,
    }


class PredictionLedger:
    """Ring-buffered PREDICT-vs-MIRROR ledger. Pure library — gating and
    singleton lifecycle live in the module-level helpers below."""

    def __init__(
        self,
        ring_cap: Optional[int] = None,
        grace_s: float = _DEFAULT_GRACE_S,
    ) -> None:
        if ring_cap is None:
            try:
                ring_cap = int(os.environ.get(
                    "DT_PREDICTION_LEDGER_RING_CAP", str(_DEFAULT_RING_CAP)))
            except ValueError:
                ring_cap = _DEFAULT_RING_CAP
        self._records: Deque[PredictionRecord] = deque(maxlen=max(1, int(ring_cap)))
        self.grace_s = float(grace_s)
        # (W-2 disposition): a still-PENDING record evicted at cap
        # is an ungraded prediction — a not-looking silence the ledger must
        # count rather than swallow. Exposed via calibration() and the
        # /pump-state surface.
        self.evicted_pending = 0

    def _append(self, record: PredictionRecord) -> None:
        """The ONE place a record enters the ledger.

        four `record_*` methods appended to the deque directly, so a
        durable backend would have had to override all four and would have
        gone stale the first time a fifth kind was added. This is the hook a
        subclass overrides instead; `SqlitePredictionLedger` writes through
        here and nowhere else.
        """
        self._records.append(record)

    def _note_eviction(self) -> None:
        if (self._records.maxlen is not None
                and len(self._records) == self._records.maxlen
                and self._records[0].verdict is None):
            self.evicted_pending += 1

    # -- record ---------------------------------------------------------------

    def record_impacts(
        self,
        impacts: Optional[Iterable[Any]],
        traversal_id: Optional[str] = None,
        predicted_at: Optional[datetime] = None,
    ) -> List[str]:
        """File one PredictionRecord per DownstreamImpact; returns ids."""
        tid = traversal_id or str(uuid.uuid4())
        ts = as_naive_utc(predicted_at) if predicted_at else now_utc()
        ids: List[str] = []
        for imp in impacts or []:
            entity_id = str(getattr(imp, "entity_id", "") or "")
            if not entity_id:
                continue
            severity = getattr(imp, "severity", None)
            record = PredictionRecord(
                prediction_id=str(uuid.uuid4()),
                traversal_id=tid,
                entity_id=entity_id,
                kind="impact",
                probability=float(getattr(imp, "probability", 0.0) or 0.0),
                horizon_s=float(getattr(imp, "expected_delay_s", 0.0) or 0.0),
                severity=str(getattr(severity, "value", severity) or "medium").lower(),
                predicted_at=ts,
                hop_distance=int(getattr(imp, "hop_distance", 0) or 0),
                path=tuple(str(n) for n in (getattr(imp, "path", None) or ())),
            )
            self._note_eviction()
            self._append(record)
            ids.append(record.prediction_id)
        return ids

    def record_prediction(
        self,
        entity_id: str,
        probability: float,
        horizon_s: float,
        indicator: Optional[str] = None,
        kind: str = "stated",
        severity: str = "medium",
        traversal_id: Optional[str] = None,
        predicted_at: Optional[datetime] = None,
    ) -> str:
        """Direct filing for non-traversal apertures — a recorded claim
        (the corpus-#15 shape: an operator- or model-stated prediction),
        optionally indicator-scoped. Graded by the same machinery."""
        record = PredictionRecord(
            prediction_id=str(uuid.uuid4()),
            traversal_id=traversal_id or str(uuid.uuid4()),
            entity_id=str(entity_id),
            kind=str(kind),
            probability=float(probability),
            horizon_s=float(horizon_s),
            severity=str(severity).lower(),
            predicted_at=as_naive_utc(predicted_at) if predicted_at else now_utc(),
            indicator=str(indicator) if indicator else None,
        )
        self._note_eviction()
        self._append(record)
        return record.prediction_id

    def record_value_prediction(
        self,
        entity_id: str,
        property_name: str,
        predicted_value: float,
        tolerance: float,
        horizon_s: float,
        confidence: float = 0.5,
        traversal_id: Optional[str] = None,
        predicted_at: Optional[datetime] = None,
        couplings: Tuple[str, ...] = (),
        quantiles: Optional[Dict[str, float]] = None,
        model_id: Optional[str] = None,
        source: Optional[str] = None,
    ) -> str:
        """ (value-kind v1): file a value prediction — entity E's
        property P will read ~V (+/- tolerance) at horizon H. Tolerance is
        caller-owned and mandatory: the ledger never guesses resolution.

        AND THE SPREAD IT CAME FROM, WHERE THE CALLER HAS ONE.
        `tolerance` answers *did the world land inside the band we chose*, and
        that question rewards choosing a wider one: measured on one reality,
        a `gain_sigma:` ten times too wide scored `confirm_rate` 1.0 against
        an honest declaration's 0.95, and `brier` ranked them the same way
        because every record here is filed at ONE stated confidence, which
        makes `brier` a monotone restatement of the hit rate rather than a
        second opinion.

        Quantiles are what the proper scores need. They do not change the
        verdict -- that is still the point against its tolerance -- and they
        do not enter the producer figures. They make `own_projections`
        computable, and pinball loss grows with the width of an interval
        whether or not it contained the answer, so a band bought by declaring
        ignorance finally costs something.

        Optional on the same rule as everything else here: a caller with no
        spread supplies none and is scored on the hit rate alone. Nothing is
        invented to fill the gap.
        """
        if not tolerance or float(tolerance) <= 0:
            raise ValueError("value predictions require a positive tolerance")
        record = PredictionRecord(
            prediction_id=str(uuid.uuid4()),
            traversal_id=traversal_id or str(uuid.uuid4()),
            entity_id=str(entity_id),
            kind="value",
            probability=float(confidence),
            horizon_s=float(horizon_s),
            severity="medium",
            predicted_at=as_naive_utc(predicted_at) if predicted_at else now_utc(),
            indicator=str(property_name),
            value=float(predicted_value),
            tolerance=float(tolerance),
            couplings=tuple(couplings),
            quantiles=(_validated_quantiles(quantiles)
                       if quantiles is not None else None),
            model_id=str(model_id) if model_id is not None else None,
            # `is not None`, NOT truthiness -- the same guard the distribution
            # filer carries, and for the same reason: `None` is the producer
            # predicate, so folding `""` to `None` silently reclassifies a
            # caller who supplied an empty source as somebody outside.
            source=str(source) if source is not None else None,
        )
        self._note_eviction()
        self._append(record)
        return record.prediction_id

    def record_distribution(
        self,
        entity_id: str,
        property_name: str,
        quantiles: Dict[str, float],
        horizon_s: float,
        model_id: str,
        traversal_id: Optional[str] = None,
        predicted_at: Optional[datetime] = None,
        entity_type: Optional[str] = None,
        source: Optional[str] = None,
    ) -> str:
        """File a distributional forecast -- entity E's property P will be
        distributed like these quantiles at horizon H, according to model M.

        ``q05`` and ``q95`` are MANDATORY, on the same argument that makes
        ``tolerance`` mandatory on a value prediction: the ledger never guesses
        resolution. A caller who supplies only a median has supplied a point
        prediction, and ``record_value_prediction`` is where those go -- filing
        one here would produce a record that ``coverage_90`` silently skips,
        and a calibration figure computed over an unstated subset is worse than
        no figure.

        Extra levels are kept and scored. They widen the CRPS approximation
        without changing what ``coverage_90`` means.
        """
        quantiles = _validated_quantiles(quantiles)
        record = PredictionRecord(
            prediction_id=str(uuid.uuid4()),
            traversal_id=traversal_id or str(uuid.uuid4()),
            entity_id=str(entity_id),
            kind="distribution",
            probability=0.9,          # the interval this record is scored on
            horizon_s=float(horizon_s),
            severity="medium",
            predicted_at=as_naive_utc(predicted_at) if predicted_at else now_utc(),
            indicator=str(property_name),
            value=float(quantiles.get("q50", quantiles[_REQUIRED_LEVELS[0]])),
            quantiles=dict(quantiles),
            model_id=str(model_id),
            entity_type=str(entity_type) if entity_type else None,
            # `is not None`, NOT truthiness. `if source` folded `""` to `None`,
            # and `None` is the producer predicate -- so a caller who supplied
            # an empty source was silently reclassified as a producer, judged
            # by the shadow axioms and able to raise the exit code of the audit
            # it was being measured inside. That is precisely the failure
            # `source=` was added to stop, reachable through a falsy value.
            source=str(source) if source is not None else None,
        )
        self._note_eviction()
        self._append(record)
        return record.prediction_id

    def record_projected_values(
        self,
        topology: Any,
        tolerance_map: Optional[Dict[str, float]] = None,
        default_tolerance: Optional[float] = None,
        traversal_id: Optional[str] = None,
        predicted_at: Optional[datetime] = None,
    ) -> Tuple[List[str], int]:
        """Callsite-ready bridge for `TwinNode.projected_values`.

        Properties without a caller-owned tolerance are SKIPPED and counted,
        never guessed. Returns (recorded_ids, skipped_count).

        THIS SAID `projected_values` WAS A DARK SCHEMA FIELD THAT NO
        PRODUCER CONSTRUCTS. Two do, in `twin/traverser.py`, and have since the
        world-model arc; the sentence described the tree it was written
        against and was still being shipped two releases later. Second of this
        shape in a month, after a README guard that pinned a disclaimer the
        engine had outgrown -- a claim about what the code does NOT do is the
        kind that rots silently, because nothing fails when it stops being
        true.
        """
        tolerance_map = tolerance_map or {}
        ids: List[str] = []
        skipped = 0
        nodes = getattr(topology, "nodes", None) or {}
        for node in nodes.values():
            entity = getattr(node, "entity", None)
            entity_id = str(getattr(entity, "id", "") or "")
            if not entity_id:
                continue
            for prop, pv in (getattr(node, "projected_values", None) or {}).items():
                tolerance = tolerance_map.get(str(prop), default_tolerance)
                if not tolerance or float(tolerance) <= 0:
                    skipped += 1
                    continue
                ids.append(self.record_value_prediction(
                    entity_id=entity_id,
                    property_name=str(prop),
                    predicted_value=float(getattr(pv, "value", 0.0)),
                    tolerance=float(tolerance),
                    horizon_s=float(getattr(pv, "horizon_s", 0.0) or 0.0),
                    confidence=float(getattr(pv, "confidence", 0.5) or 0.5),
                    traversal_id=traversal_id,
                    predicted_at=predicted_at,
                ))
        return ids, skipped

    # -- grade ----------------------------------------------------------------

    def pending(self) -> List[PredictionRecord]:
        return [r for r in self._records if r.verdict is None]

    def records(self) -> List[PredictionRecord]:
        return list(self._records)

    @staticmethod
    def _observations_for(
        histories: Iterable[Any],
        entity_id: str,
        property_name: str,
        start: datetime,
        end: datetime,
    ) -> List[Tuple[datetime, float]]:
        """Numeric observations for (entity, property) in [start, end],
        read defensively from the in-memory histories."""
        out: List[Tuple[datetime, float]] = []
        for history in histories or []:
            raw = getattr(history, "_history", None)
            if not isinstance(raw, dict):
                continue
            for ts, value in raw.get((entity_id, property_name)) or []:
                if (isinstance(ts, datetime) and isinstance(value, (int, float))
                        and start <= ts <= end):
                    out.append((ts, float(value)))
        return out

    def _grade_distribution_record(
        self,
        record: PredictionRecord,
        histories: Optional[Iterable[Any]],
        now: datetime,
    ) -> Optional[PredictionResidualProblem]:
        """Score a distributional forecast against the observed mirror.

        Same maturity discipline as the value aperture -- a distribution stated
        for a horizon is not scoreable early, and a silent channel is
        UNGRADEABLE rather than either kind of error.

        CONFIRMED means the observation landed inside the stated 90% interval;
        FALSIFIED means outside. That is a per-record verdict, and on its own it
        says almost nothing: a well-calibrated 90% interval is SUPPOSED to be
        missed one time in ten. The figure that means something is the rate
        across many records, which is what ``calibration()["coverage_90"]``
        reports -- and a model at 100% coverage is badly calibrated in the
        other direction, having bought its hit-rate with intervals too wide to
        act on.

        A miss is therefore not emitted as a finding. The pinball losses are
        recorded on the record either way, because a forecast scored only when
        it was wrong cannot produce a calibration curve.
        """
        window_end = record.predicted_at + timedelta(
            seconds=record.horizon_s + self.grace_s)
        if now < window_end or histories is None:
            return None
        observations = self._observations_for(
            list(histories), record.entity_id, record.indicator or "",
            record.predicted_at, window_end)
        if not observations:
            record.verdict = GRADE_UNGRADEABLE
            record.graded_at = now
            return None
        target = record.predicted_at + timedelta(seconds=record.horizon_s)
        observed_at, observed = min(
            observations, key=lambda o: abs((o[0] - target).total_seconds()))
        record.scores = _score_quantiles(
            record.quantiles or {}, observed, observed_at, record.model_id)
        record.verdict = (GRADE_CONFIRMED if record.scores["covered_90"]
                          else GRADE_FALSIFIED)
        record.graded_at = now
        return None

    def _grade_value_record(
        self,
        record: PredictionRecord,
        histories: Optional[Iterable[Any]],
        now: datetime,
    ) -> Optional[PredictionResidualProblem]:
        """value-kind grading — against the OBSERVATION stream,
        at maturity only (a value predicted AT horizon is not confirmable
        early), using the observation closest to the horizon AND nearer to
        this horizon than to any other this episode filed. No observations
        in-window = the channel was silent = UNGRADEABLE (not-looking is not
        evidence), and so is a window whose readings all belong to a sibling
        horizon — silence AT the instant this record is about. Without
        histories the record stays pending — the mirror is required to
        grade."""
        window_end = record.predicted_at + timedelta(
            seconds=record.horizon_s + self.grace_s)
        if now < window_end or histories is None:
            return None
        observations = self._observations_for(
            list(histories), record.entity_id, record.indicator or "",
            record.predicted_at, window_end)
        target = record.predicted_at + timedelta(seconds=record.horizon_s)
        # AND EACH READING GRADES ONE HORIZON, not every horizon
        # whose window contains it. This took the observation closest to the
        # horizon with no bound on how far away the closest one was, so a
        # single reading graded every record filed over it: measured, twelve
        # forecasts spanning an hour all came back `confirmed` from one tank
        # reading taken 60 s after the rollout, for a `confirm_rate` of 1.0
        # and a `brier` of 0.0025 off the quietest possible mirror.
        #
        # THE BOUND IS THE OTHER HORIZONS THIS EPISODE FILED, and it is not a
        # number anyone had to choose: a reading grades the record whose
        # horizon it is NEAREST to, and the records themselves say where
        # those are. A rollout files one per step, so the horizons come
        # spaced by the caller's own `step_s` and the rule reads as *the
        # reading nearest this instant*, which is what grading at an instant
        # means.
        #
        # `grace_s` was tried here first and is wrong, which is worth
        # recording because it looks right: it is already this ledger's
        # statement of how long past the horizon the window stays open, so
        # reading it symmetrically seemed to introduce nothing. But a ledger
        # may declare `grace_s=0` -- one in this tree's own suite does -- and
        # that means *I will not wait past the horizon*, not *a reading must
        # land on it to the second*. Under the symmetric reading it made
        # every real mirror ungradeable.
        siblings = [
            other for other in self._records
            if other.kind == record.kind
            and other.entity_id == record.entity_id
            and other.indicator == record.indicator
            and other.traversal_id == record.traversal_id]
        horizons = sorted({
            other.predicted_at + timedelta(seconds=other.horizon_s)
            for other in siblings}) or [target]
        mine = [
            observation for observation in observations
            if min(horizons,
                   key=lambda h: abs(
                       (observation[0] - h).total_seconds())) == target]
        if not mine:
            record.verdict = GRADE_UNGRADEABLE
            record.graded_at = now
            return None
        observed_at, observed = min(
            mine, key=lambda o: abs((o[0] - target).total_seconds()))
        # SCORED BEFORE IT IS JUDGED, AND THE TWO ARE DIFFERENT
        # QUESTIONS. The verdict below is the point against its declared
        # tolerance and is untouched; this is what the spread was worth. A
        # record with no quantiles is not scored and is not counted, on the
        # same rule the producer aperture follows: a rate over an unstated
        # subset is worse than no rate.
        #
        # `covered_90` here is the central 90% of the declared spread, and the
        # verdict is the 95% tolerance -- two levels of one declaration, so an
        # observation between the two edges is covered by neither statement
        # wrongly. They are reported apart and never summed.
        if record.quantiles:
            record.scores = _score_quantiles(
                record.quantiles, observed, observed_at, record.model_id)
        delta = abs(observed - (record.value or 0.0))
        if record.tolerance is not None and delta <= record.tolerance:
            record.verdict = GRADE_CONFIRMED
            record.graded_at = now
            return None
        record.verdict = GRADE_FALSIFIED
        record.graded_at = now
        return PredictionResidualProblem(
            id=f"pvm-{record.prediction_id}",
            entity_id=record.entity_id,
            entity_type="",
            problem_type="prediction_residual:value_missed",
            severity="warning" if record.probability >= _HIGH_PROBABILITY else "info",
            evidence={
                "predicted_value": record.value,
                "observed_value": observed,
                "observed_at": observed_at.isoformat(),
                "delta": round(delta, 6),
                "tolerance": record.tolerance,
                "indicator": record.indicator,
                "predicted_probability": record.probability,
                "horizon_s": record.horizon_s,
                "grace_s": self.grace_s,
                "traversal_id": record.traversal_id,
                "predicted_at": record.predicted_at.isoformat(),
                "aperture": "value",
            },
            reason="projected value missed the observed mirror beyond tolerance",
        )

    def grade_matured(
        self,
        problems: Sequence[Any],
        observed_entity_ids: Set[str],
        now: Optional[datetime] = None,
        histories: Optional[Iterable[Any]] = None,
    ) -> List[PredictionResidualProblem]:
        """Grade pending records; return falsified-prediction emissions.

        Confirmation is eager (a matching problem grades the record even
        before maturity); falsification and ungradeability wait for the
        window to close (predicted_at + horizon + grace). A problem with
        no readable timestamp confirms on presence alone — the honest v0
        approximation for stores that do not carry one. Coverage is
        approximated by ``observed_entity_ids`` membership until per-
        channel freshness (S-d) sharpens it; that approximation is why
        UNGRADEABLE exists as a verdict instead of defaulting to either
        error direction.
        """
        now = as_naive_utc(now) if now else now_utc()
        by_entity: Dict[str, List[Any]] = {}
        for p in problems or []:
            ptype = str(getattr(p, "problem_type", "") or "")
            if ptype.startswith("prediction_residual"):
                continue  # never grade a prediction against our own emissions
            eid = str(getattr(p, "entity_id", "") or "")
            if eid:
                by_entity.setdefault(eid, []).append(p)

        emissions: List[PredictionResidualProblem] = []
        for record in self._records:
            if record.verdict is not None:
                continue
            if record.kind == "value":
                emission = self._grade_value_record(record, histories, now)
                if emission is not None:
                    emissions.append(emission)
                continue
            if record.kind == "distribution":
                self._grade_distribution_record(record, histories, now)
                continue
            window_end = record.predicted_at + timedelta(
                seconds=record.horizon_s + self.grace_s)
            hit = None
            for p in by_entity.get(record.entity_id, []):
                if record.indicator is not None:
                    # indicator-scoped record: only the same signal confirms
                    # (corpus #15: a decoupled sibling on the same entity
                    # must NOT read as confirmation).
                    if _problem_indicator(p) != record.indicator:
                        continue
                ts = _problem_ts(p)
                if ts is None or record.predicted_at <= ts <= window_end:
                    hit = p
                    break
            if hit is not None:
                record.verdict = GRADE_CONFIRMED
                record.graded_at = now
                continue
            if now < window_end:
                continue  # window still open — wait
            if record.entity_id not in observed_entity_ids:
                record.verdict = GRADE_UNGRADEABLE
                record.graded_at = now
                continue
            record.verdict = GRADE_FALSIFIED
            record.graded_at = now
            evidence: Dict[str, Any] = {
                "predicted_probability": record.probability,
                "horizon_s": record.horizon_s,
                "grace_s": self.grace_s,
                "traversal_id": record.traversal_id,
                "hop_distance": record.hop_distance,
                "path": list(record.path),
                "predicted_at": record.predicted_at.isoformat(),
                # D4 aperture family, vs the plan aperture: traversal
                # for impact-kind records, stated for recorded claims.
                "aperture": "traversal" if record.kind == "impact" else "stated",
            }
            if record.indicator is not None:
                evidence["indicator"] = record.indicator
            emissions.append(PredictionResidualProblem(
                id=f"pvm-{record.prediction_id}",
                entity_id=record.entity_id,
                entity_type="",
                problem_type=(
                    PREDICTION_RESIDUAL_TYPE if record.kind == "impact"
                    else f"prediction_residual:{record.kind}_missing"
                ),
                severity="warning" if record.probability >= _HIGH_PROBABILITY else "info",
                evidence=evidence,
                reason="predicted impact did not manifest in-window on an observed entity",
            ))
        return emissions

    # -- calibration ----------------------------------------------------------

    def calibration(self) -> Dict[str, Any]:
        """OutcomeFeedbackLoop-style summary over graded records."""
        confirmed = [r for r in self._records if r.verdict == GRADE_CONFIRMED]
        falsified = [r for r in self._records if r.verdict == GRADE_FALSIFIED]
        ungradeable = [r for r in self._records if r.verdict == GRADE_UNGRADEABLE]
        graded = confirmed + falsified
        # The mean confidence the graded records were FILED at. Computed here
        # because two keys below report it and neither may re-derive it.
        mean_stated = (sum(r.probability for r in graded) / len(graded)
                       if graded else None)
        brier = (
            sum((r.probability - (1.0 if r.verdict == GRADE_CONFIRMED else 0.0)) ** 2
                for r in graded) / len(graded)
        ) if graded else None
        by_kind: Dict[str, Dict[str, int]] = {}
        for r in self._records:
            bucket = by_kind.setdefault(r.kind, {
                "pending": 0, "confirmed": 0, "falsified": 0, "ungradeable": 0})
            bucket[r.verdict or "pending"] += 1
        return {
            "recorded": len(self._records),
            "pending": len(self.pending()),
            "evicted_pending": self.evicted_pending,
            "by_kind": by_kind,
            "confirmed": len(confirmed),
            "falsified": len(falsified),
            "ungradeable": len(ungradeable),
            "confirm_rate": (len(confirmed) / len(graded)) if graded else None,
            # HOW MANY EPISODES THOSE GRADED RECORDS CAME FROM.
            #
            # `confirm_rate` and `brier` read as one figure per trial, and a
            # rollout files one record per step of ONE trajectory: twelve
            # steps driven by one declared gain, confirmed or falsified
            # together. Measured, 12 confirmed and 0 falsified against a
            # mirror that never moved, and 0 and 12 against one that drifted.
            # A reader given `1.0 over 12 records` reads twelve successes.
            #
            # This is an UPPER BOUND on independence and not a claim of it:
            # two rollouts of one entity over overlapping horizons are two
            # episodes and still correlated. What it rules out is the case
            # that is purely an artefact of how the engine files -- one
            # trajectory counted as many. `None` rather than 0 when nothing
            # has been graded, on the same rule every other aggregate here
            # follows: a zero would read as a measurement.
            "episodes_n": (len({r.traversal_id for r in graded})
                           if graded else None),
            "mean_predicted_probability": mean_stated,
            # WHAT `confirm_rate` SHOULD BE, beside what it is.
            #
            # A value record is graded against a band the FILER chose, and
            # `record_value_prediction` states the confidence that band was
            # drawn at. So the hit rate has a target, and without it printed
            # beside it a rate of 1.0 reads as a perfect score when it is
            # evidence of a band wider than the one declared. Measured on one
            # reality, a spread ten times too wide scored 1.0 where an honest
            # one scored 0.95, and nothing in the report said which was right.
            #
            # It is the MEAN of the stated confidences rather than a constant,
            # because the ledger holds records from more than one filer and
            # they need not agree on how sure they were. No threshold is
            # attached and no remedy fires from it: this states the target and
            # the author weighs the distance, which is the rule the per-
            # coupling remedy already follows.
            # ONE NUMBER UNDER TWO NAMES, computed once and assigned twice
            # rather than written twice -- `mean_stated` above is the single
            # expression, because a figure spelled out in two places is a
            # figure that eventually disagrees with itself. The older name
            # describes the INPUT (what the filers said); this one names it as
            # the TARGET for the rate two lines up, which is the reading a
            # caller looking at `confirm_rate` has no reason to reach for.
            "expected_confirm_rate": mean_stated,
            "brier": brier,
            **self._distribution_calibration(),
            "own_projections": self._own_projection_calibration(),
        }

    def _own_projection_calibration(self) -> Dict[str, Any]:
        """The proper scores for forecasts THIS ENGINE made, kept apart.

        `_distribution_calibration` answers *which producer is worth
        keeping*, and its own docstring says a pooled score cannot answer it.
        So the engine's own projections are not poured into that figure --
        they are a different population answering a different question, which
        is whether the spreads declared in the model are honest. Mixing them
        would make `coverage_90` a number about nobody.

        THE STRATUM IS THE COUPLING, and it is the one a producer's record
        can never have. A value filed by a rollout names the declared
        transitions that drove it, so an author asking *which of my gains has
        a spread I should not trust* gets an answer per gain rather than one
        number for the model. `by_horizon` is kept for the same reason it
        exists next door: a model calibrated at a minute and useless at an
        hour is one figure describing neither.

        Every rate carries its denominator and every one is `None` rather than
        zero before anything is scored, on the rule the whole ledger follows.
        """
        scored = [r for r in self._records
                  if r.kind == "value" and r.scores is not None]
        if not scored:
            return {"n": 0, "pinball": None, "crps_approx": None,
                    "coverage_90": None, "expected_coverage_90": 0.9,
                    "by_coupling": {}, "by_horizon": {},
                    "unattributed_n": 0}

        def _aggregate(records: List[PredictionRecord]) -> Dict[str, Any]:
            n = len(records)
            return {
                "n": n,
                "pinball": round(
                    sum(r.scores["pinball_mean"] for r in records) / n, 9),
                "crps_approx": round(
                    sum(r.scores["crps_approx"] for r in records) / n, 9),
                "coverage_90": round(
                    sum(1 for r in records if r.scores["covered_90"]) / n, 6),
                "episodes_n": len({r.traversal_id for r in records}),
            }

        by_coupling: Dict[str, List[PredictionRecord]] = {}
        unattributed = 0
        for record in scored:
            drove = tuple(record.couplings or ())
            if not drove:
                # Counted, never claimed. The same shape the sibling leg uses
                # for a record that never stated its entity type.
                unattributed += 1
                continue
            # A value two couplings drove belongs to both: this is a
            # membership fact, not a partition, and the counts are per
            # coupling rather than summing to `n`.
            for coupling in drove:
                by_coupling.setdefault(str(coupling), []).append(record)

        by_horizon: Dict[str, List[PredictionRecord]] = {}
        for record in scored:
            by_horizon.setdefault(str(record.horizon_s), []).append(record)

        return {
            **_aggregate(scored),
            # WHAT THE COVERAGE SHOULD BE. `_REQUIRED_LEVELS` is the central
            # 90%, so a well-declared spread is missed one time in ten and a
            # coverage of 1.0 is the other failure -- the one the docstring of
            # `_grade_distribution_record` has always named and the one no
            # figure about this engine could previously show.
            "expected_coverage_90": 0.9,
            "by_coupling": {k: _aggregate(v) for k, v in by_coupling.items()},
            "by_horizon": {k: _aggregate(v) for k, v in by_horizon.items()},
            "unattributed_n": unattributed,
        }

    def _distribution_calibration(self) -> Dict[str, Any]:
        """Quantile scores over graded distribution records, and the strata.

        **Every figure here carries its own denominator.** ``coverage_90`` over
        four records and over four thousand are different statements, and a
        rate reported without the count it was computed from is the shape this
        engine's top-level envelope exists to refuse. So each aggregate is
        emitted beside its ``_n``, and every one of them is ``None`` -- not
        zero -- when nothing has been scored. A zero would read as "perfectly
        calibrated" for a model that has never been graded.

        The strata are ``by_model`` and ``by_horizon``, and they are the reason
        ``model_id`` is mandatory on a distribution record. A pooled score
        cannot answer the only question worth asking of a forecaster, which is
        whether THIS one is worth keeping; and a model that is well calibrated
        at an hour and useless at a day is a single number that describes
        neither. ``by_entity_type`` is the third the design named, and it is here on
        one condition: the caller STATED the type when it filed. The ledger
        still cannot derive it -- it holds an id and has never held a model,
        and reading a type out of an id's shape is the name-heuristic class
        this package has removed from three axioms. So the stratum covers the
        records that carry one, and ``entity_type_unattributed_n`` says how
        many it does not cover. A rate over an unstated subset is the shape
        this docstring's own second paragraph refuses.
        """
        scored = [r for r in self._records
                  if r.kind == "distribution" and r.scores is not None]
        if not scored:
            return {
                "pinball": None, "pinball_n": 0,
                "crps_approx": None, "crps_approx_n": 0,
                "coverage_90": None, "coverage_90_n": 0,
                "by_model": {}, "by_horizon": {}, "by_entity_type": {},
                "entity_type_unattributed_n": 0,
            }

        def _aggregate(records: List[PredictionRecord]) -> Dict[str, Any]:
            n = len(records)
            return {
                "n": n,
                "pinball": round(
                    sum(r.scores["pinball_mean"] for r in records) / n, 9),
                "crps_approx": round(
                    sum(r.scores["crps_approx"] for r in records) / n, 9),
                "coverage_90": round(
                    sum(1 for r in records if r.scores["covered_90"]) / n, 6),
            }

        by_model: Dict[str, Dict[str, Any]] = {}
        for record in scored:
            by_model.setdefault(str(record.model_id), []).append(record)
        by_horizon: Dict[str, Dict[str, Any]] = {}
        for record in scored:
            by_horizon.setdefault(f"{record.horizon_s:g}s", []).append(record)
        by_entity_type: Dict[str, List[PredictionRecord]] = {}
        unattributed = 0
        for record in scored:
            if record.entity_type:
                by_entity_type.setdefault(str(record.entity_type), []).append(record)
            else:
                unattributed += 1

        overall = _aggregate(scored)
        return {
            "pinball": overall["pinball"],
            "pinball_n": overall["n"],
            "crps_approx": overall["crps_approx"],
            "crps_approx_n": overall["n"],
            "coverage_90": overall["coverage_90"],
            "coverage_90_n": overall["n"],
            "by_model": {k: _aggregate(v) for k, v in by_model.items()},
            "by_horizon": {k: _aggregate(v) for k, v in by_horizon.items()},
            "by_entity_type": {k: _aggregate(v)
                               for k, v in by_entity_type.items()},
            # NOT folded into the stratum as a bucket. A key named for the
            # absence would collide the first time somebody declares an entity
            # type with that name, and the count belongs beside the figure it
            # qualifies rather than inside it.
            "entity_type_unattributed_n": unattributed,
        }


# -- gated module singleton (PlanOutcomeRecorder gate-off semantics) -----------

_LEDGER: Optional[PredictionLedger] = None


def get_prediction_ledger() -> PredictionLedger:
    global _LEDGER
    if _LEDGER is None:
        _LEDGER = PredictionLedger()
    return _LEDGER


def reset_prediction_ledger() -> None:
    """Test hook."""
    global _LEDGER
    _LEDGER = None


def record_traversal_impacts(
    impacts: Optional[Iterable[Any]],
    traversal_id: Optional[str] = None,
) -> List[str]:
    """Gated recording callsite: no-op while OFF —
    zero memory accumulation in disabled deployments."""
    if not predict_vs_mirror_enabled():
        return []
    return get_prediction_ledger().record_impacts(impacts, traversal_id=traversal_id)


def grade_prediction_ledger(
    problems: Sequence[Any],
    observed_entity_ids: Set[str],
    now: Optional[datetime] = None,
    histories: Optional[Iterable[Any]] = None,
) -> List[PredictionResidualProblem]:
    """Gated grading pass for the Core hook; returns falsified emissions
    ready to join the D2 gate's input batch. `histories` enables the
    value-kind aperture — without the mirror, value records
    stay pending."""
    if not predict_vs_mirror_enabled():
        return []
    return get_prediction_ledger().grade_matured(
        problems, observed_entity_ids, now=now, histories=histories)
