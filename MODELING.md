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
rather than `declared_model`. `trend` fits a straight line and carries its SLOPE AS PROCESS NOISE.
It is available by name and is deliberately not the default: extrapolating a fitted line states a
direction for a series that may have none.

**`trend` widens; it does not point.** An earlier draft of this paragraph described the model as
extrapolating its fitted line, which is what the name suggests and not what the model does. The fitted line supplies the level
AT THE LAST SAMPLE, and the slope becomes the variance the level gains per second — so the median of
a `trend` forecast is FLAT across every horizon, and a steeper fitted slope makes the band wider
rather than the forecast higher. That is the demotion in the paragraph above, carried through to the
arithmetic: a series that has been climbing is reported as more uncertain, not as certain to keep
climbing. An author who wants a declared direction declares a coupling with a `gain:`, which is a
statement about cause that somebody signed for, rather than asking a curve fit to supply one.

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

**A time course this engine supplied says so.** `temporal:` is optional, and
where it is absent -- or present and short of a key -- the edge keeps this
engine's own 60 s dead time and 60 s time constant. That default is not small:
on the shipped `pump_tank_dynamics` model, dropping `time_constant_s` alone
moves the first reported level from 61.01 to 69.99 and reports a tank as
settled that is halfway there, because 60 s stands in for a declared 600 s.

So an edge that carries a `transition:` and does not carry the pair reports it
twice. A `missing_declaration` question names the key that is absent and the
number this engine used in its place, and any envelope whose values were
computed across that edge carries `time_course_not_declared` in its
`assumptions`. -- the question is raised by `gaps` and by every verb
that actually CROSSED the edge: `rollout`, `plan` and `traverse`. Until then
only `gaps` raised it, so the bare fact reached the verb that used the number
and the key and the value reached only a verb that computed nothing. The values are unchanged -- this is a reporting rule, not a
refusal, and it is the one stamp in that list naming something a reader can
remove by editing the file rather than an assumption about the model itself.

`response_model` is deliberately not in that pair. A response SHAPE beside a
declared time constant is a materially weaker assumption than the time constant
is, and `exponential` is the documented first-order form.

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

**A source that returns to where it started has still made a change**, and the
formula says so literally: its target settles at `baseline + offset` rather
than at `baseline`. Measured with `offset: 7.0` and `gain: 0.02`, a pump taken
1000 -> 1500 -> 1000 leaves its tank at 57.0 while a pump nobody touched
leaves it at 50.0. The offset belongs to the COUPLING having fired, not to
the net displacement, so it is charged once the coupling has run and is not
refunded when the source comes back. Declare the constant term only where it
describes something that persists once the source has moved at all.

**`gain_sigma:` is how sure you are of the gain, and it is optional.** A
datasheet that reads *0.003 per rpm, plus or minus 10 %* has told you one;
most couplings are declared without it and behave exactly as before. Declare
it and every value the coupling drives carries a standard deviation and a
95 % interval beside it, `clearance_probability` becomes an actual
probability rather than a 0 or a 1, and a rollout's projections become
FALSIFIABLE -- the declared band is the window inside which a later reading
counts as having confirmed them, so the engine can be scored on its own
forecasts.

Where `gain_sigma: estimate` asks this engine to propose one, the proposal
carries `residual_autocorrelation` and
`gain_sigma_assumes_independent_residuals` beside it. The standard error
offered as a spread assumes the fit's residuals are independent, and neither
fit path gives it that -- both difference the target's readings, so the
residuals correlate at lag 1 near -0.5 either way. What decides whether that
matters is the declared `response_model`: fitted through `step`, the regressor
is differenced along with the target and the correlation cancels out of the
estimator; fitted through `exponential`, the regressor is a level and the
standard error comes out several times too wide. Measured over 200 trials at
each of two noise levels: 1.03x the true scatter on `step`, 5.17x on
`exponential`. The engine reports both facts and corrects neither number --
the error is in the conservative direction, and choosing between two
estimators on an author's behalf is the same class of decision as adopting a
fitted gain.

Nothing infers it. A spread is not read off a correlation, and it is not
`confidence:` under another name: that field weights whether the coupling
exists at all, on a unitless 0-1 scale, and turning it into a variance would
be the engine inventing a number nobody declared as one. A gain with no
declared spread reports NO interval, rather than an interval of zero width --
a value nobody measured the spread of and a value known to be exact are
different claims, and the second is much the stronger.

**One declared spread is one uncertainty, however many ways it reaches a value.** The rule is worth
stating because both halves of it are load-bearing. Contributions that come from the SAME declared
number add LINEARLY and with their signs: one coupling walked at two movement instants because its
source was acted on twice, or one spread arriving at a target by two different paths through the
graph. Contributions from DIFFERENT declarations add in quadrature, which is what the
`independent_declared_spreads` stamp on the envelope has always meant. Two pumps feeding one tank
under the same rule are two couplings and two gains -- the datasheet's tolerance describes a
population, and each pump is its own draw from it -- so their spreads combine in quadrature. The
same pump throttled twice is one gain, so its contributions add. The signs matter as much as the
pooling: move a source out and back and its target ends where it started FOR ANY GAIN, so the
gain's spread cannot reach it and the reported interval is correctly nothing at all.

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

**A hit rate is reported against the rate it should be, because on its own it
rewards declaring ignorance.** `confirm_rate` asks whether a later reading
landed inside the band your `gain_sigma:` drew, so a spread ten times wider
than the truth is confirmed every time. Measured on one tank that really
scatters by 2.3 points, forecast by the same gain declared twice:

| declared spread | accepted band | `confirm_rate` | `coverage_90` | `crps_approx` |
|---|---|---|---|---|
| honest | +/- 4.5 | 0.95 | 0.95 | 0.99 |
| ten times too wide | +/- 45.0 | **1.00** | **1.00** | **3.19** |

So two things travel with the rate. `expected_confirm_rate` is the confidence
the band was drawn at -- 0.95 -- and a rate of 1.00 beside a target of 0.95 is
an overshoot rather than a perfect score. And `calibration.own_projections`
carries the PROPER scores: pinball loss, a CRPS approximation and
`coverage_90` against its own `expected_coverage_90` of 0.9. Those grow with
the width of an interval whether or not it contained the answer, which is why
the last column above ranks the two declarations the other way round. The leg
is stratified `by_coupling` and `by_horizon`, so an author asking which of
their gains carries a spread not worth trusting gets an answer per gain.

No trigger hangs off the distance. How much overshoot is too much is a domain
question, and this engine reports the evidence and the target beside it.

These figures are kept apart from the `coverage_90` that scores an outside
producer's forecasts, and deliberately: that one answers *which forecaster is
worth keeping*, and pooling the engine's own projections into it would make it
a number about nobody.

**All four of `from`, `to`, `gain` and `source` are required, and a block
missing any of them is refused rather than completed.** This is the same rule
`consistency:` follows for its tolerance and `homeostasis:` for its setpoint,
and it matters more here: a gain nobody declared is a number a reader would
act on, invented by the engine. A refused block is reported by name on three
surfaces: in `model_describe` under `transitions.refused_blocks`, before
anything is run and carrying the rule it was declared on; as a
`missing_declaration` question from `gaps`, naming the key that is absent; and
again as a `missing_declaration` decline if a traversal needed it.

An edge that declares no `transition:` at all is a different claim and gets a
different name. It has refused nothing — there is nothing to refuse — so it
raises `missing_dynamics` when a caller asks for a value across it, and no
refusal question. Saying *no transition declared* about a block sitting in the
file would send an author looking for something they had already written.

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
on it. **That includes a property an ACTION also moved**: a value is its
baseline, plus every movement of its own, plus whatever the couplings
delivered. An action does not displace a coupling into the same property and
a coupling does not overwrite an action; they superpose, which is what the one
rule means. Where the action's own effect reads the standing value -- `set`
moves the property BY `X - standing`, `scale k` by `standing x (k-1)` -- the
value it reads is the one the property has at the instant the action lands,
couplings included.

**Edges in SERIES are a different question, and the engine composes them by
multiplying their step responses.** A value two hops out is charged the first
edge's response fraction and then the second edge's, against a source that is
already lagged, so it develops as the PRODUCT `f1(t) x f2(t - d1)`. For linear
stages in series the exact answer is their convolution, and the two are not
the same curve: two equal 600 s lags with no dead time give a series response
of `1 - (1 + t/tau)exp(-t/tau)` against a product of `(1 - exp(-t/tau))^2`,
and the product is early by up to 16.2 units per 100 at `t = 960 s`. The
steady state is exact and the TRANSIENT is fast, so a breach two hops out is
predicted sooner than the declared dynamics imply.

`series_edges_compose_by_product` is stamped on any result that relied on it,
which means a chain of edges that actually shape a transient: one hop does not
carry the stamp, and neither does a chain of `step` edges, whose product IS
their convolution.

**Two exponential stages in series are composed EXACTLY**, and carry
`series_edges_composed_exactly`. The walk charges each edge's response against
a source already lagged, so the contribution it forms is `f1 * f2`; scaling
that by `H / (f1 * f2)` lands it on the convolution without the propagation
needing the un-lagged movement or the upstream gain. The correction rides the
FRACTION, so a value and its declared spread cannot come apart, and it is
applied PER CONTRIBUTION -- a target fed by a chain and by a direct edge gets
each one right, because superposition is linear.

**What has no closed form still composes by product and still says so.** A
chain containing a `linear` or `logarithmic` stage keeps
`series_edges_compose_by_product`. A third hop gets the exact two-stage
composition for its solvable head and the product beyond it: measured on three
equal 600 s lags at `t = 1800 s`, that moves the answer from 28.11 units of
error to 18.42, and it is still stamped, because closer is not exact. A
rollout crossing both kinds carries BOTH stamps.

**A `series_errors` row per step records what the approximation would have
cost** -- the `product` that was avoided, the `exact` value used, and the
signed gap, as fractions of the final impact. **The rows belong to the EXACT
branch**, which is the half of this that reads backwards at speed and did: an
outside comparison put them beside `series_edges_compose_by_product`, where
there are none. Where the product is actually used the exact value has no
closed form, so the cost is not knowable and nothing can be reported; the stamp
says an approximation happened and these rows say what one WOULD have cost
where the engine avoided it. On two equal 600 s lags the
product leads by up to 0.161 per unit at `t = 900 s`, closing to 0.012 by an
hour. An author reading a multi-hop transient learns from it how much of that
transient depends on the composition being exact.

This section used to end by saying the exact composition was not available:
the partial-fraction form for distinct time constants cancels catastrophically
as two of them approach each other, so a robust version would need a
near-equality tolerance -- a number nobody declared and therefore not this
engine's to pick. **That argument is about the formulation and not about the
convolution.** Measured at `t = 900 s` with `tau1 = 600 s`, sweeping `tau2`
down onto it, the partial fraction holds to 2e-14 at a separation of 1 s, reads
`0.625` against a true `0.442174599629` at a separation of `1e-13`, and divides
by zero at equality. The divided-difference form

    h(t) = 1 - e^{-at} (1 + a t phi(-(b-a) t)), phi(x) = (e^x - 1)/x

holds every digit across the same sweep and meets the equal-tau closed form
`1 - (1 + t/tau)exp(-t/tau)` exactly, because `expm1` is built for it and the
only branch is `x != 0`, an exact comparison rather than a tolerance. The one
bound the correction carries is a property of float64 and not of any model:
below the ULP of 1.0 the exact response has no significant digit, so the walk
keeps the product there, where both curves are zero to representable precision
anyway.

**That sign was published as a minus until 2026-09-22**, and this note stays
because a reader who implemented the printed form got a different engine. Under
the `phi` defined beside it the minus version returns `1.1116` at
`tau1 = tau2 = 600 s` and `t = 900 s`, where the response is `0.442174599629`
-- a step response above one, which no plant has and this engine has never
reported. Only the derivation was wrong: every figure in the paragraph above
was measured from the code, which is why two rounds of review read past it. The
plus form agrees with what runs across every combination of the two time
constants and the elapsed time.

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

## Asking what caused what: `edge_direction` and `causal`

`traverse` walks declared edges. `infer` asks a different question -- *how
likely is this entity faulty, given what the last check could see* -- and it
needs to know which of those edges are claims about CAUSE. An edge without
`edge_direction: causal` stays traversable and is simply not such a claim.

```yaml
domain:
  causal:
    evidence_severity: [warning, high, critical]   # optional; see below

  relationship_rules:
    - type: powers
      source_type: Supply
      target_type: Feeder
      edge_direction: causal
      causal:
        weight: 0.80        # P(this parent alone explains a faulty child)
        leak: 0.02          # P(child faulty with no parent at fault)
        # latent_confounder: shared_supply   # optional, and see below
```

`weight` and `leak` are noisy-OR parameters, so several parents compose without
anyone writing a full conditional table: two parents at 0.80 and 0.70 with a
0.02 leak give `1 - 0.20 x 0.30 x 0.98`. **A weight nobody declared stops the
answer** rather than being supplied -- `infer` declines `cpt_missing`, names the
edges, and asks for the number, because a posterior is a product of weights and
one the engine chose would make the answer partly a statement about the engine
with no way to tell which part. `examples/substation_feeder.yaml` is the worked
specimen; its header states one question answered three ways.

`latent_confounder` names an unobserved common cause on an edge. Under an
intervention it makes the query unidentifiable, and `infer` says so
(`not_identifiable`) instead of returning a number that ignores it.

**`do` is an intervention and not an observation.** The intervened node's
incoming edges are CUT before the query is answered, which is the whole reason
this is a verb rather than a filter over `traverse`. On the shipped specimen,
asking about the supply with the feeder OBSERVED faulty gives 0.679054 and with
the feeder FORCED faulty gives 0.05 -- the same node in the same state, a factor
of thirteen apart. Seeing a thing fail is evidence about what feeds it; breaking
it yourself is not.

### What counts as faulty evidence: `causal.evidence_severity`

`infer` reads the last `check()`. An entity in its `not_checked` leg is left
UNOBSERVED rather than assumed clean, and the count rides in every answer. The
other half of that rule is which findings make an entity FAULTY, and it is a
floor on severity:

```yaml
domain:
  causal:
    evidence_severity: [warning, high, critical]
```

**Undeclared, this engine counts `high` and `critical` and no others** -- so a
model whose breaches are all warnings returns every posterior sitting at its
prior, which reads like a graph that is not wired up. That default was
invisible from the answer until 0.2.6: it is now disclosed as
`evidence_severity_not_declared` on every envelope that used it, on the same
rule as every other number this engine supplies rather than reads.

A declaration this engine cannot use -- an empty list, a single value where a
list belongs, or one naming a severity that does not exist -- is treated as NO
declaration, deliberately. Partially applying a list with a typo in it would
leave an author reading a posterior computed against a floor they did not write
and cannot see.

**But trying and being refused is not the same as never trying**, and until
0.2.6 it looked the same: `[critical, hihg]` and an absent block both returned
the bare `evidence_severity_not_declared`, so an author who mistyped a severity
read *not declared*, concluded the file had not loaded, and had nothing to pull
on. A refused declaration now carries `evidence_severity_unusable` BESIDE the
first stamp -- the floor really was this engine's, so that claim stands -- and
`model_describe` names the word in `unread_fields`:

```
causal.evidence_severity   unknown_value   value: hihg   did_you_mean: high
```

A value of the wrong shape is reported there too, as `malformed_value` rather
than `unknown_value`, because a scalar `critical` names a real severity and an
empty list names none: calling either an unrecognised value would misdescribe
it, and there would be no near-miss to offer.

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

**`expected_findings` is the MEDIAN trajectory's count, and the name invites the other
reading.** It sums a cost per finding the rollout produced — `1.0 / priority_score`, so critical
costs 1 and info 1/5 — over the single trajectory the engine simulated. It is not an average over
the declared spread. That matters because a finding is a comparison against a declared line, so the
objective is a STEP FUNCTION of values the engine often knows only to within a `gain_sigma:`.
Measured on the example above, throttling a tank to settle at 84.912 against a `warning: 85` scores
14.333, and settling at 85.012 scores 16.000 — a tenth of a point moving the ranking by 12 %, while
the declared spread on that value at that step is 0.3988, four times the gap that flipped it.

So a ranked plan stamps `objective_evaluated_at_median` on the envelope, and every candidate carries
`margin_sigmas`: how close the nearest decision came, measured as the smallest distance from an
imagined value to a line it was judged against, in units of that value's own declared spread. A
candidate scoring 14.333 with `margin_sigmas: 0.027` and one scoring 16.000 are not two findings
apart; they are one coin flip apart, and the engine now says which it is. It is a MEASUREMENT and
changes no ranking — `None` when nothing declared a spread that reached the trajectory, because a
distance in units nobody declared is not a measurement. Rank on `clearance_probability` instead when
the question is *how likely is this to stay clear*: that one samples the declared spread and returns
an interval.

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

**A tie that survives both then breaks toward the wider margin.** Two
candidates can share an objective AND an action count, and before this rule the
one listed first in `candidates:` won -- so where the author wrote a setting
decided which setting was recommended. On the shipped `pump_tank_dynamics`
model two candidates tie at `expected_findings` 0.000 while settling 0.03 and
15.08 declared spreads from the line that decides whether they file a finding.
The tighter one is a coin flip; the engine had already measured both and
reported them as `margin_sigmas`.

The spread is the author's, so this decides nothing on the model's behalf:
further from a decision is the direction `clearance_probability` already
optimises, in units the model declared. **A candidate carrying no measured
headroom sorts last among its ties**, so a model with no `gain_sigma:` keeps
the order it had, and the rule is stamped `ties_break_toward_the_wider_margin`
only where a declared spread actually reached a trajectory.

**The figure it ranks on is `clearance_sigmas`, not `margin_sigmas`,** and the
difference is the whole of the rule. `margin_sigmas` is the closest a value
came to any line, as an ABSOLUTE distance; among candidates that breach it
measures wherever a discrete step happened to fall as the trajectory crossed
the line, so ranking on it moved the recommendation when the step size changed.
`clearance_sigmas` is SIGNED — positive is headroom, negative is how far the
worst excursion went past a line — so larger is safer whether or not a line was
ever crossed. Both are reported. A clear candidate shows the same number twice;
a breaching one can report a `margin_sigmas` of 0.920 and a `clearance_sigmas`
of -4.985, and only the second says which of those a reader is looking at.

**The cost of a finding is derived from `Severity.priority_score`, not declared
again.** A second severity table is how two parts of one engine come to
disagree about which finding is worse.

## The assumption stamps

Every number this engine projects rests on approximations the engine made
rather than an author declared. A stamp names one of them. It is not a warning
and not a finding: it is the engine saying which of its OWN choices the value in
front of you depends on, so that a reader who disagrees with a choice knows
which number to distrust.

They arrive in an `assumptions` list on the `simulation` and `plan`
sub-envelopes, and on each `plan` candidate where the candidates differ. An
EMPTY list means the engine made none of them, which is a different claim from
the key being absent.

| stamp | what it discloses |
|---|---|
| `first_order_response` | the coupling was developed as dead time then an exponential approach -- the ordinary shape, and still a shape this engine chose |
| `time_course_not_declared` | the time course crossed was not declared; this engine supplied a delay or a time constant, or both |
| `evidence_severity_not_declared` | `infer` read the last check against THIS engine's severity floor, because the model declared none. Declare `causal.evidence_severity:` to choose it |
| `evidence_severity_unusable` | the model DID declare `causal.evidence_severity:` and this engine could not use it, so the floor above was its own. Carried beside the stamp above, never instead of it; `model_describe` names the value that was refused |
| `steady_state_reached` | the horizon outlasted the transient, so the value reported is the settled one |
| `series_edges_composed_exactly` | two couplings in series were composed by the exact cascade response |
| `series_edges_compose_by_product` | two couplings in series were composed by multiplying response fractions, which is an approximation |
| `first_order_uncertainty` | the spread was propagated to first order; exact for a declared constant gain, approximate once two uncertain factors multiply |
| `independent_declared_spreads` | declared spreads were combined in quadrature, which is correct only if they are independent -- nothing in a model states that they are |
| `gaussian_from_mean_sigma` | a forecast arrived as a mean and a sigma and was expanded to quantiles under a normal assumption the producer did not state |
| `exogenous_inputs_held` | everything outside the traversed subgraph was held still for the whole horizon |
| `no_action_scheduled` | no action was scheduled, so what is reported is the world left alone |
| `linear_superposition` | contributions from several sources onto one target were summed; real couplings saturate and interact |
| `declared_coupling_not_probability_pruned` | a declared coupling was followed regardless of how likely it is to carry the effect |
| `seeded_from_projection` | the rollout was seeded from a projection rather than the last observed value, so the starting point is itself a model output |
| `deterministic_transitions` | the candidate was scored on one trajectory because no declared spread reached it; a `clearance_probability` under this stamp is a 0 or a 1 |
| `declared_gain_spread_sampled` | the candidate was scored over trajectories sampled from the declared gain spreads |
| `worst_step_binds_the_horizon` | a trajectory counts as breaching if it breaches at any step, so one bad minute scores as breaching |
| `movement_between_sampled_steps` | the axioms ran at the sampled steps and nowhere between them, and a property that moved more than once turned at an instant off the grid |
| `objective_evaluated_at_median` | `expected_findings` was evaluated on the median trajectory, and it is a step function -- rank on `clearance_probability` when the question is how likely the candidate is to stay clear |
| `ties_break_toward_fewer_actions` | candidates equal on the objective were ordered by acting less |
| `ties_break_toward_the_wider_margin` | candidates still equal were ordered by the wider signed headroom, and only where a declared spread reached a trajectory |

One stamp carries a value rather than standing alone:
`action_property_from_parameter_name:<property>` says that an action template
named a parameter no `entity_property:` bound, so the engine matched the
parameter name to a property of the same name.

**This list is a baseline, not a closed set on the wire.** A patch release may
add a stamp -- an engine that starts disclosing an approximation it had been
making silently is a fix, and holding it back for a major version would be the
wrong trade. So `schema/envelope.schema.json` types `assumptions` as an array
of string with no `enum`, and this table is derived from the engine's own
vocabulary rather than transcribed beside it. Read a stamp you do not
recognise as an approximation newer than your copy of this document.

## `step_s` decides what gets judged, not only what you see

A `rollout` evaluates the eight axioms at each sampled instant -- `step_s`,
`2 x step_s`, and so on to the horizon -- and **nowhere between them**. Reading
`step_s` as a rendering choice is the mistake: it is also the list of moments
at which this engine looked.

It costs nothing while a property moves once, because a first-order response
from a single movement is monotonic and its extremes are its endpoints, which
are sampled. It costs something as soon as a property moves twice, because the
trajectory can turn between two samples and a turn nobody judged is a breach
nobody found. Measured on two settings 950 s apart, with the line placed at
88.1 and the true peak 88.314 at `t = 950`:

| `step_s` | samples `t = 950` | verdict |
|---:|---|---|
| 950 | yes | breach |
| 475 | yes | breach |
| 300 | no | clean |
| 200 | no | clean |
| 100 | no | clean |

**A finer grid is not a safer one.** 100 s reports clean where 950 s reports
the breach; what decides is whether the turning instant falls on the grid, so
halving `step_s` to be careful buys nothing in particular. Where a property
moved more than once and turned off the grid, the envelope says so with
`movement_between_sampled_steps`. **Choose `step_s` so that the instants your
actions are scheduled at are sampled** -- those are the moments a declared
trajectory can turn.

The engine does not add instants of its own. Judging a moment the caller did
not ask for would put a row in `per_step` nobody requested, and picking which
moments would be the engine choosing the resolution of the answer.

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
