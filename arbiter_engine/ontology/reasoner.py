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


# The production-prediction substrate lives in `prediction_production` since
# 2026-09-02. It is re-exported here because two callers reach it through this
# module by dotted path, and because the import is what keeps the new module
# reachable from the curated exports rather than stranded beside them.
#
# THE FACADE IS COMPLETE ON PURPOSE, private test helper included. A partial one
# fails on whichever name a caller happens to want, which is how the first
# version of this move broke a suite that never imported anything public.
from .prediction_production import (  # noqa: E402,F401
    DEFAULT_PRODUCTION_PREDICTION_EMIT_POLICY,
    DEFAULT_PRODUCTION_PREDICTION_SEVERITY_FLOOR,
    DT_PRODUCTION_PREDICTION_ENABLED,
    DT_PRODUCTION_PREDICTION_RING_CAP,
    DT_PRODUCTION_PREDICTION_SEVERITY_FLOOR,
    KNOWN_PRODUCTION_PREDICTION_EMIT_POLICIES,
    KNOWN_PRODUCTION_PREDICTION_SEVERITY_FLOORS,
    PRODUCTION_PREDICTION_EMIT_POLICY_FULL_EMIT,
    PRODUCTION_PREDICTION_EMIT_POLICY_HYBRID,
    PRODUCTION_PREDICTION_EMIT_POLICY_SUPPRESSED,
    PRODUCTION_PREDICTION_SEVERITY_CRITICAL,
    PRODUCTION_PREDICTION_SEVERITY_HIGH,
    PRODUCTION_PREDICTION_SEVERITY_LOW,
    PRODUCTION_PREDICTION_SEVERITY_MEDIUM,
    ProductionPrediction,
    _reset_production_prediction_for_tests,
    get_production_prediction_count,
    get_production_predictions,
    get_severity_for_entity_prediction,
    known_production_predictions,
    record_production_prediction,
    resolve_production_prediction_emit_policy,
    resolve_production_prediction_severity_floor,
)
