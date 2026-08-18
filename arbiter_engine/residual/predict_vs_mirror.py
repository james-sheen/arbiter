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

Gate-off semantics follow the PlanOutcomeRecorder precedent (the established pattern,
``DT_PREDICT_VS_MIRROR_ENABLED`` default OFF): the module-level singleton
record/grade paths are no-ops with zero memory accumulation; the
``PredictionLedger`` class itself is a pure library. Ring cap via
``DT_PREDICTION_LEDGER_RING_CAP`` (default 1000). Value-level predictions
(``ProjectedValue`` vs observed property) are the named v1 follow-up —
same ledger, ``kind="value"``.
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
    """The established pattern gate — default OFF."""
    return os.environ.get(
        "DT_PREDICT_VS_MIRROR_ENABLED", ""
    ).strip().lower() in ("1", "true", "yes")


@dataclass
class PredictionRecord:
    """One traversal-time prediction awaiting its mirror."""

    prediction_id: str
    traversal_id: str
    entity_id: str
    kind: str                       # "impact" (traversal) | "stated" (recorded claim); "value" reserved
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
            self._records.append(record)
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
        self._records.append(record)
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
    ) -> str:
        """ (value-kind v1): file a value prediction — entity E's
        property P will read ~V (+/- tolerance) at horizon H. Tolerance is
        caller-owned and mandatory: the ledger never guesses resolution."""
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
        )
        self._note_eviction()
        self._records.append(record)
        return record.prediction_id

    def record_projected_values(
        self,
        topology: Any,
        tolerance_map: Optional[Dict[str, float]] = None,
        default_tolerance: Optional[float] = None,
        traversal_id: Optional[str] = None,
        predicted_at: Optional[datetime] = None,
    ) -> Tuple[List[str], int]:
        """Callsite-ready bridge for `TwinNode.projected_values` — a dark
        schema field today (no producer constructs ProjectedValue yet);
        this files whatever appears there the day a producer lands.
        Properties without a caller-owned tolerance are SKIPPED and
        counted, never guessed. Returns (recorded_ids, skipped_count)."""
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

    def _grade_value_record(
        self,
        record: PredictionRecord,
        histories: Optional[Iterable[Any]],
        now: datetime,
    ) -> Optional[PredictionResidualProblem]:
        """value-kind grading — against the OBSERVATION stream,
        at maturity only (a value predicted AT horizon is not confirmable
        early), using the observation closest to the horizon. No
        observations in-window = the channel was silent = UNGRADEABLE
        (not-looking is not evidence). Without histories the record stays
        pending — the mirror is required to grade."""
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
            "mean_predicted_probability": (
                sum(r.probability for r in graded) / len(graded)) if graded else None,
            "brier": brier,
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
    """Gated recording callsite (the established pattern wire): no-op while OFF —
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
