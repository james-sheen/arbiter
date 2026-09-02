"""
Unified Axiom Reasoner - Layer 2 Detection.

The UnifiedAxiomReasoner orchestrates all axiom checkers and integrates
with the ontology to provide semantic problem detection.

Flow:
1. Load meta-ontology + domain ontology
2. For each entity, get health indicators from ontology
3. For each indicator, check relevant axioms
4. Return problems with full ontology context
"""

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from ..clock import as_naive_utc, now_utc
from ..interfaces import (
    AxiomChecker,
    DetectionResult,
    Entity,
    IndicatorSpec,
    OntologyReasonerInterface,
    Problem,
    RelationshipGraph,
    ObservationHistory,
    CheckOutcome,
)
from ..types import (
    Axiom, AxiomParameters, AxiomReadiness, AXIOM_MINIMUMS, DetectionLayer,
    Severity, NotEvaluated, NotEvaluatedReason,
)
# dedup uses Severity.priority_score (lower = more urgent; warning
# shares medium's rank) instead of a local "higher = more urgent"
# weight dict that diverged from it.
#
# this imported a constants module from the surrounding distribution
# — the engine's only module-level import reaching outside `detection/`, and
# enough on its own to make the package non-extractable. The originating
# package was named here verbatim until an internal ruling, which is how a comment
# recording a leak becomes the last copy of it: the build's stray scan matches
# import statements only, deliberately, so prose naming it passes every net.
# `detection.types.Severity` already carries
# `priority_score` and documents itself as mirroring the canonical one.
# Verified equal before switching, not assumed: identical members, and
# identical scores for all six (CRITICAL 1, HIGH 2, MEDIUM 3, WARNING 3,
# LOW 4, INFO 5). If the two ever diverge, this dedup silently changes which
# problem survives a merge — so `test_engine_standalone_import_cd1555.py`
# pins the parity rather than trusting the mirror comment.
_CanonicalSeverity = Severity
from .loader import OntologyLoader
from .axioms import (
    StabilityChecker,
    BoundednessChecker,
    ConnectivityChecker,
    ConsistencyChecker,
    ResponsivenessChecker,
    HomeostasisChecker,
    ConservationChecker,
    MonotonicityChecker,
)

logger = logging.getLogger(__name__)


def _record_fires(
    axiom: Axiom,
    entity: Entity,
    indicator: Optional[IndicatorSpec],
    problems: List[Problem],
) -> None:
    """count axiom fires at the dispatch boundary.

    An internal ruling decided all eight checkers should report fire counts; had
    wired a mixin into three of them, at each individual problem-creation
    site. Recording here instead of inside the checkers is deliberate:

    - **Uniform by construction.** Every checker reached through the
      dispatcher is counted. The mixin required an explicit call per problem
      site, so a checker could mix it in then not call it — a failure mode
      nothing could detect, and one that an internal ruling named while proposing a decorator.
      There are 34 problem-creation sites across the five previously-uncounted
      checkers; instrumenting each would have reproduced the hazard 34 times.
    - **One place to change.** Three call sites in this module rather than
      eight scattered across the checker package.

    Not counted here: the traverser's structural CONSERVATION path
    (`_check_flow_balance`), which never reaches this dispatcher. That is the
    undeclared path of, and v1 did not count it either — so this is a
    preserved gap, not a new one.

    Instrumentation must never break detection: any failure is swallowed with
    a debug line, per the bootstrap-aware shape used elsewhere in
    this method.
    """
    if not problems:
        return
    try:
        from ..fire_frequency import get_shared_tracker

        domain = (entity.metadata or {}).get('domain_id') if entity else None
        name = indicator.name if indicator is not None else None
        tracker = get_shared_tracker()
        for _ in problems:
            tracker.record_fire(axiom.value, domain, name)
    except Exception as exc:  # noqa: BLE001 — telemetry is never load-bearing
        logger.debug("fire counting skipped: %s", exc)


class UnifiedAxiomReasoner(OntologyReasonerInterface):
    """
    Domain-agnostic problem detection via ontological reasoning.

    The reasoner:
    1. Loads health ontologies (meta + domain)
    2. Maps entities to health indicators
    3. Checks all 6 axioms against indicators
    4. Returns problems with ontology context

    Performance target: 10-100ms per entity.
    """

    def __init__(
        self,
        meta_ontology_path: Optional[str] = None,
        domain_ontology_path: Optional[str] = None,
        params: Optional[AxiomParameters] = None,
        readiness_thresholds: Optional[Dict[str, int]] = None,
        family_registry: Optional[Any] = None,
        derived_engine: Optional[Any] = None,
        overlay: Optional[Any] = None,
    ):
        self.params = params or AxiomParameters()
        self.loader = OntologyLoader()
        # domain-configurable readiness thresholds (axiom_value -> min_obs)
        self._readiness_thresholds = readiness_thresholds or {}
        self._family_registry = family_registry
        self._derived_engine = derived_engine
        #: optional RuntimeYAMLOverlay threaded through to
        # axiom checkers. BoundednessChecker is the first integration
        # (first adjustment dimension). Sibling axiom checkers
        # gain overlay-awareness as later CDs land their thresholds.
        self.overlay = overlay
        self._consistency_rules: List[Dict[str, Any]] = []
        self._responsiveness_pairs: List[Dict[str, Any]] = []

        # Initialize axiom checkers. typed against the AxiomChecker
        # Protocol, so the contract this table relies on is declared rather
        # than inferred from the eight entries below.
        self._axiom_checkers: Dict[Axiom, AxiomChecker] = {
            Axiom.STABILITY: StabilityChecker(self.params),
            Axiom.BOUNDEDNESS: BoundednessChecker(self.params, overlay=overlay),
            Axiom.CONNECTIVITY: ConnectivityChecker(self.params),
            Axiom.CONSISTENCY: ConsistencyChecker(self.params),
            Axiom.RESPONSIVENESS: ResponsivenessChecker(self.params),
            Axiom.HOMEOSTASIS: HomeostasisChecker(self.params),
            Axiom.CONSERVATION: ConservationChecker(self.params),
            Axiom.MONOTONICITY: MonotonicityChecker(self.params),
        }

        # Load ontologies if provided
        if meta_ontology_path:
            self.loader.load_meta_ontology(meta_ontology_path)
        if domain_ontology_path:
            self.loader.load_domain_ontology(domain_ontology_path)

    def set_domain_rules(
        self,
        consistency_rules: Optional[List[Dict[str, Any]]] = None,
        responsiveness_pairs: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Set domain-specific rules loaded from domain YAML.

        Args:
            consistency_rules: Cross-entity invariant rules for CONSISTENCY axiom.
            responsiveness_pairs: I/O property pairs for RESPONSIVENESS axiom.
        """
        if consistency_rules is not None:
            self._consistency_rules = consistency_rules
        if responsiveness_pairs is not None:
            self._responsiveness_pairs = responsiveness_pairs

    def load_ontology(self, meta_path: str, domain_path: str) -> None:
        """Load meta-ontology and domain ontology."""
        self.loader.load_meta_ontology(meta_path)
        self.loader.load_domain_ontology(domain_path)

    def get_indicators(self, entity_type: str) -> List[IndicatorSpec]:
        """Get health indicators for an entity type (including derived)."""
        indicators = self.loader.get_indicators(entity_type)
        if self._derived_engine:
            indicators = list(indicators) + self._derived_engine.get_indicator_specs(entity_type)
        return indicators

    def get_layer(self) -> DetectionLayer:
        """Get the detection layer."""
        return DetectionLayer.ONTOLOGY

    def detect(
        self,
        entities: List[Entity],
        graph: RelationshipGraph,
        history: ObservationHistory
    ) -> DetectionResult:
        """
        Run ontology-based detection on entities.

        For each entity:
        1. Get health indicators from ontology
        2. For each indicator, check relevant axioms
        3. Collect and deduplicate problems
        """
        start_time = time.perf_counter()
        problems: List[Problem] = []
        warnings: List[Problem] = []
        not_evaluated: List[NotEvaluated] = []
        evaluations = 0

        # Log axiom readiness summary (once per run, not per entity)
        self._log_readiness_summary(entities, history)

        # built once per run, not per entity: CONNECTIVITY needs to
        # resolve edge targets and target types against what was actually
        # declared, and rebuilding this inside the loop would make an O(n)
        # check O(n^2) on the largest domain packs.
        entity_map: Mapping[str, Entity] = {e.id: e for e in entities}

        for entity in entities:
            entity_problems = self._detect_entity(
                entity, graph, history, entities=entity_map)
            # surface what this pass declined to evaluate.
            not_evaluated.extend(
                getattr(entity_problems, "not_evaluated", ()))
            evaluations += getattr(entity_problems, "evaluations_attempted", 0)
            for problem in entity_problems:
                if problem.severity.value in ('warning', 'info'):
                    warnings.append(problem)
                else:
                    problems.append(problem)

        # Cross-entity I/O pair RESPONSIVENESS checks
        io_problems = self._check_io_pairs(entities, history)
        # kept so a decline raised *inside* the pair loop (against a
        # real, discovered pair) would still reach the result. The pass's own
        # two guards deliberately stay silent; see `_check_io_pairs`.
        not_evaluated.extend(getattr(io_problems, "not_evaluated", ()))
        for problem in io_problems:
            if problem.severity.value in ('warning', 'info'):
                warnings.append(problem)
            else:
                problems.append(problem)

        duration_ms = (time.perf_counter() - start_time) * 1000

        return DetectionResult(
            problems=problems,
            warnings=warnings,
            layer=DetectionLayer.ONTOLOGY,
            entities_checked=len(entities),
            duration_ms=duration_ms,
            not_evaluated=not_evaluated,
            evaluations_attempted=evaluations,
        )

    def _log_readiness_summary(
        self,
        entities: List[Entity],
        history: ObservationHistory,
    ) -> None:
        """Log a compact readiness summary for axiom detection diagnostics."""
        # Limit to one log per 60 seconds to avoid spam
        now = time.perf_counter()
        if hasattr(self, '_last_readiness_log') and (now - self._last_readiness_log) < 60:
            return
        self._last_readiness_log = now

        # Collect per-entity readiness stats
        ready_count = 0
        total_indicators = 0
        sample_entity = None
        sample_obs = 0
        sample_required = 0

        for entity in entities:
            indicators = self.get_indicators(entity.type)
            if not indicators:
                continue
            for indicator in indicators:
                total_indicators += 1
                obs = history.get_observation_count(
                    entity.id, indicator.property_name
                )
                # Use lowest axiom threshold for this indicator.
                # was an inline copy of the minimums table whose
                # CONSERVATION (10) and MONOTONICITY (20) had drifted from the
                # derived floors (1 and 3), over-gating both by roughly an
                # order of magnitude. Single source now: types.AXIOM_MINIMUMS.
                required = min(
                    (self._readiness_thresholds.get(
                        a.value, AXIOM_MINIMUMS.get(a, 1))
                     for a in indicator.relevant_axioms),
                    default=1,
                )
                if obs >= required:
                    ready_count += 1
                if sample_entity is None or obs > sample_obs:
                    sample_entity = entity.id
                    sample_obs = obs
                    sample_required = required

        if total_indicators > 0:
            logger.info(
                f"Axiom readiness: {ready_count}/{total_indicators} indicators ready "
                f"across {len(entities)} entities. "
                f"Best: {sample_entity} obs={sample_obs}/{sample_required}"
            )
        elif entities:
            types = set(e.type for e in entities)
            logger.debug(
                f"Axiom detection: {len(entities)} entities, "
                f"0 indicators (types: {types})"
            )

    def _detect_entity(
        self,
        entity: Entity,
        graph: RelationshipGraph,
        history: ObservationHistory,
        *,
        entities: Optional[Mapping[str, Entity]] = None,
    ) -> List[Problem]:
        """Detect problems for a single entity.

        returns a :class:`CheckOutcome` — still a ``List[Problem]``
        for every existing caller, now also carrying what was declined.
        """
        problems = []
        not_evaluated: List[NotEvaluated] = []
        evaluations = 0

        # Compute derived properties before axiom checking (Level 1)
        if self._derived_engine:
            from ..interfaces import PropertyMetadata
            derived_values = self._derived_engine.compute(entity, history)
            for prop_name, value in derived_values.items():
                entity.properties[prop_name] = value
                entity.property_metadata[prop_name] = PropertyMetadata(
                    source="derived", confidence=0.95,
                )

        # Get indicators for this entity type
        indicators = self.get_indicators(entity.type)

        # Check each indicator against its relevant axioms
        for indicator in indicators:
            for axiom in indicator.relevant_axioms:
                indicator_problems = self.check_axiom(
                    axiom, entity, indicator, graph, history,
                    entities=entities,
                )
                problems.extend(indicator_problems)
                # `extend` keeps the problems and drops the
                # not-evaluated records, so collect them explicitly.
                not_evaluated.extend(
                    getattr(indicator_problems, "not_evaluated", ()))
                # the denominator for the envelope's "checked N
                # invariants". Counted at the dispatch, so it includes
                # evaluations that ran clean and found nothing.
                evaluations += 1

        # the raw-property walk used to run here, classifying every
        # entity property by word-token and applying count / percentage / ratio
        # rules to whatever the spelling matched. Removed.
        #
        # Not primarily because it read a name, though it did and the published
        # guide refuses that move. Because its findings had NO DENOMINATOR: they
        # ran outside the `relevant_axioms` loop above, so `checked.invariants`
        # never counted the cells they came from, and a consumer computing
        # attempted-minus-findings-minus-declines got a negative contribution
        # from checks the envelope never claimed to attempt.
        #
        # The rules it applied are DECLARABLE and now declared. Sized first, by
        # instrumenting the walk rather than grepping the packs: 31 property
        # keys reached it across six lanes, 11 produced a finding, and six of
        # those were real -- three on indicators that simply had not declared
        # CONSISTENCY, three on properties no pack declares at all.
        consistency_checker = self._axiom_checkers[Axiom.CONSISTENCY]
        if isinstance(consistency_checker, ConsistencyChecker):
            # Domain-configurable consistency rules
            if self._consistency_rules:
                domain_consistency = consistency_checker.check_domain_rules(
                    entity, self._consistency_rules
                )
                _record_fires(
                    Axiom.CONSISTENCY, entity, None, domain_consistency)
                problems.extend(domain_consistency)
                not_evaluated.extend(
                    getattr(domain_consistency, "not_evaluated", ()))

        # Also run comprehensive responsiveness checks (queue, throughput, domain extensions)
        responsiveness_checker = self._axiom_checkers[Axiom.RESPONSIVENESS]
        if isinstance(responsiveness_checker, ResponsivenessChecker):
            responsiveness_problems = responsiveness_checker.check_all(entity, history)
            _record_fires(
                Axiom.RESPONSIVENESS, entity, None, responsiveness_problems)
            problems.extend(responsiveness_problems)
            not_evaluated.extend(
                getattr(responsiveness_problems, "not_evaluated", ()))

        # Deduplicate problems from different axioms on same entity+property.
        # E.g., BOUNDEDNESS detects threshold_critical:cpuUsage and HOMEOSTASIS detects
        # homeostasis_anomaly:cpuUsage — merge into single problem with highest severity.
        problems = self._deduplicate_axiom_problems(problems)

        # Phase D: Attach diagnostic sequences from matching failure modes
        if self._family_registry:
            self._attach_diagnostics(entity, problems)

        # `_deduplicate_axiom_problems` returns a plain list, so the
        # outcome is rebuilt here rather than threaded through it.
        outcome = CheckOutcome(problems, not_evaluated)
        outcome.evaluations_attempted = evaluations  #
        return outcome

    @staticmethod
    def _severity_priority(severity) -> int:
        """Lower = more urgent. Mirrors ``Severity.priority_score``.

         follow-up: pre-fix the reasoner kept its own ``_SEVERITY_WEIGHT``
        dict that put ``WARNING=1, LOW=2`` (higher = more urgent) — backwards
        for WARNING, which canonically ranks at MEDIUM's level.
        Sourcing from the canonical enum ensures dedup ordering matches every
        other consumer.
        """
        sev_str = severity.value if hasattr(severity, 'value') else str(severity)
        try:
            return _CanonicalSeverity(sev_str).priority_score
        except ValueError:
            return 99

    @staticmethod
    def _merge_axiom_chain(winner: Problem, loser: Problem) -> str:
        """Build the ``additional_axioms`` string for the dedup winner.

        pre-fix when a higher-severity problem replaced an existing
        accumulator the new winner only inherited ``existing.evidence['axiom']``
        — any chain previously accumulated on existing was lost. This builder
        returns a comma-separated, deduplicated, sorted set covering every
        non-winning axiom that fired on the same (entity, indicator).
        """
        axioms = set()
        if winner.evidence.get('additional_axioms'):
            axioms.update(
                a for a in winner.evidence['additional_axioms'].split(',') if a
            )
        if loser.evidence.get('axiom'):
            axioms.add(loser.evidence['axiom'])
        if loser.evidence.get('additional_axioms'):
            axioms.update(
                a for a in loser.evidence['additional_axioms'].split(',') if a
            )
        # The winner's own axiom is recorded in ``axiom`` — don't duplicate it.
        axioms.discard(winner.evidence.get('axiom', ''))
        return ','.join(sorted(axioms))

    def _deduplicate_axiom_problems(self, problems: List[Problem]) -> List[Problem]:
        """Merge problems from different axioms on same entity+property.

        Winner is the strictly more urgent problem (lower priority_score);
        ties keep the existing entry. The ``additional_axioms`` evidence
        field on the winner records every other axiom that fired on the
        same (entity, indicator), preserving the chain across multi-way
        dedups.
        """
        if len(problems) <= 1:
            return problems

        seen = {}  # (entity_id, indicator_name) -> Problem
        for p in problems:
            indicator = p.evidence.get('indicator_name', p.evidence.get('property', ''))
            if not indicator:
                # No indicator key — keep as-is (e.g., consistency checks)
                seen[id(p)] = p
                continue
            key = (p.entity_id, indicator)
            if key not in seen:
                seen[key] = p
                continue

            existing = seen[key]
            new_score = self._severity_priority(p.severity)
            existing_score = self._severity_priority(existing.severity)
            # Lower priority_score wins; tie keeps existing.
            if new_score < existing_score:
                winner, loser = p, existing
            else:
                winner, loser = existing, p

            chain = self._merge_axiom_chain(winner, loser)
            if chain:
                winner.evidence['additional_axioms'] = chain
            seen[key] = winner
        return list(seen.values())

    def check_axiom(
        self,
        axiom: Axiom,
        entity: Entity,
        indicator: IndicatorSpec,
        graph: RelationshipGraph,
        history: ObservationHistory,
        *,
        entities: Optional[Mapping[str, Entity]] = None,
    ) -> List[Problem]:
        """Check a specific axiom for an entity/indicator.

        returns a :class:`CheckOutcome`, which is a ``List[Problem]``
        that additionally carries what was *not* evaluated. The two silent
        empty returns below — no registered checker, and a checker that raised
        — used to be indistinguishable from a clean pass.
        """
        checker = self._axiom_checkers.get(axiom)
        if not checker:
            logger.warning(f"No checker for axiom: {axiom}")
            return CheckOutcome().declined(
                axiom, entity, indicator.name,
                NotEvaluatedReason.NOT_APPLICABLE,
                detail=f"no checker registered for {axiom}",
            )

        try:
            # hand the entity registry to checkers that declare they
            # need it. CONNECTIVITY has to answer "does an entity of this type
            # exist" and "does this edge target resolve", and neither question
            # is answerable from `entity` and `graph` alone; it previously
            # approximated both by scanning edge-endpoint id strings for a
            # `<type>/` prefix, which passed on phantoms.
            if getattr(checker, "wants_entities", False):
                problems = checker.check(entity, indicator, graph, history,
                                         entities=entities)
            else:
                problems = checker.check(entity, indicator, graph, history)
            _record_fires(axiom, entity, indicator, problems)
            # (callsite) — emit axiom-verdict (axiom, entity)
            # at production-readiness shape. Verdict semantics: empty problems
            # → PASS, non-empty → FAIL (with max problem confidence as the
            # verdict confidence). `record_axiom_verdict` internally checks
            # DT_AXIOM_VERDICT_PRODUCTION_ENABLED gate; hybrid emit-policy fires
            # on verdict-transition OR confidence >= threshold. Defensive
            # try/except, bootstrap-aware.
            try:
                from arbiter_engine.ontology.axiom_verdicts_production import (
                    record_axiom_verdict,
                )
                if problems:
                    confidences = [
                        getattr(p, 'confidence', 0.0) or 0.0 for p in problems
                    ]
                    verdict_confidence = max(confidences) if confidences else 0.5
                    verdict = "FAIL"
                else:
                    verdict_confidence = 1.0
                    verdict = "PASS"
                record_axiom_verdict(
                    axiom_name=str(axiom.value if hasattr(axiom, 'value') else axiom),
                    entity_id=entity.id,
                    verdict=verdict,
                    confidence=float(verdict_confidence),
                )
            except Exception:  # noqa: BLE001 — defensive; substrate-unavailable
                pass
            # (callsite) — emit prediction at production-readiness
            # shape. Complementary to verdict callsite above: verdict
            # = PASS/FAIL/UNKNOWN (categorical); prediction = scalar severity
            # value + tier. PASS → prediction_severity=0.0 + LOW (routine);
            # FAIL → prediction_severity=max(problem.confidence) + severity tier
            # derived from max problem.severity. UNKNOWN path skipped (no emit
            # on uncertain prediction). `record_production_prediction` internally
            # checks DT_PRODUCTION_PREDICTION_ENABLED gate.
            try:
                if problems:
                    confidences = [
                        getattr(p, 'confidence', 0.0) or 0.0 for p in problems
                    ]
                    prediction_severity = max(confidences) if confidences else 0.5
                    # Severity tier: maximum problem severity name
                    severities = [
                        getattr(p, 'severity', None) for p in problems
                    ]
                    sev_names = [
                        getattr(s, 'name', str(s)) for s in severities if s is not None
                    ]
                    severity_tier = (
                        str(sev_names[0]).upper() if sev_names else "MEDIUM"
                    )
                else:
                    prediction_severity = 0.0
                    severity_tier = "LOW"
                record_production_prediction(
                    entity_id=entity.id,
                    axiom_engine=str(axiom.value if hasattr(axiom, 'value') else axiom),
                    prediction_severity=float(prediction_severity),
                    severity=severity_tier,
                )
            except Exception:  # noqa: BLE001 — defensive
                pass
            # preserve any not-evaluated records the checker
            # attached. `getattr` rather than isinstance because a checker
            # returning a plain list is still legal per the Protocol, so
            # adoption can be incremental.
            return CheckOutcome(
                problems, getattr(problems, "not_evaluated", ()))
        except Exception as e:
            logger.error(f"Error checking {axiom} for {entity.id}: {e}")
            # also emit UNKNOWN verdict on checker exception
            try:
                from arbiter_engine.ontology.axiom_verdicts_production import (
                    record_axiom_verdict,
                )
                record_axiom_verdict(
                    axiom_name=str(axiom.value if hasattr(axiom, 'value') else axiom),
                    entity_id=entity.id,
                    verdict="UNKNOWN",
                    confidence=0.0,
                )
            except Exception:  # noqa: BLE001
                pass
            # a checker that raised is NOT a clean pass. The
            # exception stays swallowed (one broken checker must not take down
            # a detection pass), but it is now reported rather than erased.
            return CheckOutcome().declined(
                axiom, entity, indicator.name,
                NotEvaluatedReason.CHECKER_ERROR,
                detail=f"{type(e).__name__}: {e}",
            )

    def get_axiom_readiness(
        self,
        entity: Entity,
        history: ObservationHistory
    ) -> Dict[Axiom, AxiomReadiness]:
        """
        Get axiom readiness for an entity.

        Returns readiness status for each axiom based on available history.
        """
        readiness = {}
        indicators = self.get_indicators(entity.type)

        # second inline copy of the same table, removed. Both copies
        # carried CONSERVATION 10 / MONOTONICITY 20 against the derived 1 / 3.
        default_min_observations = AXIOM_MINIMUMS

        for axiom in Axiom:
            # Get max observation count across all indicators for this axiom
            max_observations = 0
            for indicator in indicators:
                if axiom in indicator.relevant_axioms:
                    count = history.get_observation_count(entity.id, indicator.property_name)
                    max_observations = max(max_observations, count)

            # use domain-configurable thresholds, fall back to defaults
            required = self._readiness_thresholds.get(
                axiom.value, default_min_observations.get(axiom, 1)
            )
            is_ready = max_observations >= required
            ratio = min(1.0, max_observations / required) if required > 0 else 1.0

            readiness[axiom] = AxiomReadiness(
                axiom=axiom,
                entity_id=entity.id,
                entity_type=entity.type,
                observations_count=max_observations,
                required_count=required,
                is_ready=is_ready,
                readiness_ratio=ratio,
            )

        return readiness

    def get_all_entity_readiness(
        self,
        entities: List[Entity],
        history: ObservationHistory
    ) -> Dict[str, Dict[Axiom, AxiomReadiness]]:
        """Get axiom readiness for all entities."""
        return {
            entity.id: self.get_axiom_readiness(entity, history)
            for entity in entities
        }

    def set_io_relationships(self, io_relationships):
        """Set I/O relationships for RESPONSIVENESS checker."""
        responsiveness_checker = self._axiom_checkers.get(Axiom.RESPONSIVENESS)
        if hasattr(responsiveness_checker, 'set_io_relationships'):
            responsiveness_checker.set_io_relationships(io_relationships)

    def _check_io_pairs(
        self, entities: List[Entity], history: ObservationHistory
    ) -> List[Problem]:
        """Run cross-entity I/O pair RESPONSIVENESS checks.

        Iterates over discovered IO relationships and checks each matching
        entity pair for correlation breakdown, latency spikes, and missing
        responses.
        """
        # these two bare returns were instrumented as declines and the
        # instrumentation was then REVERTED. The channel is a *declaration
        # deficit* channel: every record answers "you declared this axiom and I
        # did not evaluate it". This pass is called unconditionally from
        # `detect` and is gated by no declaration at all — it runs opportunis-
        # tically when IO relationships happen to have been discovered. A record
        # here reports the absence of a capability nobody asked for, fires on
        # every pass in every domain without IO discovery, and makes
        # `Envelope.is_fully_evaluated` structurally unreachable. A field that
        # can never be True is worse than no field. Leave these silent.
        responsiveness_checker = self._axiom_checkers.get(Axiom.RESPONSIVENESS)
        if not isinstance(responsiveness_checker, ResponsivenessChecker):
            return []
        if not responsiveness_checker.io_relationships:
            return []

        entity_map = {e.id: e for e in entities}
        problems = []

        for io_rel in responsiveness_checker.io_relationships:
            # IO relationships may use entity IDs or entity types depending on source
            input_eid = getattr(io_rel, 'input_entity_id', None)
            output_eid = getattr(io_rel, 'output_entity_id', None)

            if input_eid and output_eid:
                # Direct entity ID match (from IODiscovery)
                input_entity = entity_map.get(input_eid)
                output_entity = entity_map.get(output_eid)
                if input_entity and output_entity:
                    pair_problems = responsiveness_checker.check_io_pair(
                        input_entity, output_entity, io_rel, history,
                    )
                    problems.extend(pair_problems)
            else:
                # Type-based match (from types.IORelationship)
                input_type = getattr(io_rel, 'input_entity_type', None)
                output_type = getattr(io_rel, 'output_entity_type', None)
                if not input_type or not output_type:
                    continue
                inputs = [e for e in entities if e.type == input_type]
                outputs = [e for e in entities if e.type == output_type]
                for inp in inputs:
                    for out in outputs:
                        if inp.id != out.id:
                            pair_problems = responsiveness_checker.check_io_pair(
                                inp, out, io_rel, history,
                            )
                            problems.extend(pair_problems)

        return problems

    def get_statistics(self) -> Dict:
        """Get statistics about the reasoner."""
        return {
            'meta_ontology_loaded': self.loader.meta_loaded,
            'domain_ontology_loaded': self.loader.domain_loaded,
            'indicator_cache_size': len(self.loader._indicator_cache),
            'axiom_checkers': list(self._axiom_checkers.keys()),
        }

    def _attach_diagnostics(
        self, entity: Entity, problems: List[Problem]
    ) -> None:
        """Attach diagnostic sequences from matching failure modes to problems."""
        if not problems:
            return
        type_def = self._find_type_def(entity)
        if not type_def:
            return
        for problem in problems:
            if not problem.axiom:
                continue
            matching = type_def.get_failure_modes_for_axiom(problem.axiom)
            best = self._best_failure_mode_match(problem, matching)
            if best and best.diagnostic_sequence:
                problem.diagnostic_sequence = [
                    {
                        'check': s.check,
                        'requires': s.requires,
                        'rules_out': s.rules_out,
                        'action_if_confirmed': s.action_if_confirmed,
                    }
                    for s in best.diagnostic_sequence
                ]
                if best.action_constraints:
                    problem.action_constraints = list(best.action_constraints)

    def _find_type_def(self, entity: Entity):
        """Find TypeDefinition for an entity across all registered families."""
        for family in self._family_registry.get_all_families().values():
            td = family.get_type(entity.type)
            if td:
                return td
            # Fallback: classify by properties
            props = getattr(entity, 'properties', None) or {}
            if props:
                type_name, confidence = family.classify(props)
                if confidence > 0.5:
                    td = family.get_type(type_name)
                    if td:
                        return td
        return None

    @staticmethod
    def _best_failure_mode_match(problem: Problem, failure_modes: list):
        """Find the best FailureMode match for a problem."""
        if not failure_modes:
            return None
        indicator = problem.evidence.get('indicator_name', '')
        for fm in failure_modes:
            if fm.constraint_ref and fm.constraint_ref in indicator:
                return fm
            if fm.constraint_ref and fm.constraint_ref in problem.problem_type:
                return fm
        return failure_modes[0]


# ============================================================
# ProductionPrediction production-readiness
# substrate sibling, on the sibling-within-existing-module shape.
#
# 5-field frozen dataclass + 5 public functions + the default-off env-gates
# DT_PRODUCTION_PREDICTION_ENABLED and DT_PRODUCTION_PREDICTION_SEVERITY_FLOOR
# + ring-cap eviction. Foundation UnifiedAxiomReasoner class above preserved
# unchanged, per the in-place extension discipline.
#
# Hybrid default-on emit-policy decision (15-precedent
# uniform-knob discipline; the axis-closure shape).
#
# Domain-agnostic: entity_id + axiom_engine + prediction_severity scalars
# opaque; no per-domain dispatch. Composes emit-policy decision +
# attestation severity floor + the NaturalCategoryDispatcher
# (severity axis = 1 of 8 canonical axes; no new axis). EU AI Act
# Article 16 (risk-management system requires prediction-attestation on
# every AI prediction) + SOC2 audit-trail completeness compliance addressed
# via per-prediction audit-trail substrate.
# ============================================================

import os as _os_cd1213
import threading as _threading_cd1213
from dataclasses import dataclass as _dataclass_cd1213
from datetime import datetime as _datetime_cd1213
from typing import Dict as _Dict_cd1213, List as _List_cd1213, Tuple as _Tuple_cd1213


def _env_bool_cd1213(name: str, default: bool = False) -> bool:
    raw = _os_cd1213.environ.get(name, "1" if default else "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


DT_PRODUCTION_PREDICTION_ENABLED: bool = _env_bool_cd1213(
    "DT_PRODUCTION_PREDICTION_ENABLED", default=False
)
DT_PRODUCTION_PREDICTION_RING_CAP: int = int(
    _os_cd1213.environ.get("DT_PRODUCTION_PREDICTION_RING_CAP", "10000")
)

# Per decision — a default-off env-gate (3-value enum)
PRODUCTION_PREDICTION_EMIT_POLICY_HYBRID: str = "hybrid"
PRODUCTION_PREDICTION_EMIT_POLICY_FULL_EMIT: str = "full_emit"
PRODUCTION_PREDICTION_EMIT_POLICY_SUPPRESSED: str = "suppressed"
KNOWN_PRODUCTION_PREDICTION_EMIT_POLICIES = frozenset([
    PRODUCTION_PREDICTION_EMIT_POLICY_HYBRID,
    PRODUCTION_PREDICTION_EMIT_POLICY_FULL_EMIT,
    PRODUCTION_PREDICTION_EMIT_POLICY_SUPPRESSED,
])
DEFAULT_PRODUCTION_PREDICTION_EMIT_POLICY: str = (
    PRODUCTION_PREDICTION_EMIT_POLICY_HYBRID
)

# Per decision — a default-off env-gate
# (CENTENARY MILESTONE — 4-value enum)
PRODUCTION_PREDICTION_SEVERITY_LOW: str = "LOW"
PRODUCTION_PREDICTION_SEVERITY_MEDIUM: str = "MEDIUM"
PRODUCTION_PREDICTION_SEVERITY_HIGH: str = "HIGH"
PRODUCTION_PREDICTION_SEVERITY_CRITICAL: str = "CRITICAL"
KNOWN_PRODUCTION_PREDICTION_SEVERITY_FLOORS = frozenset([
    PRODUCTION_PREDICTION_SEVERITY_LOW,
    PRODUCTION_PREDICTION_SEVERITY_MEDIUM,
    PRODUCTION_PREDICTION_SEVERITY_HIGH,
    PRODUCTION_PREDICTION_SEVERITY_CRITICAL,
])
DEFAULT_PRODUCTION_PREDICTION_SEVERITY_FLOOR: str = (
    PRODUCTION_PREDICTION_SEVERITY_MEDIUM
)

_SEVERITY_RANK_CD1213: _Dict_cd1213[str, int] = {
    PRODUCTION_PREDICTION_SEVERITY_LOW: 1,
    PRODUCTION_PREDICTION_SEVERITY_MEDIUM: 2,
    PRODUCTION_PREDICTION_SEVERITY_HIGH: 3,
    PRODUCTION_PREDICTION_SEVERITY_CRITICAL: 4,
}

DT_PRODUCTION_PREDICTION_SEVERITY_FLOOR: str = _os_cd1213.environ.get(
    "DT_PRODUCTION_PREDICTION_SEVERITY_FLOOR",
    DEFAULT_PRODUCTION_PREDICTION_SEVERITY_FLOOR,
).upper()
if DT_PRODUCTION_PREDICTION_SEVERITY_FLOOR not in KNOWN_PRODUCTION_PREDICTION_SEVERITY_FLOORS:
    DT_PRODUCTION_PREDICTION_SEVERITY_FLOOR = DEFAULT_PRODUCTION_PREDICTION_SEVERITY_FLOOR


@_dataclass_cd1213(frozen=True)
class ProductionPrediction:
    """ per-(entity, axiom_engine) production-readiness prediction event.

    5 opaque fields domain-agnostic invariant. Frozen for
    audit-trail provenance emit-policy decision.

    Mirrors ProductionFeedback 5-field shape: KEY (entity_id +
    axiom_engine composite key) + METRIC (prediction_severity) + TIMESTAMP
    (observed_at) + PROVENANCE (emit_policy_per_cd1212).
    """

    entity_id: str
    axiom_engine: str
    prediction_severity: float
    observed_at: _datetime_cd1213
    emit_policy_per_cd1212: str
    cluster_id: Optional[str] = None  # (Bucket A) per-axis cluster-scope


def resolve_production_prediction_emit_policy(value):  # noqa: ANN001
    """Safe-default to hybrid."""
    if value is None or value not in KNOWN_PRODUCTION_PREDICTION_EMIT_POLICIES:
        return DEFAULT_PRODUCTION_PREDICTION_EMIT_POLICY
    return value


def resolve_production_prediction_severity_floor(value):  # noqa: ANN001
    """Safe-default to MEDIUM."""
    if value is None:
        return DEFAULT_PRODUCTION_PREDICTION_SEVERITY_FLOOR
    v = value.upper()
    if v not in KNOWN_PRODUCTION_PREDICTION_SEVERITY_FLOORS:
        return DEFAULT_PRODUCTION_PREDICTION_SEVERITY_FLOOR
    return v


def _severity_at_or_above_floor_cd1213(severity: str, floor: str) -> bool:
    s = resolve_production_prediction_severity_floor(severity)
    f = resolve_production_prediction_severity_floor(floor)
    return _SEVERITY_RANK_CD1213[s] >= _SEVERITY_RANK_CD1213[f]


_PRODUCTION_PREDICTIONS: _List_cd1213["ProductionPrediction"] = []
_PRODUCTION_PREDICTION_LOCK = _threading_cd1213.RLock()
_PRODUCTION_PREDICTION_LAST_SEVERITY: _Dict_cd1213[_Tuple_cd1213[str, str], float] = {}


def record_production_prediction(
    entity_id: str,
    axiom_engine: str,
    prediction_severity: float,
    severity: str = PRODUCTION_PREDICTION_SEVERITY_MEDIUM,
    observed_at=None,
    emit_policy=None,
    cluster_id: Optional[str] = None,
):
    """Record a prediction event at production-readiness shape.

    optional ``cluster_id`` stamps the record
    for per-axis cluster-scope filtering. Additive, None default; the
    emission callsites have no cluster in scope and pass None (the param
    exists for any cluster-aware caller).

    Returns the stored ProductionPrediction when gate enabled AND
    emit_policy admits the event; returns None when gate off OR
    emit_policy suppressed OR hybrid mode rejects per severity-floor
    gate (severity < DT_PRODUCTION_PREDICTION_SEVERITY_FLOOR).

    Hybrid mode gate (decision): admits if severity is
    at-or-above the configured severity-floor.
    """
    if not DT_PRODUCTION_PREDICTION_ENABLED:
        return None
    policy = resolve_production_prediction_emit_policy(emit_policy)
    if policy == PRODUCTION_PREDICTION_EMIT_POLICY_SUPPRESSED:
        return None
    ts = as_naive_utc(observed_at) if observed_at else now_utc()
    if policy == PRODUCTION_PREDICTION_EMIT_POLICY_HYBRID:
        if not _severity_at_or_above_floor_cd1213(
            severity, DT_PRODUCTION_PREDICTION_SEVERITY_FLOOR
        ):
            return None
    record = ProductionPrediction(
        entity_id=entity_id,
        axiom_engine=axiom_engine,
        prediction_severity=float(prediction_severity),
        observed_at=ts,
        emit_policy_per_cd1212=policy,
        cluster_id=cluster_id,  # (Bucket A)
    )
    with _PRODUCTION_PREDICTION_LOCK:
        _PRODUCTION_PREDICTIONS.append(record)
        _PRODUCTION_PREDICTION_LAST_SEVERITY[(entity_id, axiom_engine)] = (
            float(prediction_severity)
        )
        if len(_PRODUCTION_PREDICTIONS) > DT_PRODUCTION_PREDICTION_RING_CAP:
            del _PRODUCTION_PREDICTIONS[
                : len(_PRODUCTION_PREDICTIONS) - DT_PRODUCTION_PREDICTION_RING_CAP
            ]
    return record


def _filter_by_cluster_id_cd1436(predictions, cluster_id: Optional[str]):
    """ helper: filter predictions by cluster_id when non-None.

    cluster_id=None returns the full list (backward compat). cluster_id="X"
    returns only predictions with ``p.cluster_id == "X"``. Records emitted
    previously carry cluster_id=None and are excluded from a specific-
    cluster query. Mirror of the RCA / axiom_verdicts
    pattern.
    """
    if cluster_id is None:
        return list(predictions)
    return [p for p in predictions if p.cluster_id == cluster_id]


def get_production_predictions(cluster_id: Optional[str] = None):
    """All recorded production prediction records. Empty when gate off.

    optional ``cluster_id`` filter. None = all (backward compat);
    string value returns only predictions stamped with that cluster_id.
    """
    if not DT_PRODUCTION_PREDICTION_ENABLED:
        return []
    with _PRODUCTION_PREDICTION_LOCK:
        return _filter_by_cluster_id_cd1436(_PRODUCTION_PREDICTIONS, cluster_id)


def get_production_prediction_count(cluster_id: Optional[str] = None) -> int:
    """Aggregate count of recorded production prediction records.

    Dashboard-data defensive-accessor entry point. Returns 0 when gate off.

    optional ``cluster_id`` filter. None = aggregate count;
    string value returns count of predictions stamped with that cluster_id.
    """
    if not DT_PRODUCTION_PREDICTION_ENABLED:
        return 0
    with _PRODUCTION_PREDICTION_LOCK:
        return len(_filter_by_cluster_id_cd1436(_PRODUCTION_PREDICTIONS, cluster_id))


def get_severity_for_entity_prediction(entity_id: str, axiom_engine: str):
    """Last-known prediction_severity for (entity, axiom_engine); None when unknown or gate off."""
    if not DT_PRODUCTION_PREDICTION_ENABLED:
        return None
    with _PRODUCTION_PREDICTION_LOCK:
        return _PRODUCTION_PREDICTION_LAST_SEVERITY.get((entity_id, axiom_engine))


def known_production_predictions():
    """Diagnostic accessor — sorted unique (entity_id, axiom_engine) pairs."""
    if not DT_PRODUCTION_PREDICTION_ENABLED:
        return []
    with _PRODUCTION_PREDICTION_LOCK:
        return sorted({(r.entity_id, r.axiom_engine) for r in _PRODUCTION_PREDICTIONS})


def _reset_production_prediction_for_tests() -> None:
    with _PRODUCTION_PREDICTION_LOCK:
        _PRODUCTION_PREDICTIONS.clear()
        _PRODUCTION_PREDICTION_LAST_SEVERITY.clear()
