"""An indicator's ROLE, declared in the model instead of guessed from English.

THE DEFECT THIS CLOSES
Two axioms decided whether they applied by reading the indicator's NAME.
`RESPONSIVENESS` evaluated only names containing `response` or `latency`;
`CONSISTENCY` only names tokenising to `count`, `percent`/`pct` or `ratio`.
Every other declared pair reached its return having evaluated nothing.

Since the engine at least SAYS so, and that honesty leg is what made
this diagnosable in minutes rather than never. But the model was still allowed
to promise a check the engine could not deliver, and the author found out at run
time, per entity, per cycle, by reading a decline — and only if they read
declines at all, which is precisely the habit the envelope exists to build and
cannot assume.

**It is also the project's own rule broken in the component that names it**:
*no hardcoded domain patterns — axiom checkers must not contain if/else branches
for specific domains, including property name normalization.* Name-token gating
IS property-name normalisation deciding whether a check runs. The engine was
domain-agnostic in its data structures and domain-COUPLED in its applicability
rules, which is the harder half to see because nothing in the YAML mentions it.

WHY A ROLE RATHER THAN A LONGER TOKEN LIST
Adding `pulldown_error` to a list of latency words would fix one model and leave
the rule exactly as it was: English deciding coverage. A role is a declaration —
`role: latency` says what KIND of quantity this is, which is the thing the check
actually needs to know. The vocabulary is engine-level semantics, not domain
vocabulary, so a cold-chain model and a Kubernetes model use the same four words.

INFERENCE IS KEPT, AND IT ANNOUNCES ITSELF
Removing name matching outright would silently change coverage for every model
already relying on it. So an indicator with NO declared role falls back to the
original rules, reproduced here exactly — substring for latency, whole-token for
the others, each preserving the reasoning of the CD that set it (moved
consistency off substrings because `observed_generation` read as a ratio). What
changes is that the fallback is now VISIBLE: callers can ask where a role came
from, and the declines say `inferred from the name` rather than presenting a
guess as a rule.

A DECLARED ROLE SUPPRESSES INFERENCE ENTIRELY. `response_count` is a count of
responses; if its author says `role: count`, the engine must not also treat it as
a latency because the word `response` appears in it. Guessing alongside an
explicit declaration is how a config option becomes advisory.
"""

from __future__ import annotations

import re
from typing import Any, FrozenSet, Optional, Tuple

from ...types import Axiom

# The four roles. Engine-level semantics: what kind of quantity this is.
LATENCY = "latency"
COUNT = "count"
PERCENTAGE = "percentage"
RATIO = "ratio"

ROLES: FrozenSet[str] = frozenset({LATENCY, COUNT, PERCENTAGE, RATIO})

#: Spellings an author might reasonably write. Being punished for `pct` when the
#: engine wanted `percentage` is the kind of friction that sends people back to
#: relying on the name.
_ALIASES = {
    "response": LATENCY,
    "response_time": LATENCY,
    "responsetime": LATENCY,
    "duration": LATENCY,
    "lag": LATENCY,
    "counts": COUNT,
    "percent": PERCENTAGE,
    "percentages": PERCENTAGE,
    "pct": PERCENTAGE,
    "ratios": RATIO,
    "fraction": RATIO,
}

#: Which roles each axiom has a universal rule for. This is the ONE place the
#: mapping lives: the checkers gate on it and the load-time reachability report
#: reads it, so a checker that grows a rule cannot drift from the report that
#: tells authors which pairs are evaluable.
AXIOM_ROLES = {
    Axiom.RESPONSIVENESS: frozenset({LATENCY}),
    Axiom.CONSISTENCY: frozenset({COUNT, PERCENTAGE, RATIO}),
}

# --- legacy inference, preserved exactly -------------------------------------
# whole word-tokens, NOT substrings — a substring test mis-reads
# `observed_generation` as a ratio (gene-ratio-n), `account` / `discount` as
# counts, and `configuration` / `duration` / `migration` as ratios.
_COUNT_TOKENS = frozenset({"count", "counts"})
_PERCENT_TOKENS = frozenset({"percent", "percentage", "percentages", "pct"})
_RATIO_TOKENS = frozenset({"ratio", "ratios"})

#: RESPONSIVENESS matched on SUBSTRING, not token, and that difference is
#: deliberate rather than an oversight to tidy up: `p99latency` and
#: `responsetime` carry no separator, so a token rule would silently narrow
#: coverage for models that work today. Preserved as-found.
_LATENCY_SUBSTRINGS = ("response", "latency")

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def name_word_tokens(name: Any) -> set:
    """Split a name into lowercase word tokens across snake, camel and kebab
    boundaries. `ready_ratio` -> {ready, ratio}."""
    spaced = _CAMEL_BOUNDARY.sub(" ", str(name))
    return {t for t in re.split(r"[^a-zA-Z0-9]+", spaced.lower()) if t}


def normalise_role(raw: Any) -> Optional[str]:
    """A declared role string -> a canonical role, or None if unrecognised.

    Returning None for an unknown word rather than raising is the loader's
    convention for every other enum-ish field: a domain-authoring mistake is
    reported and skipped, not turned into an import-time crash for the caller.
    """
    if raw is None:
        return None
    word = str(raw).strip().lower().replace("-", "_")
    if not word:
        return None
    if word in ROLES:
        return word
    return _ALIASES.get(word)


def declared_role(indicator: Any) -> Optional[str]:
    return normalise_role(getattr(indicator, "role", None))


def roles_for(indicator: Any) -> Tuple[FrozenSet[str], str]:
    """The roles this indicator carries, and WHERE THEY CAME FROM.

    Returns ``(roles, source)`` with source one of ``declared`` / ``inferred`` /
    ``none``. The source is half the value: a decline that says a role was
    guessed from the name tells the author what to declare, and a decline that
    hides it sends them to rename their indicator instead.
    """
    explicit = declared_role(indicator)
    if explicit:
        return frozenset({explicit}), "declared"

    name = str(getattr(indicator, "name", "") or "")
    found = set()
    lowered = name.lower()
    if any(s in lowered for s in _LATENCY_SUBSTRINGS):
        found.add(LATENCY)
    tokens = name_word_tokens(name)
    if tokens & _COUNT_TOKENS:
        found.add(COUNT)
    if tokens & _PERCENT_TOKENS:
        found.add(PERCENTAGE)
    if tokens & _RATIO_TOKENS:
        found.add(RATIO)
    return frozenset(found), ("inferred" if found else "none")


def applies(axiom: Axiom, indicator: Any) -> Tuple[bool, FrozenSet[str], str]:
    """Does ``axiom`` have a universal rule for ``indicator``?

    Returns ``(applies, matched_roles, source)``. An axiom absent from
    AXIOM_ROLES is not role-gated at all and always applies — the answer for
    BOUNDEDNESS and friends, which read thresholds rather than names.
    """
    wanted = AXIOM_ROLES.get(axiom)
    if wanted is None:
        return True, frozenset(), "not_role_gated"
    roles, source = roles_for(indicator)
    matched = roles & wanted
    return bool(matched), matched, source


def explain_absence(axiom: Axiom, indicator: Any) -> str:
    """The decline detail. Says what would make the check run.

    The sentences this replaces described the ENGINE'S RULE — *check() only
    evaluates indicators whose name contains 'response' or 'latency'* — which
    is true and leaves the reader to work out that renaming their indicator is
    the remedy. Renaming a domain concept to satisfy a checker is the wrong
    remedy; declaring what the concept IS, is the right one.
    """
    wanted = sorted(AXIOM_ROLES.get(axiom, frozenset()))
    roles, source = roles_for(indicator)
    if source == "declared":
        got = sorted(roles)
        return (f"declared role {got[0]!r} has no {axiom.value} rule; "
                f"this axiom applies to roles {wanted}")
    return (f"no role is declared for this indicator and none could be inferred "
            f"from its name; declare one of {wanted} as `role:` on the "
            f"indicator to have {axiom.value} evaluate it")


def unreachable_axioms(indicator: Any) -> list:
    """Declared (indicator, axiom) pairs that can never produce an evaluation.

    Statically decidable from the indicator alone, which is the point: the
    author declared `axioms: [RESPONSIVENESS]`, the loader accepted it,
    `model_describe` reported it, and the pair could never fire. Today that is
    discoverable at load instead of at cycle 1.
    """
    out = []
    for axiom in getattr(indicator, "relevant_axioms", None) or []:
        ok, _, _ = applies(axiom, indicator)
        if not ok:
            out.append(axiom)
    return out
