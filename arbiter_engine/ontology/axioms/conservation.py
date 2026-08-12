"""
CONSERVATION Axiom Checker.

CONSERVATION: Quantities preserved through transformations.

Detects:
- Input/output imbalance (requests lost, current leaking)
- Flow conservation violations
- Unaccounted losses

Mathematical formula:
    |Σ(inputs) - Σ(outputs) - Σ(accounted_losses)| > margin × Σ(inputs)

Parameters:
- loss_margin = 0.05: 5% acceptable loss
- window_seconds = 300: 5-minute accounting window
- min_samples = 10: Minimum samples for meaningful accounting
"""

import logging
from datetime import timedelta
from typing import List, Optional

from ...interfaces import (
    Entity,
    Problem,
    RelationshipGraph,
    ObservationHistory,
    IndicatorSpec,
    apply_property_confidence,
    CheckOutcome,
)
from ...types import (
    Axiom, Severity, AxiomParameters, DetectionLayer, NotEvaluatedReason,
)
# — resolve_axiom_threshold at conservation_loss_margin
# read-sites (firing-gate threshold). 3-tier precedence: sentinel >
# indicator.conservation_config > global params. window_seconds + min_samples
# preserved as global params (sample-window / sample-count, not calibration).
from ...axiom_thresholds import (
    resolve_axiom_threshold,
)

logger = logging.getLogger(__name__)


class ConservationChecker:
    """
    Check CONSERVATION axiom for entities.

    CONSERVATION requires historical data to accumulate input/output sums.
    Minimum observations: 10
    """

    def __init__(self, params: Optional[AxiomParameters] = None):
        self.params = params or AxiomParameters()

    def check(
        self,
        entity: Entity,
        indicator: IndicatorSpec,
        graph: RelationshipGraph,
        history: ObservationHistory
    ) -> List[Problem]:
        """
        Check CONSERVATION for an entity/indicator.

        Uses indicator config to identify input/output property pairs.
        The indicator should have conservation metadata:
          - input_property: property name for input accumulator
          - output_properties: list of property names for outputs
          - loss_margin: acceptable loss (overrides default)
        """
        problems = []

        if indicator.indicator_type.value != 'numeric':
            return CheckOutcome(problems).declined(
                Axiom.CONSERVATION, entity, indicator.name,
                NotEvaluatedReason.WRONG_INDICATOR_TYPE,
                detail=(
                    f"CONSERVATION evaluates numeric indicators; this one is "
                    f"{indicator.indicator_type.value}"),
            )

        conservation_config = getattr(indicator, 'conservation_config', None)
        if not conservation_config:
            result = self._check_simple_conservation(entity, indicator, history)
            confirmed = apply_property_confidence(
                entity, indicator.property_name, result)
            # the helper seam. `_check_simple_conservation` returns a
            # CheckOutcome carrying its decline, but `apply_property_confidence`
            # returns a plain list, so the records were dropped here. Same shape
            # in STABILITY: a decline inside a helper is lost the moment the
            # caller passes it through anything list-shaped.
            return CheckOutcome(
                confirmed, getattr(result, "not_evaluated", ()))

        input_prop = conservation_config.get('input_property')
        output_props = conservation_config.get('output_properties', [])
        # 3-tier precedence: sentinel > conservation_config >
        # global params. Pre-existing indicator-config override preserved as
        # the resolver's fallback arg.
        margin_fallback = conservation_config.get(
            'loss_margin', self.params.conservation_loss_margin
        )
        margin = resolve_axiom_threshold(
            entity, indicator.property_name, "CONSERVATION",
            fallback=margin_fallback,
            bound="warn",
        )

        if not input_prop or not output_props:
            return problems

        window = timedelta(seconds=self.params.conservation_window_seconds)

        input_values = history.get_values(entity.id, input_prop, window)
        # the gate stays a tunable param (kept it global on
        # purpose); what was wrong was its DEFAULT. It sat at 10 while the
        # derived floor is 1, re-imposing one layer down the over-gate
        # removed from the reasoner: readiness reported the axiom evaluable and
        # the checker returned before evaluating anything.
        if len(input_values) < self.params.conservation_min_samples:
            # same shape as MONOTONICITY above: corrected
            # this default from 10 to the derived floor of 1 after it had been
            # silently suppressing evaluation.
            return CheckOutcome(problems).declined(
                Axiom.CONSERVATION, entity, indicator.name,
                NotEvaluatedReason.INSUFFICIENT_SAMPLES,
                detail=f"no observations of input property {input_prop}",
                observations_count=len(input_values),
                required_count=self.params.conservation_min_samples,
            )

        total_input = sum(v[1] for v in input_values if v[1] is not None)
        if total_input <= 0:
            return problems

        total_output = 0.0
        for out_prop in output_props:
            out_values = history.get_values(entity.id, out_prop, window)
            total_output += sum(v[1] for v in out_values if v[1] is not None)

        deficit = total_input - total_output
        deficit_ratio = abs(deficit) / total_input if total_input > 0 else 0

        if deficit_ratio > margin:
            severity = Severity.HIGH if deficit_ratio > margin * 3 else Severity.MEDIUM
            problems.append(Problem.from_entity(
                entity=entity,
                problem_type=f'conservation_violation:{indicator.name}',
                severity=severity,
                reason=f"{indicator.name}: input/output imbalance ({deficit_ratio*100:.1f}% deficit)",
                axiom=Axiom.CONSERVATION,
                source_layer=DetectionLayer.ONTOLOGY,
                evidence={
                    'indicator': indicator.name,
                    'total_input': total_input,
                    'total_output': total_output,
                    'deficit': deficit,
                    'deficit_ratio': deficit_ratio,
                    'margin': margin,
                    'window_seconds': self.params.conservation_window_seconds,
                    'samples': len(input_values),
                },
                confidence=min(1.0, deficit_ratio / margin),
            ))

        return apply_property_confidence(entity, indicator.property_name, problems)

    def _check_simple_conservation(
        self,
        entity: Entity,
        indicator: IndicatorSpec,
        history: ObservationHistory,
    ) -> List[Problem]:
        """
        Simple conservation check: look for paired properties.

        If indicator name contains 'in' or 'received', look for
        a corresponding 'out' or 'sent' property and check balance.
        """
        problems = []

        prop = indicator.property_name
        if not prop:
            return CheckOutcome(problems).declined(
                Axiom.CONSERVATION, entity, indicator.name,
                NotEvaluatedReason.MISSING_PROPERTY,
                detail="the indicator declares no property_name",
            )

        in_markers = ['_in', '_received', '_requests', 'input_']
        out_suffixes = {
            '_in': '_out', '_received': '_sent',
            '_requests': '_responses', 'input_': 'output_',
        }

        matched_marker = None
        for marker in in_markers:
            if marker in prop:
                matched_marker = marker
                break

        if not matched_marker:
            # the terminus of the YAML-declared CONSERVATION path.
            # With no `conservation:` block the checker falls back to guessing
            # a paired property by name, and an indicator whose name carries
            # none of the markers evaluates nothing at all. That is the common
            # case, not the edge one — added the config block precisely
            # so a domain need not rely on this.
            return CheckOutcome(problems).declined(
                Axiom.CONSERVATION, entity, indicator.name,
                NotEvaluatedReason.MISSING_CONFIG,
                detail=(
                    "no conservation config, and the property name carries "
                    "none of the flow markers (_in, _received, _requests, "
                    "input_) the fallback matches on"),
            )

        out_prop = prop.replace(matched_marker, out_suffixes[matched_marker])
        window = timedelta(seconds=self.params.conservation_window_seconds)

        in_values = history.get_values(entity.id, prop, window)
        out_values = history.get_values(entity.id, out_prop, window)

        if (len(in_values) < self.params.conservation_min_samples or
                len(out_values) < self.params.conservation_min_samples):
            return problems

        total_in = sum(v[1] for v in in_values if v[1] is not None)
        total_out = sum(v[1] for v in out_values if v[1] is not None)

        if total_in <= 0:
            return problems

        deficit_ratio = abs(total_in - total_out) / total_in
        # simple-conservation path: no indicator-config layer, so
        # precedence is just sentinel > global params.
        margin = resolve_axiom_threshold(
            entity, indicator.property_name, "CONSERVATION",
            fallback=self.params.conservation_loss_margin,
            bound="warn",
        )

        if deficit_ratio > margin:
            problems.append(Problem.from_entity(
                entity=entity,
                problem_type=f'conservation_violation:{indicator.name}',
                severity=Severity.MEDIUM,
                reason=f"{prop} vs {out_prop}: {deficit_ratio*100:.1f}% imbalance",
                axiom=Axiom.CONSERVATION,
                source_layer=DetectionLayer.ONTOLOGY,
                evidence={
                    'indicator': indicator.name,
                    'input_property': prop,
                    'output_property': out_prop,
                    'total_input': total_in,
                    'total_output': total_out,
                    'deficit_ratio': deficit_ratio,
                    'margin': margin,
                },
                confidence=min(1.0, deficit_ratio / margin),
            ))

        return problems
