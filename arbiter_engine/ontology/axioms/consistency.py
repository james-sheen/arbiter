"""
CONSISTENCY Axiom Checker.

CONSISTENCY: System maintains coherent state.

Detects:
- Logical impossibilities (count < 0, percentage > 100)
- Contradictory states
- Reference integrity violations
- Learned invariant violations

Works from cold start for universal rules.
Requires history for learned invariants.
"""

import logging
import re
from typing import Any, List, Optional

from ...interfaces import (
    Entity,
    Problem,
    RelationshipGraph,
    ObservationHistory,
    IndicatorSpec,
    apply_property_confidence,
    CheckOutcome,
    absent_current_value,
)
from ...types import (
    Axiom, Severity, AxiomParameters, DetectionLayer, NotEvaluatedReason,
)

from . import roles

logger = logging.getLogger(__name__)


# the consistency axiom classifies a numeric property as a count /
# percentage / ratio by its NAME. Matching is on whole word-tokens, NOT
# substrings — a substring test mis-reads `observed_generation` as a ratio
# (gene-ratio-n), `account` / `discount` as counts, and `configuration` /
# `duration` / `operation` / `migration` as ratios. Tokens come from
# _name_word_tokens (snake_case / camelCase / kebab-case boundaries).
# these now live in `roles.py`, which is the single authority for
# what an indicator's role is and which axioms have a rule for it. Re-exported
# under their original names because `check_entity` below still classifies RAW
# PROPERTY KEYS by token — it has no IndicatorSpec and therefore no declared
# role to read, so name tokens are the only signal available there and remain
# the right one. Two test modules also import these names directly.
_COUNT_TOKENS = roles._COUNT_TOKENS
_PERCENT_TOKENS = roles._PERCENT_TOKENS
_RATIO_TOKENS = roles._RATIO_TOKENS
_name_word_tokens = roles.name_word_tokens


class ConsistencyChecker:
    """
    Check CONSISTENCY axiom for entities.

    CONSISTENCY works from cold start for universal rules
    like non-negative counts and valid percentages.
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
        Check CONSISTENCY for an entity/indicator.

        Applies universal consistency rules based on property names.
        """
        problems = []

        # was a bare `return problems`, reported from outside as
        # issue #1. CONSISTENCY's universal rules all compare a VALUE against
        # what its role permits, so with no value there is nothing to judge —
        # and saying so is the entire point of the not_checked leg.
        value = entity.get_property(indicator.property_name)
        if value is None:
            # which absence, not just that there is one.
            reason, clause, seen = absent_current_value(entity, indicator, history)
            return CheckOutcome(problems).declined(
                Axiom.CONSISTENCY, entity, indicator.name, reason,
                detail=(
                    f"{clause}; "
                    f"CONSISTENCY judges a value against the range its role "
                    f"permits"),
                observations_count=seen or None,
            )

        # which universal rules apply is a DECLARED role now, and the
        # token rule is the fallback when no role is declared. A model
        # saying `role: ratio` gets the ratio rule on an indicator called
        # `product_temp_c_redundant`; before, only a name tokenising to the
        # word `ratio` could reach it.
        applicable, matched_roles, role_source = roles.applies(
            Axiom.CONSISTENCY, indicator)

        # Rule 1: Count fields must be non-negative
        if roles.COUNT in matched_roles:
            problems.extend(self._check_count(entity, indicator.name, value))

        # Rule 2: Percentage fields must be 0-100
        if roles.PERCENTAGE in matched_roles:
            problems.extend(self._check_percentage(entity, indicator.name, value))

        # Rule 3: Ratio fields must be 0-1
        if roles.RATIO in matched_roles:
            problems.extend(self._check_ratio(entity, indicator.name, value))

        # Rule 4: do two readings that should agree, agree?
        #
        # The original promise behind the axiom name. Issue #4 established that
        # everything above is single-value plausibility — it asks whether a
        # number is possible on its own terms, and would behave identically if
        # every other indicator on the entity were deleted. Redundant-signal
        # agreement is a different question and needs a different input: the
        # model has to say WHICH readings are supposed to match, because
        # nothing about two numbers reveals that they measure the same thing.
        #
        # Runs independently of the role gate. A redundant pair of temperature
        # sensors carries no role — `temp_c` tokenises to nothing — and
        # requiring one would make the commonest case of this capability
        # unreachable.
        agreement_declined = None
        if roles.has_cross_signal_rule(indicator):
            found, agreement_declined = self._check_agreement(
                entity, indicator, value)
            problems.extend(found)

        result = apply_property_confidence(
            entity, indicator.property_name, problems)

        # a peer the entity does not carry is a decline, not silence.
        # Returned here rather than from `_check_agreement` so it passes through
        # `apply_property_confidence` with everything else; a decline emitted on
        # a separate path is how return-shape drift starts.
        if agreement_declined is not None:
            return CheckOutcome(result).declined(
                Axiom.CONSISTENCY, entity, indicator.name,
                NotEvaluatedReason.MISSING_PROPERTY,
                detail=agreement_declined,
            )

        # every rule here is keyed on the indicator NAME tokenising to
        # count / percent / pct / ratio. An indicator named anything else —
        # `temperature`, `flow_in`, `queue_depth` — matched no rule and reached
        # this return having evaluated nothing, returning an empty list that
        # read as a clean pass. This is the dominant case rather than the edge
        # one: most indicator names are not count/percent/ratio words.
        if not applicable:
            # names the remedy (declare a role) rather than the rule
            # (your name did not tokenise), which pointed the reader at
            # renaming a domain concept to satisfy a checker.
            return CheckOutcome(result).declined(
                Axiom.CONSISTENCY, entity, indicator.name,
                NotEvaluatedReason.NOT_APPLICABLE,
                detail=roles.explain_absence(Axiom.CONSISTENCY, indicator),
            )
        if role_source == "inferred":
            logger.debug(
                "CONSISTENCY applied to %r via a role INFERRED from its name "
                "(%s); declare `role:` to make it explicit",
                indicator.name, ", ".join(sorted(matched_roles)),
            )
        return result

    def _check_agreement(
        self,
        entity: Entity,
        indicator: IndicatorSpec,
        value: Any,
    ) -> tuple:
        """compare this reading against the peers it must agree with.

        Returns ``(problems, decline_detail_or_None)``.

        ``agrees_with`` names PROPERTIES, matching
        ``conservation.output_properties``. A checker holds an ``IndicatorSpec``
        and an ``Entity`` and never the model, so it cannot resolve a declared
        indicator name through a ``property_mapping``; a block naming things
        this method cannot look up would be a declaration nothing reads.

        Tolerance is RELATIVE to the larger magnitude of the pair, not to the
        first-named reading. Dividing by one of the two makes the verdict depend
        on which was written first, and dividing by their mean makes a pair
        straddling zero produce a denominator near zero from values that are
        nowhere near it. ``max(abs(a), abs(b))`` is the conservative choice and
        is symmetric, which is the property a redundancy check needs most:
        `a agrees with b` must mean the same as `b agrees with a`, since a model
        may reasonably declare the block on either side or both.
        """
        config = indicator.consistency_config or {}
        peers = config.get("agrees_with") or []
        if isinstance(peers, str):
            # A bare string iterates its characters, which is the
            # failure this loader learned about the hard way. One peer written
            # without brackets is the likeliest way to write this block.
            peers = [peers]

        tolerance = config.get("tolerance")
        absolute = config.get("tolerance_absolute")
        if tolerance is None and absolute is None:
            tolerance = self.params.consistency_agreement_tolerance

        try:
            reading = float(value)
        except (TypeError, ValueError):
            return [], (
                f"cross-signal agreement needs a numeric reading; "
                f"{indicator.property_name} is {value!r}")

        problems: List[Problem] = []
        missing: List[str] = []
        for peer in peers:
            other = entity.get_property(str(peer))
            if other is None:
                missing.append(str(peer))
                continue
            try:
                other = float(other)
            except (TypeError, ValueError):
                missing.append(str(peer))
                continue

            difference = abs(reading - other)
            scale = max(abs(reading), abs(other))
            if absolute is not None:
                allowed = float(absolute)
                measure = difference
                units = "absolute"
            else:
                allowed = float(tolerance)
                # Both readings exactly zero: they agree, and the relative
                # measure is 0/0. Answering `0.0` is the only reading of that
                # which is not an accusation.
                measure = (difference / scale) if scale else 0.0
                units = "relative"

            if measure > allowed:
                problems.append(Problem.from_entity(
                    entity=entity,
                    problem_type=f'redundant_disagreement:{indicator.name}',
                    severity=Severity.WARNING,
                    reason=(
                        f"{indicator.name} and {peer} are declared redundant "
                        f"and disagree"),
                    axiom=Axiom.CONSISTENCY,
                    source_layer=DetectionLayer.ONTOLOGY,
                    evidence={
                        'indicator': indicator.name,
                        'property': indicator.property_name,
                        'peer': str(peer),
                        'value': reading,
                        'peer_value': other,
                        'difference': difference,
                        'divergence': measure,
                        'tolerance': allowed,
                        'tolerance_kind': units,
                    },
                    confidence=1.0,
                ))

        if missing:
            # Deliberately reported even when other peers DID compare. A pair
            # declared redundant and silently dropped is the absent-data
            # silence this engine exists to refuse, and `two of three agreed`
            # is not an answer about the third.
            return problems, (
                f"declared redundant with {', '.join(missing)}, which this "
                f"entity does not carry as a numeric property; agreement "
                f"cannot be judged against a reading that is not there")
        return problems, None

    def check_entity(
        self,
        entity: Entity,
        graph: RelationshipGraph
    ) -> List[Problem]:
        """
        Check all properties of an entity for consistency.

        This is a comprehensive check that doesn't require an indicator spec.
        """
        problems = []

        def check_props(props: dict, path: str = ''):
            for key, value in props.items():
                full_path = f"{path}.{key}" if path else key
                key_tokens = _name_word_tokens(key)

                if isinstance(value, dict):
                    check_props(value, full_path)
                elif isinstance(value, (int, float)):
                    # classify by whole word-token, not substring —
                    # so `observed_generation` is not mis-read as a ratio.
                    if key_tokens & _COUNT_TOKENS:
                        problems.extend(self._check_count(entity, full_path, value))

                    if key_tokens & _PERCENT_TOKENS:
                        problems.extend(self._check_percentage(entity, full_path, value))

                    if key_tokens & _RATIO_TOKENS:
                        problems.extend(self._check_ratio(entity, full_path, value))

        check_props(entity.properties)
        return problems

    def _check_count(
        self,
        entity: Entity,
        property_name: str,
        value: Any
    ) -> List[Problem]:
        """Check that count value is non-negative."""
        problems = []

        try:
            numeric_value = float(value)
            if numeric_value < 0:
                problems.append(Problem.from_entity(
                    entity=entity,
                    problem_type='impossible_value',
                    severity=Severity.CRITICAL,
                    reason=f"Impossible value: {property_name} = {value} (count cannot be negative)",
                    axiom=Axiom.CONSISTENCY,
                    source_layer=DetectionLayer.ONTOLOGY,
                    evidence={
                        'property': property_name,
                        'value': value,
                        'rule': 'count >= 0',
                    },
                    confidence=1.0,
                ))
        except (TypeError, ValueError):
            pass

        return problems

    def _check_percentage(
        self,
        entity: Entity,
        property_name: str,
        value: Any
    ) -> List[Problem]:
        """Check that percentage value is 0-100."""
        problems = []

        try:
            numeric_value = float(value)
            if numeric_value < 0 or numeric_value > 100:
                problems.append(Problem.from_entity(
                    entity=entity,
                    problem_type='impossible_value',
                    severity=Severity.HIGH,
                    reason=f"Impossible value: {property_name} = {value} (percentage must be 0-100)",
                    axiom=Axiom.CONSISTENCY,
                    source_layer=DetectionLayer.ONTOLOGY,
                    evidence={
                        'property': property_name,
                        'value': value,
                        'rule': '0 <= percentage <= 100',
                    },
                    confidence=1.0,
                ))
        except (TypeError, ValueError):
            pass

        return problems

    def _check_ratio(
        self,
        entity: Entity,
        property_name: str,
        value: Any
    ) -> List[Problem]:
        """Check that ratio value is 0-1."""
        problems = []

        try:
            numeric_value = float(value)
            if numeric_value < 0 or numeric_value > 1:
                problems.append(Problem.from_entity(
                    entity=entity,
                    problem_type='impossible_value',
                    severity=Severity.HIGH,
                    reason=f"Impossible value: {property_name} = {value} (ratio must be 0-1)",
                    axiom=Axiom.CONSISTENCY,
                    source_layer=DetectionLayer.ONTOLOGY,
                    evidence={
                        'property': property_name,
                        'value': value,
                        'rule': '0 <= ratio <= 1',
                    },
                    confidence=1.0,
                ))
        except (TypeError, ValueError):
            pass

        return problems

    def check_domain_rules(
        self,
        entity: Entity,
        rules: list,
    ) -> List[Problem]:
        """Check domain-configurable consistency rules.

        Rules are dicts with:
            entity_type: str — must match entity.type
            property: str — the property to check
            operator: str — 'lt', 'le', 'gt', 'ge', 'eq', 'ne'
            bound_property: str — another property that sets the bound
            severity: str — 'WARNING', 'HIGH', 'CRITICAL'
            name: str — rule description
        """
        problems = []
        _ops = {
            'le': lambda a, b: a <= b,
            'lt': lambda a, b: a < b,
            'ge': lambda a, b: a >= b,
            'gt': lambda a, b: a > b,
            'eq': lambda a, b: a == b,
            'ne': lambda a, b: a != b,
        }

        for rule in rules:
            rule_entity_type = rule.get('entity_type', '')
            entity_type_str = entity.type if isinstance(entity.type, str) else getattr(entity.type, 'value', str(entity.type))

            if rule_entity_type and rule_entity_type.lower() != entity_type_str.lower():
                continue

            prop_name = rule.get('property', '')
            op_name = rule.get('operator', 'le')
            bound_prop = rule.get('bound_property', '')
            bound_value = rule.get('bound_value')

            prop_val = entity.get_property(prop_name)
            if prop_val is None:
                continue

            # Determine bound
            bound = None
            if bound_prop:
                bound = entity.get_property(bound_prop)
            elif bound_value is not None:
                bound = bound_value

            if bound is None:
                continue

            try:
                prop_num = float(prop_val)
                bound_num = float(bound)
            except (TypeError, ValueError):
                continue

            op_fn = _ops.get(op_name)
            if not op_fn:
                continue

            if not op_fn(prop_num, bound_num):
                sev_str = rule.get('severity', 'HIGH').upper()
                sev = Severity.HIGH
                try:
                    sev = Severity(sev_str.lower())
                except (ValueError, KeyError):
                    for s in Severity:
                        if s.name == sev_str:
                            sev = s
                            break

                problems.append(Problem.from_entity(
                    entity=entity,
                    problem_type=f'consistency_rule_violation:{rule.get("name", prop_name)}',
                    severity=sev,
                    reason=f"Consistency rule violated: {prop_name} ({prop_num}) {op_name} {bound_prop or bound_value} ({bound_num})",
                    axiom=Axiom.CONSISTENCY,
                    source_layer=DetectionLayer.ONTOLOGY,
                    evidence={
                        'rule_name': rule.get('name', ''),
                        'property': prop_name,
                        'value': prop_num,
                        'operator': op_name,
                        'bound': bound_num,
                        'bound_source': bound_prop or 'static',
                    },
                    confidence=1.0,
                ))

        return problems

    def check_state_contradictions(
        self,
        entity: Entity,
        state_groups: dict
    ) -> List[Problem]:
        """
        Check for contradictory states.

        Args:
            entity: Entity to check
            state_groups: Dict mapping property name to valid states
                          e.g., {'phase': ['Running', 'Pending']}
        """
        problems = []

        for property_name, valid_states in state_groups.items():
            value = entity.get_property(property_name)
            if value is not None and str(value) not in valid_states:
                problems.append(Problem.from_entity(
                    entity=entity,
                    problem_type='invalid_state',
                    severity=Severity.HIGH,
                    reason=f"Invalid state: {property_name} = '{value}'",
                    axiom=Axiom.CONSISTENCY,
                    source_layer=DetectionLayer.ONTOLOGY,
                    evidence={
                        'property': property_name,
                        'value': value,
                        'valid_states': valid_states,
                    },
                    confidence=1.0,
                ))

        return problems

    def check_mutual_exclusion(
        self,
        entity: Entity,
        mutually_exclusive: List[List[str]]
    ) -> List[Problem]:
        """
        Check that mutually exclusive properties are not all set.

        Args:
            mutually_exclusive: List of property groups that should be mutually exclusive
                               e.g., [['running', 'waiting', 'terminated']]
        """
        problems = []

        for group in mutually_exclusive:
            set_properties = []
            for prop in group:
                value = entity.get_property(prop)
                if value is not None:
                    set_properties.append(prop)

            if len(set_properties) > 1:
                problems.append(Problem.from_entity(
                    entity=entity,
                    problem_type='contradictory_state',
                    severity=Severity.CRITICAL,
                    reason=f"Contradictory state: multiple mutually exclusive properties set",
                    axiom=Axiom.CONSISTENCY,
                    source_layer=DetectionLayer.ONTOLOGY,
                    evidence={
                        'set_properties': set_properties,
                        'mutually_exclusive_group': group,
                    },
                    confidence=1.0,
                ))

        return problems
