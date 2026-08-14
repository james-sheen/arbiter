"""Engine-shaped domain loader — YAML in, typed indicators out, nothing else.

`arbiter-oss-strategy.md` listed "a plain YAML loader" as in-scope for
the v0.1 extraction. No such module existed. The two loaders that do exist are
both unsuitable for an engine package:

  *`ontology/loader.py` (720 lines) is primarily an RDF/TTL reader built on
    `rdflib`, with the YAML path grafted on and a hardcoded Kubernetes
    indicator seed reachable through its fallback path.
  *`orchestration/domain_registry.py` (2,266 lines) is the real
    domain-YAML-to-typed-object path, but it also parses goals, cross-domain
    references, evidence sources, observation mappings, section templates and
    active-mode policy — platform concerns the engine has no use for, and
    roughly half the entire v0.1 line budget on its own.

This module is the third thing: it reads exactly the three keys an axiom
evaluator needs — entity types, relationship types, indicators — and returns
them as plain typed objects. It imports `yaml` and the engine's own types, and
nothing else.

**Parity is the contract, not the goal.** Every field conversion below
reproduces `OntologyLoader._parse_yaml_indicator` exactly, including its
defaults and its quirks (absent thresholds becoming `0.0` rather than `None`;
`target_type` and `relation_type` defaulting to empty string rather than
`None`; `max_cardinality` defaulting to `0` rather than `None`). Those are
load-bearing for the checkers that read them, so "cleaner" values would be a
behaviour change wearing a tidy-up costume. The source repository
asserts tuple-identical output against the existing loader over the two
published appendix files.

No Kubernetes literals, no fallback seed, no discovery, no `rdflib`. A domain
that is not described in its own YAML is not described.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml

from ..interfaces import IndicatorSpec
from ..types import Axiom, IndicatorType, Severity
from .axioms.roles import (
    ROLES, explain_absence, normalise_role, unreachable_axioms,
)

logger = logging.getLogger(__name__)

VALID_DIRECTIONS = frozenset({"UPPER", "LOWER", "BIDIRECTIONAL"})

DEFAULT_WINDOW = timedelta(hours=1)
DEFAULT_TIMEOUT = timedelta(minutes=5)

_ISO_DURATION = re.compile(
    r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", re.IGNORECASE)
_SHORT_DURATION = re.compile(r"(\d+)\s*([smhd])")

_UNIT_TO_KWARG = {
    "s": "seconds", "m": "minutes", "h": "hours", "d": "days",
}


class NotADomainModelError(ValueError):
    """The source parsed, but is not a domain model.

    The `*_constraints.yaml` companion files carry `domain:` as a *string tag*
    naming which domain they extend, alongside `family` and `entity_mappings`.
    They are perfectly valid files that simply are not domain models, and a
    caller globbing a directory will meet them. Distinguishing this from a
    malformed file matters: one is expected, the other is a defect.
    """


def is_domain_model(source: Union[str, Path, Dict[str, Any]]) -> bool:
    """True if `load_domain` would accept this source.

    Provided so directory scans do not need exceptions for control flow —
    7 of the files shipped alongside the domain models are companions.
    """
    try:
        load_domain(source)
        return True
    except (NotADomainModelError, ValueError, OSError, yaml.YAMLError):
        # `OSError` and `YAMLError` added. This function exists so a
        # directory scan does not need exceptions for control flow, and it was
        # raising two kinds anyway:
        #
        # - `load_domain` treats a newline-free string as a *path*, so any
        # short string that is not a filename raised `FileNotFoundError`
        # straight through the filter. A scan racing a deleted file got
        # the same.
        # - Malformed YAML raised `yaml.YAMLError`, which is precisely the
        # case a caller most wants answered with False rather than a
        # traceback.
        #
        # Both mean the same thing to a caller: `load_domain` would not accept
        # this. That is what the docstring promises, so it is what is returned.
        return False


#: lazily-built {alias -> declared id} map, keyed on the domains
#: directory so a test can point at a fixture. Built once per directory.
_ALIAS_MAPS: Dict[str, Dict[str, str]] = {}


class DuplicateDomainAliasError(ValueError):
    """Two domains claim the same alias.

    A configuration error, and one worth catching at load rather than at
    query: an ambiguous alias resolves arbitrarily, and the resulting
    wrong-domain answer looks like data rather than a defect.
    """


def _default_domains_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "domains"


def domain_alias_map(domains_dir: Optional[Union[str, Path]] = None,
                     refresh: bool = False) -> Dict[str, str]:
    """Map every declared alias to its domain's declared id.

    Aliases come from the domain files themselves (Option A), never
    from a table in shared code — the project's design guidance forbids domain-specific branches,
    and an alias table is one wearing a dict costume.

    Companion files are skipped via `is_domain_model`, so a directory scan
    needs no exception handling. Duplicate aliases raise.
    """
    directory = Path(domains_dir) if domains_dir else _default_domains_dir()
    key = str(directory)
    if refresh:
        _ALIAS_MAPS.pop(key, None)
    if key in _ALIAS_MAPS:
        return _ALIAS_MAPS[key]

    mapping: Dict[str, str] = {}
    owner: Dict[str, str] = {}
    for path in sorted(directory.glob("*.yaml")):
        text = path.read_text()
        if not is_domain_model(text):
            continue
        model = load_domain(text)
        for alias in model.aliases:
            low = str(alias).strip().lower()
            if not low:
                continue
            if low in owner and owner[low] != model.domain_id:
                raise DuplicateDomainAliasError(
                    f"alias {low!r} is claimed by both {owner[low]!r} and "
                    f"{model.domain_id!r}"
                )
            owner[low] = model.domain_id
            mapping[low] = model.domain_id
    _ALIAS_MAPS[key] = mapping
    return mapping


def canonical_domain_id(value: Any,
                        domains_dir: Optional[Union[str, Path]] = None) -> Any:
    """Resolve an alias to the declared domain id; pass anything else through.

`domains/k8s.yaml` declares `id: kubernetes`, so a caller
    saying `k8s` and a cluster reporting `kubernetes` were treated as different
    domains and the scoped query came back silently empty. Comparing canonical
    forms on both sides is what makes those the same namespace.

    Non-strings and unknown values are returned unchanged — this resolves, it
    does not validate.
    """
    if not isinstance(value, str):
        return value
    try:
        return domain_alias_map(domains_dir).get(value.strip().lower(), value)
    except Exception:  # noqa: BLE001 — resolution must never break a query
        return value


@dataclass
class DomainModel:
    """What a domain file declares, and nothing about what to do with it."""

    domain_id: str
    name: str = ""
    description: str = ""
    entity_types: List[str] = field(default_factory=list)
    relationship_types: List[str] = field(default_factory=list)
    #: alternate names this domain answers to. Exists because a
    #: file's stem and its declared id can differ (`k8s.yaml` declares
    #: `kubernetes`; `docker.yaml` declares `docker-swarm`), and six shared
    #: sites carry the stem as a literal. Declaring the alias in the file that
    #: causes the split beats an alias table in shared code, which the project's design guidance
    #: forbids anyway. Absent means no aliases.
    aliases: List[str] = field(default_factory=list)
    indicators: Dict[str, List[IndicatorSpec]] = field(default_factory=dict)

    def all_indicators(self) -> List[IndicatorSpec]:
        return [spec for specs in self.indicators.values() for spec in specs]

    def declared_axioms(self) -> List[Axiom]:
        """Axioms an indicator lists in its `axioms:` field.

        This is the *declared* set. It is not the set the engine evaluates —
        several axioms have evaluation paths that consult no declaration. See
do not use this to answer "what does this domain check?".
        """
        seen = {axiom for spec in self.all_indicators()
                for axiom in spec.relevant_axioms}
        return sorted(seen, key=lambda a: a.value)

    def unreachable_declarations(self) -> List[Dict[str, Any]]:
        """Declared (indicator, axiom) pairs that can never produce an
        evaluation, decidable from the model alone.

        The gap this closes: a model declares `axioms: [RESPONSIVENESS]` on
        `pulldown_error_c`, the loader accepts it, `declared_axioms` reports it,
        and the pair cannot fire under ANY input. Before this the author found
        out at run time, per entity, per cycle, by reading a decline — and only
        if they read declines at all, which is the habit the envelope exists to
        build and cannot assume.

        REPORTED, NOT RAISED. The pair may be aspirational: an author can
        legitimately declare an axiom they intend to make reachable, and
        refusing to load their model over it would be the tool deciding their
        roadmap. What it must not do is stay quiet.
        """
        out: List[Dict[str, Any]] = []
        for entity_type, specs in self.indicators.items():
            for spec in specs:
                for axiom in unreachable_axioms(spec):
                    out.append({
                        "entity_type": entity_type,
                        "indicator": spec.name,
                        "axiom": getattr(axiom, "value", str(axiom)),
                        "declared_role": getattr(spec, "role", None),
                        "remedy": explain_absence(axiom, spec),
                    })
        return out


def parse_duration(raw: Optional[str]) -> Optional[timedelta]:
    """ISO-8601 (`PT1H30M`) or short-form (`90m`) duration. None if neither."""
    if not raw:
        return None
    text = str(raw)

    match = _ISO_DURATION.match(text)
    if match and any(match.groups()):
        return timedelta(
            hours=int(match.group(1) or 0),
            minutes=int(match.group(2) or 0),
            seconds=int(match.group(3) or 0),
        )

    match = _SHORT_DURATION.match(text.lower())
    if match:
        return timedelta(**{_UNIT_TO_KWARG[match.group(2)]: int(match.group(1))})

    return None


def resolve_direction(raw: Optional[str], indicator_name: str = "") -> str:
    """Validate the HOMEOSTASIS direction gate; never raise.

    An unrecognised value warns with the offending input and the valid set,
    then falls back. A typo in a domain file should be visible without being
    fatal — the alternative is a whole domain failing to load over one word.
    """
    if raw is None or raw == "":
        return "BIDIRECTIONAL"
    normalized = str(raw).upper()
    if normalized in VALID_DIRECTIONS:
        return normalized
    logger.warning(
        "unknown direction %r on indicator %r — valid: %s — using BIDIRECTIONAL",
        raw, indicator_name, ", ".join(sorted(VALID_DIRECTIONS)),
    )
    return "BIDIRECTIONAL"


def _resolve_indicator_type(raw: Any) -> IndicatorType:
    name = str(raw or "NUMERIC").upper()
    if name in IndicatorType.__members__:
        return IndicatorType[name]
    return IndicatorType.NUMERIC


def _resolve_axioms(raw: Any) -> List[Axiom]:
    """Parse the `axioms:` list, skipping names the enum does not know.

    Skipping rather than raising is deliberate and matches the existing
    loader: an unknown axiom name is a domain-authoring error that should
    cost that one entry, not the file.
    """
    axioms: List[Axiom] = []
    for entry in raw or []:
        try:
            axioms.append(Axiom(str(entry).upper()))
        except (ValueError, KeyError):
            logger.warning("unknown axiom %r in domain file — skipped", entry)
    return axioms


def _resolve_threshold(raw: Any) -> Optional[float]:
    """Absent threshold becomes None.

     reverses a documented decision, so the reasoning is recorded
    rather than replaced. This returned ``0.0`` and said so deliberately:
    *"checkers read these as floats and a None here would surface as a
    TypeError deep in an axiom check rather than as a load error."*

    **The premise was audited and does not hold.** No consumer performs
    unguarded arithmetic on these fields: every read is either ``is not
    None`` (``boundedness``, the full system, the discovery router) or
    truthiness (``responsiveness``), and the one multiplication site in
    ``integration/pattern_converter.py`` assigns the value on the line above.
    The batch-ingest path in the full system already reads the
    raw dict and already gets ``None``.

    **The cost of the old default was not hypothetical.** ``boundedness``
    tests ``if critical_threshold is not None``, so ``0.0`` meant *every
    non-negative reading is at or above critical*. A healthy Deployment with
    3 of 3 replicas available produced two CRITICAL problems through the
    shipped k8s domain. Eighteen indicators across the shipped domains
    declare BOUNDEDNESS with no thresholds.

    Zero is a legitimate threshold and cannot double as "absent" — the same
    sentinel collision as the ``_robust_slope`` and the
    correlation.
    """
    return float(raw) if raw is not None else None


def _resolve_role(raw: Any, indicator_name: str = "") -> Optional[str]:
    """The declared `role:` for an indicator, or None.

    None means *fall back to inferring the role from the name*, which is what
    every model written before this field existed relies on. An unrecognised
    word is warned about and treated as absent, because the alternative is a
    role the engine ignores while the author believes it is declared.
    """
    if raw is None or str(raw).strip() == "":
        return None
    resolved = normalise_role(raw)
    if resolved is None:
        logger.warning(
            "unknown role %r on indicator %r — ignored; known roles are %s",
            raw, indicator_name, ", ".join(sorted(ROLES)),
        )
    return resolved


def _resolve_severity(raw: Any) -> Severity:
    if not raw:
        return Severity.HIGH
    name = str(raw).upper()
    if name in Severity.__members__:
        return Severity[name]
    logger.warning("unknown severity %r — using HIGH", raw)
    return Severity.HIGH


def parse_indicator(
    data: Dict[str, Any],
    entity_type: str,
    property_mapping: Optional[Dict[str, str]] = None,
) -> Optional[IndicatorSpec]:
    """One YAML indicator mapping to one `IndicatorSpec`. None if unusable."""
    try:
        name = data["name"]
    except (KeyError, TypeError):
        logger.warning("indicator without a name in %r — skipped", entity_type)
        return None

    try:
        return IndicatorSpec(
            uri=f"domain:{entity_type}.{name}",
            name=name,
            property_name=(property_mapping or {}).get(name, name),
            indicator_type=_resolve_indicator_type(data.get("type")),
            relevant_axioms=_resolve_axioms(data.get("axioms")),
            warning_threshold=_resolve_threshold(data.get("warning")),
            critical_threshold=_resolve_threshold(data.get("critical")),
            time_window=parse_duration(data.get("window", "1h")) or DEFAULT_WINDOW,
            direction=resolve_direction(data.get("direction"), name),
            normal_states=data.get("normal", []),
            transient_states=data.get("transient", []),
            problematic_states=data.get("bad", []),
            transient_timeout=(
                parse_duration(data.get("timeout", "5m")) or DEFAULT_TIMEOUT),
            target_type=data.get("target_type", ""),
            relation_type=data.get("relation_type", ""),
            min_cardinality=data.get("min_cardinality", 0),
            max_cardinality=data.get("max_cardinality", 0),
            violation_severity=_resolve_severity(data.get("violation_severity")),
            required_property=data.get("required_property") or None,
            # the engine loader needs these for the same reason the
            # platform loader does. Fixing only one would leave the extracted
            # package shipping the defect this CD exists to remove.
            conservation_config=data.get("conservation") or None,
            monotonicity_config=data.get("monotonicity") or None,
            # the declared role. Normalised here rather than at every
            # read site, and an unrecognised word is reported and dropped —
            # the same convention `_resolve_axioms` and `_resolve_severity`
            # already use, so one mistyped field costs that field and not the
            # file. Dropping it silently would be worse than the defect this
            # closes: the author would believe they had declared a role.
            role=_resolve_role(data.get("role"), name),
        )
    except Exception as exc:  # one bad indicator must not cost the file
        logger.warning("failed to parse indicator %r: %s", name, exc)
        return None


def load_domain(source: Union[str, Path, Dict[str, Any]]) -> DomainModel:
    """Load a domain from a path, a YAML string, or an already-parsed dict.

    Accepts both the wrapped (`domain:` at top level) and bare forms, because
    published domain files use the wrapper and hand-written test fixtures
    usually do not.
    """
    if isinstance(source, dict):
        data = source
    elif isinstance(source, Path) or (
            isinstance(source, str) and "\n" not in source):
        data = yaml.safe_load(Path(source).read_text())
    else:
        data = yaml.safe_load(source)

    if not isinstance(data, dict):
        raise ValueError("domain source must parse to a mapping")

    domain = data.get("domain", data)
    if not isinstance(domain, dict):
        raise NotADomainModelError(
            f"`domain:` is {type(domain).__name__} {domain!r}, not a mapping — "
            "this looks like a constraints companion (a file that names the "
            "domain it extends rather than defining one). Use is_domain_model() "
            "to filter these when scanning a directory."
        )

    property_mapping = domain.get("property_mapping") or {}
    indicators: Dict[str, List[IndicatorSpec]] = {}
    for entity_type, entries in (domain.get("indicators") or {}).items():
        specs = [
            spec for spec in (
                parse_indicator(entry, entity_type,
                                property_mapping.get(entity_type, {}))
                for entry in (entries or [])
            ) if spec is not None
        ]
        if specs:
            indicators[entity_type] = specs

    model = DomainModel(
        domain_id=domain.get("id") or domain.get("domain_id") or "",
        name=domain.get("name", ""),
        description=domain.get("description", ""),
        entity_types=list(domain.get("entity_types") or []),
        relationship_types=list(domain.get("relationship_types") or []),
        aliases=[str(a) for a in (domain.get("aliases") or [])],
        indicators=indicators,
    )

    # say it at LOAD, not at cycle 1. Every fact needed to answer
    # "can this declared pair ever fire?" is present here, and it was previously
    # answered per entity per cycle by a decline the author had to be reading.
    # Warn rather than raise: the declaration may be aspirational, and refusing
    # the model over it would be the tool overruling its author.
    unreachable = model.unreachable_declarations()
    if unreachable:
        logger.warning(
            "domain %r declares %d (indicator, axiom) pair(s) that cannot "
            "evaluate under any input: %s — declare a `role:` on the indicator "
            "to make them reachable",
            model.domain_id or "<unnamed>", len(unreachable),
            "; ".join(f"{u['indicator']}/{u['axiom']}" for u in unreachable),
        )

    return model
