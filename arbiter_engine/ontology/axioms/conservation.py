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
            result = self._check_undeclared_conservation(
                entity, indicator, history)
            confirmed = apply_property_confidence(
                entity, indicator.property_name, result)
            # the helper seam. The helper returns a
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

        # reported from outside as issue #1. The SHIPPED example's
        # `conservation:` block declares `output_properties` and no
        # `input_property`, so this exit is the one it actually takes: a
        # configured-looking indicator returning an empty list that the
        # envelope reports as a clean pass. The INSUFFICIENT_SAMPLES decline
        # below never gets the chance to fire.
        if not input_prop or not output_props:
            missing = "input_property" if not input_prop else "output_properties"
            return CheckOutcome(problems).declined(
                Axiom.CONSERVATION, entity, indicator.name,
                NotEvaluatedReason.MISSING_CONFIG,
                detail=(
                    f"conservation config declares no {missing}; a balance "
                    f"needs both an input and at least one output to compare"),
            )

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
            # this was a bare `return problems`: an empty list, no
            # finding and no decline, which the envelope reports as a clean
            # pass. Same shape as the exit twelve lines above, found
            # while removing the name-inference path that shared it. The
            # samples ARE here — the gate above passed — so this is not
            # insufficient data; a deficit RATIO is simply undefined against a
            # zero total, and saying so is the only honest answer.
            return CheckOutcome(problems).declined(
                Axiom.CONSERVATION, entity, indicator.name,
                NotEvaluatedReason.UNDEFINED_FOR_VALUES,
                detail=(
                    f"the {len(input_values)} in-window observations of "
                    f"{input_prop} total {total_input:g}; a conservation "
                    f"deficit is expressed as a fraction of the input and has "
                    f"no value when there is no input to lose"),
                observations_count=len(input_values),
            )

        # which output properties actually answered. This loop used
        # to sum an absent property as zero, which is not a measurement of
        # zero: an output side that was never observed became a 100% deficit,
        # reported as a HIGH-severity finding ABOUT THE SYSTEM while the fault
        # was a property name the model got wrong. Measured against a control:
        # a block naming `outfow` for `outflow` produced
        # `conservation_violation. 100.0% deficit` with nothing on any
        # surface saying the model was at fault. Worse than a missed detection
        # -- it sends somebody to the plant to look for a leak that is a typo.
        total_output = 0.0
        unobserved = []
        for out_prop in output_props:
            out_values = history.get_values(entity.id, out_prop, window)
            if not out_values:
                unobserved.append(out_prop)
                continue
            total_output += sum(v[1] for v in out_values if v[1] is not None)

        if len(unobserved) == len(output_props):
            # THE MIRROR of the zero-input exit above, and deliberately no
            # wider. When nothing on the output side was observed, the deficit
            # is the whole input and none of it is measured. Certain, so it
            # declines.
            #
            # A PARTIAL absence does not decline, because it cannot be told
            # from a legitimately sparse channel -- an overflow that runs
            # rarely has no readings in most windows and is not a modelling
            # error. That case names the unobserved properties in the
            # finding's `reason` instead -- see the clause below, which is
            # where it ended up once the envelope's five keys were measured
            # rather than assumed. Said here too because the reader deciding
            # whether this branch is wide enough is reading THIS comment.
            return CheckOutcome(problems).declined(
                Axiom.CONSERVATION, entity, indicator.name,
                NotEvaluatedReason.MISSING_PROPERTY,
                detail=(
                    f"conservation balances {input_prop} against "
                    f"{', '.join(output_props)}, and none of those was "
                    f"observed in the {window.total_seconds():.0f}s window; a "
                    f"deficit against an unobserved output side would be the "
                    f"whole input and none of it measured. Check the property "
                    f"names in the block against the ones the model declares"),
                observations_count=0,
            )

        deficit = total_input - total_output
        deficit_ratio = abs(deficit) / total_input if total_input > 0 else 0

        if deficit_ratio > margin:
            severity = Severity.HIGH if deficit_ratio > margin * 3 else Severity.MEDIUM
            # the partial-absence clause rides in `reason` and not in
            # `evidence`, because the envelope serialises five keys per finding
            # and evidence is not one of them. A signal a consumer cannot read
            # is not a signal; this is the only free-text field that survives.
            unmeasured = (
                f"; {', '.join(unobserved)} contributed no observations, so "
                f"that part of the deficit is unmeasured rather than measured "
                f"as zero" if unobserved else "")
            problems.append(Problem.from_entity(
                entity=entity,
                problem_type=f'conservation_violation:{indicator.name}',
                severity=severity,
                reason=(f"{indicator.name}: input/output imbalance "
                        f"({deficit_ratio*100:.1f}% deficit){unmeasured}"),
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
                    # present only when some output property
                    # contributed nothing, so a reader can see how much of the
                    # deficit is unmeasured rather than measured as zero.
                    **({'unobserved_output_properties': unobserved}
                       if unobserved else {}),
                },
                confidence=min(1.0, deficit_ratio / margin),
            ))

        return apply_property_confidence(entity, indicator.property_name, problems)

    def _check_undeclared_conservation(
        self,
        entity: Entity,
        indicator: IndicatorSpec,
        history: ObservationHistory,
    ) -> List[Problem]:
        """CONSERVATION was declared and the balance was not. Decline, always.

        This used to guess the other half of the balance from the
        indicator's NAME: an ``_in`` / ``_received`` / ``_requests`` / ``input_``
        marker was rewritten to ``_out`` / ``_sent`` / ``_responses`` /
        ``output_`` and the result treated as the outflow property. Reported
        from outside as issue #9 against the sibling case — a die sensor and an
        external diode share a suffix and not a thermal environment, and the
        same is true of a balance: which quantities offset which is a fact
        about the system, not about its vocabulary.

        MEASURED BEFORE REMOVING, across the shipped domain packs. Nine
        indicators reached this path with a marker matched, and **three of the
        nine named a partner property that does not exist in their own model**.
        An absent partner yields no observations, which fell into the
        sample-count return below — a bare empty list, no finding and no
        decline. So the guess was not merely unsound: a third of the time it
        produced the silent clean pass this engine exists to make impossible.
        The other six were correct by luck of an English naming convention, and
        every one of them could have declared the block instead.

        THE REMEDY IS THE DECLARATION, NOT A RENAME. `roles.py` states the same
        rule for CONSISTENCY: *renaming a domain concept to satisfy a checker
        is the wrong remedy; declaring what the concept IS, is the right one.*
        The detail below names the block to write, and never a property the
        engine picked.
        """
        problems: List[Problem] = []

        prop = indicator.property_name
        if not prop:
            return CheckOutcome(problems).declined(
                Axiom.CONSERVATION, entity, indicator.name,
                NotEvaluatedReason.MISSING_PROPERTY,
                detail="the indicator declares no property_name",
            )

        # the terminus of the YAML-declared CONSERVATION path, and
        # since the only exit from it. An internal ruling added the config block
        # precisely so a domain need not rely on a guess; this is what makes
        # relying on one impossible.
        return CheckOutcome(problems).declined(
            Axiom.CONSERVATION, entity, indicator.name,
            NotEvaluatedReason.MISSING_CONFIG,
            detail=(
                f"CONSERVATION is declared on {indicator.name} but the balance "
                f"is not: add `conservation: {{input_property: ..., "
                f"output_properties: [...]}}` naming the properties that "
                f"offset each other. The engine no longer infers the pair from "
                f"the property name"),
        )

