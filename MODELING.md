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
tempting.** `consistency: {agrees_with: [...]}` says two readings are redundant and must match,
**within a tolerance you declare**: `tolerance:` is relative and `tolerance_absolute:` is in the
reading's own units. **One of them is required.** Neither is guessed, for the same reason a setpoint
without a tolerance does not get one: how far apart two readings may be before they disagree is a
fact about your system, and an engine that supplied it would be answering a domain question. Declare
neither and the pair declines `missing_config` naming the block to write, while every other rule on
that indicator goes on reporting. `tolerance_absolute: 0` is the right declaration for two statements
of one number that must be identical.
Redundancy is a claim about the system, not an inference from naming: two channels of one part are
the tempting pair and often the wrong one, because a temperature sensor exposing `Name` and `Name1`
may be reporting its own die and an external diode, which differ by tens of degrees on a healthy
board. Pair them and the engine reports disagreement between readings that were never supposed to
agree — a false finding on every working machine. **If a rule can generate the pairs, it does not
know the pairs.**

**Two more `consistency:` keys say a value is impossible without comparing it to a threshold.**
`grid: 0.01` declares the steps the quantity can take — a tick, a lot, a dial position — and a
reading between them is reported `impossible_value`, which no `warning:` or `critical:` can express
because the bad value is neither high nor low. `ordered_below: cap` declares that this reading must
not exceed another: a floor under a ceiling, a start before an end. Both readings may be plausible
alone and impossible together, and single-value plausibility cannot see that by construction.
`ordered_below:` takes a bare property name on the same entity, or the same
`{via: <relation>, property: <name>, aggregate: <fn>}` form the other cross-entity references take.

Both are declared as facts, so neither needs a `role:` beside it — like `agrees_with:`, they make
CONSISTENCY reachable on their own. A grid of zero or an empty `ordered_below:` declares nothing and
is reported as an unreachable pair rather than treated as a rule.

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

**Separately, the deficit is judged as a PROPORTION of the input, and that decides what you should
feed it.** What is compared is the shortfall against the inflow, not against an absolute quantity —
so one real loss is a large fraction of a single interval's flow and a vanishing fraction of a
lifetime total. If what you hold is a counter that only ever climbs, difference it and balance the
per-interval rate. A lifetime counter balanced against another lifetime counter gets quieter every
day the system runs, and nothing in the result says so.

**Telling a broken sensor from a real fault is a separate question, and this format answers it
without a range.** A reading that never moves is a dead probe rather than a very steady system, and
saying so is opt-in: declare `expect_variation: true` on the indicator and STABILITY in its
`axioms:`. Anything the checker could not evaluate — no value, too few samples, no threshold
configured — is reported in the envelope's `not_checked` leg rather than passing silently, which is
the distinction a range would otherwise have to carry.

**It answers *has this ever moved*, not *has it stopped moving*, and on a wide window those are far
apart.** The check reads the observations inside the indicator's `window:`, so a series that varied
and then went flat still contains variation and the axiom stays quiet — until every varying sample
has aged out of it. A probe that died twenty minutes into an hour-long window is not reported for
forty more.

**The window is the lever, and there is a floor under it.** Narrow it and a freeze is found sooner;
narrow it too far and fewer samples fall inside than the check needs, and it declines
`insufficient_samples` instead of answering. Pick the span from how quickly a dead probe has to be
noticed, then check the collection cadence still fills it — the two numbers are a pair, and a window
chosen without the cadence beside it lands on one side or the other.

**STABILITY's oscillation arm is period-2 by construction, and the slower kind is a second, declared
question.** The shipped detector asks whether each value is close to the one two back and far from
the one before — A-B-A-B. A quantity hunting on a four-, six- or eight-sample period scores exactly
zero there and reads as maximally stable, which is a detector correctly answering the question it
was built to answer. Declare `stability: {detect_slow_oscillation: true}` to ask the other one. It
counts zero-crossings about the mean inside the window and reports the period it measured — *cycling
on a period of about nine samples* is a sentence you can check against your own graph, which a
dominant bin in a periodogram is not.

**Declared rather than inferred, for the same reason `expect_variation` is.** A day/night thermal
swing, a duty-cycled compressor and a batch process are all correctly periodic, and a checker that
turned this on by itself would report the normal operation of every one of them. Two optional keys
tune it: `min_amplitude` (default `0.05`, relative to the largest absolute value in the window, so
one declaration works for a temperature in Kelvin and a ratio in zero-to-one) and `min_crossings`
(default `4`). Below six samples the arm returns without reporting, because the period-2 arm above
has already declined on a starved input and two records for one evaluation would break the
denominator the envelope rests on.

**A STATE indicator declares its vocabulary, and one half of it is checked.**
`type: STATE` reads a categorical value rather than a number, and takes two lists:

```yaml
- name: phase
  type: STATE
  axioms: [STABILITY]
  normal: [Running]
  bad: [Failed, Unknown]
```

A current value in `bad:` is a finding -- `declared_bad_state`, at HIGH. **A value in
neither list is not.** That asymmetry is deliberate and the shipped models are the argument
for it: the vocabulary above leaves `Pending` and `Succeeded` in neither list, and both are
ordinary. A rule firing on *not in `normal:`* would report every state a model did not
happen to enumerate, which is noise on the majority to catch a case nobody has met.

**So `normal:` decides nothing, and is reported rather than checked.** It appears in
`model_describe` under `states`, and in the finding's evidence beside the state that fired,
where it says what the model considered healthy. It is documentation the engine carries
rather than a rule the engine applies -- and it is worth declaring for exactly that reason,
because the next person to read your model learns the intended vocabulary from it.

## Relationship indicators, and how a CONNECTIVITY check is declared

Everything above measures a quantity. **CONNECTIVITY measures a shape**, and it is declared
differently: `type: RELATIONSHIP`, no thresholds, and a small vocabulary of its own. This
section exists because the axiom table below has listed CONNECTIVITY since the first version
of this document while the format for declaring one appeared only in `water_tank.yaml` --
so the only way to write one was to find the example and copy it, which is how a model
shipped with a cardinality floor and no ceiling.

```yaml
- name: feeds_a_tank
  type: RELATIONSHIP
  axioms: [CONNECTIVITY]
  target_type: Tank          # the entity type at the far end
  relation_type: feeds       # the edge type, from `relationship_types:`
  min_cardinality: 1         # fewer than this is a finding
  max_cardinality: 2         # more than this is a finding
  violation_severity: HIGH   # see below: this reaches ONE of three findings
```

**`target_type` and `relation_type` are both required, and they are different questions.**
`relation_type` names the edge; `target_type` names what must be at the other end of it. An
edge of the right type pointing at an entity of the wrong type does not count toward
cardinality, and neither does an edge pointing at an id nothing declared -- **crediting a
dangling reference toward a floor is how a phantom topology passes.** Omit `relation_type`
and the indicator's own `name` is used, which is convenient and worth declaring anyway: the
name is documentation and the edge type is a fact about the graph.

**Declaring neither cardinality is legal and checks nothing.** The invariant is whatever you
declare; an indicator with a `relation_type` and no bounds records that a relationship exists
in the model, and evaluates to nothing.

**Three findings come out of this one indicator, and `violation_severity` reaches one.**

| finding | when | severity |
|---|---|---|
| `missing_relationship` | resolved edges are below `min_cardinality` | the declared `violation_severity` |
| `excess_relationships` | resolved edges are above `max_cardinality` | `MEDIUM` |
| `dangling_relationship` | an edge points at an id no entity claims | `MEDIUM` |

The two fixed at `MEDIUM` are a deliberate distinction rather than an oversight: a missing
edge is a fault in the system, and an excess or dangling one is a complaint about the model.
**Stated here because a declaration that appears to set a severity, and sets it for one of
three findings, is otherwise something you discover from a report you did not expect.**

**`required_property` gates the check on the population, not on the entity.** Give it a
property name, and the cardinality check runs only if **some** entity of this indicator's own
type carries that property. If none does, the check declines `missing_property` and says so,
rather than reporting every entity as missing a relationship.

The reason is worth the sentence, because it is the difference between a real finding and a
denominator that lies. A model naming a property nothing carries has either a typo or a
population that has not been observed yet, and neither is a cardinality violation. Asked of
one entity the two cases are identical; asked of the population they separate -- **a name the
model supplies resolves on somebody, and a typo resolves nowhere.** Presence of the key is
what counts, not its value: an entity carrying an empty one still carries it.

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

**A declared number is the FIRST value that counts as a breach, on every axiom that takes one.** A
reading AT the number fires; it is not the last value still acceptable. `critical: 40` says *40 is
already critical*, and a datasheet phrased as *shall not exceed 40* is transcribed as `critical: 41`
— the limit and the firing point are not the same number, and this is the one place that says so.

This was worth stating because the engine did not always agree with itself. RESPONSIVENESS read the
same two field names BOUNDEDNESS reads and fired only past them, so one axiom answered *600 is
already critical* and the other *600 is still fine*, from the same key on the same kind of number.
An author transcribing a published limit had no way to tell which rule applied, and the guess that
went wrong produced either a finding against a conforming subject or a breach nobody reported. The
comparators agree now, in the inclusive direction: it is the one four of the six already used, and
it makes a finding appear at the bound rather than disappear there.

### A bound that is not the same for every instance

All four keys take `{from_property: <name>}` instead of a number, and the bound is then read off
each entity at check time. A margin requirement, a contracted ceiling and a regulatory floor are
timestamped numbers owned by another system and different per instance; written as literals they
say every entity of this type shares one line, which is false of most books, and the only way to
express the truth was one entity type per instance.

```yaml
- name: margin_balance
  axioms: [BOUNDEDNESS]
  lower_critical: {from_property: margin_requirement}
```

`margin_requirement` may itself be declared as an indicator with `axioms: []` — recorded, carried
in history, never judged. RESPONSIVENESS takes the same form on its two keys, and HOMEOSTASIS on
its `setpoint:` and `tolerance:`.

**A bound that was declared and has not arrived is not the same as no bound.** The first is a check
you asked for that could not run, and it declines `no_threshold` naming the property it wanted; the
second is a check nobody asked for. The same decline covers a value that is not a finite number,
which matters most for `NaN`: every comparison against a `NaN` floor is false, so accepting one
would pass the entire book in silence.

For a bound a caller sets rather than a model declares, `session.set_declared_thresholds(entity_id,
indicator, lower_critical=...)` sets one entity's band, reaching indicators whose model declares a
literal or nothing at all. Passing `None` removes it. An instance bound takes precedence over a
`from_property` on the same key, and `model_describe` reports `instance_thresholds` — how many
entities are judged against bounds that are not in the model, and by which mechanism — beside
`unread_declared_thresholds`, which names bounds no check will consult.

This is a different capability from `set_threshold_override`, which retunes an axiom's calibration
parameter and does not touch a declared bound.

### Saying a forecast is expected

`forecast: {expected: true}` on an indicator says an outside forecaster is supposed to supply one.
It is what makes a MISSING forecast reportable: *371 forecasts received* is not a measurement until
something says out of how many, and counting what arrived and calling that the denominator is the
shape the envelope exists to refuse. A model that declares nothing gets a question rather than a
zero — `expected: 0` beside `received: 12` would read as twelve unexpected forecasts, when the truth
is that nobody has said which pairs should carry one.

```yaml
- name: margin_balance
  axioms: [BOUNDEDNESS]
  forecast:
    expected: true
    models: [garch_v3, lstm_v1]   # optional ALLOW-LIST; an id outside it declines model_unknown
    expected_from: [garch_v3]     # optional OBLIGATION list; who owes one for every subject
    max_age: 15m                  # optional; older than this declines stale_forecast
```

Both optional keys follow the same rule as every other line in this document: there is no check
until somebody declares the number. Without `models:` no id is unknown, because refusing every id
the engine has not seen would refuse the first forecast any producer ever sends. Without `max_age:`
nothing is stale, because how old is too old is a minute for a quote and a day for a balance.

This block is distinct from `dynamics:`, which says how the engine's own projector should model the
series. That one is a method; this one is an expectation of somebody else.

### Judging the forecaster itself

A forecaster is an ordinary entity, and monitoring one needs no ninth axiom. A model that is
miscalibrated, a model that skips subjects and a model that delivers late are the same three shapes
BOUNDEDNESS, CONSERVATION and RESPONSIVENESS already judge. What was missing was never an axiom; it
was a way to get the numbers onto an entity.

`feed_model_figures(session, "<your type>")` does that, and **the type name is yours**. The engine
package does not contain one — a type name compiled into a domain-free core would be a domain word
in the single place this project refuses to put one — so the caller passes it and the model below
declares it. Rename `ForecastModel` to anything and nothing in the engine notices.

Six properties are produced, and an indicator declared on a property the ledger cannot yet support
declines rather than reading a default. A `coverage_90` of 0.0 for a model that has never been
scored would look like catastrophic miscalibration, so absent stays absent.

| property | what it is |
|---|---|
| `forecasts_issued` | how many records this model has filed |
| `forecasts_expected` | how many `forecast: {expected_from: [...]}` names this model for. ABSENT when nothing does — being in `models:` is permission to send one, not a debt, and deriving the figure from the allow-list charged every permitted producer with the whole book |
| `graded_n` | how many have matured and been scored — the denominator for the two below |
| `coverage_90` | the share of matured intervals that contained the outcome |
| `pinball_loss` | the quantile loss over the same records |
| `forecast_age_s` | how long since this model last filed anything |

```yaml
ForecastModel:
  # A model that skips subjects. `loss_margin: 0` because a forecast that was
  # expected and never sent is the finding, not a rounding error.
  - name: forecasts_expected
    type: NUMERIC
    axioms: [CONSERVATION]
    window: 24h
    flow: in
    conservation:
      input_property: forecasts_expected
      output_properties: [forecasts_issued]
      loss_margin: 0
  - name: forecasts_issued
    type: NUMERIC
    axioms: []
    flow: out

  # A DECLARED setpoint, and the rare case where the number is not a choice: a
  # q05-q95 interval covers 90% by the definition of those quantiles, so 0.90
  # is what the model claimed about itself when it chose to emit them.
  - name: coverage_90
    type: NUMERIC
    axioms: [HOMEOSTASIS]
    window: 7d
    homeostasis: {setpoint: 0.90, tolerance: 0.05}

  # A LEARNED baseline, and the ordinary case. Nobody publishes an acceptable
  # pinball loss — it has no units a contract could name — so a declared bound
  # here would be a number the model chose for itself.
  - name: pinball_loss
    type: NUMERIC
    axioms: [HOMEOSTASIS]
    window: 7d

  - name: graded_n
    type: NUMERIC
    axioms: [MONOTONICITY]
    window: 7d
    monotonicity: {expected_direction: increasing, allow_reset: true}

  # A model that delivers late. `role:` is what makes this evaluate.
  - name: forecast_age_s
    type: NUMERIC
    role: latency
    axioms: [RESPONSIVENESS]
    warning: 900
    critical: 1800
    window: 6h
```

The figures go onto the entity **and** into the observation history, because the axioms do not all
read the same surface: BOUNDEDNESS and RESPONSIVENESS judge the current value, and CONSERVATION
reads the series. An entity carrying the properties alone declines `insufficient_samples` and
reports no imbalance at all, which is the silent outcome this pairing exists to close.

`examples/margin_book.yaml` is this block in a whole model, with the accounts it forecasts.


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

## Forecasting an indicator: `dynamics`, `horizon`, `lookback`

The eight axioms judge what has been observed. `project` answers the neighbouring question — what
the series is about to do — and it is declared on the indicator, in three keys that no axiom reads:

```yaml
- name: level_pct
  type: NUMERIC
  axioms: [BOUNDEDNESS]
  window: 6h
  critical: 95
  dynamics: {model: local_level, q: 0.001, r: 0.09, report_above: 0.2}
  horizon: 1h
  lookback: 24h
```

`dynamics:` names the model and carries that model's own parameters. `horizon:` is how far ahead to
forecast, and `lookback:` how much history to fit on; omit either and the caller's horizon and this
indicator's `window:` are used.

**Two models ship.** `local_level` is a random walk seen through measurement noise — the least a
forecast can assume and still be one. `q` is the variance the level gains per SECOND and `r` is the
variance of a single reading; declare both from a datasheet, or omit both and they are estimated
from the series, in which case the forecast says so by carrying `source: estimated_parameters`
rather than `declared_model`. `trend` fits a straight line and extrapolates it. It is available by
name and is deliberately not the default: extrapolating a fitted line states a direction for a
series that may have none.

**A forecast that does not fit is refused, not delivered.** The filter tests its own innovations
against what the declared model predicts, and parameters that do not describe the series are
declined with the measured value attached. A series with no wander at all cannot separate `q` from
`r` and is declined too. Nothing substitutes a plausible parameter and reports the result anyway.

### `report_above` — the floor rule, applied to a probability

**A reporting probability is a specification, not a guess.** This is the same rule as *a floor is a
specification*, one level out, and it is the one thing about `project` most likely to surprise.

The engine can compute that a series has a 31% chance of crossing `critical:` within the horizon.
It cannot know whether 31% is worth acting on — that depends on what the breach costs and what a
false alarm costs, and both are facts about the engagement rather than about the arithmetic. So
**without `report_above:` there is no finding.** The probability is still computed, still attached
to the decline that says why no verdict was reached, and still filed for grading; what does not
happen is the engine picking a number and calling the result a judgement.

Declare `report_above: 0.2` and a projected breach at or above 0.2 becomes a finding. Declare
nothing and you get the measurement plus a question asking you for the line.

## The structural constraint: stay first-order

A domain model may not contain:

1. **Cycles in derived properties.** If A is computed from B and B from A, there is no evaluation
   order and no fixed point to check.
2. **Condition trees deeper than three levels.** Beyond that, a human can no longer say what the
   rule means, and neither can a reviewer.
3. **Nested references** of the form `derived.derived.X` — references resolve one level, flat.

And, more generally: no constraints *about* the constraints.

**The rule is that checking stays polynomial**, and *first-order* is the shorthand for it. A model
expressive enough to encode problems you cannot check in reasonable time fails in the worst
available way: not an error message, but a checker that quietly becomes too slow on the one domain
that grew. The restriction buys a guarantee — **evaluation cost stays predictable as the graph
grows** — which is what lets a domain expert add indicators without consulting anyone about
performance.

**So a derivation rule MAY quantify a join variable**, which the shorthand appears to forbid. In
`body: [holds(A, B), clears_at(B, C)]` the variable `B` is existential: it says *there is some B*.
That is allowed because the two bounds on a rule — at most three body atoms, and the head predicate
absent from its own body — make evaluation a nested-loop join over a non-recursive conjunctive
query, which is polynomial. What stays forbidden is what leaves polynomial time: recursion, an
unbounded body, and a constraint whose subject is another constraint.

**Polynomial is not the same as affordable**, and the engine says so rather than implying otherwise.
Three body atoms sharing no variables is the full cross product, cubic in the facts; the engine
stops such a rule at a binding budget and declines `binding_budget_exhausted` naming it, because a
rule nobody can afford to evaluate should be reported rather than attempted.

The constraint should be enforced at load time, not by convention. A model that violates it should
be rejected outright, with an override for people who know why they want one.

## Deriving facts: `rules` and `closure`

A rule composes declared edges into a new one:

```yaml
relationship_types: [holds, clears_at, exposed_to]
closure: [holds, clears_at]
rules:
  - name: exposure
    head: exposed_to(A, C)
    body: [holds(A, B), clears_at(B, C)]
```

Variables are names; atoms are binary, because the graph's edges are. `entail` evaluates every rule
once and reports what it derived, what it refused, and why. **Every derived edge carries the rule
and the facts that produced it**, so a finding resting on one can be traced back to the
declarations it came from rather than appearing as an edge with no author.

Deriving is not adopting. Nothing enters the graph until a caller asks, at which point each derived
edge is written with `source: inferred` and its proof, and later checks can read it — a CONNECTIVITY
indicator can count an `exposed_to` that nobody fed in.

### `closure:` — where absence becomes evidence

A graph holds the edges someone fed it. A rule that finds no binding may be false, or may be a rule
nobody supplied the facts for, and **those are different answers**. Naming a predicate in `closure:`
is the author stating that the feed for it is complete. For everything else, an entity that could
have bound the rule's first atom and has no fact under that predicate produces
`open_world_undecidable` — unknown, not false.

This is the same discipline as every other refusal in this engine: the alternative is concluding
from silence, and silence is what the `not_checked` leg exists to stop being mistaken for an answer.

## Indicators the engine COMPUTES: `derived`

An indicator does not have to be fed. It can be an expression over other
properties of the same entity:

```yaml
- name: drop_c
  derived: "inlet_c - outlet_c"
  align_tolerance: 2s
  axioms: [HOMEOSTASIS]
  window: 1h
  homeostasis: {setpoint: 0, tolerance: 0.5}
```

**This is why there is no ninth axiom.** A relation that should hold — a parity
residual, an arbitrage-free condition, a spread, a conservation gap — is a
derived value plus an axiom that already exists. Declare the difference, give it
HOMEOSTASIS with a setpoint, and departures are reported without the engine
learning what any of those words mean. The axioms judge the result and none of
them knows it was computed.

**Expressions are arithmetic over property names**, parsed and never evaluated
as code: `+ - * / // % **`, parentheses, and `abs`, `min`, `max`, `sqrt`, `log`.
Anything else — an attribute, a subscript, a comparison, a call to something
not on that list — is refused by shape rather than by a list of forbidden names.

**References resolve one level, flat.** An operand that is itself derived is
refused at load and reported in `unreachable_declarations`, because a chain has
an evaluation order nobody declared and a cycle has none at all. Write the
expression out over base properties.

### `align_tolerance` — the two failures are different

The CURRENT value is missing when an operand is, and `check` names the operand:
the axiom declines on the derived property, which nobody feeds, so being told
only that `drop_c` is missing sends you looking for a feed that was never
supposed to exist.

The SERIES is missing for a different reason. Two feeds are not sampled on the
same tick, so building a derived series means deciding which readings count as
one moment. `align_tolerance` is that decision. Declare it too tightly and the
operands are all present while the joined series is empty; the decline says how
many points each operand had and how many survived, which is the only way to
tell that apart from a feed that stopped.

## Reaching across an edge: `via`

A balance whose two halves live on different entities, and a reading that must
agree with the same reading taken somewhere else, are both declared by naming
the edge to follow:

```yaml
# on the Source
- name: sent
  axioms: [CONSERVATION]
  conservation:
    input_property: sent
    output_properties: [{via: feeds, property: arrived}]   # summed over all targets
    loss_margin: 0.02        # a relative allowance
    loss_absolute: 5         # or a fixed one; the larger allowance wins

# on the Point
- name: reading
  axioms: [CONSISTENCY]
  consistency:
    agrees_with: [{via: measured_by, property: reading, aggregate: median}]
    tolerance: 0.001
```

A bare property name is the existing form and still means a property of the
entity being checked. A mapping crosses **one** edge — references resolve one
level here for the same reason they do in `derived:`.

**Only CONSISTENCY needs `aggregate:`, and the asymmetry is real.** A balance
SUMS its output side by definition: three outfeeds carry three parts of one
flow. An agreement COMPARES, and three readings are three candidate answers —
so with more than one peer the engine asks which you meant rather than picking,
because the choice changes the verdict. Against the smallest of two readings a
point can agree while against the middle one it does not, on identical data.

**An absent peer is never a zero.** An edge that reaches nobody, and targets
that carry no such property, each decline — `precondition_unmet` and
`missing_property`. Resolving either to an empty sum turns an unfinished model
into a 100% deficit reported as a fault in the system, which sends somebody
looking for a leak that is a missing relationship.

## Dynamics on an edge: `transition`

An edge already says how FAST a change crosses it and how LIKELY a fault is to
follow it. Neither says how MUCH. A `transition:` block on a relationship rule
says which property drives which, and by what gain:

```yaml
relationship_rules:
  - type: feeds
    source_type: Pump
    target_type: Tank
    temporal:                    # the TIME COURSE -- optional, and separate
      propagation_delay_s: 120
      time_constant_s: 600
      response_model: exponential
    transition:                  # the MAGNITUDE
      from: speed_rpm            # a property of the source type
      to: level_pct              # a property of the target type
      gain: 0.003                # units of `to` per unit of `from`, at steady state
      source: datasheet          # datasheet | contract | measured | estimated
      # gain_sigma: 0.0003       # the DECLARED spread on that gain, same units
      # offset: 0.0
```

With this declared, `traverse` in a value mode reports what the downstream
value BECOMES rather than only who is reachable, and `rollout` steps that
forward under actions.

**A key this engine does not read is reported, not ignored.** Every key inside
`temporal:`, `transition:` and `planning:` is compared against the set the
loader actually reads, and anything else comes back under
`model_describe`'s `unread_fields` with a did-you-mean where there is a near
match. This matters more here than elsewhere because the failures are silent in
both directions: a mistyped `propagation_delay_s` leaves the edge on the
engine's default dead time, and a mistyped `gain_sigma` leaves the coupling
with no spread at all -- which stops `clearance_probability` being a
probability and stops a rollout filing anything it can later be graded on.
The same applies to an `action_templates:` entry this engine accepted, where a
mistyped `settle_s` otherwise leaves the actuator reading as instantaneous and
suppresses the `settle_exceeds_step` decline that exists to say so. A template
missing `applies_to` or `parameters_schema` is refused whole instead, and is
not picked over key by key.

`dynamics:` is deliberately exempt: the keys inside it belong to the model an
author named, not to this engine.

**`offset:` is a constant term on the coupling, and it is charged once.** The
contribution is `(gain x change + offset) x response fraction`, so the offset
crosses the same declared dead time the gain does -- a constant that walks
straight through a delay makes the delay meaningless. It belongs to the
COUPLING and not to each movement of its source: when a rollout moves one
property twice, which is what a staged ramp or a `candidates:` sweep deeper
than one step looks like, the two movements develop on their own clocks and
superpose, and the offset develops from the first of them. So the settled
value is `gain x total change + offset` once, however many adjustments it took
to arrive.

**`gain_sigma:` is how sure you are of the gain, and it is optional.** A
datasheet that reads *0.003 per rpm, plus or minus 10 %* has told you one;
most couplings are declared without it and behave exactly as before. Declare
it and every value the coupling drives carries a standard deviation and a
95 % interval beside it, `clearance_probability` becomes an actual
probability rather than a 0 or a 1, and a rollout's projections become
FALSIFIABLE -- the declared band is the window inside which a later reading
counts as having confirmed them, so the engine can be scored on its own
forecasts.

Nothing infers it. A spread is not read off a correlation, and it is not
`confidence:` under another name: that field weights whether the coupling
exists at all, on a unitless 0-1 scale, and turning it into a variance would
be the engine inventing a number nobody declared as one. A gain with no
declared spread reports NO interval, rather than an interval of zero width --
a value nobody measured the spread of and a value known to be exact are
different claims, and the second is much the stronger.

**`gain_sigma: estimate` asks for one instead of stating it.** It says a
spread exists and that you have not measured it, which is a third thing again
from declaring a number and from declaring nothing at all. `model_describe`
then reports a fitted spread under `proposed_transitions.fitted[*].gain_sigma`
-- the standard error of the fitted gain, which is how well your readings pin
the slope down. It is a PROPOSAL: the transition carries no interval until you
write a number into the file yourself, exactly as `gain: estimate` projects
nothing until its magnitude is adopted. The engine does not edit your model.

**A declared coupling is told how its own projections turned out.** Once
rollouts have filed predictions and `check` has graded them,
`model_describe`'s `transitions.declared[*].projections` carries `graded`,
`confirmed`, `falsified` and `confirm_rate` for that coupling, with the
denominator beside the rate because a rate over five readings is not the
statement a rate over five hundred is. Below half confirmed it adds a
`remedy` naming what to consider -- the gain may be wrong, the declared spread
may be too narrow, or the coupling may not hold in the regime the readings
came from. Nothing is changed for you.

**All four of `from`, `to`, `gain` and `source` are required, and a block
missing any of them is refused rather than completed.** This is the same rule
`consistency:` follows for its tolerance and `homeostasis:` for its setpoint,
and it matters more here: a gain nobody declared is a number a reader would
act on, invented by the engine. A refused block is reported by name — in
`model_describe` under `transitions.refused_blocks`, before anything is run,
and again as a `missing_declaration` decline if a traversal needed it.

**`source:` is the provenance of the NUMBER and is not optional.** A gain off a
datasheet and a gain somebody fitted are different claims, and a reader
deciding whether to act on a projection is entitled to know which they have.

**An edge without a `transition:` projects nothing across itself, and says
so.** The decline is `missing_dynamics`, with the question *how fast does a
change propagate through this edge* — which is the model edit that would
answer it. Nothing is inferred from a property's name, its units, or a
correlation between two series; that inference is the class this format
removed from `role:`, from flow direction and from `agrees_with:`.

**`gain: estimate` declares the coupling and withholds the number.** The
engine then fits it from observations and reports it under
`model_describe.proposed_transitions` with its sample count and a confidence
interval — as a PROPOSAL. A transition carrying it projects nothing and
declines `gain_not_adopted` until a number is written into the model. This is
the only way a learned gain comes to exist: the engine never searches for
which properties are coupled, because that search finds a gain between a
pump's lifetime run-hours counter and a tank's level, since over any window
where the pump ran, both rise.

**Where a gain IS declared and the data contradict it, that is a finding and
never an edit.** The disagreement is reported with both numbers and the
interval; the declaration is not changed. A declaration is the author's claim
about the system, and a tool that rewrote its own input would leave nobody
able to say what the model asserts.

**Several transitions may ride on one rule**, as a list, when one relationship
drives more than one property. Contributions from concurrent edges to the same
property ADD, and `linear_superposition` is stamped on any result that relied
on it.

## Acting on the model: `action_templates`

A rollout needs to know where and when a change enters. An action template
declares which entity property a parameter writes:

```yaml
action_templates:
  - name: throttle_pump
    applies_to: Pump
    parameters_schema:
      speed_rpm:
        type: number
        entity_property: speed_rpm   # the property this parameter writes
    effect: set                      # set | add | scale
    settle_s: 60                     # 0 is a step
    source: runbook
```

**The effect model only.** Whether an action may run, who approves it and how
it is dispatched are not part of this format and not part of the engine. A
rollout carrying actions reports `tier: 3` — the same classification a
hypothetical traversal carrying overrides already reports — and then reports
what would happen. It never acts.

**`effect:` is declared because the same number means three different things.**
`set` moves the property to the value, `add` moves it by the value, `scale`
multiplies it. Nothing about the number says which, so the model does.

**Two actions on one property at one instant compose by their effect, not by
addition.** Only `add` is additive: two of them sum, as they always have.
Two `scale` factors multiply, which needs no ordering because multiplication
is commutative. Two DIFFERENT `set` values have no answer -- `at_s` is the
only ordering this engine has and they share it -- so the pair is refused as
`contradictory_actions`, naming both values, and the property is left where it
was. The same setting twice is redundant rather than contradictory and is
applied once. Two effects of DIFFERENT kinds at one instant are refused for
the same reason: `add 100` and `scale 2` give 2100 or 2200 depending on which
is read first, and that ordering does not exist. Schedule them at different
times and they become a sequence instead, where the later one supersedes the
earlier and both develop on their own clocks.

## Choosing between actions: `planning`

`rollout` answers *what happens if I do this*. Ranking candidates needs an
objective, and which objective is a domain question:

```yaml
planning:
  objective: expected_findings      # or clearance_probability
  min_severity: high                # required by clearance_probability
  max_rollouts: 200
  max_depth: 1

action_templates:
  - name: throttle_pump
    applies_to: Pump
    parameters_schema:
      speed_rpm:
        entity_property: speed_rpm
        candidates: [1000, 2000, 3000]   # what a planner may try
```

**Without `planning.objective` every candidate is still evaluated and none is
ranked.** The rollouts run, each candidate reports what it does, and the
judgement that is not the engine's to make is not made — the same refusal
`project` makes when it has computed a breach probability and no
`report_above:` says what counts.

**`candidates:` is a declaration, not a range to sweep.** A template says which
property a parameter writes; it does not say which values are worth trying,
and searching a numeric range the author never wrote would be the engine
choosing the operating envelope. A template with no `candidates:` is reported
and not searched, and a caller may pass candidate actions to `plan` instead.

**Doing nothing is always a candidate, and ties break toward fewer actions.** A
planner that cannot return *leave it alone* will always recommend acting; and
where acting buys nothing the model can measure, recommending it is worse than
recommending none, because a person has to carry it out.

**The cost of a finding is derived from `Severity.priority_score`, not declared
again.** A second severity table is how two parts of one engine come to
disagree about which finding is worse.

## When the world is open: `calendar`

Every window in this format is a span of time, and by default that is wall-clock
time. For a domain that is not always running, it should not be:

```yaml
calendar:
  sessions:
    - days: [Mon, Tue, Wed, Thu, Fri]
      open: "09:30"
      close: "16:00"
      tz: America/New_York
  holidays: [2026-11-26, 2026-12-25]
```

Declare this and a `window: 1h` means an hour of OPEN time. On the first morning
of a week it reaches back into the previous session, not into the closed days.

**Why it matters more than it sounds.** On the first morning, a wall-clock hour
spans everything that was shut. A series sampled once a minute during the
session then looks like a series sampled once every three days:
`floor_unreachable_at_this_rate` fires on data that is arriving perfectly well,
a freeze check calls a closed shop frozen, and every one of those findings is
about a span in which nothing could have been observed.

**Declaring nothing is not declaring closed.** A domain with no `calendar:` is
always open and behaves exactly as it did before this key existed, which is the
right default for anything that runs around the clock.

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
