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
behaviour change wearing a tidy-up costume. The parity claim is checkable where
you are: loading a domain model through this module and through the ontology
loader yields tuple-identical output, and `examples/water_tank.yaml` declares all
eight axiom families, so it exercises every conversion above.

No Kubernetes literals, no fallback seed, no discovery, no `rdflib`. A domain
that is not described in its own YAML is not described.
"""

from __future__ import annotations

import dataclasses
import difflib
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


class MalformedDomainModelError(ValueError):
    """A key that must hold a sequence holds something else.

    Distinct from :class:`NotADomainModelError`, which says *this is
    not a domain model*. This says *this is a domain model and it is wrong*,
    which is the author's defect rather than the caller's mistake.

    A ``ValueError``, so ``is_domain_model`` keeps classifying a malformed file
    as *not loadable* rather than letting it escape a directory scan.
    """


def _require_sequence(value: Any, key: str, context: str = "") -> List[Any]:
    """Return `value` as a list, or raise naming what was found instead.

    Four keys were coerced with ``list(value or [])`` or iterated with
    ``for x in (value or [])``, and neither guards the shape. YAML then splits
    the two failure modes by TYPE, and **the quiet one is the dangerous one**:

    - a number or a bool raises ``TypeError: 'float' object is not iterable``
      from inside the loader — a traceback naming a line of ours, for a defect
      in the caller's file;
    - a **bare string** iterates its CHARACTERS. ``entity_types: Chassis`` —
      forgetting the brackets, which is the likeliest mistake here — loaded as
      seven entity types named C, h, a, s, s, i, s, and every subsequent check
      ran against that without a word.

    Found while verifying a published fix, from a probe whose own YAML was
    mis-indented. Reported by nobody: the mis-indentation was mine, and the
    engine's answer to it was a traceback.

    Raising rather than warning-and-skipping is deliberate, and it is the same
    reasoning as issue #1. A skipped entity type means its indicators silently
    do not exist, so the envelope reports a clean pass over checks that were
    never attempted — the exact failure the three-legged envelope exists to
    prevent. A load error is recoverable; a vacuous pass is not detectable.
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    where = f" for {context}" if context else ""
    found = f"{type(value).__name__} {value!r}"
    hint = (" — a bare string is read character by character, so this would "
            "have loaded silently as one entry per letter; wrap it in `[ ]`"
            if isinstance(value, str) else "")
    raise MalformedDomainModelError(
        f"`{key}`{where} is {found}, not a list{hint}")


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
        several axioms have evaluation paths that consult no
        declaration. Do not use this to answer "what does this domain check?".
        """
        seen = {axiom for spec in self.all_indicators()
                for axiom in spec.relevant_axioms}
        return sorted(seen, key=lambda a: a.value)

    def unread_fields(self) -> List[Dict[str, Any]]:
        """Declared FIELDS whose consuming axiom is not declared.

        Reported from outside as issue #5, against the field had added
        the day before. `expect_variation: true` on an indicator whose `axioms:`
        omits STABILITY is accepted, never read, and reported nowhere -- so a
        frozen sensor produced an envelope byte-identical to a live one, which
        is the defect that field was added to end, reachable again through a
        model the new documentation would lead an author to write.

        **The report named one field; this covers the class.** Measured on a
        single indicator declaring `role`, `expect_variation`, `direction`,
        `conservation:` and `monotonicity:` with only BOUNDEDNESS in its axiom
        list: five dead declarations, no findings, no declines, and
        `unreachable_declarations` empty. `expect_variation` was simply the
        newest.

        THE MIRROR of :meth:`unreachable_declarations`. That one answers *this
        axiom is declared and can never fire*; this answers *this field is
        declared and nothing will ever read it*. Same surface, because it is
        the one an author already has to consult, and the CONSISTENCY problem
        in issue #4 was caught by exactly that habit.

        REPORTED, NOT RAISED, for the reason the sibling gives: an
        over-declared model is not a broken one, and refusing to load it would
        be the tool deciding an author's roadmap. What it must not do is stay
        quiet, which is what it did.

         INVERTED THE CHECK, and that is the reporter's design. Matching
        declared fields against a list of known-inert ones can only ever catch
        keys somebody thought of. Comparing every key the author typed against
        the set the loader READS catches the rest: a field the documentation
        invented, a field a later version removes, and — the common case — a
        typo. `plausable_range` and `directon` both loaded clean, and so would
        `expect_variaton`, which would have re-opened issue #5 with no signal
        at all. Fifth independent sighting before it was closed; the fourth was
        our own guide teaching a key nothing reads.

        Two reasons, one list. `axiom_not_declared` is the case and its
        remedy is to declare the axiom; `unknown_key` is this one and its remedy
        is to correct or drop the key. A caller that only asks *is this empty?*
        gets one answer, and a caller that must act gets the distinction —
        reading the two as one backlog is how the wrong fix gets applied.
        """
        out: List[Dict[str, Any]] = []
        for entity_type, specs in self.indicators.items():
            for spec in specs:
                axioms = set(spec.relevant_axioms or ())
                typed = spec.declared_keys or frozenset()
                for field_name, consumers in sorted(_FIELD_CONSUMERS.items()):
                    key = _YAML_NAME.get(field_name, field_name)
                    if key not in typed:
                        continue          # the author did not write it
                    if axioms & set(consumers):
                        continue          # a consumer is declared; it is read
                    names = " or ".join(sorted(a.value for a in consumers))
                    out.append({
                        "entity_type": entity_type,
                        "indicator": spec.name,
                        "field": _YAML_NAME.get(field_name, field_name),
                        "reason": "axiom_not_declared",
                        "read_by": sorted(a.value for a in consumers),
                        "remedy": (
                            f"`{_YAML_NAME.get(field_name, field_name)}` is read "
                            f"only by {names}; add it to this indicator's "
                            f"`axioms:` list, or remove the field"),
                    })
                for key in sorted(typed - _KNOWN_INDICATOR_KEYS):
                    near = difflib.get_close_matches(
                        key, sorted(_KNOWN_INDICATOR_KEYS), n=1, cutoff=0.8)
                    remedy = (f"`{key}` is not a key this engine reads, so "
                              f"nothing will ever consume it")
                    if near:
                        remedy += f" — did you mean `{near[0]}`?"
                    out.append({
                        "entity_type": entity_type,
                        "indicator": spec.name,
                        "field": key,
                        "reason": "unknown_key",
                        "read_by": [],
                        "did_you_mean": near[0] if near else None,
                        "remedy": remedy,
                    })
        return out

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


#:. Which axiom READS each optional indicator field.
#:
#: A hand-written map, because the fact it records lives in checker code and
#: cannot be derived from a field name -- `expect_variation` is read by
#: STABILITY and nothing about the string says so. That makes it a closed enum,
#: which is the shape that has produced three defects here already. The guard is
#: NOT more care: `test_unread_fields_cd1694` derives the field set from
#: `IndicatorSpec` and fails when one is neither mapped here nor named in
#: `_SHARED_FIELDS` below. A field added without a decision breaks the build.
_FIELD_CONSUMERS: Dict[str, tuple] = {
    "expect_variation": (Axiom.STABILITY,),
    "normal_states": (Axiom.STABILITY,),
    "transient_states": (Axiom.STABILITY,),
    "problematic_states": (Axiom.STABILITY,),
    "transient_timeout": (Axiom.STABILITY,),
    "conservation_config": (Axiom.CONSERVATION,),
    "homeostasis_config": (Axiom.HOMEOSTASIS,),   #
    "monotonicity_config": (Axiom.MONOTONICITY,),
    "consistency_config": (Axiom.CONSISTENCY,),   #
    "stability_config": (Axiom.STABILITY,),       #
    "role": (Axiom.CONSISTENCY, Axiom.RESPONSIVENESS),
    "direction": (Axiom.HOMEOSTASIS,),
    "target_type": (Axiom.CONNECTIVITY,),
    "relation_type": (Axiom.CONNECTIVITY,),
    "min_cardinality": (Axiom.CONNECTIVITY,),
    "max_cardinality": (Axiom.CONNECTIVITY,),
    "required_property": (Axiom.CONNECTIVITY,),
    # see the note under `_SHARED_FIELDS`: the ceiling pair is shared,
    # the floor pair is not.
    "lower_warning_threshold": (Axiom.BOUNDEDNESS,),
    "lower_critical_threshold": (Axiom.BOUNDEDNESS,),
}

#: Fields read by more than one axiom family, or by the loader itself, so
#: declaring one says nothing about which axioms should be present. Listed
#: explicitly rather than defaulted-past, so the classification of every field
#: is a decision somebody made.
_SHARED_FIELDS = frozenset({
    "uri", "name", "property_name", "indicator_type", "relevant_axioms",
    "time_window", "warning_threshold", "critical_threshold",
    "violation_severity",
    # `flow_direction` is here rather than mapped to CONSERVATION
    # above, and the reason is the second sentence of this block's own
    # docstring: declaring it says nothing about which axioms should be
    # present. Its reader is the TOPOLOGY BUILDER, which seeds it onto every
    # node it makes; the structural balance then runs on FLOW cycles in the
    # graph, and no indicator's `axioms:` list gates it.
    #
    # Mapping it to CONSERVATION was tried first and is wrong in a way worth
    # recording, because it looks right. A balance has two sides and only one
    # of them carries the `conservation:` block — `water_tank.yaml` declares
    # the block on `inflow_lps` and lists `outflow_lps` inside it, leaving the
    # outflow indicator with `axioms: []` on purpose. Under the mapping, the
    # outflow could not declare its direction without also declaring an axiom
    # it does not want, which would then decline `missing_config` once per
    # cycle forever. The engine would have been demanding a false declaration
    # to accept a true one.
    "flow_direction",
})

#: the floor pair is BOUNDEDNESS-only, unlike the ceiling pair above.
#: `warning_threshold` / `critical_threshold` are shared because the traverser
#: and the discovery router read them too; nothing outside BOUNDEDNESS reads a
#: floor, so declaring one without BOUNDEDNESS is an unread field and says so.

#: Every key an indicator block may legitimately carry.
#:
#: THE SCHEMA IS THE LIST. This is not a denylist of keys known to be bad; it is
#: the set `parse_indicator` actually reads, so a key outside it is one nothing
#: will ever consume. That inversion is the reporter's, and it is what makes the
#: check cover cases nobody has seen: a field the docs invented, a field a later
#: version removes, and — the common one — a typo.
#:
#: Held as a literal rather than derived by `ast` at import time, because a
#: library that reads its own source fails wherever the source is not on disk.
#: `test_unknown_indicator_keys_cd1689` does the derivation instead and asserts
#: equality, so drift breaks the build rather than the check going quiet. Same
#: guard shape as `_FIELD_CONSUMERS` above, for the same reason.
#:
#: `name` is here and absent from that derivation's `.get()` scan because
#: `parse_indicator` reads it by subscript — the one key it requires.
#: Keys the model FORMAT carries that NO AXIOM reads, consumed instead by a
#: component outside the engine. Named explicitly so the exemption is a
#: decision somebody made and can be grepped, rather than an absence.
#:
#: `plausible_range` is read by the document-ingest pipeline, which uses it to
#: drop extracted properties outside the interval. Ten shipped domain files
#: declare it, 169 times between them — so reporting it as unknown would put
#: 169 rows in front of every author here, and a check that is red for a
#: legitimate reason every run teaches people to skip it. It is also simply
#: untrue: something does read it, just not an axiom.
#:
#: The cost is stated rather than hidden. An engine-only caller who writes this
#: key still gets silence from the engine about it. That was acceptable only
#: once the modelling guide stopped teaching it — the reporter wrote
#: it because our own documentation offered it, and that cause is closed. The
#: typo case, which was their stronger argument, is caught regardless.
_NON_AXIOM_KEYS = frozenset({"plausible_range"})

_KNOWN_INDICATOR_KEYS = frozenset({
    "name", "type", "axioms", "window", "warning", "critical", "role",
    "lower_warning", "lower_critical",
    "direction", "expect_variation", "conservation", "monotonicity",
    "consistency", "stability", "flow", "homeostasis",
    "normal", "transient", "bad", "timeout", "target_type", "relation_type",
    "min_cardinality", "max_cardinality", "required_property",
    "violation_severity",
}) | _NON_AXIOM_KEYS

#: Where the YAML key differs from the dataclass attribute, so a remedy names
#: what the author actually typed.
_YAML_NAME = {
    "flow_direction": "flow",
    "homeostasis_config": "homeostasis",
    "conservation_config": "conservation",
    "monotonicity_config": "monotonicity",
    "consistency_config": "consistency",
    "stability_config": "stability",
    "normal_states": "normal",
    "transient_states": "transient",
    "problematic_states": "bad",
    "transient_timeout": "timeout",
    "warning_threshold": "warning",
    "critical_threshold": "critical",
    "lower_warning_threshold": "lower_warning",
    "lower_critical_threshold": "lower_critical",
    "time_window": "window",
}


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


#: the two sides of a balance. A closed set of exactly two, because
#: a balance has exactly two sides; anything else is a different axiom.
FLOW_DIRECTIONS = frozenset({"in", "out"})


def _resolve_flow_direction(raw: Any, indicator_name: str = "") -> Optional[str]:
    """The declared `flow:` for an indicator, or None.

    None means *undeclared*, and undeclared means this quantity is not summed
    into either side of a structural balance. That is the safe default: the
    path this replaces decided the same question by matching the indicator's
    name against English tokens, and got `engage_human_in_loop` and
    `bad_actor_input` on the inflow side of a conservation sum.

    An unrecognised word is warned about and treated as absent, the convention
    `_resolve_role` and `_resolve_expect_variation` already use. Coercing
    `flow: inbound` to `"in"` by prefix would be the same inference one layer
    down, and the author would believe they had declared something exact.
    """
    if raw is None or str(raw).strip() == "":
        return None
    word = str(raw).strip().lower()
    if word in FLOW_DIRECTIONS:
        return word
    logger.warning(
        "unknown flow %r on indicator %r — ignored; write one of %s",
        raw, indicator_name, ", ".join(sorted(FLOW_DIRECTIONS)),
    )
    return None


#: The words YAML authors actually write for a boolean, beyond what the parser
#: already turns into `True`/`False`. Quoted values arrive here as strings.
_TRUE = {"true", "yes", "y", "on", "1"}
_FALSE = {"false", "no", "n", "off", "0"}


def _resolve_expect_variation(raw: Any, indicator_name: str = "") -> Optional[bool]:
    """The declared `expect_variation:` for an indicator, or None.

    None means *undeclared*, and undeclared means the frozen-series check does
    not run. That is the safe default in both directions: a model written
    before this field keeps its behaviour, and a quantity that is legitimately
    constant is never accused of being a dead sensor because nobody said it
    should move.

    An unrecognised value is warned about and treated as absent, for the same
    reason `_resolve_role` does it — `expect_variation: sometimes` coerced to
    True by truthiness would give the author a check they did not ask for and
    cannot see, which is worse than the defect this closes.
    """
    if raw is None or str(raw).strip() == "":
        return None
    if isinstance(raw, bool):
        return raw
    word = str(raw).strip().lower()
    if word in _TRUE:
        return True
    if word in _FALSE:
        return False
    logger.warning(
        "unreadable expect_variation %r on indicator %r — ignored; write "
        "true or false", raw, indicator_name,
    )
    return None


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
            # the floor pair. Same resolver as the ceiling pair, so
            # `lower_warning: 0` is a legitimate floor and not an absence.
            lower_warning_threshold=_resolve_threshold(data.get("lower_warning")),
            lower_critical_threshold=_resolve_threshold(data.get("lower_critical")),
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
            # the cross-signal block. Same shape as the two above and
            # for the same reason: a list plus a tolerance does not fit a flat
            # field beside `warning:`/`critical:`.
            consistency_config=data.get("consistency") or None,
            # the fourth nested block, for the opt-in slow-period
            # oscillation detector. Nested for the same reason as the other
            # three: several parameters that would collide as flat fields.
            stability_config=data.get("stability") or None,
            # the fifth nested block. Carries `must_return_within`,
            # a duration, which cannot be a flat field beside `warning:`
            # without reading as a threshold on the value rather than on time.
            homeostasis_config=data.get("homeostasis") or None,
            # the declared role. Normalised here rather than at every
            # read site, and an unrecognised word is reported and dropped —
            # the same convention `_resolve_axioms` and `_resolve_severity`
            # already use, so one mistyped field costs that field and not the
            # file. Dropping it silently would be worse than the defect this
            # closes: the author would believe they had declared a role.
            role=_resolve_role(data.get("role"), name),
            # Same convention as `role` above: normalised here, and an
            # unrecognised value is reported and dropped rather than coerced.
            # `expect_variation: yes` must not become False by way of
            # `bool("yes")` logic somewhere downstream.
            expect_variation=_resolve_expect_variation(
                data.get("expect_variation"), name),
            # Same convention again: normalised here, unrecognised
            # values reported and dropped. Which side of a balance a quantity
            # sits on is a domain fact, and the path this feeds used to read it
            # off the indicator's name.
            flow_direction=_resolve_flow_direction(data.get("flow"), name),
            # what the AUTHOR typed, which the values cannot say.
            declared_keys=frozenset(data.keys()) if isinstance(data, dict)
            else frozenset(),
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
        # shape-checked before iterating. A scalar here used to raise
        # a TypeError from this line, and a string used to yield one bogus
        # `indicator without a name` warning per CHARACTER.
        specs = [
            spec for spec in (
                parse_indicator(entry, entity_type,
                                property_mapping.get(entity_type, {}))
                for entry in _require_sequence(
                    entries, "indicators", f"entity type {entity_type!r}")
            ) if spec is not None
        ]
        if specs:
            indicators[entity_type] = specs

    model = DomainModel(
        domain_id=domain.get("id") or domain.get("domain_id") or "",
        name=domain.get("name", ""),
        description=domain.get("description", ""),
        entity_types=_require_sequence(
            domain.get("entity_types"), "entity_types"),
        relationship_types=_require_sequence(
            domain.get("relationship_types"), "relationship_types"),
        aliases=[str(a) for a in
                 _require_sequence(domain.get("aliases"), "aliases")],
        indicators=indicators,
    )

    # say it at LOAD, not at cycle 1. Every fact needed to answer
    # "can this declared pair ever fire?" is present here, and it was previously
    # answered per entity per cycle by a decline the author had to be reading.
    # Warn rather than raise: the declaration may be aspirational, and refusing
    # the model over it would be the tool overruling its author.
    unreachable = model.unreachable_declarations()
    if unreachable:
        # the remedy is PER PAIR, and it was already computed one
        # attribute away. This printed a single blanket `declare a role:` for
        # every unreachable pair, which is simply wrong for CONSERVATION: a
        # `role:` does nothing there and the `conservation:` block is what is
        # missing. `unreachable_declarations()` carries the right remedy for
        # each pair and says so correctly in the same process, so a reader who
        # looked at both surfaces was told two different things about one
        # condition. The warning now prints what the report computed rather
        # than a second guess at it.
        logger.warning(
            "domain %r declares %d (indicator, axiom) pair(s) that cannot "
            "evaluate under any input: %s",
            model.domain_id or "<unnamed>", len(unreachable),
            "; ".join(f"{u['indicator']}/{u['axiom']} — {u['remedy']}"
                      for u in unreachable),
        )

    return model
