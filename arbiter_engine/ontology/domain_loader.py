"""Engine-shaped domain loader — YAML in, typed indicators out, nothing else.

The decision that scoped this package listed "a plain YAML loader" as
in-scope for the v0.1 extraction. No such module existed. The two loaders that do exist are
both unsuitable for an engine package:

  *`ontology/loader.py` (720 lines) is primarily an RDF/TTL reader built on
    `rdflib`, with the YAML path grafted on and a hardcoded Kubernetes
    indicator seed reachable through its fallback path.
  *the platform's own domain registry (2,266 lines) is the real
    domain-YAML-to-typed-object path, but it also parses goals, cross-domain
    references, evidence sources, observation mappings, section templates and
    active-mode policy — platform concerns the engine has no use for, and
    roughly half the entire v0.1 line budget on its own.

**BOTH FIGURES ARE AS MEASURED ON 2026-08-02**, the day this module was
written, and neither is re-derived. They are the sizes that made a third loader
the cheaper answer, so the number that matters is the one the decision was taken
against; a figure silently tracking the file would stop being evidence for the
paragraph it sits in. Read as current they are wrong, and were — an outside
review measured the first at 860 against a docstring saying 720 and reported it
as a stale number, correctly. Both files have grown since. A census run where
this module is authored found exactly these two line-count claims and no
others; the checker that refuses an undated third lives there too, and is not
in this tree.

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
import math
import re
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from collections.abc import Mapping
from typing import Any, Dict, List, Optional, Union

import yaml

from ..axiom_thresholds import THRESHOLD_FIELDS
from ..interfaces import IndicatorSpec
from ..types import (Axiom, AxiomParameters, IndicatorType, Severity,
                     read_severity_floor)
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


def _require_mapping(value: Any, key: str) -> Dict[str, Any]:
    """Return `value` as a dict, or raise naming what was found instead.

    For `axiom_parameters:`. The same reasoning as the sequence check
    above: a block of the wrong SHAPE is the author's defect in the document,
    and loading it as though nothing were declared would evaluate every axiom
    with defaults the file was written to replace, without a word.
    """
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    raise MalformedDomainModelError(
        f"`{key}` is {type(value).__name__} {value!r}, not a mapping of "
        f"parameter names to values")


def _axiom_parameter_value(value: Any, kind: type) -> Any:
    """`value` as a parameter of `kind`, or None when it is not one.

    A bool is refused although Python counts it as an int: `true` for a
    window size is a slip, not a window of one. A count takes a whole number,
    written either way (`30` or `30.0`). Anything else must be a finite
    number; no range is imposed, because the parameters are the author's to
    choose and the axioms already decline honestly on any they cannot use.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    if kind is int:
        if isinstance(value, float) and not value.is_integer():
            return None
        return int(value)
    return float(value)


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
        #   - `load_domain` treats a newline-free string as a *path*, so any
        #     short string that is not a filename raised `FileNotFoundError`
        #     straight through the filter. A scan racing a deleted file got
        #     the same.
        #   - Malformed YAML raised `yaml.YAMLError`, which is precisely the
        #     case a caller most wants answered with False rather than a
        #     traceback.
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

    A Kubernetes domain file declares `id: kubernetes`, so a caller
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
    #: file's stem and its declared id can differ -- a file stemmed `k8s`
    #: declaring `kubernetes`, one stemmed `docker` declaring `docker-swarm`,
    #: neither of them shipped here -- and six shared
    #: sites carry the stem as a literal. Declaring the alias in the file that
    #: causes the split beats an alias table in shared code, which the project's design guidance
    #: forbids anyway. Absent means no aliases.
    aliases: List[str] = field(default_factory=list)
    #: Derivation rules, as the author wrote them. Parsed and checked by the
    #: `entail` verb, not here: the loader's job is to carry what the file
    #: says, and a rule that cannot be evaluated is a DECLINE with a reason
    #: rather than a file that will not load.
    rules: List[Dict[str, Any]] = field(default_factory=list)
    #: Predicates the author declares COMPLETE. For anything not named here,
    #: the absence of a fact is not evidence of its absence, and `entail` says
    #: so rather than concluding from silence.
    closure: List[str] = field(default_factory=list)
    #: Per-edge semantics, keyed by (source type, target type, relation): which
    #: edges are CAUSAL, how strongly a fault travels one, any declared
    #: unobserved common cause, and -- since -- the `transition:` block
    #: saying which property drives which and by how much.
    #:
    #: CORRECTED THE SENTENCE THAT USED TO END THIS COMMENT. It said
    #: *nothing on the public surface could [read them]: `traverse` builds its
    #: topology from the relationship graph, which has no access to them* --
    #: an accurate description of a defect, recorded here as though it were a
    #: property of the design. `api._build_topology` now passes these to the
    #: builder the same way passed it the indicators, so a declared
    #: `temporal:` block reaches the edge a released caller traverses. Before
    #: that, a rule declaring 120s/600s/0.9 produced an edge carrying
    #: 60.0/60.0/1.0 and stamped `auto`.
    relationship_rules: List[Dict[str, Any]] = field(default_factory=list)
    #: the EFFECT model of an operator action, and only that.
    #:
    #: `evidence/tech_brief.md` shows the unpublished operator half carrying
    #: `action_templates:` with an `active_mode_policy` and an
    #: `approval_chain`. Neither is here and neither belongs here: the open
    #: engine reports what an action WOULD do and never decides whether it may
    #: run or dispatches it. What is brought across is the mapping from a
    #: parameter to the entity property it writes, which is the one fact a
    #: rollout needs to know where the first delta enters.
    action_templates: List[Dict[str, Any]] = field(default_factory=list)
    #: what `plan` is asked to optimise, and what it may spend.
    #:
    #: DECLARED, because which objective a plan pursues is a domain question
    #: and not a property of the arithmetic. Minimising expected findings and
    #: maximising the chance of clearing a severity are different questions
    #: with different answers, and an engine that picked one would be deciding
    #: what the operator cares about. Absent, `plan` reports its candidates
    #: and ranks nothing -- the same refusal `project` makes when it computes
    #: a breach probability and no `report_above:` says what counts.
    planning: Dict[str, Any] = field(default_factory=dict)
    #: the domain-level `causal:` block. One key today,
    #: `evidence_severity:`, naming which finding severities make an entity
    #: FAULTY evidence for `infer`. Absent means the engine's own floor, and
    #: the envelope is stamped to say so: everywhere else in this engine a
    #: number nobody declared is disclosed, and this one was not.
    causal: Dict[str, Any] = field(default_factory=dict)
    #: When the world this model describes is OPEN, as declared sessions and
    #: holidays. A domain that declares none is always open and behaves exactly
    #: as it did before this existed; one that declares sessions has its
    #: windows measured in open time by `CalendarHistory`.
    calendar: Dict[str, Any] = field(default_factory=dict)
    indicators: Dict[str, List[IndicatorSpec]] = field(default_factory=dict)
    #: -- the evaluation parameters this model sets for itself, as the
    #: author wrote them. `evaluation_parameters()` reads them into the
    #: `AxiomParameters` the session's reasoner is built with. A key that is
    #: not a parameter, or a value that is not a number of that parameter's
    #: kind, is refused and reported by `unread_fields`, and the engine's own
    #: default stands for that one key. Absent, every default stands, exactly
    #: as before this existed.
    axiom_parameters: Dict[str, Any] = field(default_factory=dict)

    def declared_axiom_parameters(self) -> Dict[str, Any]:
        """The declared parameters this engine ACCEPTED, each as its own kind.

        Only these reach the reasoner. A refused entry is left out rather than
        coerced: a window of `"seven"` days is a question for the author, and
        answering it with the default while reporting it is the one honest
        reading.
        """
        accepted: Dict[str, Any] = {}
        for key, value in (getattr(self, "axiom_parameters", None) or {}).items():
            kind = _AXIOM_PARAMETER_KINDS.get(key)
            if kind is None:
                continue
            number = _axiom_parameter_value(value, kind)
            if number is not None:
                accepted[key] = number
        return accepted

    def evaluation_parameters(self) -> AxiomParameters:
        """The parameters every axiom of this model is evaluated with."""
        return AxiomParameters(**self.declared_axiom_parameters())

    def axiom_parameters_in_effect(self) -> Dict[str, Dict[str, Any]]:
        """Every parameter, its value, and whether the model or the engine set it.

        EVERY ONE, not only the declared ones. A reader asking why HOMEOSTASIS
        answered as it did needs the baseline window it was given, and a
        default is exactly the number nobody chose -- so each row says which
        it is.
        """
        declared = self.declared_axiom_parameters()
        defaults = AxiomParameters()
        return {
            name: {"value": declared.get(name, getattr(defaults, name)),
                   "source": "declared" if name in declared else "default"}
            for name in sorted(_AXIOM_PARAMETER_KINDS)
        }

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

        Reported from outside as issue #5, against the field that an internal ruling had added
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

        Three reasons, one list. `axiom_not_declared` is the case and
        its remedy is to declare the axiom; `unknown_key` is the and its
        remedy is to correct or drop the key; `unknown_value` is the, a
        key that exists carrying a value the engine does not recognise, and its
        remedy is to correct the value. A caller that only asks *is this empty?*
        gets one answer, and a caller that must act gets the distinction —
        reading them as one backlog is how the wrong fix gets applied.

        The third arrived the way the second did: from outside, against the
        field the previous one added. compared every key the author
        typed against the set the loader reads, which catches `directon`.
        Nothing compared VALUES, so `direction: hihger` passed through the same
        gap one level down, and `type: numric` did it without even a log line.
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
                # ONE LEVEL DOWN, same rule. This said `forecast:` was the
                # ONLY nested block with a closed key set the engine reads by
                # name, and three more had been true of that -- `temporal:`,
                # `transition:` and `planning:`, all added after this sentence
                # was written and none of them compared against anything.
                # They are checked in `_unread_coupling_keys` below.
                # `dynamics:` is still not checked: it carries a model's own
                # parameters, which are the model's to define, not the
                # loader's to enumerate.
                forecast_block = spec.forecast_config or {}
                if isinstance(forecast_block, dict):
                    for key in sorted(set(forecast_block) - _KNOWN_FORECAST_KEYS):
                        near = _did_you_mean(
                            key, sorted(_KNOWN_FORECAST_KEYS), cutoff=0.8)
                        remedy = (f"`forecast.{key}` is not a key this engine "
                                  f"reads, so nothing will ever consume it")
                        if near:
                            remedy += f" — did you mean `{near}`?"
                        out.append({
                            "entity_type": entity_type,
                            "indicator": spec.name,
                            "field": f"forecast.{key}",
                            "reason": "unknown_key",
                            "read_by": [],
                            "did_you_mean": near,
                            "remedy": remedy,
                        })
                for key in sorted(typed - _KNOWN_INDICATOR_KEYS):
                    near = _did_you_mean(
                        key, sorted(_KNOWN_INDICATOR_KEYS), cutoff=0.8)
                    remedy = (f"`{key}` is not a key this engine reads, so "
                              f"nothing will ever consume it")
                    if near:
                        remedy += f" — did you mean `{near}`?"
                    out.append({
                        "entity_type": entity_type,
                        "indicator": spec.name,
                        "field": key,
                        "reason": "unknown_key",
                        "read_by": [],
                        "did_you_mean": near,
                        "remedy": remedy,
                    })
                # the third reason, and the value-side twin of the
                # one above. inverted the KEY check and caught
                # `directon`; `direction: hihger` is the same author error
                # against a key that exists, and reached nothing an author can
                # query. Seven closed-vocabulary resolvers fall back or skip,
                # and `type` did it in total silence -- substituting NUMERIC,
                # so the indicator evaluated the wrong axioms and the model
                # loaded clean. Reported from outside, found while a method
                # document was being reviewed rather than by anyone using it.
                #
                # The valid set travels in the record from the resolver that
                # owns it. Holding four vocabularies here would be the
                # number-written-twice defect, and it would go stale the first
                # time a member was added -- which happened to the decline
                # vocabulary the same week.
                for key in sorted(spec.unresolved_values or {}):
                    entry = spec.unresolved_values[key]
                    valid = entry.get("valid") or []
                    for value in entry.get("values") or []:
                        near = _did_you_mean(value, valid, cutoff=0.7)
                        remedy = (
                            f"`{key}: {value}` is not a value this engine "
                            f"recognises, so the declaration was not applied; "
                            f"valid values are {', '.join(str(v) for v in valid)}")
                        if near:
                            remedy += f" — did you mean `{near}`?"
                        out.append({
                            "entity_type": entity_type,
                            "indicator": spec.name,
                            "field": key,
                            "reason": "unknown_value",
                            "value": value,
                            "read_by": [],
                            "did_you_mean": near,
                            "remedy": remedy,
                        })
        out.extend(self._unread_coupling_keys())
        out.extend(self._unresolved_coupling_values())
        return out

    def _unresolved_coupling_values(self) -> List[Dict[str, Any]]:
        """ -- the VALUE half of the block above, which had none.

        `_unread_coupling_keys` catches `response_modle:`. It cannot catch
        `response_model: lienar`, and that one is worse: the key is read, the
        value is not recognised, and three call sites fell back to exponential
        without a word. Measured on the shipped `pump_tank_planning` model,
        `exponential` scores 8.667 and `linear` 7.333 -- so a misspelling
        returned a different number than the author asked for, quietly. The
        engine already reports an unrecognised value this way for the closed
        vocabularies on an INDICATOR; a coupling block simply had no such
        check.

        The accepted set is imported, never transcribed: the resolver owns it,
        for the reason `_record_unresolved` already states.
        """
        from ..temporal.temporal_edge import (
            RESPONSE_MODEL_NAMES, resolve_response_model,
        )

        #: `(block, key, resolver, valid)`. One row today; a tuple because the
        #: next closed vocabulary inside a coupling block should be added here
        #: rather than beside it.
        vocabularies = (
            ("temporal", "response_model", resolve_response_model,
             list(RESPONSE_MODEL_NAMES)),
        )

        out: List[Dict[str, Any]] = []
        for rule in (getattr(self, "relationship_rules", None) or ()):
            if not isinstance(rule, dict):
                continue
            label = (f"{rule.get('source_type', '?')}"
                     f"-{rule.get('type', '?')}->"
                     f"{rule.get('target_type', '?')}")
            for where, key, resolve, valid in vocabularies:
                block = rule.get(where)
                if not isinstance(block, dict) or key not in block:
                    continue
                _model, unresolved = resolve(block.get(key))
                if unresolved is None:
                    continue
                near = _did_you_mean(unresolved, valid, cutoff=0.7)
                remedy = (
                    f"`{where}.{key}: {unresolved}` is not a value this "
                    f"engine recognises, so the declaration was not applied "
                    f"and the engine's own default was used instead; valid "
                    f"values are {', '.join(valid)}")
                if near:
                    remedy += f" — did you mean `{near}`?"
                out.append({
                    "field": f"{where}.{key}",
                    "reason": "unknown_value",
                    "value": unresolved,
                    "read_by": [],
                    "did_you_mean": near,
                    "remedy": remedy,
                    "rule": label,
                })
        return out

    def _unread_coupling_keys(self) -> List[Dict[str, Any]]:
        """The same rule, applied to the blocks that say how a value moves.

        `temporal:` and `transition:` on a relationship rule, and the
        domain's `planning:` block, are read key by key and were compared
        against nothing. They are also the newest part of the schema, which is
        the shape the sibling check above already names as the one most worth
        misspelling -- and the cost is silent in both directions: a mistyped
        `propagation_delay_s` substitutes the engine's default dead time, and
        a mistyped `gain_sigma` removes every interval the coupling would have
        carried, which stops `clearance_probability` being a probability and
        stops a rollout filing anything it could later be graded on.

        A rule is identified the way `model_describe`'s transition coverage
        identifies one, rather than by position: a reader who has to count
        list entries to find the typo has been given the wrong end of it.
        """
        out: List[Dict[str, Any]] = []

        def report(where: str, block: Any, known: frozenset, rule: str) -> None:
            if not isinstance(block, dict):
                return
            for key in sorted(set(block) - known):
                near = _did_you_mean(key, sorted(known), cutoff=0.8)
                remedy = (f"`{where}.{key}` is not a key this engine reads, "
                          f"so nothing will ever consume it")
                if near:
                    remedy += f" — did you mean `{near}`?"
                row = {
                    "field": f"{where}.{key}",
                    "reason": "unknown_key",
                    "read_by": [],
                    "did_you_mean": near,
                    "remedy": remedy,
                }
                if rule:
                    row["rule"] = rule
                out.append(row)

        # READ WITH `getattr`, NOT AS ATTRIBUTES. A `DomainModel` can reach
        # here carrying ONLY `indicators`: a caller can build one with
        # `__new__` and set that single field, which is a fair fixture for a
        # method whose indicator half is what it is exercising.
        # Assuming the other three fields exist raised `AttributeError` on
        # thirty of its cases -- none of them in the engine lane, all of them
        # in the net.
        for rule in (getattr(self, "relationship_rules", None) or ()):
            if not isinstance(rule, dict):
                continue
            label = (f"{rule.get('source_type', '?')}"
                     f"-{rule.get('type', '?')}->"
                     f"{rule.get('target_type', '?')}")
            for where, known in _COUPLING_BLOCKS:
                report(where, rule.get(where), known, label)
        # ONLY TEMPLATES THIS ENGINE ACCEPTED. `action_templates:` is the one
        # block with a COMPETING schema: eleven of the nineteen models this
        # repository ships declare the orchestrator's richer shape -- `params`,
        # `risk`, `blast_radius`, `duration` -- and `load_templates` already
        # refuses each of those whole, by name, with `malformed_action:
        # template is missing applies_to, parameters_schema`. That single
        # decline says the real thing. Reporting its six or seven keys
        # individually would bury it under rows calling each one unknown, when
        # every one of them is valid in the schema the author was writing --
        # the shape `_apply_transitions` already refuses for an exhausted
        # budget, where a decline per item hides the one fact that matters.
        #
        # So the required keys are the gate, read from the module that
        # enforces them rather than restated here.
        from ..twin.actions import REQUIRED_TEMPLATE_KEYS
        for template in (getattr(self, "action_templates", None) or ()):
            if not isinstance(template, dict):
                continue
            if any(not template.get(key) for key in REQUIRED_TEMPLATE_KEYS):
                continue          # refused whole, and told so already
            label = str(template.get("name") or "?")
            report("action_templates", template,
                   _KNOWN_ACTION_TEMPLATE_KEYS, label)
            schema = template.get("parameters_schema")
            if isinstance(schema, dict):
                for parameter, spec in sorted(schema.items()):
                    # The parameter NAMES are the author's; only the spec
                    # beside each one has a closed set.
                    report(f"action_templates.parameters_schema.{parameter}",
                           spec, _KNOWN_ACTION_PARAM_KEYS, label)
        report("planning", getattr(self, "planning", None),
               _KNOWN_PLANNING_KEYS, "")
        report("causal", getattr(self, "causal", None),
               _KNOWN_CAUSAL_KEYS, "")
        out.extend(self._unread_evidence_severity())
        report("axiom_parameters", getattr(self, "axiom_parameters", None),
               _KNOWN_AXIOM_PARAMETER_KEYS, "")
        out.extend(self._unread_axiom_parameter_values())
        return out

    def _unread_axiom_parameter_values(self) -> List[Dict[str, Any]]:
        """The VALUE side of `axiom_parameters:`.

        The key side is the shared `unknown_key` report above. This is the
        other way a declaration can fail to take: a known parameter given
        something that is not a number of its kind. The default stood for that
        key, and a reader who only saw the envelope could not tell a refused
        declaration from no declaration -- so the row says which word, and what
        was used instead.
        """
        rows: List[Dict[str, Any]] = []
        block = getattr(self, "axiom_parameters", None) or {}
        defaults = AxiomParameters()
        for key, value in sorted(block.items(), key=lambda kv: str(kv[0])):
            kind = _AXIOM_PARAMETER_KINDS.get(key)
            if kind is None or _axiom_parameter_value(value, kind) is not None:
                continue
            wanted = "a whole number" if kind is int else "a finite number"
            rows.append({
                "field": f"axiom_parameters.{key}",
                "reason": "malformed_value",
                "value": (value if isinstance(value, (str, int, float, bool))
                          or value is None else repr(value)),
                "read_by": [], "did_you_mean": None,
                "remedy": (f"`axiom_parameters.{key}` takes {wanted}, so the "
                           f"declaration was refused and the engine's own "
                           f"{getattr(defaults, key)} was used"),
            })
        return rows

    def _unread_evidence_severity(self) -> List[Dict[str, Any]]:
        """The VALUE side of `causal.evidence_severity:`.

        The comment beside `_KNOWN_CAUSAL_KEYS` says a misspelled key in a
        block whose absence is legal silently takes the default it was written
        to replace. That is just as true one level down, and the key side was
        closed while the value side was not: `evidence_severity: [critical,
        hihg]` fell back to the engine's floor and said so with a stamp that
        an omission produces identically. An outside review measured four
        different author actions collapsing into one bare disclosure, three of
        them the author TRYING to declare the floor.

        The stamp on the envelope now says a declaration was refused. This says
        WHICH WORD, which is the half a stamp cannot carry.
        """
        read = read_severity_floor(getattr(self, "causal", None))
        if not read.present or read.problem is None:
            return []

        field = "causal.evidence_severity"
        valid = [member.value for member in Severity]
        valid_text = ", ".join(valid)
        rows: List[Dict[str, Any]] = []

        if read.problem == "unknown_value":
            for value in read.rejected:
                near = _did_you_mean(value, valid, cutoff=0.7)
                remedy = (
                    f"`{field}: {value}` is not a severity this engine "
                    f"recognises, so the whole floor was refused and the "
                    f"engine's own was used; valid values are {valid_text}")
                if near:
                    remedy += f" -- did you mean `{near}`?"
                rows.append({
                    "field": field, "reason": "unknown_value",
                    "value": value, "read_by": [], "did_you_mean": near,
                    "remedy": remedy,
                })
            return rows

        # NOT `unknown_value`: nothing here is an unrecognised severity. A
        # scalar `critical` names a real one and a `[]` names none, so calling
        # either an unknown value would misdescribe it confidently -- and
        # `did_you_mean` would have nothing to say.
        written = (self.causal or {}).get("evidence_severity")
        if read.problem == "empty":
            detail = "at least one severity; an empty list declares no floor"
        elif written is None:
            # `evidence_severity:` on its own line. The author DID write the
            # key, so this is not an omission -- and telling them it is not a
            # single value would describe something they did not do.
            detail = "a list of severities; this key was written with none"
        else:
            detail = "a list of severities, not a single value"
        rows.append({
            "field": field, "reason": "malformed_value",
            "value": written,
            "read_by": [], "did_you_mean": None,
            "remedy": (f"`{field}` takes {detail}, so the declaration was "
                       f"refused and the engine's own floor was used; valid "
                       f"values are {valid_text}"),
        })
        return rows

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
        out.extend(self._unreachable_derivations())
        return out

    def _unreachable_derivations(self) -> List[Dict[str, Any]]:
        """Derived indicators that cannot be computed as declared.

        THREE WAYS, and each is decidable here rather than per cell:

        an expression that will not parse; an operand that is ITSELF derived,
        which the format forbids because references resolve one level and a
        chain has an evaluation order nobody declared; and an operand that
        names the indicator's own property, which is the same rule at depth
        zero.

        Reported rather than raised, like everything else on this surface.
        """
        from ..derived.indicator import operands_of

        out: List[Dict[str, Any]] = []
        for entity_type, specs in self.indicators.items():
            derived_properties = {
                (spec.property_name or spec.name) for spec in specs if spec.derived}
            for spec in specs:
                if not spec.derived:
                    continue
                own = spec.property_name or spec.name
                names = operands_of(spec.derived)
                if not names:
                    out.append({
                        "entity_type": entity_type, "indicator": spec.name,
                        "axiom": None, "declared_role": getattr(spec, "role", None),
                        "reason": "underivable",
                        "remedy": (f"`derived: {spec.derived}` is not an arithmetic "
                                   f"expression over property names, so this "
                                   f"indicator can never be computed"),
                    })
                    continue
                chained = sorted(n for n in names
                                 if n in derived_properties and n != own)
                if chained:
                    out.append({
                        "entity_type": entity_type, "indicator": spec.name,
                        "axiom": None, "declared_role": getattr(spec, "role", None),
                        "reason": "underivable",
                        "remedy": (f"operand(s) {chained} are themselves derived; "
                                   f"references resolve ONE level, so write the "
                                   f"expression out over base properties"),
                    })
                if own in names:
                    out.append({
                        "entity_type": entity_type, "indicator": spec.name,
                        "axiom": None, "declared_role": getattr(spec, "role", None),
                        "reason": "underivable",
                        "remedy": (f"`{own}` derives from itself, which has no "
                                   f"evaluation order and no fixed point"),
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
    # READ BY A VERB RATHER THAN BY AN AXIOM, which is a third category this
    # set had not had to hold before. `_FIELD_CONSUMERS` answers *which axiom
    # reads this*, and for a projection field the honest answer is none: the
    # `project` verb reads all three whatever the indicator declares under
    # `axioms:`. Mapping them to an axiom would make `unread_fields` tell an
    # author to declare BOUNDEDNESS in order to get a forecast, which is false
    # and would be acted on.
    "dynamics_config", "horizon", "lookback", "forecast_config",
    # Read by the derived-indicator machinery rather than by an axiom: the
    # axioms judge the RESULT, and none of them knows it was computed.
    "derived", "align_tolerance",
    # B-2.7 — DERIVED, NOT TYPED, which is the reason it is here rather than
    # mapped to BOUNDEDNESS and RESPONSIVENESS. The author writes
    # `critical: {from_property: sla_ms}`; the loader lifts the property name
    # out into this field. `declared_keys` records `critical`, not this, so a
    # remedy naming this field would name something nobody wrote -- and the
    # key they DID write is classified two lines up, where the report will
    # find it. Mapping it would also be the wrong answer on the merits: the
    # four keys it serves are split, with the ceiling pair shared and the
    # floor pair BOUNDEDNESS-only.
    "threshold_sources",
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

#: The keys the `forecast:` block carries. A NESTED block is a second surface
#: with the same failure mode as the first, and it had no check: the loader
#: stored the mapping whole, `run_forecasts` read `expected`/`models`/`max_age`
#: and `_expected_per_model` read `expected_from`, and anything else the author
#: typed was accepted and consumed by nothing. A misspelled `expected_from` did
#: not report an unknown key -- it reported `missing_property` on
#: `forecasts_expected`, which sends the author to look at their feed.
#: the top-level names a domain model may declare, and the test for
#: whether a document IS one. Not a validation set: an unknown key here is not
#: refused, because `domain:` has never checked its own top level and making it
#: do so would refuse models that load today. What this answers is narrower and
#: is the question `is_domain_model` exists to answer -- does this document
#: declare ANYTHING this loader reads.
#:
#: Every member is read by `load_domain` below. A name added there and not here
#: makes this filter narrower than the loader, which turns a real model into a
#: companion; `test_a_companion_beside_the_models_is_not_one` re-derives the set
#: from the loader's own source and fails on the difference rather than trusting
#: this list to have been updated.
_MODEL_KEYS = frozenset({
    "id", "domain_id", "name", "description", "entity_types",
    "relationship_types", "aliases", "rules", "closure", "relationship_rules",
    "calendar", "action_templates", "planning", "causal", "indicators",
    "property_mapping", "axiom_parameters",
})

_KNOWN_FORECAST_KEYS = frozenset({
    "expected", "models", "expected_from", "max_age",
})

#: the COUPLING blocks, one level down from a relationship rule.
#:
#: `forecast:` was the only nested block whose keys were checked, and the
#: comment beside that check said so in as many words. These three are read by name exactly as it is, they were
#: added later than it, and nothing compared them against anything: measured on
#: one rule, `propagation_delay: 120` silently took the engine's 60 s default
#: and `gain_sgima: 0.002` silently left the coupling with no spread at all.
#:
#: DERIVED, NOT TRANSCRIBED. `test_a_coupling_block_is_checked_too` re-reads
#: `twin/builder.py` and fails when a key the parser reads is missing here --
#: a guard that is narrower than the schema it covers reports a clean model
#: for a typo, which is the defect rather than a smaller version of it.
_KNOWN_TEMPORAL_KEYS = frozenset({
    "propagation_delay_s", "time_constant_s", "response_model",
    "coupling_strength",
})

#: `clamp_to_bounds` IS NOT HERE, and its absence is the decision. It was
#: parsed onto `Transition` and consumed by nothing, and it cannot be honoured:
#: the only bounds this engine holds are `warning:` and `critical:`, which are
#: DETECTION lines, not physical limits. Clamping an imagined value to them
#: would cap every excursion at exactly the line a simulation exists to cross,
#: so a tank projected to 130 would report what one projected to 96 reports --
#: and `plan` ranks candidates on that difference.
_KNOWN_TRANSITION_KEYS = frozenset({
    "from", "to", "gain", "source", "gain_sigma", "offset",
})

_KNOWN_PLANNING_KEYS = frozenset({
    "objective", "min_severity", "max_rollouts", "max_depth",
})

#: The domain-level `causal:` block. One member, and it is here from the first
#: day rather than after a typo reached somebody: a misspelled key in a block
#: whose absence is legal would silently take the default it was written to
#: replace.
_KNOWN_CAUSAL_KEYS = frozenset({"evidence_severity"})

#: The domain-level `axiom_parameters:` block -- the evaluation parameters a
#: model may set for itself., closing the second half of issue #14:
#: `homeostasis_baseline_days` was fixed at seven days for every caller that
#: came in through the session, so a model observed monthly could never build a
#: HOMEOSTASIS baseline, whatever its indicators declared.
#:
#: DERIVED FROM THE DATACLASS, NOT TRANSCRIBED. The keys are the fields of
#: `AxiomParameters` and their kinds are its annotations, so a parameter added
#: there is declarable here the same day, and one removed there is reported as
#: unknown rather than accepted and ignored.
_AXIOM_PARAMETER_KINDS: Dict[str, type] = {
    # An annotation arrives as a string where the defining module postpones
    # them; every field is an int or a float, and a count must stay a count.
    field_.name: (int if field_.type in (int, "int") else float)
    for field_ in dataclasses.fields(AxiomParameters)
}
_KNOWN_AXIOM_PARAMETER_KEYS = frozenset(_AXIOM_PARAMETER_KINDS)

#: `action_templates:` is mixed, which is why it is here rather than trusted.
#: A mistyped `entity_property` is caught at rollout time -- the action is
#: refused and counted -- but a mistyped `settle_s` is silent, and it silences
#: the engine too: `settle_s: 300` against a 60 s step declines
#: `settle_exceeds_step`, saying the actuator is slower than the step and the
#: ramp is not modelled, and `settl_s: 300` produces no decline and a
#: trajectory that reads as though the actuator were instantaneous.
#:
#: `description` and a parameter's `type` are ACCEPTED AND NOT ACTED ON. They
#: document the model for a human and the engine reads neither; both ship in
#: its own worked example, so the set is what the loader knows about rather
#: than what changes behaviour, exactly as the indicator set above is.
_KNOWN_ACTION_TEMPLATE_KEYS = frozenset({
    "name", "applies_to", "description", "parameters_schema", "effect",
    "settle_s", "source",
})

#: `tolerance` is how close a later reading must come to what the
#: parameter writes, read when an EXECUTED action is filed; `twin/actions.py`
#: refuses the template if it is not a positive number.
_KNOWN_ACTION_PARAM_KEYS = frozenset({
    "type", "entity_property", "candidates", "tolerance",
})

#: Which nested block each is checked against, and the label a row carries.
_COUPLING_BLOCKS = (("temporal", _KNOWN_TEMPORAL_KEYS),
                    ("transition", _KNOWN_TRANSITION_KEYS))

_KNOWN_INDICATOR_KEYS = frozenset({
    "name", "type", "axioms", "window", "warning", "critical", "role",
    "lower_warning", "lower_critical",
    "direction", "expect_variation", "conservation", "monotonicity",
    "consistency", "stability", "flow", "homeostasis",
    "normal", "transient", "bad", "timeout", "target_type", "relation_type",
    "min_cardinality", "max_cardinality", "required_property",
    "violation_severity",
    "dynamics", "horizon", "lookback", "forecast",
    "derived", "align_tolerance",
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
    "dynamics_config": "dynamics",
    "forecast_config": "forecast",
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


def _did_you_mean(value: Any, valid: List[Any],
                  cutoff: float) -> Optional[str]:
    """Nearest member of a closed set, matched WITHOUT case.

    `difflib` is case-sensitive and every one of these vocabularies is not: the
    resolvers upper- or lower-case the author's word before comparing, so
    `NUMERIC` and `numeric` both load. The RECORDED valid sets do not share a
    convention -- some are the enum's members, some its values -- so a
    suggestion appeared only when the author's case happened to match the set's,
    and which case that was varied per key with nothing telling the author
    which. Measured across all seven closed vocabularies before the change:
    every one lost its suggestion in one case and kept it in the other, five on
    upper and two on lower. The shipped example declares `type: NUMERIC`, so the
    case an author is most likely to copy was the one that produced nothing.

    Worse at the KEY site, where case genuinely matters: `WARNING:` is not a key
    this engine reads, lower-casing it is the entire fix, and that was the one
    input the suggester had nothing to say about.

    Returns the CANONICAL spelling from `valid`, which is what the remedy prints
    in the same sentence, so the two cannot disagree. A vocabulary holding two
    members differing only by case would fold here; none does, and one would be
    a defect in the vocabulary rather than in this.
    """
    canonical: Dict[str, str] = {}
    for member in valid:
        canonical.setdefault(str(member).lower(), str(member))
    near = difflib.get_close_matches(
        str(value).lower(), list(canonical), n=1, cutoff=cutoff)
    return canonical[near[0]] if near else None


def _record_unresolved(sink: Optional[dict], key: str, value: Any,
                       valid: List[str]) -> None:
    """Record a closed-vocabulary value the loader did not recognise.

    The VALID SET travels with the record because the resolver owns it. The
    reporter must not hold its own copy of four vocabularies -- that is the
    number-written-twice defect `declared_keys` was introduced to avoid, and
    it would go stale the first time a member was added.

    `axioms:` is a list, so its entries accumulate; the scalar keys hold one.
    """
    if sink is None:
        return
    entry = sink.setdefault(key, {"values": [], "valid": valid})
    entry["values"].append(value)


def resolve_direction(raw: Optional[str], indicator_name: str = "",
                      unresolved: Optional[dict] = None) -> str:
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
    _record_unresolved(unresolved, "direction", raw, sorted(VALID_DIRECTIONS))
    return "BIDIRECTIONAL"


def _resolve_indicator_type(raw: Any, unresolved: Optional[dict] = None) -> IndicatorType:
    """records an unrecognised value rather than swallowing it.

    This was the SILENT one of the four closed-vocabulary resolvers: the other
    three at least logged. `type: numric` and `type: temperature` both arrived
    as NUMERIC with no signal at any level, so an indicator typed wrongly by a
    typo evaluated the wrong axioms and reported a clean model.

    Absent is NOT unresolved. An omitted `type:` legitimately defaults, and
    conflating the two would report every indicator that never declared one.
    """
    if raw is None or raw == "":
        return IndicatorType.NUMERIC
    name = str(raw).upper()
    if name in IndicatorType.__members__:
        return IndicatorType[name]
    _record_unresolved(unresolved, "type", raw,
                       sorted(m.lower() for m in IndicatorType.__members__))
    return IndicatorType.NUMERIC


def _resolve_axioms(raw: Any, unresolved: Optional[dict] = None) -> List[Axiom]:
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
            # a log line is not a surface an author can query. The
            # skip is still deliberate; what changes is that it now reaches
            # the report the author already consults.
            _record_unresolved(unresolved, "axioms", entry,
                               sorted(a.value for a in Axiom))
    return axioms


def _resolve_threshold(raw: Any) -> Optional[float]:
    """Absent threshold becomes None.

    An internal ruling reverses a documented decision, so the reasoning is recorded
    rather than replaced. This returned ``0.0`` and said so deliberately:
    *"checkers read these as floats and a None here would surface as a
    TypeError deep in an axiom check rather than as a load error."*

    **The premise was audited and does not hold.** No consumer performs
    unguarded arithmetic on these fields: every read is either ``is not
    None`` (``boundedness``, the platform's composition root, the discovery
    router) or truthiness (``responsiveness``), and the one multiplication
    site anywhere assigns the value on the line above. The platform's
    batch-ingest path already reads the raw dict and already gets ``None``.

    The audit above spans both this package and the platform that derives it;
    the platform-side readers are named by what they do rather than by path,
    because a reader here cannot open them to check.

    **The cost of the old default was not hypothetical.** ``boundedness``
    tests ``if critical_threshold is not None``, so ``0.0`` meant *every
    non-negative reading is at or above critical*. A healthy Deployment with
    3 of 3 replicas available produced two CRITICAL problems through the
    shipped k8s domain. Eighteen indicators across the shipped domains
    declare BOUNDEDNESS with no thresholds.

    Zero is a legitimate threshold and cannot double as "absent" — the same
    sentinel collision as the ``_robust_slope`` and the
    correlation.

    B-2.7 — a MAPPING is not a number and is not an absence either: it says the
    number lives on the entity. It resolves to None here and the property name
    is carried in ``threshold_sources``, so every ``is not None`` read in the
    package still means *this spec carries a literal bound*, which is the only
    question those reads were ever asking.
    """
    if isinstance(raw, Mapping):
        return None
    return float(raw) if raw is not None else None


def _threshold_source(raw: Any, unresolved: Optional[dict] = None,
                      key: str = "") -> Optional[str]:
    """The property a bound is read from, for ``{from_property: <name>}``.

    A mapping the loader cannot read a property name out of is RECORDED rather
    than dropped in silence — the author wrote a bound and would otherwise get
    an indicator with no bound at all, which looks exactly like never having
    declared one. Same channel as every other unrecognised value, so it reaches
    `dropped_declarations` without a fifth report being invented for it.
    """
    if not isinstance(raw, Mapping):
        return None
    name = raw.get("from_property")
    if isinstance(name, str) and name.strip():
        return name.strip()
    _record_unresolved(unresolved, key, raw,
                       ["<number>", "{from_property: <property name>}"])
    return None


def _resolve_role(raw: Any, indicator_name: str = "",
                  unresolved: Optional[dict] = None) -> Optional[str]:
    """The declared `role:` for an indicator, or None.

    None means *no role*, and is what changed that: it used to mean
    fall back to inferring one from the indicator's name. The axiom now declines
    `missing_role` instead, so None is a decision the author can see rather than
    a guess they cannot. An unrecognised word is warned about and treated as
    absent, because the alternative is a role the engine ignores while the
    author believes it is declared.
    """
    if raw is None or str(raw).strip() == "":
        return None
    resolved = normalise_role(raw)
    if resolved is None:
        logger.warning(
            "unknown role %r on indicator %r — ignored; known roles are %s",
            raw, indicator_name, ", ".join(sorted(ROLES)),
        )
        _record_unresolved(unresolved, "role", raw, sorted(ROLES))
    return resolved


#: the two sides of a balance. A closed set of exactly two, because
#: a balance has exactly two sides; anything else is a different axiom.
FLOW_DIRECTIONS = frozenset({"in", "out"})


def _resolve_flow_direction(raw: Any, indicator_name: str = "",
                            unresolved: Optional[dict] = None) -> Optional[str]:
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
    _record_unresolved(unresolved, "flow", raw, sorted(FLOW_DIRECTIONS))
    return None


#: The words YAML authors actually write for a boolean, beyond what the parser
#: already turns into `True`/`False`. Quoted values arrive here as strings.
_TRUE = {"true", "yes", "y", "on", "1"}
_FALSE = {"false", "no", "n", "off", "0"}


def _resolve_expect_variation(raw: Any, indicator_name: str = "",
                              unresolved: Optional[dict] = None) -> Optional[bool]:
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
    _record_unresolved(unresolved, "expect_variation", raw, ["false", "true"])
    return None


def _resolve_severity(raw: Any, unresolved: Optional[dict] = None) -> Severity:
    if not raw:
        return Severity.HIGH
    name = str(raw).upper()
    if name in Severity.__members__:
        return Severity[name]
    logger.warning("unknown severity %r — using HIGH", raw)
    _record_unresolved(unresolved, "violation_severity", raw,
                       sorted(s.value for s in Severity))
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

    # the seven closed-vocabulary resolvers below record what they
    # could not recognise here, so an unrecognised VALUE reaches the same
    # report an unrecognised KEY already reaches.
    unresolved: Dict[str, Any] = {}

    # B-2.7 — resolved before the spec is built, because a source and a literal
    # are read out of the SAME key and only one of them can be there.
    sources = {}
    for _field in THRESHOLD_FIELDS:
        _source = _threshold_source(data.get(_field), unresolved, _field)
        if _source is not None:
            sources[_field] = _source

    try:
        return IndicatorSpec(
            uri=f"domain:{entity_type}.{name}",
            name=name,
            property_name=(property_mapping or {}).get(name, name),
            indicator_type=_resolve_indicator_type(data.get("type"), unresolved),
            relevant_axioms=_resolve_axioms(data.get("axioms"), unresolved),
            warning_threshold=_resolve_threshold(data.get("warning")),
            critical_threshold=_resolve_threshold(data.get("critical")),
            # the floor pair. Same resolver as the ceiling pair, so
            # `lower_warning: 0` is a legitimate floor and not an absence.
            lower_warning_threshold=_resolve_threshold(data.get("lower_warning")),
            lower_critical_threshold=_resolve_threshold(data.get("lower_critical")),
            threshold_sources=sources,
            time_window=parse_duration(data.get("window", "1h")) or DEFAULT_WINDOW,
            direction=resolve_direction(data.get("direction"), name, unresolved),
            normal_states=data.get("normal", []),
            transient_states=data.get("transient", []),
            problematic_states=data.get("bad", []),
            transient_timeout=(
                parse_duration(data.get("timeout", "5m")) or DEFAULT_TIMEOUT),
            target_type=data.get("target_type", ""),
            relation_type=data.get("relation_type", ""),
            min_cardinality=data.get("min_cardinality", 0),
            max_cardinality=data.get("max_cardinality", 0),
            violation_severity=_resolve_severity(data.get("violation_severity"),
                                                 unresolved),
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
            # The projection declaration. A nested block for the same reason
            # the five above are: it carries a model name and that model's own
            # parameters, which are meaningless flattened beside `warning:`.
            dynamics_config=data.get("dynamics") or None,
            forecast_config=data.get("forecast") or None,
            horizon=parse_duration(data.get("horizon")),
            lookback=parse_duration(data.get("lookback")),
            # CARRIED, NOT PARSED. Whether the expression is well formed, and
            # whether its operands exist, are questions with better answers
            # than a file that will not load: `unreachable_declarations` says
            # so at load, and a decline says so per cell.
            derived=(str(data["derived"]) if data.get("derived") else None),
            align_tolerance=parse_duration(data.get("align_tolerance")),
            # the declared role. Normalised here rather than at every
            # read site, and an unrecognised word is reported and dropped —
            # the same convention `_resolve_axioms` and `_resolve_severity`
            # already use, so one mistyped field costs that field and not the
            # file. Dropping it silently would be worse than the defect this
            # closes: the author would believe they had declared a role.
            role=_resolve_role(data.get("role"), name, unresolved),
            # Same convention as `role` above: normalised here, and an
            # unrecognised value is reported and dropped rather than coerced.
            # `expect_variation: yes` must not become False by way of
            # `bool("yes")` logic somewhere downstream.
            expect_variation=_resolve_expect_variation(
                data.get("expect_variation"), name, unresolved),
            # Same convention again: normalised here, unrecognised
            # values reported and dropped. Which side of a balance a quantity
            # sits on is a domain fact, and the path this feeds used to read it
            # off the indicator's name.
            flow_direction=_resolve_flow_direction(data.get("flow"), name,
                                                   unresolved),
            # what the AUTHOR typed, which the values cannot say.
            unresolved_values=unresolved,
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

    # A MAPPING IS NOT A MODEL, and this used to be the whole test.
    #
    # `is_domain_model` is published as the filter a directory scan uses so it
    # does not need exceptions for control flow. It answered TRUE for any
    # mapping at all, including `{"anything": 1}`: with no `domain:` key the
    # line above falls back to the document itself, and every field below reads
    # through `.get(...)` with a default, so a file sharing nothing with this
    # vocabulary loaded as a model with no entity types, no indicators and an
    # empty id. Nothing raised and nothing was checked.
    #
    # It went unnoticed because the only companions in front of it were the
    # `*_constraints.yaml` files, whose `domain:` IS present and is a string --
    # caught one line up. The first companion of a different shape to be shipped
    # beside the examples, a surprise corpus, was accepted, and the two censuses
    # that walk that directory then read it as a model: one subscripted
    # `["domain"]` and raised `KeyError`, the other silently contributed
    # nothing, which is the worse of the two.
    #
    # THE TEST IS *DOES THIS DECLARE ANYTHING THE LOADER READS*, not the
    # presence of one chosen key. A model with only `indicators:` is degenerate
    # and is still a model; a document sharing NO key with this vocabulary is
    # not one, whatever else it contains. Derived from the key set below rather
    # than written out, so a field added there is covered here for free.
    if "domain" not in data and not (set(domain) & _MODEL_KEYS):
        # THE WHOLE SET, not a slice of it. The first draft printed
        # `sorted(_MODEL_KEYS)[:6]`, which is an alphabetical accident: it named
        # `action_templates` and `aliases` and stopped before `entity_types`,
        # so the remedy an author most needs was the one the message cut off.
        # Sixteen names fit in an error; a truncation that hides the important
        # one does not save anybody anything.
        raise NotADomainModelError(
            f"no `domain:` key and nothing this loader reads: "
            f"{sorted(domain)[:8]}. A domain model declares at least one of "
            f"{sorted(_MODEL_KEYS)} — this looks like a companion (a file "
            f"whose subject is a model rather than being one). Use "
            f"is_domain_model() to filter these when scanning a directory."
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
        rules=[r for r in _require_sequence(domain.get("rules"), "rules")
               if isinstance(r, dict)],
        closure=[str(c) for c in
                 _require_sequence(domain.get("closure"), "closure")],
        relationship_rules=[
            r for r in _require_sequence(
                domain.get("relationship_rules"), "relationship_rules")
            if isinstance(r, dict)],
        calendar=dict(domain.get("calendar") or {}),
        action_templates=[
            t for t in _require_sequence(
                domain.get("action_templates"), "action_templates")
            if isinstance(t, dict)],
        planning=dict(domain.get("planning") or {}),
        causal=dict(domain.get("causal") or {}),
        indicators=indicators,
        axiom_parameters=_require_mapping(
            domain.get("axiom_parameters"), "axiom_parameters"),
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
