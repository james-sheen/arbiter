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
)
from ...types import (
    Axiom, Severity, AxiomParameters, DetectionLayer, NotEvaluatedReason,
)

logger = logging.getLogger(__name__)


# the consistency axiom classifies a numeric property as a count /
# percentage / ratio by its NAME. Matching is on whole word-tokens, NOT
# substrings — a substring test mis-reads `observed_generation` as a ratio
# (gene-ratio-n), `account` / `discount` as counts, and `configuration` /
# `duration` / `operation` / `migration` as ratios. Tokens come from
# _name_word_tokens (snake_case / camelCase / kebab-case boundaries).
_COUNT_TOKENS = frozenset({"count", "counts"})
_PERCENT_TOKENS = frozenset({"percent", "percentage", "percentages", "pct"})
_RATIO_TOKENS = frozenset({"ratio", "ratios"})

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _name_word_tokens(name: str) -> set:
    """split a property / indicator name into lowercase word
    tokens across snake_case, camelCase and kebab-case boundaries.

    Used so the consistency axiom classifies a property by whole word
    (`ready_ratio` -> {ready, ratio}) rather than substring — a substring
    test mis-classifies `observed_generation`, `account`, `configuration`
    and similar names that merely contain a classifier word.
    """
    spaced = _CAMEL_BOUNDARY.sub(" ", str(name))
    return {t for t in re.split(r"[^a-zA-Z0-9]+", spaced.lower()) if t}


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

        # Check the indicator's value
        value = entity.get_property(indicator.property_name)
        if value is None:
            return problems

        # classify by whole word-token, not substring.
        name_tokens = _name_word_tokens(indicator.name)

        # Rule 1: Count fields must be non-negative
        if name_tokens & _COUNT_TOKENS:
            problems.extend(self._check_count(entity, indicator.name, value))

        # Rule 2: Percentage fields must be 0-100
        if name_tokens & _PERCENT_TOKENS:
            problems.extend(self._check_percentage(entity, indicator.name, value))

        # Rule 3: Ratio fields must be 0-1
        if name_tokens & _RATIO_TOKENS:
            problems.extend(self._check_ratio(entity, indicator.name, value))

        result = apply_property_confidence(
            entity, indicator.property_name, problems)

        # every rule here is keyed on the indicator NAME tokenising to
        # count / percent / pct / ratio. An indicator named anything else —
        # `temperature`, `flow_in`, `queue_depth` — matched no rule and reached
        # this return having evaluated nothing, returning an empty list that
        # read as a clean pass. This is the dominant case rather than the edge
        # one: most indicator names are not count/percent/ratio words.
        if not (name_tokens & (_COUNT_TOKENS | _PERCENT_TOKENS | _RATIO_TOKENS)):
            return CheckOutcome(result).declined(
                Axiom.CONSISTENCY, entity, indicator.name,
                NotEvaluatedReason.NOT_APPLICABLE,
                detail=(
                    "no universal rule applies: the indicator name does not "
                    "tokenise to count, percent/pct or ratio"),
            )
        return result

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
