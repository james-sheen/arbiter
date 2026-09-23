"""The assumption stamps, in one place, with what each of them discloses.

WHAT A STAMP IS. Every number this engine projects rests on approximations the
engine made rather than the author declared. A stamp names one of them. It is
not a warning and not a finding: it is the engine saying which of its own
choices the value in front of you depends on, so that a reader who disagrees
with the choice knows which number to distrust.

WHY THEY LIVE HERE. Until they lived as bare string literals at twenty
sites across four modules, and nothing anywhere held the list. The cost was not
hypothetical. An outside comparison of this engine reproduced all three of its
ENUMERATED vocabularies exactly -- the fourteen decline reasons, the six gap
types, the eight raced outcomes -- and got this one at nine of twenty, because
nine is what running the shipped example happens to show you and there was no
other way to find the rest. `COMPATIBILITY.md` meanwhile grants a patch release
permission to ADD a stamp, so the project published a rule for changing a
vocabulary it had never published. A consumer told that a list may grow needs
the list it grows from.

Importing the name rather than repeating the literal is the other half: a
misspelled stamp is now a `NameError` at import rather than a disclosure that
silently stops matching what a reader greps for.

WHAT THIS MODULE IS NOT. It is not a closed enum on the wire.
`schema/envelope.schema.json` types `assumptions` as an array of string with no
`enum`, deliberately, for two reasons. Adding a stamp would otherwise become a
schema change and contradict the compatibility rule above; and one stamp is
PARAMETERISED -- `action_property_from_parameter_name:<property>` carries a
property name that no fixed vocabulary can contain. The baseline is published
in `MODELING.md`, derived from this tuple by a test rather than transcribed.
"""

from __future__ import annotations

from typing import Tuple

# ---------------------------------------------------------------------------
# How a value travelled: the response model between one node and the next.
# ---------------------------------------------------------------------------

#: The coupling was developed as a first-order lag -- dead time, then an
#: exponential approach to the steady state. It is the ordinary shape of a
#: physical coupling and it is still a shape the engine chose to apply.
FIRST_ORDER_RESPONSE = "first_order_response"

#: The time course crossed by this value was NOT declared. The engine supplied
#: its own dead time or time constant, or both. The stamp says that it
#: happened; the `missing_declaration` question that accompanies it names the
#: absent key and the number used in its place.
TIME_COURSE_NOT_DECLARED = "time_course_not_declared"

#: The severity floor deciding what counts as FAULTY evidence was the engine's
#: and not the author's. `infer` reads the last `check()` and treats an entity
#: as faulty only when it carries a HIGH or CRITICAL finding; a model declaring
#: `causal.evidence_severity:` picks its own floor and this stamp is absent.
#:
#: Stamped because the default is INVISIBLE FROM THE ANSWER. A model whose
#: breaches are all warnings returns every posterior sitting at its prior,
#: which reads as a graph that is not wired up -- measured while writing the
#: example that first ran this verb, and reported by an outside review as a
#: place where the engine's own declare-don't-default rule was not applied to
#: itself.
EVIDENCE_SEVERITY_NOT_DECLARED = "evidence_severity_not_declared"

#: The model DID declare `causal.evidence_severity:` and the engine could not
#: use what it said, so the floor above is the engine's and the declaration was
#: not partially applied. Carried BESIDE `evidence_severity_not_declared`
#: rather than instead of it: the first stamp's claim -- the floor was ours --
#: stays exactly as true, and a consumer already matching on it keeps matching.
#:
#:, and it exists because four different author actions were one bare
#: stamp. Writing `[critical, hihg]`, writing `[]`, writing `critical` as a
#: scalar and writing nothing at all all returned the same disclosure, and
#: three of the four are someone TRYING to declare the floor. An outside review
#: measured it: a reader who mistyped a severity was told `not declared`,
#: concluded the file had not loaded, and had no thread to pull. The engine's
#: own comment beside `_KNOWN_CAUSAL_KEYS` describes this failure for a
#: misspelled KEY -- the key side was closed in the round that shipped it, the
#: value side was not.
#:
#: WHICH WORD WAS REFUSED IS NOT HERE. It is in `model_describe`, as an
#: `unknown_value` row naming the value and the nearest severity to it, because
#: `assumptions` is a list of strings and the row shape carrying a
#: `did_you_mean` already existed. This stamp says LOOK THERE; it does not
#: duplicate what is there.
EVIDENCE_SEVERITY_UNUSABLE = "evidence_severity_unusable"

#: The horizon was long enough that the transient had finished, so the value
#: reported is the steady state rather than a point on the way to it.
STEADY_STATE_REACHED = "steady_state_reached"

#: Two couplings in series were composed by the EXACT cascade response rather
#: than by multiplying their separate response fractions. Stamped because the
#: composition is a choice, even though this is the accurate one.
SERIES_EDGES_COMPOSED_EXACTLY = "series_edges_composed_exactly"

#: Two couplings in series were composed by MULTIPLYING their response
#: fractions, which is an approximation. A chain that carries a stage the exact
#: form does not cover keeps this stamp, and a rollout crossing both kinds
#: carries both stamps, which is the honest report of a mixed chain.
SERIES_EDGES_COMPOSE_BY_PRODUCT = "series_edges_compose_by_product"

# ---------------------------------------------------------------------------
# How uncertainty was arithmetic'd.
# ---------------------------------------------------------------------------

#: The spread was propagated to first order -- the product of two uncertain
#: quantities was linearised rather than integrated. Exact for a declared
#: constant gain and an approximation once two uncertain factors multiply.
FIRST_ORDER_UNCERTAINTY = "first_order_uncertainty"

#: Declared spreads from different sources were combined in quadrature, which
#: is correct only if they are independent. Nothing in a domain model states
#: that they are, so the engine assumed it and says so.
INDEPENDENT_DECLARED_SPREADS = "independent_declared_spreads"

#: A forecast record arrived as a mean and a sigma and was expanded to
#: quantiles under a NORMAL assumption -- a distribution shape the producer did
#: not state. Defined in `forecast/contract.py` as `GAUSSIAN_STAMP` and
#: re-exported here so that the vocabulary is complete in one place.
GAUSSIAN_FROM_MEAN_SIGMA = "gaussian_from_mean_sigma"

# ---------------------------------------------------------------------------
# What was held still while the value moved.
# ---------------------------------------------------------------------------

#: Everything outside the traversed subgraph was held at its current value for
#: the whole horizon. Nothing else in the world was allowed to move.
EXOGENOUS_INPUTS_HELD = "exogenous_inputs_held"

#: No action was scheduled in this rollout, so what is reported is the world
#: left alone rather than the world acted upon.
NO_ACTION_SCHEDULED = "no_action_scheduled"

#: Contributions from several sources onto one target were SUMMED. Real
#: couplings saturate and interact; this engine's arithmetic does not.
LINEAR_SUPERPOSITION = "linear_superposition"

#: A declared coupling was followed regardless of how likely it is to carry the
#: effect. The engine did not prune a branch on probability, because an author
#: who declared the edge asserted that it couples.
DECLARED_COUPLING_NOT_PROBABILITY_PRUNED = "declared_coupling_not_probability_pruned"

#: The rollout was seeded from a PROJECTION of each series rather than from its
#: last observed value, so the starting point is itself a model output.
SEEDED_FROM_PROJECTION = "seeded_from_projection"

# ---------------------------------------------------------------------------
# How a candidate was scored.
# ---------------------------------------------------------------------------

#: The candidate was scored on a single deterministic trajectory, because no
#: declared spread reached it. A `clearance_probability` under this stamp is a
#: 0 or a 1 -- an indicator of whether the median breaches, not a probability
#: with anything behind it.
DETERMINISTIC_TRANSITIONS = "deterministic_transitions"

#: The candidate was scored over trajectories sampled from the DECLARED gain
#: spreads. The spread is the author's; the sampling is the engine's.
DECLARED_GAIN_SPREAD_SAMPLED = "declared_gain_spread_sampled"

#: A trajectory counts as breaching if it breaches at ANY step, so the worst
#: step decides the whole horizon. A candidate that is clear for fifty-nine
#: minutes and breaches for one is scored as breaching.
WORST_STEP_BINDS_THE_HORIZON = "worst_step_binds_the_horizon"

#: AND THE STEPS ARE ALL THERE IS. The axioms are evaluated at the
#: sampled instants and nowhere between them, so a trajectory that turns
#: between two of them turns unjudged. This stamp fires only where that can
#: actually cost something: a property moved more than once, and one of those
#: movements landed strictly between two sampled steps. One movement cannot
#: hide an extremum -- a first-order response from a single movement is
#: monotonic -- which is why a rollout of the shipped example does not carry
#: it.
#:
#: MEASURED, on two settings nine hundred and fifty seconds apart with the
#: line at 88.1: the true peak is 88.314 at t=950 and a grid that samples that
#: instant reports the breach, while grids of 300, 200 and 100 seconds report
#: CLEAN. **Refining the grid does not fix it** -- 100 s is clean and 950 s
#: breaches -- because what matters is whether the turning instant is on the
#: grid, not how fine the grid is. `step_s` is how finely a caller asked to
#: see the trajectory; without this stamp nothing said it was also deciding
#: what got judged.
MOVEMENT_BETWEEN_SAMPLED_STEPS = "movement_between_sampled_steps"

#: `expected_findings` was evaluated on the MEDIAN trajectory. The objective is
#: a step function of the values it compares, so a candidate settling a whisker
#: below a line scores as though it cleared comfortably. This is the stamp that
#: tells a reader to rank on `clearance_probability` instead when the question
#: is how likely the candidate is to stay clear.
OBJECTIVE_EVALUATED_AT_MEDIAN = "objective_evaluated_at_median"

# ---------------------------------------------------------------------------
# How a tie was broken.
# ---------------------------------------------------------------------------

#: Candidates equal on the objective were ordered by acting less.
TIES_BREAK_TOWARD_FEWER_ACTIONS = "ties_break_toward_fewer_actions"

#: Candidates still equal after that were ordered by the wider SIGNED headroom
#: in declared spreads. Present only when a declared spread actually reached a
#: trajectory, so a model that declares no spread keeps the order it had.
TIES_BREAK_TOWARD_THE_WIDER_MARGIN = "ties_break_toward_the_wider_margin"

# ---------------------------------------------------------------------------
# The one stamp that carries a value.
# ---------------------------------------------------------------------------

#: PREFIX, not a stamp. An action template named a parameter that no
#: `entity_property:` bound, so the engine matched the parameter name to a
#: property of the same name. The property is appended after the colon, which
#: is why this vocabulary cannot be a closed enum on the wire: the set of
#: property names is the domain's, not this module's.
ACTION_PROPERTY_FROM_PARAMETER_NAME_PREFIX = "action_property_from_parameter_name:"

#: Every stamp this engine emits, excluding the parameterised prefix above.
#: `MODELING.md` publishes this list and a test derives the table from this
#: tuple, so the guide cannot drift from the code by transcription.
#:
#: ORDER IS THE GROUPING ABOVE, not alphabetical: a reader arriving at an
#: unfamiliar stamp is better served by its neighbours than by its spelling.
ASSUMPTION_STAMPS: Tuple[str, ...] = (
    FIRST_ORDER_RESPONSE,
    TIME_COURSE_NOT_DECLARED,
    EVIDENCE_SEVERITY_NOT_DECLARED,
    EVIDENCE_SEVERITY_UNUSABLE,
    STEADY_STATE_REACHED,
    SERIES_EDGES_COMPOSED_EXACTLY,
    SERIES_EDGES_COMPOSE_BY_PRODUCT,
    FIRST_ORDER_UNCERTAINTY,
    INDEPENDENT_DECLARED_SPREADS,
    GAUSSIAN_FROM_MEAN_SIGMA,
    EXOGENOUS_INPUTS_HELD,
    NO_ACTION_SCHEDULED,
    LINEAR_SUPERPOSITION,
    DECLARED_COUPLING_NOT_PROBABILITY_PRUNED,
    SEEDED_FROM_PROJECTION,
    DETERMINISTIC_TRANSITIONS,
    DECLARED_GAIN_SPREAD_SAMPLED,
    WORST_STEP_BINDS_THE_HORIZON,
    MOVEMENT_BETWEEN_SAMPLED_STEPS,
    OBJECTIVE_EVALUATED_AT_MEDIAN,
    TIES_BREAK_TOWARD_FEWER_ACTIONS,
    TIES_BREAK_TOWARD_THE_WIDER_MARGIN,
)

#: The prefixes a stamp may carry a value behind. Kept separate from the tuple
#: above because a reader validating a stamp has to test membership one way for
#: a plain stamp and another way for a parameterised one.
ASSUMPTION_STAMP_PREFIXES: Tuple[str, ...] = (
    ACTION_PROPERTY_FROM_PARAMETER_NAME_PREFIX,
)


def is_known_stamp(stamp: str) -> bool:
    """Is this one of the stamps this engine emits?

    Accepts both shapes, because both appear in the same list on the wire: a
    plain stamp matched exactly, and a parameterised one matched on its prefix.
    Offered so that a consumer checking a stamp against the vocabulary does not
    have to rediscover that the second shape exists.
    """
    if stamp in ASSUMPTION_STAMPS:
        return True
    return any(stamp.startswith(prefix) and len(stamp) > len(prefix)
               for prefix in ASSUMPTION_STAMP_PREFIXES)
