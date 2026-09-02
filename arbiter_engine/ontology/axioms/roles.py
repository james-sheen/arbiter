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

INFERENCE IS GONE, AND THE CLAIM THAT REPLACED IT WAS FALSE
This block used to say inference was kept but now ANNOUNCED ITSELF — *callers
can ask where a role came from*. They could not. The announcement existed on the
branch where NO role was inferred, where the decline says so, and was absent on
the branch where one WAS inferred and its rule ran, which is the case the
visibility was for. A claim true of one branch, written about both.

The other half of that argument was that removing name matching would silently
change coverage for every model relying on it. Measurable, and measured: across
the shipped domain packs ELEVEN (indicator, axiom) pairs relied on the guess and
NONE declared a role. All eleven now declare one, so coverage did not change and
`silently` is the word that stopped being true.

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

# --- the inference is GONE, and this is where it was --------------
# It matched `count` / `percent` / `pct` / `ratio` as whole word-tokens and
# `response` / `latency` as substrings, all of them English, and handed back a
# role the author never wrote.
#
# A ROLE IS AN INTERPRETATION FACT, and the published guide refuses to derive
# one from a name in as many words: deriving a relationship from names is a
# guess wearing the costume of a derivation. the project's design guidance lists property-name
# normalisation among the hardcoded domain patterns a domain-agnostic component
# must not contain. An internal ruling removed the same shape from CONSERVATION, which had
# been rewriting `_in` to `_out` to find the other half of a balance.
#
# REPORTED FROM OUTSIDE, against the engine our own guide describes. The
# demonstration is two indicators identical in every declared respect and given
# identical values: `error_count` had a role inferred and its rule applied,
# `errors` declined for a missing role. Nothing on any queryable surface said
# which had happened, so the visible difference between them was their name.
#
# ITS COROLLARY IS WORSE THAN THE DEFECT, and belongs to whoever reads a
# decline: the ABSENCE of a missing-role decline was not evidence that a role
# was supplied. It was evidence about the property's name.
#
# MEASURED BEFORE REMOVING, across the shipped domain packs: eleven
# (indicator, axiom) pairs relied on the guess and NONE declared a role. All
# eleven now declare one, so the removal costs no coverage -- which is the
# remedy the guide has always named. The published example had already reached
# it the hard way: it renamed a domain concept so the guess would land, then
# put the name back and declared the role instead.

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

    Returns ``(roles, source)``, source ``declared`` or ``none``. An internal ruling
    removed the third. A role now comes from the model or from nowhere.
    """
    explicit = declared_role(indicator)
    if explicit:
        return frozenset({explicit}), "declared"
    # two sources, not three. `inferred` is gone rather than hidden:
    # a caller branching on it still compiles and now never takes that arm.
    return frozenset(), "none"


def has_cross_signal_rule(indicator: Any) -> bool:
    """does this indicator declare peers it must agree with?

    A second, independent way for CONSISTENCY to have something to do. The
    role-gated rules ask *is this value possible on its own terms*; the
    cross-signal rule asks *do two readings that should agree, agree*. Neither
    implies the other, and a redundant pair of temperature sensors carries no
    role at all — `temp_c` tokenises to nothing this module knows.
    """
    config = getattr(indicator, "consistency_config", None)
    if not isinstance(config, dict):
        return False
    peers = config.get("agrees_with")
    return bool(peers)


def has_balance_rule(indicator: Any) -> bool:
    """does this indicator declare what balances against what?

    CONSERVATION had a second way in until with no ``conservation:``
    block the checker rewrote a marker in the property NAME — ``_in`` to
    ``_out``, ``_requests`` to ``_responses`` — and balanced against whatever
    that produced. Removing that made the pair statically decidable, which is
    the only reason this predicate can exist at all: before, an undeclared
    CONSERVATION *might* evaluate, so nothing could say in advance that it
    would not.
    """
    config = getattr(indicator, "conservation_config", None)
    if not isinstance(config, dict):
        return False
    return bool(config.get("input_property")) and bool(
        config.get("output_properties"))


def applies(axiom: Axiom, indicator: Any) -> Tuple[bool, FrozenSet[str], str]:
    """Does ``axiom`` have a universal rule for ``indicator``?

    Returns ``(applies, matched_roles, source)``. An axiom absent from
    AXIOM_ROLES is not role-gated at all and always applies — the answer for
    BOUNDEDNESS and friends, which read thresholds rather than names.

    a declared cross-signal block makes CONSISTENCY applicable
    whatever the role says. This has to live HERE rather than only in the
    checker, because `unreachable_axioms` below reads the same function: an
    indicator declaring `consistency: {agrees_with:...}` with no role would
    otherwise be reported by `model_describe` as a declaration that can never
    fire, while firing. A false entry in the honesty leg is worse than a
    missing capability — it is the capability we have, denied in the report a
    reader trusts to be exhaustive.

    CONSERVATION is the MIRROR of that case, and it is the first
    entry here that subtracts rather than adds. It is not role-gated, so it
    reached the `not_role_gated` line above and was reported as reachable; with
    the name fallback gone, `axioms: [CONSERVATION]` and no `conservation:`
    block can never evaluate under any input, which is exactly what
    `unreachable_declarations` exists to say. Three shipped domain packs were
    in that state on the day this landed — and two of them named a partner
    property that did not exist in their own model, so they had been reporting
    a clean pass rather than a check.

    Note this reports a MODELLING gap and refuses nothing: an over-declared
    model is not a broken one, and the loader still loads it.
    """
    if axiom is Axiom.CONSERVATION and not has_balance_rule(indicator):
        return False, frozenset(), "no_balance_declared"
    wanted = AXIOM_ROLES.get(axiom)
    if wanted is None:
        return True, frozenset(), "not_role_gated"
    roles, source = roles_for(indicator)
    matched = roles & wanted
    if not matched and axiom is Axiom.CONSISTENCY and has_cross_signal_rule(indicator):
        return True, frozenset(), "cross_signal"
    return bool(matched), matched, source


def explain_absence(axiom: Axiom, indicator: Any) -> str:
    """The decline detail. Says what would make the check run.

    The sentences this replaces described the ENGINE'S RULE — *check() only
    evaluates indicators whose name contains 'response' or 'latency'* — which
    is true and leaves the reader to work out that renaming their indicator is
    the remedy. Renaming a domain concept to satisfy a checker is the wrong
    remedy; declaring what the concept IS, is the right one.
    """
    # CONSERVATION is not role-gated, so every sentence below is the
    # wrong one for it: `wanted` would be the empty list and the remedy would
    # read *declare one of [] as `role:`*. The remedy here is a block, and it
    # names the block rather than a property the engine picked out of a name.
    if axiom is Axiom.CONSERVATION and not has_balance_rule(indicator):
        config = getattr(indicator, "conservation_config", None)
        if isinstance(config, dict) and config:
            missing = ("input_property" if not config.get("input_property")
                       else "output_properties")
            return (f"the conservation block declares no {missing}; a balance "
                    f"needs both an input and at least one output to compare")
        return ("no conservation block is declared, so there is nothing to "
                "balance against; declare `conservation: {input_property: "
                "..., output_properties: [...]}` naming the properties that "
                "offset each other")
    wanted = sorted(AXIOM_ROLES.get(axiom, frozenset()))
    roles, source = roles_for(indicator)
    # CONSISTENCY has a second way in, so a decline that names only
    # the first tells half the truth. The remedy an author needs depends on
    # which question they meant to ask, and the sentence now offers both.
    alt = ""
    if axiom is Axiom.CONSISTENCY:
        alt = (", or declare `consistency: {agrees_with: [...]}` to compare it "
               "against a redundant reading instead")
    if source == "declared":
        got = sorted(roles)
        return (f"declared role {got[0]!r} has no {axiom.value} rule; "
                f"this axiom applies to roles {wanted}{alt}")
    # this said *and none could be inferred from its name* until the
    # sentence outlived the mechanism. An internal ruling removed the inference; the clause
    # stayed, on an author-facing surface, telling a reader that the spelling
    # was tried and failed. That is the rename this function's own docstring
    # calls the wrong remedy, recommended by the string the function returns.
    return (f"no role is declared for this indicator, and the engine does not "
            f"read one from its name; declare one of {wanted} as `role:` on "
            f"the indicator to have {axiom.value} evaluate it{alt}")


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
