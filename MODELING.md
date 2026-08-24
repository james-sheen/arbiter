# The domain model format

*Eight axioms over a typed graph, declared in YAML, kept first-order on purpose.*

---

## Why this document exists

`arbiter-engine` checks a domain model that you write. This specifies what that
model means -- what an indicator is, what it means for one to declare an axiom,
and why an axiom might be absent.

The format is deliberately small: three concepts -- entities, relationships,
indicators -- one vocabulary of eight invariants, and one structural rule.
Everything an implementation might add around it (storage, collection, alerting,
remediation) is out of scope here.

`examples/water_tank.yaml` in this repository is a worked model declaring every
one of the eight axioms at least once, so it doubles as a schema reference.

## The model

A domain declares three things.

**Entity types** — the kinds of thing that exist.

```yaml
entity_types: [ModelEndpoint, ModelVersion, InferenceRequest]
```

**Relationship types** — how they connect. Edges are typed, and the vocabulary is per-domain.

```yaml
relationship_types: [serves, routes_to, derived_from]
```

**Indicators** — what is measurable about each entity type, and which invariants each measurement
must satisfy. This is where the work is.

```yaml
indicators:
  ModelEndpoint:
    - name: p99_latency_ms
      type: NUMERIC
      axioms: [RESPONSIVENESS, BOUNDEDNESS]
      warning: 500
      critical: 2000
```

An indicator carries a `name`, a `type`, a list of `axioms` it is expected to satisfy, an optional
`direction`, and optional `warning` / `critical` thresholds. Some axioms take a configuration block
of their own — `conservation:` and `monotonicity:` appear below — and two of them read a declared
`role:` rather than guessing the kind of quantity from the name.

**Two declarations exist because a name cannot carry the fact, and both are places a derivation is
tempting.** `consistency: {agrees_with: [...]}` says two readings are redundant and must match.
Redundancy is a claim about the system, not an inference from naming: two channels of one part are
the tempting pair and often the wrong one, because a temperature sensor exposing `Name` and `Name1`
may be reporting its own die and an external diode, which differ by tens of degrees on a healthy
board. Pair them and the engine reports disagreement between readings that were never supposed to
agree — a false finding on every working machine. **If a rule can generate the pairs, it does not
know the pairs.**

**HOMEOSTASIS learns its normal from the window, which means a fault that lasts is eventually
absorbed into it.** The baseline is a mean and spread over recent history, and that history contains
the deviation — so as a fault persists the mean walks toward it, the spread widens, and the score
falls until the axiom goes quiet on a fault that is still running. That is what a *rolling* baseline
is, and it is the right default: a quantity that legitimately drifts must not be accused forever.

**When you know where a quantity is supposed to sit, say so, and the check stops depending on
history at all.** `homeostasis: {setpoint: 0, tolerance: 5}` compares against a number you wrote
rather than one the engine inferred, so nothing about it moves when the reading does.
`tolerance_critical` defaults to twice `tolerance`. A setpoint without a tolerance is refused rather
than given one — how far is too far is a fact about your system, and an engine that guessed it would
be deciding a domain question. This is also the way past the widest sample floor in the format: the
learned path needs thirty observations inside a seven-day window, so a series sampled less often than
roughly every six hours can never reach it, while a declared setpoint needs none.

`homeostasis: {must_return_within: 15m}` asks the other question — *did this come back inside my
deadline* — by building the baseline from samples older than that span. **Its limit is stated because
it is easy to mistake for the fix**: it moves the absorption horizon out by the span rather than
removing it, so a fault outlasting the deadline by long enough is absorbed again. Use it when you
have a deadline and no target; use a setpoint when you have a target.

**MONOTONICITY tolerates some backward movement, and the number is yours to set.** A counter
declared `expected_direction: increasing` fires after **three** reversals inside the window, not
after one — noise, retransmits and clock skew all produce a single backward step in series that are
fine. Write `monotonicity: {reversal_tolerance: 1}` for a quantity where one rollback is a fault,
and `{reset_tolerance: N}` for the separate count of drops-to-near-zero that `allow_reset` excuses
individually. Both default to 3. **Below the tolerance the axiom is quiet, exactly as BOUNDEDNESS is
quiet at 84 against a `warning:` of 85** — the difference that matters is that these are now numbers
you declare rather than numbers the engine keeps to itself.

**CONSERVATION needs both halves of the balance named, and it will not work either out.** Declare
the pairing in the `conservation:` block: `input_property:` and `output_properties:`. An indicator
listing CONSERVATION without that block is reported as an unreachable declaration when the model
loads, and declines every cycle rather than passing quietly — it is a check the engine cannot run,
not a check that found nothing. There is a separate one-word field, `flow: in` or `flow: out`, which
tells the traversal kernel which side of a balance a quantity sits on when it walks a flow cycle
through the topology; the kernel holds no indicator, so it cannot read the block. Declare `flow:` on
both sides. Neither field is inferred from the property's name, and both used to be: the engine
rewrote an `_in` marker to `_out` and balanced against whatever that produced, which in three
shipped models named a property that did not exist. `bytes_in` and `bytes_out` balance;
`bad_actor_input` and `line_input_status` do not; nothing in those names says which is which.

**Telling a broken sensor from a real fault is a separate question, and this format answers it
without a range.** A reading that never moves is a dead probe rather than a very steady system, and
saying so is opt-in: declare `expect_variation: true` on the indicator and STABILITY in its
`axioms:`. Anything the checker could not evaluate — no value, too few samples, no threshold
configured — is reported in the envelope's `not_checked` leg rather than passing silently, which is
the distinction a range would otherwise have to carry.

## The eight axioms

An axiom is a structure-quantified invariant. It is stated once, in general terms, and evaluated
against every indicator that declares it. A violation becomes a problem.

| Axiom | The invariant it asserts |
|---|---|
| **STABILITY** | The system tends toward equilibrium. Flags oscillation and state-bouncing |
| **BOUNDEDNESS** | Quantities stay within limits. Threshold breach, and trend toward exhaustion |
| **CONNECTIVITY** | Required relationships hold. Orphaned entities, missing edges |
| **CONSISTENCY** | State is internally coherent. Logical impossibilities — a negative count, a percentage above 100 |
| **RESPONSIVENESS** | Things respond to input. Unresponsive entities, degrading latency |
| **HOMEOSTASIS** | A property stays in its normal range, measured as deviation from a rolling baseline rather than against a fixed line |
| **CONSERVATION** | Quantities are preserved across transformations. Inflow and outflow should balance; a persistent deficit means something is being lost or double-counted |
| **MONOTONICITY** | Properties that should only move one way keep doing so. Unexpected reversals |

Eight is not a magic number. It is the set that turned out to be sufficient for every domain
modelled so far, and the claim being made is modest: **these eight cover a useful fraction of what
goes wrong in systems that can be described as a typed graph with numeric measurements.** If you
find a ninth you need, the format does not stop you.

## The rule that is easy to get wrong

**A floor is a specification, not a guess.**

BOUNDEDNESS has four threshold keys. `warning:` and `critical:` are ceilings; `lower_warning:` and
`lower_critical:` are floors. Declaring both pairs on one indicator gives you a band, and a reading
outside it in either direction is reported with the direction stated.

The question is not whether a floor is expressible. It is where the number comes from.

**Declare a floor when something told you the number.** A datasheet says the fan stalls below 1000
rpm. A contract says throughput under 500 tps is a breach. Physics says a pressure cannot go below
ambient. The number exists before you write the model, and the model transcribes it.

**Do not invent one.** For accuracy, satisfaction, margin, compliance rate — the metrics where lower
is worse and nobody has published a line — a floor encodes an assumption you almost never have:
that you know the correct value in advance. Use HOMEOSTASIS instead and let the baseline decide
what "too low" means. It asks whether *this* system has changed, which is the question you actually
wanted answered.

Both halves of that were always the rule. Until 0.1.7 only the second half was expressible, so the
guide said *BOUNDEDNESS is for upper bounds only* — true of the engine, and over-general as advice.
It was reported from outside by someone transcribing real fan thresholds from a vendor declaration:
exactly the case where the number is given to you and the guidance did not apply.

A metric with no published floor carries `direction: LOWER`, declares HOMEOSTASIS, and has no
thresholds at all:

```yaml
- name: accuracy_score
  type: NUMERIC
  axioms: [HOMEOSTASIS, MONOTONICITY]
  direction: LOWER
```

A quantity whose floor is documented declares it:

```yaml
- name: speed_rpm
  type: NUMERIC
  axioms: [BOUNDEDNESS]
  lower_warning: 2000       # vendor minimum, with margin
  lower_critical: 1000      # vendor stall speed
  critical: 12000           # both pairs: the band a fan must run inside
```

`direction:` is not involved. It selects which side HOMEOSTASIS fires on, and it has never had
anything to do with thresholds — one field meaning two things across two axioms is the confusion
that separate floor keys exist to avoid.

Contrast an upper-is-worse indicator, where a fixed line is meaningful and BOUNDEDNESS applies
alongside baseline deviation:

```yaml
- name: hallucination_rate
  type: NUMERIC
  axioms: [HOMEOSTASIS, BOUNDEDNESS]
  direction: UPPER
  warning: 0.05
  critical: 0.15
```

Encoding a floor as a bound is a category error, and it is the single most common mistake when
writing a domain for the first time.

## The structural constraint: stay first-order

A domain model may not contain:

1. **Cycles in derived properties.** If A is computed from B and B from A, there is no evaluation
   order and no fixed point to check.
2. **Condition trees deeper than three levels.** Beyond that, a human can no longer say what the
   rule means, and neither can a reviewer.
3. **Nested references** of the form `derived.derived.X` — references resolve one level, flat.

And, more generally: no quantifiers nested inside quantifiers, and no constraints *about* the
constraints.

**Why this matters more than it looks.** These restrictions are what keep checking polynomial. A
model that permits nested quantification is expressive enough to encode problems you cannot check
in reasonable time, and the failure mode is not an error message — it is a checker that quietly
becomes too slow on the one domain that grows. The restriction buys a guarantee: **evaluation cost
stays predictable as the graph grows**, which is the property that lets a domain expert add
indicators without consulting anyone about performance.

The constraint should be enforced at load time, not by convention. A model that violates it should
be rejected outright, with an override for people who know why they want one.

## Coverage is a declaration, and absences are choices

The set of axioms a domain declares is a statement about **what that domain chose to model**, not
about what is true of it. A domain that declares six of the eight has not failed a test — it has
recorded that two invariants were not modelled.

This matters when comparing domains. It is tempting to read coverage counts as a capability score,
and that reading is wrong in both directions: a domain with all eight may be shallow in each, and a
domain with five may carry far more indicators on the ones it declares. **The informative signal is
shape, not count** — which axioms carry weight, and how many indicators sit behind each.

Where an axiom is absent, say so as an absence. "This domain does not model CONNECTIVITY" is honest
and useful. Presenting it as though the invariant were inapplicable is a claim about the world that
the model does not support.

## What this format deliberately does not specify

- **How measurements arrive.** Collection, scraping, agents, push versus pull — all out of scope.
- **What to do about a violation.** Alerting, remediation, escalation are separate concerns.
- **How baselines are computed.** HOMEOSTASIS needs a rolling baseline; the window length, the
  statistic, and the minimum sample count are implementation choices.
- **Severity semantics.** Whether warning means page-someone is yours to decide.

## Honest limits

**This finds violations of invariants you declared.** It does not discover invariants you did not
think of. A domain model is a statement of what you believe about a system, and the checker's job
is to tell you where reality disagrees with that statement — which is valuable precisely because it
is bounded, and worth being explicit about because the adjacent claim is very tempting to make.

The corollary is uncomfortable and worth stating plainly: **the things this misses are the things
you did not model.** Findings about the measurement apparatus itself are the sharpest example —
a broken collector produces a *plausible* data stream, not an anomalous one, so no amount of axiom
coverage reaches it.

Treat the model as a hypothesis about the system, not as an oracle over it.
