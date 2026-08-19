"""
Ontology loader for RDF/TTL files.

This module handles loading and parsing ontologies using rdflib.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Set
from datetime import timedelta

try:
    from rdflib import Graph, Namespace, URIRef, Literal
    from rdflib.namespace import RDF, RDFS, OWL, XSD
    HAS_RDFLIB = True
except ImportError:
    HAS_RDFLIB = False
    Graph = None
    Namespace = None
    URIRef = None

from ..interfaces import IndicatorSpec
from ..types import Axiom, IndicatorType, Severity

logger = logging.getLogger(__name__)

# Define namespaces
if HAS_RDFLIB:
    HEALTH = Namespace("http://example.org/health#")
    AXIOM = Namespace("http://example.org/axiom#")
    K8S = Namespace("http://example.org/k8s#")


# (implements): HOMEOSTASIS direction allow-list.
# Module-level frozenset for grep-auditability + family-loader-warn
# pattern (typos surface in operator logs but don't crash YAML parse).
_VALID_HOMEOSTASIS_DIRECTIONS = frozenset({"UPPER", "LOWER", "BIDIRECTIONAL"})


class OntologyLoader:
    """
    Load and query RDF/TTL ontologies.

    Supports:
    - Loading meta-ontology (health concepts)
    - Loading domain ontology (K8s, OpenBMC, etc.)
    - Querying health indicators by entity type
    - Extracting threshold and state configurations
    """

    def __init__(self, builtin_k8s_indicators: bool = True):
        """
        Args:
            builtin_k8s_indicators: whether an entity type with no
                declared indicators falls back to the hardcoded Kubernetes set
                (``Pod``/``restartCount``, ``Node``/``cpuUsage``,...).
                Defaults ``True`` so the platform is unchanged. **The extracted
                engine sets this ``False``**: a library that invents indicators
                its user never declared cannot claim to be domain-agnostic, and
                the seed is domain-specific behaviour in a shared component.
        """
        if not HAS_RDFLIB:
            # `info`, not `warning`, and worded as a configuration
            # rather than a failure. `rdflib` is an optional dependency and is
            # deliberately OUT of the extracted engine's scope, so its absence
            # is the intended state for every engine user rather than a
            # degraded one. As a warning on the first line of output it read as
            # a defect to anyone running the demo for the first time, which is
            # the audience least able to tell the difference.
            logger.info(
                "rdflib is not installed; using the built-in ontology loader. "
                "This is the supported default — rdflib is optional.")
            self.graph = None
        else:
            self.graph = Graph()

        self.meta_loaded = False
        self.domain_loaded = False
        self._builtin_k8s_indicators = builtin_k8s_indicators
        self._indicator_cache: Dict[str, List[IndicatorSpec]] = {}
        # dedup tracker so the rejection WARN fires once per
        # distinct malformed key rather than on every write attempt.
        self._malformed_indicator_keys_warned: Set[str] = set()

    @staticmethod
    def _is_valid_indicator_cache_key(key: str) -> bool:
        """reject malformed indicator-cache keys.

        Empty bare keys (``""``) and namespaced keys whose ``:``-
        partitioned segments are empty (``":"``, ``"k8s:"``,
        ``":Pod"``) poison the lookup path in ``get_indicators`` /
        ``has_indicators``: ``partition(':')`` on such a key produces
        an empty ``key_type``, which compares equal to a caller-
        supplied empty ``target_lower_ns`` (e.g. when ``entity_type=""``
        is passed) and silently returns the malformed entry's specs.

        Pre-fix one malformed cache entry could poison every future
        empty-target lookup. Post-fix the writer rejects the malformed
        key with a single WARN per distinct bad key (dedup tracker),
        and the lookup loops defensively skip any malformed entry that
        might still be present (e.g. tests injecting directly into
        ``_indicator_cache``).

        Returns True for well-formed keys (non-empty bare keys, or
        namespaced keys with both segments non-empty).
        """
        if not key:
            return False
        if ':' in key:
            domain, _, entity_type = key.partition(':')
            if not domain or not entity_type:
                return False
        return True

    def _write_indicator_cache(
        self, key: str, value: List[IndicatorSpec]
    ) -> bool:
        """gate-checked write into ``_indicator_cache``.

        Returns True when the write succeeded (key was well-formed),
        False when the key was rejected as malformed. Dedup-WARNs
        each distinct malformed key once.
        """
        if not self._is_valid_indicator_cache_key(key):
            if key not in self._malformed_indicator_keys_warned:
                self._malformed_indicator_keys_warned.add(key)
                logger.warning(
                    "OntologyLoader rejected malformed "
                    "indicator-cache key %r — empty bare key or "
                    "namespaced key with empty segment poisons lookups "
                    "(get_indicators matches empty target_lower_ns "
                    "against empty key_type). Caller stack should "
                    "supply a non-empty entity_type before reaching "
                    "this write site.",
                    key,
                )
            return False
        self._indicator_cache[key] = value
        return True

    def load_meta_ontology(self, path: str) -> bool:
        """Load the health meta-ontology."""
        if not HAS_RDFLIB:
            return self._load_fallback_meta()

        try:
            path = Path(path)
            if path.exists():
                self.graph.parse(str(path), format='turtle')
                self.meta_loaded = True
                logger.info(f"Loaded meta-ontology from {path}")
                return True
            else:
                logger.warning(f"Meta-ontology not found: {path}")
                return self._load_fallback_meta()
        except Exception as e:
            logger.error(f"Failed to load meta-ontology: {e}")
            return self._load_fallback_meta()

    def load_domain_ontology(self, path: str) -> bool:
        """Load a domain-specific ontology."""
        if not HAS_RDFLIB:
            return self._load_fallback_domain()

        try:
            path = Path(path)
            if path.exists():
                self.graph.parse(str(path), format='turtle')
                self.domain_loaded = True
                self._indicator_cache.clear()
                logger.info(f"Loaded domain ontology from {path}")
                return True
            else:
                logger.warning(f"Domain ontology not found: {path}")
                return self._load_fallback_domain()
        except Exception as e:
            logger.error(f"Failed to load domain ontology: {e}")
            return self._load_fallback_domain()

    def _load_fallback_meta(self) -> bool:
        """Load fallback meta-ontology (hardcoded defaults)."""
        self.meta_loaded = True
        logger.info("Using fallback meta-ontology")
        return True

    def _load_fallback_domain(self) -> bool:
        """Load fallback domain ontology with K8s defaults.

        gated on ``builtin_k8s_indicators``. Seeding the cache is the
        second half of the same defect as ``_get_fallback_indicators`` — it
        pre-populates every K8s type before any domain is loaded, so the
        indicators are present even for a caller that asked for a different
        domain entirely.
        """
        self.domain_loaded = True
        if self._builtin_k8s_indicators:
            self._indicator_cache = self._get_k8s_default_indicators()
            logger.info("Using fallback K8s domain ontology")
        else:
            logger.info(
                "Using fallback domain ontology with no built-in indicators "
                "(builtin_k8s_indicators=False)")
        return True

    def get_indicators(self, entity_type: str, domain_id: str = '') -> List[IndicatorSpec]:
        """Get health indicators for an entity type.

        First looks up {domain_id}:{entity_type} to preserve per-domain
        indicator isolation when two domains share the same entity type name.
        Falls back to bare entity_type for backward compatibility.

        When the cache holds both 'Pod' (YAML, capital) and 'pod'
        (auto-discovery, lowercase), this returns the UNION rather than
        the first match — so YAML-declared indicators (responseLatency,
        phase, scheduledOn) coexist with auto-discovered ones for the
        same entity type. YAML wins on name conflict.

        Both the namespaced and bare lookups are now
        case-insensitive. previously the namespaced shortcut
        (``{domain_id}:{entity_type}``) used direct dict membership
        which silently missed when YAML stored ``'k8s:Pod'`` and the
        caller queried ``('pod', 'k8s')`` (or vice versa) — control
        then fell through to the bare case-union which aggregated
        across **all** domains, breaking the per-domain isolation the
        namespaced path was meant to provide.
        """
        # Namespaced lookup with case-insensitive prefix.
        # If any case-equivalent namespaced key exists (even with empty
        # specs), short-circuit with the accumulated union. An empty
        # namespaced bucket carries the explicit "this domain has nothing
        # for this type" signal — fall-through to the bare case-union
        # would aggregate other domains' specs and leak across isolation.
        if domain_id:
            domain_lower = domain_id.lower()
            target_lower_ns = entity_type.lower()
            ns_union: List[IndicatorSpec] = []
            ns_seen_names: Set[str] = set()
            ns_matched = False
            for cached_key, specs in self._indicator_cache.items():
                # skip malformed keys (empty bare / empty
                # namespaced segment) that might have been injected
                # directly into the cache (tests, legacy paths). The
                # writer-side gate at ``_write_indicator_cache``
                # prevents new ones; this is the defensive read-side
                # complement.
                if not self._is_valid_indicator_cache_key(cached_key):
                    continue
                if ':' not in cached_key:
                    continue
                key_domain, _, key_type = cached_key.partition(':')
                if key_domain.lower() != domain_lower:
                    continue
                if key_type.lower() != target_lower_ns:
                    continue
                ns_matched = True
                for spec in specs:
                    if spec.name in ns_seen_names:
                        continue
                    ns_seen_names.add(spec.name)
                    ns_union.append(spec)
            if ns_matched:
                return ns_union

        # union all case-equivalent unnamespaced keys so YAML
        # ('Pod') and auto-discovery ('pod') results coexist.
        target_lower = entity_type.lower()
        union: List[IndicatorSpec] = []
        seen_names = set()
        for cached_key, specs in self._indicator_cache.items():
            # defense: skip malformed cache keys.
            if not self._is_valid_indicator_cache_key(cached_key):
                continue
            if ':' in cached_key:
                continue
            if cached_key.lower() != target_lower:
                continue
            for spec in specs:
                if spec.name in seen_names:
                    continue
                seen_names.add(spec.name)
                union.append(spec)
        if union:
            return union

        if not HAS_RDFLIB or not self.graph:
            return self._get_fallback_indicators(entity_type)

        indicators = []
        try:
            # Find entity class in ontology
            entity_class = self._get_entity_class(entity_type)
            if not entity_class:
                return self._get_fallback_indicators(entity_type)

            # Get indicators for this entity type
            for indicator in self.graph.objects(entity_class, HEALTH.hasIndicator):
                spec = self._parse_indicator(indicator)
                if spec:
                    indicators.append(spec)

        except Exception as e:
            logger.error(f"Error getting indicators for {entity_type}: {e}")
            return self._get_fallback_indicators(entity_type)

        # gate-checked write rejects malformed keys with a
        # single WARN per distinct bad key.
        self._write_indicator_cache(entity_type, indicators)
        return indicators

    def _get_entity_class(self, entity_type: str) -> Optional[URIRef]:
        """Look up entity class in ontology by type name."""
        if not HAS_RDFLIB:
            return None

        # Try common namespaces
        for ns in [K8S, HEALTH]:
            uri = ns[entity_type]
            if (uri, RDF.type, OWL.Class) in self.graph:
                return uri
            if (uri, RDF.type, RDFS.Class) in self.graph:
                return uri

        # Try case-insensitive search
        for s, p, o in self.graph.triples((None, RDF.type, OWL.Class)):
            if str(s).lower().endswith(entity_type.lower()):
                return s

        return None

    def _parse_indicator(self, indicator_uri: URIRef) -> Optional[IndicatorSpec]:
        """Parse indicator specification from ontology."""
        if not HAS_RDFLIB:
            return None

        try:
            # Get indicator type
            indicator_type = self._get_indicator_type(indicator_uri)

            # Get indicator name (local part of URI)
            name = str(indicator_uri).split('#')[-1].split('/')[-1]

            # Get relevant axioms
            axioms = []
            for axiom in self.graph.objects(indicator_uri, HEALTH.relevantAxiom):
                axiom_name = str(axiom).split('#')[-1].split('/')[-1]
                try:
                    axioms.append(Axiom(axiom_name.upper()))
                except ValueError:
                    pass

            spec = IndicatorSpec(
                uri=str(indicator_uri),
                name=name,
                indicator_type=indicator_type,
                relevant_axioms=axioms,
            )

            # Parse type-specific fields
            if indicator_type == IndicatorType.NUMERIC:
                spec.warning_threshold = self._get_float(indicator_uri, HEALTH.warningThreshold)
                spec.critical_threshold = self._get_float(indicator_uri, HEALTH.criticalThreshold)
                # the third loader. A field carried by two of the
                # three input formats is the shape that reads as supported and
                # is not, in whichever format the reader happened not to use.
                spec.lower_warning_threshold = self._get_float(
                    indicator_uri, HEALTH.lowerWarningThreshold)
                spec.lower_critical_threshold = self._get_float(
                    indicator_uri, HEALTH.lowerCriticalThreshold)
                spec.time_window = self._get_duration(indicator_uri, HEALTH.timeWindow)

            elif indicator_type == IndicatorType.STATE:
                spec.normal_states = self._get_list(indicator_uri, HEALTH.normalStates)
                spec.transient_states = self._get_list(indicator_uri, HEALTH.transientStates)
                spec.problematic_states = self._get_list(indicator_uri, HEALTH.problematicStates)
                spec.transient_timeout = self._get_duration(indicator_uri, HEALTH.transientTimeout)

            elif indicator_type == IndicatorType.RELATIONSHIP:
                spec.target_type = self._get_string(indicator_uri, HEALTH.targetType)
                spec.min_cardinality = self._get_int(indicator_uri, HEALTH.minCardinality) or 0
                spec.max_cardinality = self._get_int(indicator_uri, HEALTH.maxCardinality)
                severity_str = self._get_string(indicator_uri, HEALTH.violationSeverity)
                if severity_str:
                    try:
                        spec.violation_severity = Severity(severity_str.lower())
                    except ValueError:
                        pass

            return spec

        except Exception as e:
            logger.error(f"Error parsing indicator {indicator_uri}: {e}")
            return None

    def _get_indicator_type(self, indicator_uri: URIRef) -> IndicatorType:
        """Determine indicator type from ontology."""
        if not HAS_RDFLIB:
            return IndicatorType.NUMERIC

        # Check explicit type
        for type_uri in self.graph.objects(indicator_uri, RDF.type):
            type_str = str(type_uri).lower()
            if 'numeric' in type_str:
                return IndicatorType.NUMERIC
            elif 'state' in type_str:
                return IndicatorType.STATE
            elif 'relationship' in type_str:
                return IndicatorType.RELATIONSHIP
            elif 'timestamp' in type_str:
                return IndicatorType.TIMESTAMP

        # Infer from properties
        # the floor pair counts as evidence of a numeric indicator
        # too. Testing only the ceiling would classify an indicator declaring
        # nothing but a floor as STATE or RELATIONSHIP, and BOUNDEDNESS then
        # declines it for the wrong indicator type.
        for predicate in (HEALTH.warningThreshold, HEALTH.criticalThreshold,
                          HEALTH.lowerWarningThreshold,
                          HEALTH.lowerCriticalThreshold):
            if self._get_float(indicator_uri, predicate) is not None:
                return IndicatorType.NUMERIC
        if self._get_list(indicator_uri, HEALTH.normalStates):
            return IndicatorType.STATE
        if self._get_string(indicator_uri, HEALTH.targetType):
            return IndicatorType.RELATIONSHIP

        return IndicatorType.NUMERIC

    def _get_float(self, uri: URIRef, predicate: URIRef) -> Optional[float]:
        """Extract float value from ontology."""
        if not HAS_RDFLIB:
            return None
        for obj in self.graph.objects(uri, predicate):
            try:
                return float(obj)
            except (TypeError, ValueError):
                pass
        return None

    def _get_int(self, uri: URIRef, predicate: URIRef) -> Optional[int]:
        """Extract int value from ontology."""
        if not HAS_RDFLIB:
            return None
        for obj in self.graph.objects(uri, predicate):
            try:
                return int(obj)
            except (TypeError, ValueError):
                pass
        return None

    def _get_string(self, uri: URIRef, predicate: URIRef) -> Optional[str]:
        """Extract string value from ontology."""
        if not HAS_RDFLIB:
            return None
        for obj in self.graph.objects(uri, predicate):
            return str(obj)
        return None

    def _get_list(self, uri: URIRef, predicate: URIRef) -> List[str]:
        """Extract list value from ontology (RDF collection or multiple values)."""
        if not HAS_RDFLIB:
            return []

        values = []
        for obj in self.graph.objects(uri, predicate):
            # Handle RDF collection
            if isinstance(obj, URIRef):
                # Try to parse as list
                for item in self.graph.items(obj):
                    values.append(str(item))
            else:
                values.append(str(obj))
        return values

    def _get_duration(self, uri: URIRef, predicate: URIRef) -> Optional[timedelta]:
        """Parse xsd:duration to Python timedelta."""
        if not HAS_RDFLIB:
            return None

        for obj in self.graph.objects(uri, predicate):
            duration_str = str(obj)
            return self._parse_duration(duration_str)
        return None

    def _parse_duration(self, duration_str: str) -> Optional[timedelta]:
        """Parse ISO 8601 duration string."""
        if not duration_str:
            return None

        # Handle PT1H30M format
        import re
        match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration_str, re.IGNORECASE)
        if match:
            hours = int(match.group(1) or 0)
            minutes = int(match.group(2) or 0)
            seconds = int(match.group(3) or 0)
            return timedelta(hours=hours, minutes=minutes, seconds=seconds)

        # Handle simple formats
        match = re.match(r'(\d+)\s*([smhd])', duration_str.lower())
        if match:
            value = int(match.group(1))
            unit = match.group(2)
            if unit == 's':
                return timedelta(seconds=value)
            elif unit == 'm':
                return timedelta(minutes=value)
            elif unit == 'h':
                return timedelta(hours=value)
            elif unit == 'd':
                return timedelta(days=value)

        return None

    def set_domain_indicators(self, indicators: Dict[str, list],
                              property_mapping: Optional[Dict[str, Dict[str, str]]] = None,
                              merge: bool = True) -> int:
        """
        Load indicators from domain YAML config into the cache.

        when called multiple times for the same entity_type (e.g.
        first by YAML load, then by `_inject_discovered_indicators`), the
        default merge=True preserves earlier specs and appends new ones,
        with existing-name specs taking precedence (YAML wins on conflict).
        Pass merge=False to fully replace the cache for the given types.

        previously behavior was always replace, which silently wiped the
        YAML indicators (responseLatency, phase, scheduledOn, etc.) the
        first time auto-discovery injected anything for the same type.

        Args:
            indicators: Dict mapping entity_type -> list of indicator dicts
            property_mapping: Optional dict mapping entity_type -> {indicator_name -> property_name}
            merge: If True, append to existing cache (preserving earlier
                specs by name); if False, replace the cache for these types.

        Returns:
            Number of indicators loaded
        """
        count = 0
        for entity_type, indicator_list in indicators.items():
            type_mapping = (property_mapping or {}).get(entity_type, {})
            specs = []
            for data in indicator_list:
                # accept an already-parsed IndicatorSpec as well as a
                # raw dict. `domain_loader.load_domain()` emits
                # specs, this method expected dicts, and feeding one to the
                # other raised `AttributeError: 'IndicatorSpec' object has no
                # attribute 'get'` — so the engine-shaped loader was written
                # and unreachable, with no non-test caller.
                #
                # Widening the ingestion rather than making the loader emit
                # dicts: specs are the typed form the checkers consume, and
                # round-tripping typed -> dict -> typed exists only to satisfy
                # a parser the caller does not need.
                if isinstance(data, IndicatorSpec):
                    specs.append(data)
                    count += 1
                    continue
                spec = self._parse_yaml_indicator(data, entity_type, type_mapping)
                if spec:
                    specs.append(spec)
                    count += 1
            if not specs:
                continue
            if merge and entity_type in self._indicator_cache:
                existing = self._indicator_cache[entity_type]
                existing_names = {s.name for s in existing}
                # Append only specs whose name isn't already present.
                # Earlier-loaded specs (typically YAML) win on conflict.
                additions = [s for s in specs if s.name not in existing_names]
                # gate (no-op when entity_type already passed
                # the gate via the prior insertion, but kept for the
                # case where ``entity_type in cache`` happened via
                # direct injection that bypassed the writer).
                self._write_indicator_cache(
                    entity_type, list(existing) + additions
                )
            else:
                self._write_indicator_cache(entity_type, specs)
        logger.info(f"Loaded {count} domain indicators for {len(indicators)} entity types (merge={merge})")
        return count

    def has_indicators(self, entity_type: str) -> bool:
        """Check if entity type has configured indicators.

        Used by discovery engine to decide whether to auto-generate indicators.

        Now case-insensitive to mirror ``get_indicators``. Pre-fix
        ``has_indicators('pod')`` returned False even when the cache held
        ``'Pod'`` (YAML), inviting auto-discovery to overwrite curated
        specs because the caller couldn't see them.
        """
        target_lower = entity_type.lower()
        for cached_key, specs in self._indicator_cache.items():
            # defense: skip malformed cache keys.
            if not self._is_valid_indicator_cache_key(cached_key):
                continue
            if ':' in cached_key:
                continue
            if cached_key.lower() != target_lower:
                continue
            if specs:
                return True
        return False

    def _parse_yaml_indicator(self, data: Dict, entity_type: str,
                              type_mapping: Optional[Dict[str, str]] = None) -> Optional[IndicatorSpec]:
        """Parse a single indicator from YAML dict format."""
        try:
            name = data['name']
            property_name = (type_mapping or {}).get(name, name)
            ind_type_str = data.get('type', 'NUMERIC').upper()
            ind_type = IndicatorType[ind_type_str] if ind_type_str in IndicatorType.__members__ else IndicatorType.NUMERIC

            # Parse axioms
            axiom_list = []
            for a in data.get('axioms', []):
                try:
                    axiom_list.append(Axiom(a.upper()))
                except (ValueError, KeyError):
                    pass

            # Parse time window
            window = self._parse_duration(data.get('window', '1h')) or timedelta(hours=1)
            timeout = self._parse_duration(data.get('timeout', '5m')) or timedelta(minutes=5)

            # (implements): HOMEOSTASIS direction field.
            # Defaults to BIDIRECTIONAL (previously behavior). Unrecognized
            # values WARN + fall back to BIDIRECTIONAL (family-loader
            # pattern: typos surface but never crash the parse).
            direction = self._resolve_direction(data.get('direction'), name)

            return IndicatorSpec(
                uri=f"domain:{entity_type}.{name}",
                name=name,
                property_name=property_name,
                indicator_type=ind_type,
                relevant_axioms=axiom_list,
                # absent means None, not 0.0. With 0.0 the
                # BOUNDEDNESS `is not None` test treated every non-negative
                # reading as at-or-above critical, so a healthy Deployment
                # fired CRITICAL. See `domain_loader._resolve_threshold` for
                # the audit that overturned the previous default.
                warning_threshold=(
                    float(data['warning']) if data.get('warning') is not None
                    else None),
                critical_threshold=(
                    float(data['critical']) if data.get('critical') is not None
                    else None),
                # the floor pair, here for the reason that
                # gives for the nested blocks: fixing one loader and not the
                # other leaves the extracted package shipping the gap this
                # closes.
                lower_warning_threshold=(
                    float(data['lower_warning'])
                    if data.get('lower_warning') is not None else None),
                lower_critical_threshold=(
                    float(data['lower_critical'])
                    if data.get('lower_critical') is not None else None),
                time_window=window,
                normal_states=data.get('normal', []),
                transient_states=data.get('transient', []),
                problematic_states=data.get('bad', []),
                transient_timeout=timeout,
                target_type=data.get('target_type', ''),
                relation_type=data.get('relation_type', ''),
                min_cardinality=data.get('min_cardinality', 0),
                max_cardinality=data.get('max_cardinality', 0),
                violation_severity=Severity[data['violation_severity'].upper()] if data.get('violation_severity') else Severity.HIGH,
                required_property=data.get('required_property') or None,
                direction=direction,
                # nested per-axiom blocks. Without these the two
                # axioms were declarable but not configurable — CONSERVATION
                # fell through to a degenerate name-matching path and
                # MONOTONICITY silently assumed increasing/allow_reset.
                conservation_config=data.get('conservation') or None,
                monotonicity_config=data.get('monotonicity') or None,
                # the third loader gets it too; a field carried by
                # one of the two YAML paths reads as supported and is not.
                consistency_config=data.get('consistency') or None,
                stability_config=data.get('stability') or None,   #
            )
        except Exception as e:
            # `data.get` assumes a dict, so a non-dict argument made
            # the HANDLER raise, replacing a logged skip with an exception out
            # of a function whose contract is to return None on bad input. A
            # failure path that can fail is worse than no failure path: it
            # turns one malformed indicator into a lost detection pass.
            name = data.get('name', '?') if isinstance(data, dict) else repr(data)[:60]
            logger.warning("Failed to parse indicator %s: %s", name, e)
            return None

    @staticmethod
    def _resolve_direction(raw: Optional[str], indicator_name: str = "") -> str:
        """ (implements): validate direction field.

        Case-insensitive lookup against ``_VALID_HOMEOSTASIS_DIRECTIONS``;
        defaults to ``BIDIRECTIONAL`` (previously behavior) when unset.
        Typos / unrecognized values WARN with the offending value + the
        sorted valid set + the indicator name for grep-findability (context-rich-WARN pattern), then fall back to default. The parse
        never crashes on a bad direction value.
        """
        if raw is None or raw == "":
            return "BIDIRECTIONAL"
        normalized = str(raw).upper()
        if normalized in _VALID_HOMEOSTASIS_DIRECTIONS:
            return normalized
        logger.warning(
            "unknown HOMEOSTASIS direction %r on indicator %r — "
            "valid values: %s — falling back to BIDIRECTIONAL",
            raw, indicator_name,
            ", ".join(sorted(_VALID_HOMEOSTASIS_DIRECTIONS)),
        )
        return "BIDIRECTIONAL"

    def _get_fallback_indicators(self, entity_type: str) -> List[IndicatorSpec]:
        """Get fallback indicators when ontology is not available.

        this ended by returning **hardcoded Kubernetes indicators**
        for any entity type it did not recognise, so a domain that declared no
        indicators for ``Pod`` still got ``restartCount`` and ``phase``
        evaluated against it. Reached in the default configuration, not a rare
        one — ``rdflib`` is not installed, so the caller's
        ``if not HAS_RDFLIB`` branch routes here for every undeclared type.

        Inventing indicators the user never declared is the opposite of what
        this engine claims to do, and it is domain-specific behaviour living in
        a shared component, which the project's design guidance forbids outright. The seed is now
        opt-in via ``builtin_k8s_indicators``.
        """
        # Check domain-loaded indicators first. defense: also
        # validate the key shape so a poison ``""`` cache entry can't
        # short-circuit when caller queried ``entity_type=""``.
        if (
            entity_type in self._indicator_cache
            and self._is_valid_indicator_cache_key(entity_type)
        ):
            return self._indicator_cache[entity_type]
        if not self._builtin_k8s_indicators:
            return []
        defaults = self._get_k8s_default_indicators()
        return defaults.get(entity_type, [])

    def _get_k8s_default_indicators(self) -> Dict[str, List[IndicatorSpec]]:
        """Get default K8s indicators (fallback when no ontology)."""
        return {
            'Pod': [
                IndicatorSpec(
                    uri='k8s:restartCount',
                    name='restartCount',
                    indicator_type=IndicatorType.NUMERIC,
                    relevant_axioms=[Axiom.STABILITY, Axiom.BOUNDEDNESS, Axiom.HOMEOSTASIS],
                    warning_threshold=3,
                    critical_threshold=10,
                    time_window=timedelta(hours=1),
                ),
                IndicatorSpec(
                    uri='k8s:phase',
                    name='phase',
                    indicator_type=IndicatorType.STATE,
                    relevant_axioms=[Axiom.STABILITY, Axiom.CONSISTENCY],
                    normal_states=['Running'],
                    transient_states=['Pending', 'ContainerCreating'],
                    problematic_states=['Failed', 'Unknown'],
                    transient_timeout=timedelta(minutes=5),
                ),
                IndicatorSpec(
                    uri='k8s:scheduledOn',
                    name='scheduledOn',
                    indicator_type=IndicatorType.RELATIONSHIP,
                    relevant_axioms=[Axiom.CONNECTIVITY],
                    target_type='Node',
                    relation_type='scheduledOn',
                    min_cardinality=1,
                    violation_severity=Severity.CRITICAL,
                ),
            ],
            'Node': [
                IndicatorSpec(
                    uri='k8s:cpuUsage',
                    name='cpuUsage',
                    indicator_type=IndicatorType.NUMERIC,
                    relevant_axioms=[Axiom.BOUNDEDNESS, Axiom.HOMEOSTASIS],
                    warning_threshold=80,
                    critical_threshold=95,
                ),
                IndicatorSpec(
                    uri='k8s:memoryUsage',
                    name='memoryUsage',
                    indicator_type=IndicatorType.NUMERIC,
                    relevant_axioms=[Axiom.BOUNDEDNESS, Axiom.HOMEOSTASIS],
                    warning_threshold=80,
                    critical_threshold=95,
                ),
                IndicatorSpec(
                    uri='k8s:ready',
                    name='ready',
                    indicator_type=IndicatorType.STATE,
                    relevant_axioms=[Axiom.STABILITY],
                    normal_states=['True'],
                    problematic_states=['False', 'Unknown'],
                ),
            ],
            'Deployment': [
                IndicatorSpec(
                    uri='k8s:availableReplicas',
                    name='availableReplicas',
                    indicator_type=IndicatorType.NUMERIC,
                    relevant_axioms=[Axiom.BOUNDEDNESS],
                ),
                IndicatorSpec(
                    uri='k8s:readyReplicas',
                    name='readyReplicas',
                    indicator_type=IndicatorType.NUMERIC,
                    relevant_axioms=[Axiom.BOUNDEDNESS],
                ),
            ],
            'Service': [
                IndicatorSpec(
                    uri='k8s:hasEndpoints',
                    name='hasEndpoints',
                    indicator_type=IndicatorType.RELATIONSHIP,
                    relevant_axioms=[Axiom.CONNECTIVITY],
                    target_type='Endpoints',
                    relation_type='hasEndpoints',
                    min_cardinality=1,
                    violation_severity=Severity.HIGH,
                ),
            ],
        }
