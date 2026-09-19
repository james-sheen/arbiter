"""
Topology Builder — construct DigitalTwinTopology from domain YAML,
RelationshipGraph, and Entity dict.

Two entry points:
  build_from_yaml()               — full enrichment from YAML indicators,
                                     relationship rules, temporal store
  build_from_relationship_graph() — minimal migration path (no YAML)
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from ..interfaces import Entity, RelationshipGraph
from ..types import Axiom, Severity
from ..temporal.temporal_edge import TemporalAnnotationStore, ResponseModel
from ..propagation.weight_learner import LearnedWeight

from .topology import (
    TwinNode, TwinEdge, TopologyGap, DigitalTwinTopology,
    AxiomState, NodeConfidence, Transition, REQUIRED_TRANSITION_KEYS,
    ESTIMATE_SENTINEL,
    EdgeDirection, FlowType, EdgeSource, GapType, ResolutionStrategy,
)

logger = logging.getLogger(__name__)


def _indicator_field(indicator, field: str, default: str = "") -> str:
    """read a field from an indicator that may be a dict or an
    `IndicatorSpec`.

    Gap discovery was written against the raw YAML dict, which is why it only
    ever ran on the YAML builder path. The engine's public API
    (`arbiter_engine/api.py`) holds a typed `DomainModel`, so the dict requirement
    was a silent capability boundary rather than a deliberate one — `gaps`
    returned an empty questions leg for every input. Same seam, same fix as
     in the ontology loader.

    `IndicatorSpec.indicator_type` is an enum whose value is lowercase
    (`"numeric"`), while YAML writes `NUMERIC`; normalising to upper here is
    what lets one comparison serve both.
    """
    if isinstance(indicator, dict):
        return str(indicator.get(field, default) or default)
    if field == "type":
        kind = getattr(indicator, "indicator_type", None)
        return str(getattr(kind, "value", kind) or default).upper()
    return str(getattr(indicator, field, default) or default)


def _min_cardinality(indicator) -> int:
    """read `min_cardinality` from a dict or an `IndicatorSpec`."""
    if isinstance(indicator, dict):
        raw = indicator.get('min_cardinality', 0)
    else:
        raw = getattr(indicator, 'min_cardinality', 0)
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


class TopologyBuilder:
    """Build a DigitalTwinTopology from different sources."""

    @staticmethod
    def _build_id_alias_map(entities: Dict[str, Entity]) -> Dict[str, str]:
        """Map from short/raw IDs to the canonical entity.id used in nodes.

        Entity IDs may be stored as qualified ("Department/dept-finance") or
        raw ("dept-finance"). Relationship endpoints submitted separately
        might use either form. This map resolves raw IDs to their qualified
        counterparts so relationship edges align with node keys.

        Returns a dict where keys are alternative forms and values are
        canonical node IDs. Does NOT overwrite canonical->canonical entries.
        """
        aliases: Dict[str, str] = {}
        for eid in entities.keys():
            # If eid is "Type/raw", add "raw" -> "Type/raw"
            if '/' in eid:
                raw = eid.split('/', 1)[1]
                # Only add alias if raw form is not itself a canonical ID
                # and we don't already have a different alias for it
                if raw not in entities and raw not in aliases:
                    aliases[raw] = eid
        return aliases

    @staticmethod
    def _resolve_id(raw_or_qualified: str, aliases: Dict[str, str]) -> str:
        """Resolve an ID through the alias map; return original if no alias."""
        return aliases.get(raw_or_qualified, raw_or_qualified)

    def build_from_yaml(
        self,
        domain_yaml: Dict[str, Any],
        entities: Dict[str, Entity],
        graph: RelationshipGraph,
        temporal_store: Optional[TemporalAnnotationStore] = None,
        learned_weights: Optional[Dict[Tuple[str, str], LearnedWeight]] = None,
    ) -> DigitalTwinTopology:
        """Construct topology from parsed domain YAML + runtime entities."""
        domain = domain_yaml.get('domain', domain_yaml)
        domain_id = domain.get('id', domain.get('name', 'unknown'))
        topology = DigitalTwinTopology(domain_id=domain_id)

        indicators_by_type = domain.get('indicators', {})

        # 1. Create TwinNodes from entities
        for entity_id, entity in entities.items():
            axiom_states = self._axiom_states_from_yaml(
                entity.type, indicators_by_type
            )
            node = TwinNode(
                entity=entity,
                axiom_states=axiom_states,
                # seeded on BOTH builder paths. Seeding one is the
                # shape: a leg that is structurally unable to
                # perform rather than merely under-performing.
                flow_directions=self._flow_directions_from_indicators(
                    entity.type, indicators_by_type),
            )
            topology.add_node(node)

        # Build alias map for raw/qualified ID resolution
        aliases = self._build_id_alias_map(entities)

        # 2. Create TwinEdges from RelationshipGraph
        relationship_rules = domain.get('relationship_rules', [])
        rules_by_key = self._index_rules(relationship_rules)

        for source_id, edge_tuples in graph.edges.items():
            resolved_source = self._resolve_id(source_id, aliases)
            source_entity = entities.get(resolved_source)
            for rel_type, target_id in edge_tuples:
                resolved_target = self._resolve_id(target_id, aliases)
                target_entity = entities.get(resolved_target)
                edge = self._build_edge(
                    resolved_source, resolved_target, rel_type,
                    source_entity, target_entity,
                    rules_by_key, temporal_store, learned_weights,
                )
                topology.add_edge(edge)

        # 3. Detect structural gaps
        self._detect_structural_gaps(topology, indicators_by_type, entities)
        topology._update_fidelity()
        return topology

    def build_from_relationship_graph(
        self,
        entities: Dict[str, Entity],
        graph: RelationshipGraph,
        indicators_by_type: Optional[Dict[str, List]] = None,
        relationship_rules: Optional[List[Dict[str, Any]]] = None,
    ) -> DigitalTwinTopology:
        """Minimal topology from an existing RelationshipGraph (no YAML).

        ``relationship_rules`` is the THIRD parameter added to this
        builder for the same reason as the first two, and the reason is worth
        stating once more because it keeps recurring. This is the builder the
        published `api` uses. ``build_from_yaml`` is the one that reads
        relationship rules. So every declared ``temporal:`` block -- delay,
        time constant, coupling, response model -- was dropped on the only
        path a released caller can reach, and the edge was stamped
        ``EdgeSource.AUTO_DISCOVERY``: the engine telling a reader that
        nobody declared an edge the author had declared.

        Measured before the fix, on a rule declaring 120s / 600s / 0.9: the
        edge carried 60.0 / 60.0 / 1.0, three silent defaults. A model author
        could write a temporal block, run `traverse` through `api`, and get
        the same answer as an author who wrote nothing.

        Same shape as (gap discovery) and (axiom states): a
        leg structurally unable to perform rather than under-performing, on
        the builder nobody was looking at. Passed as a parameter rather than
        by switching to ``build_from_yaml`` for the reason below.

        ``indicators_by_type`` is optional and, when supplied, runs
        the same structural gap discovery the YAML path runs. Without it this
        method produced a topology with **zero gaps for every input**, which
        made the ``gaps`` primitive — the one carrying the *here is what
        I need to know next* claim — permanently empty. It was not
        under-performing; it could not perform.

        Deliberately a parameter rather than a switch to ``build_from_yaml``:
        that path also derives edge confidence from ``relationship_rules``
        instead of the flat 0.5 used here, which would change traversal
        results. The two builders were never written as substitutes, and the
        gap gap is fixable without adopting the rest.
        """
        topology = DigitalTwinTopology()
        for entity_id, entity in entities.items():
            # carry the declared axioms onto the node, the same way
            # the YAML builder does. Without this the nodes reached the
            # traverser with an empty `axiom_states`, so `_evaluate_axioms`
            # iterated nothing and `traverse` reported `findings: []` for
            # every input. Exactly the shape, one leg over: not
            # under-performing, structurally unable to perform.
            axiom_states = (
                self._axiom_states_from_yaml(entity.type, indicators_by_type)
                if indicators_by_type else {}
            )
            topology.add_node(
                TwinNode(
                    entity=entity,
                    axiom_states=axiom_states,
                    flow_directions=self._flow_directions_from_indicators(
                        entity.type, indicators_by_type),
                ))
        aliases = self._build_id_alias_map(entities)
        rules_by_key = self._index_rules(relationship_rules or [])
        for source_id, edge_tuples in graph.edges.items():
            resolved_source = self._resolve_id(source_id, aliases)
            for rel_type, target_id in edge_tuples:
                resolved_target = self._resolve_id(target_id, aliases)
                edge = TwinEdge(
                    source_id=resolved_source,
                    target_id=resolved_target,
                    relation_type=rel_type,
                    source=EdgeSource.AUTO_DISCOVERY,
                    confidence=0.5,
                )
                # a declared rule, when one matches, overrides the
                # defaults above and says so in `source`. No match leaves the
                # edge exactly as it was, so a graph built without a model is
                # unaffected: this widens what a declaration can reach, it
                # does not change what an undeclared edge does.
                self._apply_declared_rule(
                    edge,
                    self._rule_for(
                        rules_by_key, entities.get(resolved_source),
                        entities.get(resolved_target), rel_type),
                )
                topology.add_edge(edge)
        if indicators_by_type:
            self._detect_structural_gaps(
                topology, indicators_by_type, entities)
        topology._update_fidelity()
        return topology

    # -- Private helpers ---------------------------------------------------

    @staticmethod
    def _read_indicator(ind) -> Tuple[str, List[str],
                                      Dict[str, Optional[float]]]:
        """Read (name, axiom names, bounds) from an indicator.

        the bounds are returned as a MAPPING rather than as a
        ``warning, critical`` pair, and that is the fix rather than an
        incidental refactor. The pair shape is what made the floor half of
        BOUNDEDNESS unreachable: ``lower_warning`` / ``lower_critical`` are
        declared in the schema, read by ``UnifiedAxiomReasoner``, and were
        never read HERE, so they never reached ``AxiomState.evidence`` and
        ``TopologyTraverser._evaluate_axioms`` had nothing to compare against.
        A traversal over a stalled pump reported no finding while ``check``
        on the same entity reported ``below_critical_threshold`` — one
        declaration, two verbs, opposite answers.

        An internal ruling fixed exactly this shape for the CEILING half and its
        docstring below describes the failure it closed. The floor half was
        left in that state, which is the instance-not-class shape: widening
        the return to a mapping is what stops the next bound being added to
        one reader and not the other.

        indicators reach the two builders in **two different shapes
        with two different threshold names**, and nothing previously bridged
        them. ``build_from_yaml`` is fed raw YAML mappings using ``warning`` /
        ``critical``; the ``api`` layer supplies typed ``IndicatorSpec``
        objects using ``warning_threshold`` / ``critical_threshold`` and
        ``relevant_axioms``. A reader that handled only the mapping shape
        would raise on the typed one, and one that handled only the typed
        names would silently read ``None`` for every threshold — which is the
        quiet direction and therefore the dangerous one.
        """
        if hasattr(ind, 'get'):
            name = ind.get('name', '') or ''
            axioms = list(ind.get('axioms', []) or [])
            bounds = {
                'warning': ind.get('warning'),
                'critical': ind.get('critical'),
                'lower_warning': ind.get('lower_warning'),
                'lower_critical': ind.get('lower_critical'),
            }
        else:
            name = getattr(ind, 'name', '') or ''
            axioms = [
                getattr(a, 'value', str(a))
                for a in (getattr(ind, 'relevant_axioms', None) or [])
            ]
            bounds = {
                'warning': getattr(ind, 'warning_threshold', None),
                'critical': getattr(ind, 'critical_threshold', None),
                'lower_warning': getattr(
                    ind, 'lower_warning_threshold', None),
                'lower_critical': getattr(
                    ind, 'lower_critical_threshold', None),
            }
        return name, axioms, bounds

    def _flow_directions_from_indicators(
        self,
        entity_type: str,
        indicators_by_type: Optional[Dict[str, List]],
    ) -> Dict[str, str]:
        """declared `flow:` per property, for the structural balance.

        Both indicator shapes again, for the reason `_read_indicator` gives:
        YAML mappings carry ``flow``, typed ``IndicatorSpec`` objects carry
        ``flow_direction``, and reading only one of them is the quiet failure.

        **The indicator's `axioms:` list is deliberately not consulted.** A
        balance has two sides and only one of them carries the
        ``conservation:`` block: ``water_tank.yaml`` declares the block on
        ``inflow_lps`` and names ``outflow_lps`` inside it, leaving the outflow
        indicator with ``axioms: []`` on purpose. Requiring CONSERVATION here
        would mean the outflow could not state its direction without also
        declaring an axiom it does not want — demanding a false declaration in
        order to accept a true one. See `_SHARED_FIELDS` in the loader.

        This still closes half of the structural check consulted no
        declaration at all, and now the directions it sums are declared ones.
        """
        out: Dict[str, str] = {}
        for ind in (indicators_by_type or {}).get(entity_type, []) or []:
            name, _, _ = self._read_indicator(ind)
            if not name:
                continue
            if hasattr(ind, 'get'):
                raw = ind.get('flow')
            else:
                raw = getattr(ind, 'flow_direction', None)
            if raw is None:
                continue
            word = str(raw).strip().lower()
            # The loader already refused anything outside the pair; a raw dict
            # reaching the YAML builder path has not been through it, so the
            # same closed set is applied here rather than trusted from upstream.
            if word in ('in', 'out'):
                out[name] = word
        return out

    def _axiom_states_from_yaml(
        self,
        entity_type: str,
        indicators_by_type: Dict[str, List],
    ) -> Dict[str, AxiomState]:
        """Create AxiomState entries from indicator definitions.

        the thresholds are carried into ``AxiomState.evidence``.
        They were not before, and `TopologyTraverser._evaluate_axioms` reads
        BOUNDEDNESS bounds from exactly that dict, so it compared every value
        against ``None`` and returned no problems **on either builder path**.
        The traversal findings leg could not fire from a declaration at all —
        the same shape as an internal ruling, which found the gaps leg permanently empty
        on one of these builders, one leg over.
        """
        states: Dict[str, AxiomState] = {}
        type_indicators = indicators_by_type.get(entity_type, [])
        for ind in type_indicators:
            name, axiom_names, bounds = self._read_indicator(ind)
            for ax_name in axiom_names:
                try:
                    axiom = Axiom(ax_name)
                except ValueError:
                    continue
                # every declared bound is carried, floors included.
                # Enumerating the two upper ones by hand is what left the two
                # lower ones behind when they were added to the schema.
                evidence: Dict[str, Any] = {
                    key: value for key, value in bounds.items()
                    if value is not None
                }
                key = f"{axiom.value}:{name}"
                states[key] = AxiomState(
                    axiom=axiom,
                    verdict=Severity.INFO,
                    indicator_name=name,
                    evidence=evidence,
                )
        return states

    @staticmethod
    def _rule_for(
        rules_by_key: Dict, source_entity: Optional[Entity],
        target_entity: Optional[Entity], rel_type: str,
    ) -> Optional[Dict[str, Any]]:
        """The declared rule for this edge, or None.

        Keyed the way ``_index_rules`` keys them: by the two entity TYPES and
        the relation type, because a rule describes a kind of relationship
        rather than a pair of instances.
        """
        if not rules_by_key or source_entity is None or target_entity is None:
            return None
        return rules_by_key.get(
            (source_entity.type, target_entity.type, rel_type))

    def _apply_declared_rule(
        self, edge: TwinEdge, rule: Optional[Dict[str, Any]],
    ) -> None:
        """Overlay a declared relationship rule onto an edge, in place.

        ONE implementation, called from both builders. The temporal
        block was previously read only inside ``_build_edge``; a second copy
        here is the shape that drifts, and this file already carries two
        docstrings about readers that disagreed because the same fact was
        read in two places.
        """
        if not rule:
            return
        temporal_block = rule.get('temporal') or {}
        if temporal_block:
            edge.propagation_delay_s = float(temporal_block.get(
                'propagation_delay_s', edge.propagation_delay_s))
            edge.time_constant_s = float(temporal_block.get(
                'time_constant_s', edge.time_constant_s))
            edge.coupling_strength = float(temporal_block.get(
                'coupling_strength', edge.coupling_strength))
            try:
                edge.response_model = ResponseModel(
                    temporal_block.get('response_model',
                                       edge.response_model.value))
            except ValueError:
                pass
        transitions, gaps = self._transitions_from_rule(
            rule, edge.source_id, edge.target_id)
        edge.transitions = transitions
        edge.gaps = list(edge.gaps) + gaps
        # The edge IS declared, and `source` is the field that says so. It
        # read `auto` for every edge on this path, including edges a model
        # author wrote a rule for.
        edge.source = EdgeSource.YAML
        edge.confidence = 1.0

    @staticmethod
    def _transitions_from_rule(
        rule: Dict[str, Any], source_id: str, target_id: str,
    ) -> Tuple[List[Transition], List[TopologyGap]]:
        """Read `transition:` off a relationship rule.

        Accepts a single mapping or a list of them, because one
        relationship can drive more than one property. Returns the
        transitions it could build AND a gap for every block it refused, so a
        partial declaration is REPORTED rather than dropped: a block that
        names `from` and `to` and forgets `gain` is an author who meant to
        declare a coupling, and silently building an edge without one turns
        that into a value nobody projects and nobody asks about.

        Nothing here is defaulted. `REQUIRED_TRANSITION_KEYS` is the whole
        contract and a missing member names itself in the gap.
        """
        raw = rule.get('transition')
        if not raw:
            return [], []
        blocks = raw if isinstance(raw, list) else [raw]
        transitions: List[Transition] = []
        gaps: List[TopologyGap] = []
        location = f"{source_id}->{target_id}"
        for index, block in enumerate(blocks):
            if not isinstance(block, dict):
                gaps.append(TopologyGap(
                    gap_type=GapType.MISSING_DECLARATION,
                    location=location,
                    description=(
                        f"transition[{index}] on {rule.get('type', '?')} is "
                        f"{type(block).__name__}, not a mapping"),
                    discovered_during="build",
                ))
                continue
            missing = [k for k in REQUIRED_TRANSITION_KEYS
                       if block.get(k) is None]
            if missing:
                gaps.append(TopologyGap(
                    gap_type=GapType.MISSING_DECLARATION,
                    location=location,
                    description=(
                        f"transition[{index}] is missing "
                        f"{', '.join(missing)}; a transition without all of "
                        f"{', '.join(REQUIRED_TRANSITION_KEYS)} is not "
                        f"completed with a default"),
                    discovered_during="build",
                ))
                continue
            # `gain: estimate` declares the pair and withholds the
            # number. Checked before the float conversion, because `estimate`
            # is not a malformed gain; it is a different kind of claim.
            estimated = (isinstance(block.get('gain'), str)
                         and block['gain'].strip().lower()
                         == ESTIMATE_SENTINEL)
            try:
                gain = 0.0 if estimated else float(block['gain'])
                offset = float(block.get('offset', 0.0))
                # a DECLARED spread on the gain. Optional, because
                # most couplings are declared without one and an engine that
                # required it would be asking for a number nobody has. Absent
                # means undeclared, which is reported, not treated as zero.
                # `gain_sigma: estimate` declares that a spread
                # EXISTS and withholds the number, exactly as `gain: estimate`
                # does for the magnitude. The transition projects its gain as
                # normal and carries NO interval until a fitted spread is
                # adopted, because a band nobody has supplied is not a band of
                # zero width.
                sigma_estimated = (
                    isinstance(block.get('gain_sigma'), str)
                    and block['gain_sigma'].strip().lower()
                    == ESTIMATE_SENTINEL)
                gain_sigma = (0.0 if sigma_estimated
                              else float(block.get('gain_sigma', 0.0)))
            except (TypeError, ValueError):
                gaps.append(TopologyGap(
                    gap_type=GapType.MISSING_DECLARATION,
                    location=location,
                    description=(
                        f"transition[{index}] declares a non-numeric gain "
                        f"{block.get('gain')!r}"),
                    discovered_during="build",
                ))
                continue
            if gain_sigma < 0.0:
                # REFUSED, not clamped. A negative standard deviation is not a
                # small one; it is a declaration the author did not mean, and
                # silently taking its absolute value would hide a typo inside
                # an interval a reader is meant to act on.
                gaps.append(TopologyGap(
                    gap_type=GapType.MISSING_DECLARATION,
                    location=location,
                    description=(
                        f"transition[{index}] declares "
                        f"gain_sigma {gain_sigma:g}, which is negative; a "
                        f"standard deviation cannot be"),
                    discovered_during="build",
                ))
                continue
            transitions.append(Transition(
                from_property=str(block['from']),
                to_property=str(block['to']),
                gain=gain,
                source=str(block['source']),
                estimated=estimated,
                gain_sigma=gain_sigma,
                sigma_estimated=sigma_estimated,
                offset=offset,
                clamp_to_bounds=bool(block.get('clamp_to_bounds', False)),
            ))
        return transitions, gaps

    def _index_rules(
        self, rules: List[Dict],
    ) -> Dict[Tuple[str, str, str], Dict]:
        """Index relationship rules by (source_type, target_type, type)."""
        index: Dict[Tuple[str, str, str], Dict] = {}
        for rule in rules:
            key = (
                rule.get('source_type', ''),
                rule.get('target_type', ''),
                rule.get('type', ''),
            )
            index[key] = rule
        return index

    def _build_edge(
        self,
        source_id: str,
        target_id: str,
        rel_type: str,
        source_entity: Optional[Entity],
        target_entity: Optional[Entity],
        rules_by_key: Dict,
        temporal_store: Optional[TemporalAnnotationStore],
        learned_weights: Optional[Dict[Tuple[str, str], LearnedWeight]],
    ) -> TwinEdge:
        """Build a TwinEdge with enrichment from YAML, temporal, weights."""
        source_type = source_entity.type if source_entity else ""
        target_type = target_entity.type if target_entity else ""
        rule = rules_by_key.get((source_type, target_type, rel_type), {})

        # Edge direction
        dir_str = rule.get('edge_direction', 'structural')
        try:
            direction = EdgeDirection(dir_str)
        except ValueError:
            direction = EdgeDirection.STRUCTURAL

        # Flow type
        flow_type = None
        ft_str = rule.get('flow_type')
        if ft_str:
            try:
                flow_type = FlowType(ft_str)
            except ValueError:
                pass
            if direction == EdgeDirection.STRUCTURAL:
                direction = EdgeDirection.FLOW

        # Temporal annotations
        prop_delay = 60.0
        time_const = 60.0
        coupling = 1.0
        resp_model = ResponseModel.EXPONENTIAL
        if temporal_store:
            te = temporal_store.get(source_type, target_type, rel_type)
            if te:
                prop_delay = te.propagation_delay_s
                time_const = te.time_constant_s
                coupling = te.coupling_strength
                resp_model = te.response_model

        temporal_block = rule.get('temporal', {})
        if temporal_block:
            prop_delay = float(
                temporal_block.get('propagation_delay_s', prop_delay)
            )
            time_const = float(
                temporal_block.get('time_constant_s', time_const)
            )
            coupling = float(
                temporal_block.get('coupling_strength', coupling)
            )
            rm_str = temporal_block.get('response_model', resp_model.value)
            try:
                resp_model = ResponseModel(rm_str)
            except ValueError:
                pass

        # Learned weights
        prop_prob = 0.3
        obs_count = 0
        lw = 1.0
        if learned_weights:
            pair_weight = learned_weights.get((source_id, target_id))
            if pair_weight and pair_weight.is_reliable:
                prop_prob = pair_weight.probability
                obs_count = pair_weight.total_source_occurrences
                lw = pair_weight.probability

        conservation_tol = float(rule.get('conservation_tolerance', 0.05))

        # declared value dynamics. The gaps ride on the edge so the
        # traverser can report a refused block at the point a caller asks for
        # the value it would have produced.
        transitions, transition_gaps = self._transitions_from_rule(
            rule or {}, source_id, target_id)

        return TwinEdge(
            source_id=source_id,
            target_id=target_id,
            relation_type=rel_type,
            direction=direction,
            propagation_probability=prop_prob,
            propagation_delay_s=prop_delay,
            time_constant_s=time_const,
            response_model=resp_model,
            coupling_strength=coupling,
            flow_type=flow_type,
            conservation=flow_type is not None,
            conservation_tolerance=conservation_tol,
            learned_weight=lw,
            observation_count=obs_count,
            confidence=1.0 if rule else 0.5,
            source=EdgeSource.YAML if rule else EdgeSource.AUTO_DISCOVERY,
            transitions=transitions,
            gaps=transition_gaps,
        )

    def _detect_unobserved_target_types(
        self,
        topology: DigitalTwinTopology,
        indicators_by_type: Dict,
    ) -> None:
        """A declared relationship whose target type was never seen.

        Implements the decision. The model states that entities of one
        type must relate to entities of another; **not one instance of that
        other type has ever been observed**. That is not a violated invariant
        — the cardinality check never ran — so it is never a finding. It is a
        question, and the model has already written it down.

        Why this needs its own pass: the loops above iterate
        ``topology.nodes``, so a type with zero instances is invisible to them
        — there is nothing to iterate. The absence is exactly what matters.

        On the reference VPS disk incident this is the whole diagnosis: the model said
        a filesystem must have consumers, none was ever observed, and the
        system watched the disk fill without asking what was writing.

        **Deduplicated (target type, relation)**, not per entity, per the
        decision's off-ramp 2 — a domain with 500 filesystems must ask once,
        not 500 times.
        """
        observed_types = {node.entity.type for node in topology.nodes.values()}
        seen: set = set()
        for source_type, specs in (indicators_by_type or {}).items():
            for spec in specs or ():
                if _indicator_field(spec, 'type') != 'RELATIONSHIP':
                    continue
                target = _indicator_field(spec, 'target_type')
                # A cardinality floor of 0 declares no requirement, so an
                # absent target is not a gap — the same reasoning
                # applied to unconfigured CONNECTIVITY.
                if not target or not _min_cardinality(spec):
                    continue
                if target in observed_types:
                    continue
                relation = _indicator_field(spec, 'relation_type') or \
                    _indicator_field(spec, 'name')
                key = (target, relation)
                if key in seen:
                    continue
                seen.add(key)
                gap = TopologyGap(
                    gap_type=GapType.MISSING_NODE,
                    location=f"{source_type}.{relation} -> {target}",
                    description=(
                        f"No entity of type {target!r} has ever been observed, "
                        f"but {source_type} declares a required {relation} "
                        f"relationship to one"
                    ),
                    # Never LLM_INFER: an invented consumer is worse than an
                    # absent one.
                    suggested_strategy=ResolutionStrategy.HUMAN_PROVIDE,
                )
                topology.gaps.append(gap)

    def _detect_structural_gaps(
        self,
        topology: DigitalTwinTopology,
        indicators_by_type: Dict,
        entities: Dict[str, Entity],
    ) -> None:
        """Detect gaps: orphan nodes, missing properties, unobserved types."""
        self._detect_unobserved_target_types(topology, indicators_by_type)
        for entity_id, node in topology.nodes.items():
            # Orphan check
            outgoing = topology.edges.get(entity_id, [])
            incoming = topology.reverse_edges.get(entity_id, [])
            if not outgoing and not incoming:
                gap = TopologyGap(
                    gap_type=GapType.MISSING_EDGE,
                    location=entity_id,
                    description=(
                        f"Orphan entity {entity_id} has no relationships"
                    ),
                    suggested_strategy=ResolutionStrategy.AUTO_DISCOVER,
                )
                node.gaps.append(gap)
                topology.gaps.append(gap)

            # Missing property check vs indicators
            type_indicators = indicators_by_type.get(node.entity.type, [])
            for ind in type_indicators:
                # accept `IndicatorSpec` alongside raw dicts, the
                # same seam that an internal ruling removed from the ontology loader. The
                # engine's own API holds a typed `DomainModel`, so requiring
                # dicts here is what kept gap discovery on the YAML path only.
                prop_name = _indicator_field(ind, 'name')
                if _indicator_field(ind, 'type') in ('NUMERIC', 'STATE'):
                    if prop_name and prop_name not in node.entity.properties:
                        gap = TopologyGap(
                            gap_type=GapType.MISSING_PROPERTY,
                            location=f"{entity_id}.{prop_name}",
                            description=(
                                f"Missing expected property {prop_name} "
                                f"on {entity_id}"
                            ),
                            suggested_strategy=ResolutionStrategy.AUTO_DISCOVER,
                        )
                        node.gaps.append(gap)
                        topology.gaps.append(gap)
