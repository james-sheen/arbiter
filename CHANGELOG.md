# Changelog

Notable changes to `arbiter-engine`. Versions follow [semantic versioning] with
one local wrinkle recorded under [Version numbers that do not exist](#version-numbers-that-do-not-exist).

The wire contract is versioned separately from the package: every envelope
carries `meta.schema_version`, and [COMPATIBILITY.md](COMPATIBILITY.md) states
what may change without moving it.

**Entries before 0.1.7 are RECONSTRUCTED.** This file did not exist during those
releases, which is the gap it closes. They were rebuilt from the release runbook
and the decision record, and they are deliberately thinner than the entries that
follow: where the record says only that a version shipped, that is what the entry
says. A confidently detailed history assembled after the fact would be the more
useful-looking document and the less trustworthy one.

[semantic versioning]: https://semver.org/spec/v2.0.0.html

---

## [Unreleased]

### Fixed

- **The published derivation of the exact cascade response was wrong by a
  sign.** `MODELING.md` and the `cascade_fraction` docstring both printed
  `h(t) = 1 - e^{-at}(1 - a t phi(-(b-a)t))` beside `phi(x) = (e^x - 1)/x`.
  Read with the `phi` given next to it, that returns 1.1116 where the true
  two-stage step response at `tau1 = tau2 = 600 s` and `t = 900 s` is
  0.442174599629 -- a step response above one. The engine was never wrong and
  is unchanged: it agrees with the truth to twelve digits, and every NUMBER in
  the surrounding paragraph was measured from it, which is why two rounds of
  outside review read past the formula. The third copied it verbatim into a
  comparison this project did not write, which is how it was found. The sign
  is now a plus in both copies, and a test evaluates the published text rather
  than restating it -- a guard that hard-codes the corrected expression passes
  on the broken document, because the document is not what it read.

- **The only tests that put the wire contract in front of a validator ran
  nowhere.** Ten tests gate on `jsonschema`, which no lane installed: CI
  installs the package with its `mcp` extra and pytest, and the reproduction
  this project's own documents imply installs numpy, pyyaml and pytest. Among
  the ten is the single check that `envelope.schema.json` is a well-formed
  2020-12 schema, which has no derivation-based substitute -- so whether the
  document `meta.schema_version` advertises parses as a schema at all had
  never been answered on any machine here, across three Python versions and
  every release. The argument was already in the CI file, four lines above the
  install, made about the other optional extra, and stopped one line short of
  this one. CI now installs `jsonschema`; the two guards that had a bare
  `importorskip` now say why they are gated and what covers the question
  otherwise; and a skip CEILING sits beside the collected-count floor, because
  a floor catches a suite that shrinks and nothing caught one that goes quiet.
  The ceiling reads the GRADED run rather than starting another one, so its
  verdict is about the execution the job accepted, and the reason for every skip
  now appears in that run's own output. No runtime dependency changed: the
  engine still needs numpy and pyyaml.

- **Seven closed decline vocabularies, ninety-three names, published
  nowhere.** Each sub-envelope refuses out of its own closed set --
  `simulation` 39, `shadow` 18, `projection` 9, `discovery` 8, `entailment` 7,
  `inference` 7, `forecasts` 5 -- and `COMPATIBILITY.md` grants a patch release
  permission to add a member to any of them while warning, one entry above,
  that the sets are SEPARATE and that reading a reason from one against another
  is how a closed enum stops being closed. Neither the guide nor the schema
  said what any set contained, so that warning could not be followed.
  Reported from outside in the way the stamps were: a comparison that
  reproduced every published vocabulary of this engine by exact membership --
  the fourteen decline reasons, six gap types, eight raced outcomes, twenty
  assumption stamps -- listed five closed vocabularies under a heading naming
  the engine's trust surface, and none of these seven were among them. Three
  members of `simulation` appeared in its prose instead, beside a gap type, in
  a list read against the fourteen. `BRIDGES.md` Sec. 2a now publishes all
  seven, derived from the code and pinned by a test. The schema is unchanged
  and still declares no `enum` on a sub-envelope reason, so that the permission
  stays real.

- **The scrub removed the citation and shipped the broken sentence.** Fourteen
  docstrings in six modules of the published package opened on a space and a
  parenthetical naming nothing, because a deletion took the first token and
  not the space beside it -- and nine internal coordinates shipped in forms no
  rule knew, a drain letter, three round numbers, two track coordinates and
  two programme names. The rules that exist are exact: zero `CD-N`, `S-N` or
  `DDC-N` tokens reached the tree. One module's docstring published an
  internal three-phase adoption roadmap that appears in no document here, and
  an outside reader copied *Phase-1 sampling estimator* out of it into a
  comparison as though it were API documentation. The prose is rewritten at
  source, and the build now refuses both shapes rather than substituting,
  because no public replacement is derivable from a round number.

- **The assumption stamps were a vocabulary nobody could read.** Every number
  this engine projects rests on approximations it made rather than an author
  declared, and an `assumptions` stamp names one of them -- the list this
  project offers as its trust surface. The stamps existed only as bare string
  literals at twenty sites across four modules, with no definition anywhere.
  `envelope.schema.json`, which `meta.schema_version` advertises as the wire
  contract, did not contain the word `assumptions`; the published guides
  between them named six of the twenty; and `COMPATIBILITY.md` granted a patch
  release permission to ADD a stamp, so the project published a rule for
  changing a vocabulary it had never published. Reported from outside, in the
  only way it could be: a review that reproduced this engine's fourteen decline
  reasons, six gap types and eight raced outcomes by exact membership listed
  this one at nine of twenty, under a heading saying *seen*, because nine is
  what running the shipped example shows you. The stamps now have one
  definition, every emitting site imports the name instead of repeating the
  literal, and `MODELING.md` publishes the table derived from that definition.
  No stamp changed its spelling and no envelope changed.

- **The schema named its two largest sub-envelopes and nothing they carry.**
  The previous release added `simulation` and `plan` to the schema's
  `properties`, both pointing at the one generic sub-envelope definition, which
  declares the five legs and allows anything beside them. So the trajectory,
  the tier, the candidate ranking and the assumption stamps stayed undeclared
  one level below the fix -- `simulation` carries six keys beside the legs and
  `plan` eight, where four of the other sub-envelopes carry none and
  `projection` carries one. Worse, the fix asserted otherwise: the sentence it
  added said the two were *shaped like every other sub-envelope*, and a claim
  of sameness is worse than silence because it removes the reason to look. The
  three that deviate now have their own definitions, each composing the shared
  shape and adding only its own payload, and the coverage is derived from what
  the verbs emit rather than from a list written beside them.

- **Two different things undeclared in one place were reported as one.**
  `gaps` deduplicated on `(gap_type, location)`, which assumes each type asks a
  single question at a given place. `missing_declaration` stopped being one
  claim when a refused `transition:` block started using it, and a second
  arrived with the time-course report: an edge whose delay or time constant
  this engine supplied. The question TEMPLATE was fixed for exactly this reason
  one release earlier; the key beside it kept the old assumption. Where both
  claims land on one edge, one question was reported and the other silently
  dropped -- and the survivor was the refusal, so what went missing was the
  question naming the number the engine substituted. The claim is now part of
  the key. Identical claims about one place still collapse, which is what the
  deduplication was for.

- **The verb that used an undeclared number was the one that did not name it.**
  An edge whose time course this engine supplied is reported twice: a
  `missing_declaration` question naming the absent key and the number used, and
  a `time_course_not_declared` stamp on every envelope computed across that
  edge. Only the stamp reached `rollout`, `plan` and `traverse`. The question
  was raised by `gaps` alone -- a verb that computes no values -- so a caller
  who rolled a trajectory forward, every value of which rested on a 60 s
  constant standing in for a declared 600 s, and then read the leg whose stated
  purpose is what the model never declared, was told nothing. Those three verbs
  now file the question beside the stamp, scoped to the edges their walk
  actually CROSSED: an edge nothing traversed raises nothing, and a fully
  declared model stays silent. No value and no ranking changes.

- **A plan's tie-break read a figure that cannot say which side of a line a
  value sat on.** The tie between two equally-scored candidates broke toward
  the wider `margin_sigmas`, which is the minimum ABSOLUTE distance to any
  line over the horizon. Among candidates that breach, that is not a measure
  of the breach — it is wherever a discrete step fell as the trajectory
  crossed the line. Two candidates tied at 1.667 while settling about 4 and
  about 8 points past a band edge reported 1.443 and 0.089, and at
  `step_s=450` the order reversed and the deeper breach was preferred: the
  ranking moved with the step size rather than the risk. Ties now break on
  `clearance_sigmas`, the SIGNED worst headroom in declared spreads, taken
  from the same margin `clearance_probability` centres its distribution on.
  `margin_sigmas` is unchanged and, as its own description has always said,
  changes no ranking.

- **An exact tie between two candidate plans was broken by the order they were
  written in.** The ranking sorted on the objective and then the action count;
  two candidates equal on both fell to insertion order. On the shipped
  pump-and-tank model two candidates tie at `expected_findings` 0.000 while
  settling 0.03 and 15.08 declared spreads from the line that decides whether
  they file a finding — and the engine's own sampler scores the same two
  rollouts at 0.43 and 1.00 clear. Swapping their entries in the YAML swapped
  their rank. The tie now breaks toward the wider `margin_sigmas`, stamped
  `ties_break_toward_the_wider_margin` and only when a declared spread actually
  reached a trajectory. A candidate with no measured margin sorts last among
  its ties, so a model that declares no `gain_sigma:` keeps the order it had.
  No reported number changes; this reorders exact ties only.

- **A time course nobody declared was invented in silence.** `temporal:` is
  optional, and an edge without it — or with it and short of a key — kept this
  engine's own 60 s dead time and 60 s time constant, reported by nothing.
  Measured on the shipped `pump_tank_dynamics` model, dropping
  `time_constant_s` alone moved the first reported level from 61.01 to 69.99
  and reported the tank as settled when it was halfway: 60 s standing in for a
  declared 600 s. The sibling block on the same edge has refused partial
  declarations since 0.2.3 for exactly this reason. The values are unchanged;
  what is new is that an edge carrying a `transition:` without the pair now
  raises a `missing_declaration` question naming the absent key AND the number
  used in its place, and every envelope computed across it carries
  `time_course_not_declared` in `assumptions`.

- **`margin_sigmas` and `clearance_probability` measured against one axiom
  while the plan ranked on eight.** Both read `BOUNDEDNESS` evidence by name
  and had never seen a HOMEOSTASIS band. On the shipped model, whose every
  plan finding is a HOMEOSTASIS breach, the best-tying candidate settles 0.03
  spreads from the line that decides whether it files a finding and was
  reported 45.1 spreads clear; candidates already breaching reported
  comfortable positive margins. Which lines an axiom declares is now the
  axiom's own business, and the planner asks every axiom state that judges the
  property. Reported from outside. **Measured afterwards against the pre-fix
  tree, and larger than first described: `clearance_probability` had been
  returning 1.00 for EVERY candidate, including the two that already file
  findings. It was not a wrong number but a vacuous objective, ranking
  nothing.**

- **Gain fitting was unreachable from the documented shape.** Bare
  `add_observations` spaced readings ending at `now`, read once per call, so
  two series fed one after the other shared no timestamp — 0 of 5, 0.003146 s
  apart — and the fitter, which intersects on exact timestamps, paired nothing
  at EVERY declared delay including zero. It reported `delay_off_grid`, whose
  remedy could not work because the delay was never the cause. A feeding pass
  now shares one instant, with the reuse window taken from the caller's own
  `interval_seconds`; inside `as_of` nothing changes, because that path was
  always joinable — which is why no test saw this. `delay_off_grid` now fires
  only when the series genuinely share a grid the delay misses, and
  `series_not_co_sampled` names the other case. Reported from outside.

- **A wrong argument type was filed under coverage.** Passing plain mappings
  as `actions` or `candidates` raised inside the walk, and the discipline
  reported `internal_error` with `meta.source: unavailable` — which says the
  engine broke over a cell nobody could answer, when nothing was wrong with
  the model and the caller had passed a dict. Both verbs now accept a mapping
  or an `ActionInstance`; two transports were already converting one by hand
  in two copies of the same six lines, and that conversion has one home. A
  type that is neither raises at the boundary. Reported from outside.

### Added

- `plan` candidates carry `clearance_sigmas`: the signed worst headroom over
  the horizon in declared spreads — positive when the trajectory stayed clear
  of every line it was judged against, negative by how far the deepest
  excursion went past one. On the shipped example a candidate reports a
  `margin_sigmas` of 0.920 while sitting 4.985 spreads the wrong side of a
  line, and an absolute distance cannot express the difference.

- `twin.topology.TIME_COURSE_KEYS` — the two `temporal:` keys that decide
  whose number a transient is, alongside `REQUIRED_TRANSITION_KEYS` for the
  block beside it. `response_model` is deliberately not a member.
- `twin.actions.as_action_instance` — one action, however a caller spelled it.
- `residual.predict_vs_mirror.NORMAL_90_HALF_WIDTH` — the half-width of a 90%
  normal interval, in standard deviations. Added in the round that gave the
  engine's own forecasts a producer's scores and named here late: the guard
  that watches public constants for departure had been reporting it as
  unwritten since, which is the guard working.
- `simulation` and `plan` are named in `envelope.schema.json` rather than
  riding as additional properties. The prose beside that keyword enumerated
  six smaller tool-specific keys and mentioned neither, so the schema's own
  inventory was stale by exactly the surface 0.2.3 added.

- **The engine scored its own forecasts on a band it chose itself, and that
  figure rewarded declaring ignorance.** A rollout filing predictions recorded
  a POINT with a tolerance of `1.96 * gain_sigma`, so `confirm_rate` asked
  only whether a later reading landed inside the band the model drew. A wider
  declaration is therefore confirmed more often. Measured on one tank that
  really scatters by 2.3 points, forecast by the same gain declared twice —
  honestly, and ten times too wide:

  | declared spread | accepted band | `confirm_rate` | `brier` |
  |---|---|---|---|
  | honest | +/- 4.5 | 0.95 | 0.0475 |
  | ten times too wide | +/- 45.0 | 1.00 | 0.0025 |

  The useless declaration won on both. `brier` is no second opinion: every
  record is filed at one stated confidence, which makes it a monotone
  restatement of the hit rate rather than an independent score.

  `_grade_distribution_record` has always stated the rule in its own
  docstring — *a model at 100% coverage is badly calibrated in the other
  direction, having bought its hit-rate with intervals too wide to act on* —
  and that path is reachable only by an outside producer. The engine applied
  a standard to its inputs that it did not apply to itself.

  A value filed from a declared spread now states that spread as quantiles,
  and grading scores them. `calibration.own_projections` carries pinball, a
  CRPS approximation and `coverage_90` beside `expected_coverage_90`,
  stratified `by_coupling` and `by_horizon` — the coupling stratum being the
  one a producer's record can never have. On the same two declarations the
  CRPS reads 0.99 against 3.19, ranking them the other way round, because
  pinball loss grows with the width of an interval whether or not it
  contained the answer.

  `confirm_rate` also travels with `expected_confirm_rate`, in the aggregate
  and in `transitions.declared[*].projections`, so 1.00 beside a target of
  0.95 reads as an overshoot rather than as a perfect score. No trigger hangs
  off the distance: how much overshoot is too much is a domain question.

  **The verdict, the producer figures and every existing key are unchanged.**
  A record is still graded on its point against its declared tolerance; the
  engine's own scores are kept out of the `coverage_90` that answers *which
  forecaster is worth keeping*, because pooling two populations makes that
  figure a number about nobody. A caller filing no spread is scored on the hit
  rate alone — nothing is invented to fill the gap.

- **A guard written for this exact change fired on it.** A test named
  `test_the_kind_filter_is_defence_and_not_a_live_path` reported that
  `model_figures`'s `kind == "distribution"` filter could not matter, gave the
  measurement behind that — `record_distribution` was the only filer accepting
  a `model_id` — and named its own expiry: *the filter stays, because a later
  method growing a `model_id` argument would reach it.* A rollout filing under
  `arbiter_engine:rollout` is that method. The filter now does work on every
  call, the test records the transition rather than widening its list, and the
  coverage it said was missing exists: a value record with a model id is filed
  and the forecaster report is asserted not to list it.

- **Two published docstrings described a tree two releases old.** The
  prediction ledger's module docstring said *no rollout files its per-step
  values here* — made that false — and `record_projected_values` said
  `projected_values` was *a dark schema field that no producer constructs*,
  while two sites in `twin/traverser.py` construct one. The half of the first
  claim that is still true, that the transition learner reads nothing back, is
  kept.

  The second sentence was not rotting quietly — **a green test was holding it
  in place.** A decision-document pin asserted the literal *no producer
  constructs ProjectedValue yet* must be PRESENT in that module, so that
  wiring PREDICT would fail it and force the document to be revisited. PREDICT
  was wired on 2026-08-04, the document gained its superseding note the same
  day, and the sibling pin was amended to the new invariant. This one was not.
  For six weeks the suite required a published module to keep denying a
  producer that the test immediately below it named: correcting the sentence
  was the failing move and leaving it was the passing one. The pin now holds
  what is durable — the protocol, not the sentence.

- **A `transition:` block the loader refused reached `gaps` as silence.** A
  block missing any of `from`, `to`, `gain`, `source` is refused rather than
  completed with a default, and the refusal is filed as a
  `missing_declaration` gap naming the key that was absent. That gap is
  attached to the edge. `gaps` read the topology-level list, which is one of
  three populations, so a model declaring a coupling and omitting `source`
  answered `questions: []` beside `meta.source: live` — the engine reporting
  that it looked and found nothing missing, on the one verb whose whole job is
  naming what is missing.

  `DigitalTwinTopology.get_unresolved_gaps()` already collected all three
  populations. `gaps` now reads it, deduplicated on the same
  `(gap_type, location)` key, so a gap a traversal also found keeps the
  traversal's richer context path.

  **Net new questions on all six shipped examples: zero.** The collector
  returns roughly twice as many raw gap objects and they collapse onto the
  keys the traversal already reported. That measurement is also the diagnosis:
  no shipped example declares a coupling it then refuses, so no example
  exercised the path. One that does is now in the suite, and a guard pins the
  property rather than the six counts.

  A value-mode `traverse` and `rollout` reported this refusal the whole time,
  as a `missing_declaration` decline, and they distinguish it from
  `missing_dynamics` on purpose: reporting *no transition declared* for a
  block sitting in the author's file would send them looking for something
  already written. That split is unchanged and now pinned.

- **The refusal question asked for something the author had already written.**
  The description named the missing key and nothing serialised it, so the text
  reaching a caller was the gap type's generic template — written for a
  conservation gap, and asking *which quantities balance against which, and in
  which direction*. An author who declared both quantities and the direction
  and left out `source` was being asked to re-derive their own block. A gap may
  now carry an exact question, left unset everywhere else, and a refused
  transition asks: `Which value does `source` take for the transition on
  'p1->h1'?`

- **`transitions.refused_blocks` said which key and not which rule.** Blocks
  are indexed within their own rule, so two rules each refusing their first
  block both reported `transition[0]` with nothing to tell them apart. Each
  entry is now prefixed with its rule label. The element stays a string;
  readers do substring tests on the key name.

- **A README guard could not go green.** It asserted the README still called
  the PREDICT path *plumbed but unfed* — true when `ProjectedValue` was
  constructed only in a test, false since 0.1.15 fed the path with `project`,
  and red since the sentence left the README on 2026-09-17. It now pins the
  relationship in both directions and was proved live by reintroducing the
  sentence.

- **The engine's own rollout forecasts were the one population with nothing
  to beat.** Three surfaces file forecasts into the ledger. `ingest_forecasts`
  fits a parameter-free random walk beside every producer record and reports
  the outcome per record; `project` fits one beside its own forecast;
  `rollout(file_predictions=True)` filed neither, and no leg of the envelope
  said so. Measured, one session, one series, one horizon, the engine's own
  two verbs:

  | verb | ledger after one call |
  |---|---|
  | `project` | `{'local_level:estimated_parameters': 1, 'baseline_rw': 1}` |
  | `rollout` | `{'arbiter_engine:rollout': 6}` |

  So `calibration.own_projections` reported a well-formed score that could not
  separate a declared `gain:` carrying real information from one whose
  `gain_sigma:` was merely generous — which is the failure `RandomWalk`'s own
  docstring names: *a forecaster can be beautifully calibrated and still carry
  no information at all*. A rollout now files the reference beside each of its
  projections, fitted on the driven property's own readings as of the instant
  the walk was run for, and reports it under `own_projections.baseline` with
  `beats_baseline` decided on CRPS over the **matched** targets only.

  **The yardstick is excluded from the figure it is the yardstick for.** Both
  are `kind == "value"` records; pouring the reference into the headline would
  have moved the engine's own score toward the baseline by however many
  companions were filed — a defect worse than the gap.

  **This is a class reopening.** `ingest._file_baseline` records the same gap
  in the mirror direction, when the reference ran for `project` and not for a
  producer: *it was filed beside one of the two kinds.* That fix covered the
  two kinds that existed; `rollout` arrived in 0.2.3 as a third.

- **`plan` ranked by a forecast that nothing could ever grade.** The verb
  states an objective per candidate — *throttling to 800 rpm produces 4.33
  expected findings, doing nothing produces 0.0* — and filed nothing: the
  ledger was empty after a call and the plan leg carried no calibration. Most
  rows must stay ungradeable, and `rollout` already says why: a candidate
  carrying actions describes a world nobody brought about, and grading it
  against a world where nobody acted would fill the ledger with falsified
  records that say nothing about the model.

  **`do_nothing` is not a counterfactual.** It is the trajectory that obtains
  if nobody acts and the row every other row is measured against, so it is the
  one whose projections are filable. `plan(file_predictions=True)` now files
  it — default OFF, like `rollout`'s own flag, because a verb that reads as a
  query should not write to a durable ledger unasked — and what it files is
  raced against a random walk like any other forecast. The rows that do not
  file say so ONCE with a count at plan level, never on the per-candidate
  `declines`, where a by-design exclusion would sit beside real faults and
  make four healthy rows look damaged.

  `seed_mode` reaches `plan` for the first time and reaches **every candidate
  or none**: under the default `current` nothing moves, so the no-action row
  correctly files nothing. Applying `projected` to the filing row alone would
  score one row on a trajectory the others never saw — the defect that an internal ruling
  recorded, a number claiming a measurement of a plan nobody simulated.

- **`plan` never fitted the projected seed, so every candidate declined.** The
  projector step `rollout` performs before walking was absent here. Measured,
  same model and same inputs: `steps_requested: 6` through `rollout` and `0`
  through `plan`, with every candidate reporting `insufficient_samples` — a
  sample shortage reported for a projection nobody had fitted. Fitted once and
  shared by every candidate, which is also what keeps the rows comparable.

- **`project` filed a reference and reported nothing about it.** A refused fit
  was dropped on the floor — the forecast was still filed and later graded,
  raced against nothing, with no leg carrying the fact. That is the shape
  `BRIDGES.md` names in its own words, *nothing declines, because a race with
  one runner still has a winner*, sitting on the verb whose own reference
  exists to prevent it. `project` now reports `raced`, one row per issued
  forecast, in the same closed vocabulary `ingest_forecasts` uses, and counts
  `baselines_filed` beside `forecasts_issued`.

### Added

- **Two exponential lags in series now compose to their convolution.** The
  walk charged each edge's response against a source already lagged, so two
  hops developed as the PRODUCT of two curves. They are now composed exactly
  and stamped `series_edges_composed_exactly`. Measured on two equal 600 s
  lags with a 100-unit step, the answer moves from 60.35 to **44.22 at
  `t = 900 s`** — the product led by 16.1 units, so a breach two hops out was
  predicted early, and `plan` ranks on transients.

  Done as a multiplicative correction on the response FRACTION, so a value and
  its declared spread cannot come apart, and applied PER CONTRIBUTION — a
  target fed by a chain and by a direct edge gets each one right, because
  superposition is linear.

  **What has no closed form still composes by product and still says so.** A
  `linear` or `logarithmic` stage anywhere in the chain keeps
  `series_edges_compose_by_product`. A third hop gets the exact two-stage head
  and the product beyond it: measured on three equal 600 s lags, error falls
  from 28.11 units to 18.42, and it is still stamped, because closer is not
  exact. A rollout crossing both kinds carries BOTH stamps.

  `series_errors` rows now record what the approximation would have COST
  rather than what it did: the `product` avoided, the `exact` value used, and
  the signed gap.

- **The engine now says how much its one approximation costs.** A value two
  hops out is charged each edge's own step response against a source already
  lagged, so it develops as the PRODUCT of two curves where the declared
  dynamics imply their CONVOLUTION. That has been stamped
  `series_edges_compose_by_product` since 0.2.5 — which names the assumption
  and stops there, while the trajectory it produced went out as a bare number.
  A `series_errors` row per step now carries the `product` used, the `exact`
  convolution, and the signed gap, as fractions of the final impact. Measured
  on two equal 600 s lags: the product leads by up to **0.161 per unit** at
  `t = 900 s`, and the gap closes to 0.012 by an hour.

  **Quantified only where a closed form exists** — a chain of exactly two
  exponential stages. Anything else keeps the bare stamp and contributes no
  row, so an empty leg under the stamp reads *not quantifiable*, never *no
  error*. **The trajectory is unchanged**: this measures the walk, it does not
  correct it.

  The documented reason the exact form was unavailable — that the
  partial-fraction expression cancels catastrophically as two time constants
  approach each other, needing a near-equality tolerance nobody declared —
  is true of that FORMULATION and not of the convolution. Measured at
  `t = 900 s`, `tau1 = 600 s`: the partial fraction holds to 2e-14 at a 1 s
  separation, reads 0.625 against a true 0.442174599629 at 1e-13, and divides
  by zero at equality; the divided-difference form holds every digit across
  the same sweep and meets the equal-tau closed form exactly. `expm1` is built
  for it and the only branch is an exact comparison against zero.

- **Both calibration tables carry `by_target`.** The producer table strata by
  `by_model` / `by_entity_type` and the engine's own by `by_coupling`; the only
  axis they shared was `by_horizon`, which resolves neither entity nor
  property. So *did my declared coupling beat the learned producer on THIS
  series* had no surface to be asked on, although both populations forecast the
  same `(entity, property, horizon)` triples. The two tables stay separate —
  pooling them would make `coverage_90` a number about nobody — and now share
  one join key.

- **The README answers whether this is a world model.** The term appeared once
  on the published surface, in `ROADMAP.md`, and nowhere in the README — so
  the question was left to readers, one of whom answered it in 464 lines. The
  section states the line the rest of the engine holds: dynamics are declared
  or refused, never learned; `rollout` means declared transitions and declared
  action effects on a private clone that dispatches nothing; and a learned
  model belongs on the producing side, with `forecast:`, `ingest_forecasts`
  and the shadow axioms keeping its books against a random-walk baseline.

## [0.2.5] — 2026-09-20

**What a 0.2.4 user is getting.** 0.2.4 shipped the simulation surface --
`rollout`, `plan`, the transition learner, the prediction ledger -- and that
surface was wrong in ways a reader of its envelope could not see. A lagged
edge froze at whatever fraction one step reached. A property moved twice was
walked as though the whole displacement arrived at the second instant. A
coupling into a property an action also moved was dropped while the envelope
reported it applied. A plan was scored for a trajectory it had not run, an
objective was summed in binary floating point so equal costs stopped comparing
equal, and a calibration counted twelve samples of one trajectory as twelve
independent pieces of evidence. All of that is fixed below, each entry
carrying the measurement that found it.

**Nothing here breaks a reader.** `meta.schema_version` does not move. Every
change is additive -- a key, a decline member, an assumption stamp, an MCP
tool -- or a wrong number becoming right, which is what this package's
compatibility document names as patch-legal. The one thing to know before
upgrading is in **Compatibility** at the end of this section: several checks
now FIRE or DECLINE where 0.2.4 was silent, and silence was the defect in
every case.

**How this section was produced, once rather than per entry.** Four outside
readings of this surface arrived between 0.2.4 and here, and every claim in
each was REPRODUCED against the tree before anything was changed. Three of the
four ran nothing and derived their conclusions from the source; the fourth ran
everything it claimed, and all seven of its findings held. Across the four,
six claims were refuted rather than fixed, each for the same reason: true of
the concept named and false of the code implementing it -- an exponential that
never reaches 1.0 (true of the reals, false of float64), a `trend` seed said
to be a ramp (true of the word, false of `TrendCurve`). The refutations are
kept below under their own headings, because a claim this project examined and
rejected is part of the record of what was checked. The numbers quoted
throughout are measured, not derived.

### Fixed — an action on a property a coupling also drives

The eighth reading of this surface, and the first that ran everything it
claimed, reported seven defects. All seven reproduced, exactly, including
every number in them. It also delivered a patch for the two it rated highest,
with tests that pass under it and a clean run of the whole suite.

**That patch is not what shipped, and the reason is the point of this entry.**
It restores the right invariant and it introduces a new silent wrong number in
doing so. Under it, a `set` to 20 on a tank a pump is still filling reports
22.3865 at the instant of the action, where the clean tree reports 20 and then
freezes. The error is exactly `REACH * (f(t) - f(t - step_s))` -- one step's
worth of the coupling's delivery, counted twice -- and it tracks the step size
precisely: 2.3865 at `step_s=300`, 0.3869 at 60, 0.1247 at 20. It shrinks as
the step shrinks, which is the signature of a discretisation artefact in a
module whose whole design is that it has none.

It survived the patch's own six tests and all 1950 shipped ones because `add`
is immune -- its delta does not read the standing value -- and because NO
shipped test had an `action_templates:` entry whose `applies_to` entity is a
transition's target. That gap is what hid the original defect too.

- **A transition into a property an action also moved still arrives.** Every
  coupling contribution into a property that had a movement of its own was
  DISCARDED, while the envelope went on reporting the transition as applied
  and declining nothing. The drift reconciliation then treated what had
  already arrived as an unexplained displacement of the property's own and
  folded it into the latest movement, which was walked outward again -- so
  the value was lost at the target and double-counted downstream. Measured on
  a pump feeding a tank through `gain: 0.02`: `set 1500` on the pump with
  `add +5` on the tank settled at 55.0 where the declared arithmetic gives
  65.0; under a 120/600 exponential edge with the `add` at t=600 s the tank
  FROZE at 60.0341 for the remaining fifty minutes against a declared 64.9697,
  lost its declared `gain_sigma:` from that instant on, and handed the 5.03 it
  had already received to a downstream sump a second time (30.0039 against
  24.9697). Reachable from `plan` the moment a template writes a property some
  coupling also drives -- a top-up, a vent, a bleed valve, a manual reset. The
  invariant now restored every step is
  `state = baseline + sum(movements) + received`.

- **`set` and `scale` on such a property read the value it actually has.**
  Their deltas depend on where the property was, and that was read from the
  state written at the END of the previous step while the state written
  afterwards used what the couplings had delivered by THIS one. The two
  clocks are now one: the delta is resolved against the standing value at the
  action's own instant, which costs one extra walk per action and none per
  step.

- **And the doubt travels with the value.** A `set` pins a property, so the
  doubt the couplings had put into it is gone and only LATER arrivals are
  still in doubt; a `scale k` multiplies what is standing, so it multiplies
  that doubt. This is the treatment a seeded forecast's band has had since
  0.2.4 and a contribution that arrived through a declared `gain_sigma:` is
  the same kind of quantity. Measured before: a tank `set` to 20 went on
  reporting the coupling's full 0.6321 spread, and a tank scaled by 2
  reported 0.9502 where 1.5823 was carried.

- **A walk reports a spread it was handed even when it moved no value.** The
  emission loop iterated the value deltas, so a start node carrying doubt and
  gaining nothing from that walk fell out of the report. A spread is a claim
  about a value, not a by-product of changing one.

- **A forecast-seeded source pinned by a `set` at `at_s=0` hands on no band.**
  The per-instant sensitivity was ASSIGNED rather than accumulated, and an
  action at `at_s=0` lands on the seed's own instant, so `+1` became `-1`
  instead of `0`. Measured on a `random_walk` pump feeding a tank through
  `gain: 0.02` with no declared `gain_sigma:`, the pump SET to 2000 rpm: the
  tank reported 0.861 at `at_s=0` and nothing at `at_s=1` or `at_s=60`. This
  fix is the outside patch's, adopted as delivered.

- **A decomposition that disagrees with the state says so.** The fold that
  absorbed the difference remains, because propagating a state the source does
  not show is worse; it is no longer silent. Measured across 40 rollout
  configurations covering every effect kind, both seed modes and two step
  sizes: it fires in none of them.

### Fixed — the imagined world stays out of the live counter

- **A rollout no longer counts its findings in the process-wide fire-rate
  telemetry.** The reasoner records every finding it dispatches, and a rollout
  reaches the same dispatcher over a state nobody has. Measured on the shipped
  example at a tank level of 92 %: one live `check` recorded 2 fires and one
  `plan` recorded 600 in the same buckets -- `BOUNDEDNESS: 301`,
  `HOMEOSTASIS: 301` -- enough to trip this package's own high-rate WARN on a
  world that does not exist. Nothing in the tree reads the counts back, so no
  verdict moved; the rule the rollout opens with, that the clone is never the
  live history, is the same rule, and this was the one channel it was not
  being kept on. Closed with a context the rollout owns rather than a flag in
  the dispatcher, which is shared by every domain and every verb.

### Fixed — a forecast is graded at its horizon

- **A value prediction is no longer confirmed by a reading taken anywhere in
  its window.** Grading took the observation closest to the horizon with no
  bound on how far away the closest one was, so one reading graded every
  horizon the window contained. Measured: twelve predictions filed for
  t = 300 … 3600 s, then ONE tank reading 60 s after the rollout and silence
  for the rest of the hour, returned `confirmed 12, falsified 0, ungradeable
  0, confirm_rate 1.0, brier 0.0025` -- a perfect score off the quietest
  possible mirror. A reading now grades the record whose horizon it is
  NEAREST to, out of the horizons that episode filed -- a rollout files one
  per step, so the records themselves supply the spacing and nothing had to
  be chosen. One reading grades at most one record; the rest are
  `ungradeable`, which is the channel being silent at the instant they are
  about, and silence has always been that.

  `grace_s` was tried as the bound first and is recorded here because it
  looks right: it is already the ledger's statement of how long past the
  horizon it will wait, so reading it symmetrically seemed to introduce no
  new number. A ledger may declare `grace_s=0`, and one in this tree's suite
  does -- which means *I will not wait past the horizon*, not *a reading must
  land on it to the second*. Under the symmetric reading, five seconds of
  ordinary sampling jitter became `ungradeable`, and ten shipped tests in the
  derived net said so before any of this was believed.

### Added — the world model can be exercised over MCP

- **`add_relationship` is an MCP tool.** It is the only path by which a
  session acquires an edge, and a `transition:` block lives on a relationship
  RULE -- so without it every MCP session ran the simulation verbs over a
  topology with no edges. Measured through `dispatch` on the shipped example:
  a rollout throttling the pump by 500 rpm reported `transitions_applied: 0`,
  a tank flat at its baseline, and `not_checked: []`; `plan` ranked five
  candidates that all did the same nothing and chose by tie-break. That is the
  0.2.3 shape this file already describes, reached through a missing tool
  rather than a frozen transient.
- **`rollout` accepts `file_predictions`,** so the closed loop -- file,
  mirror, grade -- can be started over this transport at all.
- **A dispatch-only end-to-end test** now drives load, entities, edge,
  rollout-with-filing and describe using only what the transport offers. The
  existing guard checks that every declared tool has a handler, which it
  always did: the verbs were never declared, and only a test that has a job to
  finish can see an absence.

### Added — a declared coupling with nowhere to run is reported

- **`coupling_uninstantiated`** joins the simulation decline vocabulary, and
  `couplings_declared` / `couplings_instantiated` join `checked` on `rollout`
  and `plan`. A rule whose type joins no pair of entities in this session had
  nothing to move, and every verb answered as though it had. Reported per
  RULE: which pairs SHOULD have been joined is the author's business, and the
  engine does not guess at it.

### Added — how edges in series compose

- **`series_edges_compose_by_product`** is stamped whenever a contribution
  crosses more than one transient-shaping edge. The walk charges each edge's
  response fraction against a source that is itself already lagged, so a value
  two hops out is the PRODUCT of the two step responses; for linear stages in
  series the answer is their CONVOLUTION. Measured on two 600 s lags with unit
  gains and a 100-unit step at the head: the second hop reads 39.96 at t=600 s
  against a series response of 26.42, and 63.70 at t=960 s against 47.51 --
  early by 16.19 at the worst. Steady state is exact; `plan` ranks on
  transients.

  **Stamped rather than composed, and the reason is not cost.** Composing the
  cascade exactly is tractable only for the LTI models, and the
  partial-fraction form for distinct time constants cancels catastrophically
  as two of them approach each other -- so a robust implementation needs a
  near-equality tolerance, which is a number nobody declared and therefore not
  this engine's to choose. The stamp fires only on a chain of edges that
  actually shape a transient: one hop does not carry it, and neither does a
  chain of `step` edges, which compose exactly.

### Added — what a proposed `gain_sigma:` is worth

- **`residual_autocorrelation`** and
  **`gain_sigma_assumes_independent_residuals`** are reported beside a
  proposal. That standard error assumes independent residuals and neither fit
  path gives it that: both difference the target's readings, so the residuals
  are an MA(1) whose lag-1 correlation measures near -0.5 EITHER WAY. The
  correlation alone therefore says nothing about whether the number is wrong.
  What decides it is whether the REGRESSOR was differenced along with the
  target -- which the declared `response_model` settles. Measured over 200
  trials at each of two noise levels, the ordinary standard error against the
  empirical scatter of the fitted gain: **1.03x** on a `step` edge and
  **5.17x** on an `exponential` one, with the same autocorrelation on each.

  **A flag, not a correction.** The exact MA(1) sandwich is the textbook fix
  and it is not estimable here: the long-run variance of an MA(1) whose
  coefficient sits near -1 is nearly zero, so the sample estimate came out
  NON-POSITIVE in 81 of 200 trials -- on the very path it exists for -- and
  1.37x when it did not. Interval coverage measured 60/60 either way, so
  `disagreement` under-triggers rather than over-triggers; what is wrong is
  the claim beside the number, not any verdict, and this says so rather than
  quietly narrowing anything.

### Fixed — a spread nobody declared is not a declared zero

- **`transitions.declared[].gain_sigma` reports `None` where none was
  declared**, and carries `gain_sigma_requested` beside it. All three of a
  measured spread, `gain_sigma: estimate` and an absent key reported `0.0`,
  which is the claim that the gain is exact -- and this format's own rule is
  that a value nobody measured the spread of and a value known to be exact are
  different claims, the second much the stronger. `estimate` was the worse
  case: an author writes it to say they do NOT know the number. The runtime
  always honoured the distinction and only the report did not.

---

The first two readings of 0.2.4 found six defects and then four more, each
reproduced before it was fixed.

### Fixed

- **A rollout now integrates the transient instead of freezing it.** Declared
  transitions were applied once, in the step their source moved, with one
  step's worth of elapsed time, and never re-applied. On the engine's own edge
  defaults -- `propagation_delay_s: 60`, `time_constant_s: 60`, exponential --
  against the default `step_s: 60`, `response_fraction(60)` is exactly `0.0`:
  measured, a tank sat at `50.0` for all sixty steps of an hour-long rollout
  while the declared response said `109.8`, `transitions_applied` reported `1`,
  and nothing declined. MODELING.md's own `transition:` example produced the
  same flat line. The response is now re-derived at every step from the instant
  its source moved, which reuses `TwinEdge.response_fraction` rather than
  copying the time course into the rollout, and the trajectory matches the
  declared curve to within 1e-6 at every step.
- **`plan` could not tell its candidates apart, and recommended inaction.**
  A consequence of the above, and the one that reaches a caller as advice.
  Measured on a tank at 92 % against a declared `warning: 85`, with throttling
  the pump among the declared candidates: all four candidates scored `10.0`,
  the tie-break returned `do_nothing`, and `best` said so. The same model now
  scores `1.0` for throttling against `10.0` for doing nothing.
- **`rollout` and `plan` fabricated `checked.invariants`.** Both built the
  denominator from their own output -- `api.rollout` from findings plus
  axiom-shaped declines, `planner` from findings alone -- discarding
  `DetectionResult.evaluations_attempted`, which `interfaces.py` carries for
  this and whose comment says exactly why the sum is not a substitute. A clean
  rollout reported `checked.invariants: 0`, indistinguishable from *no axiom
  ran*; the denominator also moved with its own numerator. Measured: five steps
  over two declared indicators reported `0`, and now report `10`.
- **Values are resolved in dependency order, so nothing reads a partial one.**
  Two defects here, and the second was only visible once the first was fixed.

  The visited check asked whether a node had been SEEN, which is true both for
  a back-edge and for the second arrival of an acyclic diamond. Measured on
  `a->d` beside `a->b->c->d`: `cycle_unsupported` was filed at `c->d`, the
  longer path's contribution was dropped, and `d` carried `2.0` where the
  declared gains give `3.0`.

  Making `d` right exposed the rest. Transitions were applied when the BFS
  happened to pop their source, and a BFS pops by HOP COUNT -- so on the same
  graph with `d->e`, `d` ended correct and `e` sat at `2.0`, short by the
  whole second path. The value pass is now ordered by DEPENDENCY rather than
  by hop: a node is resolved only once every edge into it has contributed, so
  `e` carries the whole of `d`. Nested diamonds compose exactly (measured:
  `3.0` then `5.0`), a 200-node chain resolves in 0.03 s, and axiom evaluation
  on a simulating walk is deferred until every contribution has landed, so
  findings are drawn from the value the envelope reports.

  **A cycle is now exactly what the ordering cannot resolve**, which is a
  smaller and truer set than *the walk saw this node already*. Two shapes
  produce it and they get different sentences: an edge into an already
  resolved node CLOSES a loop, and an edge whose source never resolved sits
  INSIDE one. The second wording exists because advice pointing at *the edge
  that closes the loop* can name an edge that is not reported -- in
  `a->b->c->b` neither member ever resolves, so both of its edges take that
  branch and none takes the other. Measured.

  `reconvergence_unsupported`, added earlier in this same unreleased section
  to NAME the downstream damage, is retired: the damage is gone, so the reason
  had nothing left to report, and a member nobody can construct an input for
  is the dead-vocabulary shape exists to catch. It never shipped.
- **The transition learner fits the quantity the model declares.** It read
  `propagation_delay_s` and neither `response_model` nor `time_constant_s`,
  then regressed first differences against each other -- which estimates a
  steady-state gain only when the response is instantaneous. Measured on a
  series generated through the edge's own declared response at `tau = 600 s`
  sampled every 60 s with a declared gain of `0.02`: the learner fitted
  `0.00234`, filed a `disagreement`, and attached a remedy that would have
  replaced a correct datasheet number with one eight times too small. An
  `exponential` edge is now fitted through its declared response, recovering
  `0.020000`; `linear` and `logarithmic` are not first-order lags and are
  declined `response_model_unsupported` rather than fitted under a model the
  edge does not declare. Every fitted entry names the response model it was
  fitted through.
- **The published what-if takes a horizon.** `api.traverse` built its request
  without `horizon_s`, so every hypothetical walk through `api` or MCP was
  evaluated at the request default of one hour and a caller could not ask what
  a value becomes in ten minutes. `simulate_what_if` accepted the parameter and
  dropped it on the floor. Both now pass it, the MCP tool offers it, and the
  horizon used is stamped into `payload.simulation`.
- **A declared dead time now applies to the offset too.** The contribution was
  `gain * delta * fraction + offset`, so a constant term crossed an edge whose
  delay had not elapsed: measured, a 120-second delay with `offset: 7.0`
  reported the target 7 units from its reading at a 60-second horizon while the
  fraction was `0.0`. The whole contribution is charged the fraction, which is
  arithmetically identical at `fraction == 1.0`, so no steady-state answer
  moves.
- **A history that cannot be enumerated is reported.** `_clone_history`
  returned an empty clone when the session's history had no `series_keys`, so
  a rollout stepped forward with no imagined past and every windowed axiom
  declined for lack of SAMPLES -- a different statement, with a different
  remedy, from lack of horizon. It now files `precondition_unmet` saying so.

### Added

- `examples/pump_tank_dynamics.yaml` — **the first shipped example that
  declares dynamics.** None of the five existing examples declared a
  `transition:`, an `action_templates:` block or a `planning:` objective, so
  the whole surface 0.2.3 added could not be run against anything this package
  ships and existed only as prose in MODELING.md. It declares a delay and a
  lag on purpose: every rollout and plan fixture in the suite declared an
  instantaneous response, which is the one regime in which the defect above is
  invisible.
- `response_model_unsupported` from the transition learner.
- `simulation.per_step[*].response_fractions` and `.invariants`;
  `simulation.horizon_s` on `traverse`.
- `causal.leadlag.align_with_times`, so a caller needing the SPACING of the
  pairs does not re-intersect the series itself.

### Refuted

- The same reading held that `steady_state_reached` is unreachable under the
  default response model, since `1 - exp(-t/tau)` never reaches `1.0`. True of
  the real numbers and false of the arithmetic: at `t/tau` beyond about 37 the
  exponential underflows below the double-precision epsilon and the expression
  evaluates to exactly `1.0`. Measured — `response_fraction` returns `1` at
  `t = 100 tau`. The stamp is reachable and no change was made.

### Added — value-level uncertainty, and a loop that closes

The 0.2.4 reading ended with a gap list whose first three entries were the
defects above and whose next two were capabilities blocked behind them. With
those unblocked, both are here.

- **`gain_sigma:` on a `transition:` block — a DECLARED spread on the gain.**
  Every value the coupling drives now carries a standard deviation and a 95 %
  interval beside it, propagated through a chain by the delta method and
  stamped `first_order_uncertainty` so nobody reads the band as exact. An edge
  without one behaves exactly as before, and a value nobody declared a spread
  for carries NO interval rather than one of zero width: a value whose spread
  was never measured and a value known to be exact are different claims.
  Nothing is inferred -- not from a correlation, and not from `confidence:`,
  which weights whether the coupling exists at all and is in different units.
- **`clearance_probability` is a probability.** It sampled a function that
  returned the same constant every time, so the estimate was 0.0 or 1.0 and
  the interval collapsed to a point -- honestly stamped
  `deterministic_transitions`, and a boolean wearing a decimal point. With a
  declared spread the margin to the line is a random variable: measured, a
  candidate that used to score a flat `0.0` now scores `0.01` with an interval
  of `[0.0, 0.0295]`, against a margin of `-5` and a spread of `2`. The
  tightest margin over the horizon is the one sampled, because the same
  declared gain drives every step of a trajectory rather than a fresh draw per
  step; that is the engine's assumption and it is stamped
  `worst_step_binds_the_horizon`.
- **`rollout(file_predictions=True)` — the loop closes.** The durable ledger
  shipped in 0.2.3 and `grade_matured` already scored `kind == "value"`;
  nothing ever filed one, so the engine could project a value, judge it, and
  never learn whether it had been right. A rollout now files each imagined
  instant as a falsifiable value prediction, `check` matures and scores them,
  and the rollout payload carries the ledger's calibration. End to end and
  measured: five filed, the world contradicted four, **Brier 0.7225**.

  **Two refusals guard what gets filed, and both are about honesty.** A
  rollout carrying actions is a COUNTERFACTUAL -- this engine never
  dispatches, so it cannot know the actions were taken, and grading *what
  would have happened if* against a world where nobody did it would fill the
  ledger with falsified records that say nothing about the model, while
  corrupting the one figure meant to say whether its projections can be
  trusted. And a point prediction with no resolution is not falsifiable: the
  tolerance is the author's declared `gain_sigma:` band, never one this engine
  invented, on the same rule applies to a floor. Both refusals are
  counted and named (`counterfactual_not_a_prediction`,
  `no_declared_tolerance`), and `predictions_filed` plus
  `values_without_tolerance` partition every imagined value.
- `examples/pump_tank_dynamics.yaml` declares a spread, so all three have a
  specimen that ships.
- **`gain_sigma: estimate` — a fitted spread, proposed the way a fitted gain
  is.** The learner already computed a standard error on every gain it fitted:
  a measured statement of how well the readings pin the slope down, sitting
  one field away from the `gain_sigma:` that declares the same quantity, and
  reported nowhere. It now appears under
  `proposed_transitions.fitted[*].gain_sigma`, and it moves with the data --
  measured, twenty times the scatter proposed a spread twenty times wider
  (0.0075 against 0.149). A PROPOSAL: a transition asking for one carries no
  interval until a number is written into the model, exactly as
  `gain: estimate` projects nothing until its magnitude is adopted. Not the
  residual scatter, which is a different uncertainty — about the next reading
  rather than about the coupling — and folding the two together would propose
  a band that means neither.
- **A declared coupling is told how its own projections fared.** The loop ran
  one way: rollouts filed, `check` graded, and nothing read the verdicts back
  to the gain that produced them. `transitions.declared[*].projections` now
  carries `graded`, `confirmed`, `falsified` and `confirm_rate` per coupling,
  with the denominator beside the rate, and a `remedy` below half confirmed.
  An author could previously see a coupling and a fitted disagreement beside
  it, and could not see that every forecast the coupling had produced was
  contradicted by the world — which is the stronger evidence of the two,
  because it is about the model's OUTPUT rather than about a slope.

  **Still a report, still not an edit.** The engine does not rewrite a
  declaration, does not adopt a fitted spread, and does not quietly widen an
  interval because the last five forecasts missed. Pinned by a test that
  contradicts every projection and then asserts the declared gain and spread
  are exactly what the author wrote.

### Fixed — one question, one projection

- **The engine had a verb that refused to guess and a path that guessed
  silently, for the same question.** `projection/runner.py` reads `dynamics:`
  off an indicator and declines `model_missing` when there is none: *no
  `dynamics` declared, so there is no model to fit; the engine will not choose
  one on the author's behalf*. That is the rule `projector.py` states in its
  own opening, where a curve fit is deliberately NOT the default because *an
  extrapolated straight line reports a confident number for a series that is
  not going anywhere*.

  `TopologyTraverser.project_values` did the opposite: it fitted a trend curve
  to any series with three readings, whatever the model said. Measured on a
  120-sample random walk with nothing declared — `project` declined, and the
  traverser returned **2683.89 against a last reading of 2522.40**, a
  confident extrapolation of +161 on a series going nowhere.

  What made it urgent rather than untidy is that `rollout(seed_mode=
  "projected")` runs that path, and a rollout now FILES its values as
  predictions. The engine had begun scoring itself on numbers nobody declared
  a model for, through a method its own other path argues against.

  Both paths now read the one declaration and run the one projector. Measured
  after: a declared `random_walk` and a declared `trend` each return the same
  number on both paths, and they return DIFFERENT numbers from each other —
  so the declaration is what chose the model, which is the thing worth
  checking. An undeclared indicator is refused by both, by name.

  **A declared model whose FIT refused is not the same fact as an undeclared
  model**, and the remedies point in opposite directions: declare the
  parameters, versus declare a model at all. The projector's own reason is
  carried through — `local_level` on a plain random walk declines
  `unidentifiable_parameter`, *q and r do not separate from this series*. The
  first version of this swallowed that refusal and reported `model_missing`
  about a different indicator that happened to be undeclared; the second
  returns it.

  The `projection` decline vocabulary is folded into `simulation` rather than
  re-listed, the way the axioms' enum already is: a simulation that runs a
  projector can carry whatever that projector declined with, and a second copy
  of a closed set is how two vocabularies drift apart.

  `examples/pump_tank_dynamics.yaml` declares `dynamics: {model: local_level}`,
  so the shipped specimen covers this surface too.

### Fixed — a forecast keeps its doubt

Two defects in the loop this same unreleased section had just closed, both
found by asking what the filed numbers MEAN rather than whether they appear.

- **A projector returns a distribution, and only its median was kept.** So a
  rollout seeded from a forecast inherited the number and none of the doubt,
  and the predictions it filed were bounded by the declared `gain_sigma:`
  alone. Measured on a random walk at a 60-minute horizon: the source
  forecast's own 90 % band was **+/- 357.55 rpm**, which through a gain of
  0.02 is **+/- 7.15** points on the target — and the filed tolerance was
  **+/- 0.45**. Sixteen times too narrow, which falsifies projections that
  were never wrong and makes the engine's own calibration figure report that
  its forecasts are worthless. `ProjectedValue` now carries the band, and it
  rides into the walk so a transition passes it downstream through the gain
  exactly as it passes a declared spread. A target is now uncertain because
  its source is, whether or not anyone declared a spread on the coupling.
- **The seed was one forecast taken at the full horizon and then held.**
  Measured on a 60-minute rollout in 5-minute steps: step one reported the
  target at the value it reaches after an hour. That is the frozen transient
  again in a different place — a single-point answer stretched across a
  trajectory. The seed is now read off the fitted curve at EACH STEP'S OWN
  INSTANT; the fit happens once and only the forecast is repeated, which is
  the part that depends on the horizon. Measured after: the band widens as
  `sqrt(t)` for a random walk, and the filed tolerances widen with it, so a
  prediction at an hour is no longer graded against a five-minute window.
- **A third count, because two no longer partitioned.** A projected seed is
  the `project` verb's forecast and that verb files it; an action-set value is
  what the caller said they would do. Filing either would score one forecast
  twice, or score the engine on a decision. They are excluded and COUNTED, as
  `values_driven`, so `predictions_filed` + `values_without_tolerance` +
  `values_driven` is still every imagined value.

### Fixed — the second reading

- **A second movement of one property no longer restarts its response.** A
  rollout held ONE instant per `(entity, property)` -- the latest movement's --
  while the state held the cumulative delta, so a property that moved at `t1`
  and again at `t2` was walked once, as though the whole `d1 + d2` had arrived
  at `t2`. The engine stamps `linear_superposition` on every simulating walk;
  this was the one place it did not hold, and it failed loudly: the progress
  the first movement had made along its own response was discarded and the
  trajectory fell back to its baseline. Measured on a 120 s / 600 s
  exponential edge with `+500 rpm` at `t=0` and `+100 rpm` at `t=1800`: the
  tank reached `59.33` and dropped to exactly `50.00`, worst error `-9.50` at
  `t=1920`, rejoining the declared curve only as both responses saturated. The
  steady state was right throughout, which is why a test that checks where a
  trajectory ENDS could not see it -- and a HOMEOSTASIS or STABILITY axiom
  reading that trajectory reports a collapse the simulator invented, which
  `plan` then charges to whichever candidate staged its adjustment. Movements
  are now keyed by instant, one walk per instant, and their contributions sum.

  THE OFFSET IS WHY THIS IS NOT A ONE-LINE CHANGE, and the existing
  steady-state test is what caught it: `delta_target` is
  `(gain * delta + offset) * fraction`, so an edge walked in two movement
  groups charged its offset TWICE and the settled value went to
  `g*(d1+d2) + 2c` -- measured `76.0` against a declared `69.0`. The offset
  belongs to the coupling rather than to each movement of its source, so it is
  charged in the first group a source moves in suppressed thereafter,
  including for a constant term further down a chain.

- **A forecast that predicts no change now still predicts with a band.** Two
  gates stood between a projected seed's spread and the value it drives, and
  both turned on the median rather than on the spread. A seeded property was
  registered as a movement only if its value differed from the live reading,
  and the walk skipped any transition whose source delta was exactly zero,
  ahead of the variance term -- which does not depend on the median at all.

  `random_walk` fails both, and it is not a corner case: that model's median
  IS the last observation, so an entity whose property was set from its last
  reading -- what a collector writes -- seeds a value equal to its baseline,
  bit for bit. Measured on a 200-sample walk with a source carrying
  `+/- 62.75 rpm` through a gain of `0.02`: the tank carried no interval at
  any step instead of `+/- 1.25` points, `transitions_applied` was `0` so the
  declared coupling never ran at all, and `values_driven` was `0`.

  That last one is the worst of the three and was not what the reading
  reported. `values_driven` is the guard that stops a rollout filing the SEED
  as its own prediction, and with it empty the engine filed twelve of them --
  scoring `project`'s forecast a second time in the calibration, which is the
  double-count the filer's own comment refuses -- while the tank, the only
  thing the rollout actually predicted, was counted as having no tolerance.
  A source that stands still still contributes no VALUE, since the offset is
  part of a change rather than a standing term; it now contributes its doubt.

- **`_ROLLOUT_NON_AXIOM` is removed.** It subtracted the rollout's own
  refusals from a denominator derived by counting declines, and that
  denominator was replaced with `evaluations_attempted` earlier in this
  section. Nothing has read it since. A dead constant is retired for the same
  reason a dead decline reason is: the next reader has no way to tell one that
  is waiting from one that is finished.

### Refuted — the second reading

- **A `trend` seed through a lag is not a product approximation of a ramp.**
  The reading held that a `trend` model presents a ramp `r*t` to the edge, so
  applying `f(t)` to the whole delta approximates a convolution the closed
  form gives exactly. `TrendCurve.fit` returns `level = the fitted line at the
  last sample` and carries the slope as process noise `q`, so its median is
  CONSTANT across horizons and the band widens instead -- the documented
  reason a curve fit is not the default. Measured: the seed read `2311.61` at
  every one of twelve steps. With a constant median the product form is exact,
  which the reading itself grants for that case; no change was needed, and the
  proposed remedy of treating each step's increment as its own movement would
  have introduced the error it was meant to remove.

- **`TrendProjection` is not the path that guessed, and is not dead.** The
  class the entry above demoted is `projection/projector.py::TrendCurve`.
  `temporal/trend_projection.py::TrendProjection` is a different class with
  its own tests, still reached by `project_values` when no domain model is
  supplied at all -- a kernel used directly against a hand-built topology,
  which `_declared_dynamics` documents as deliberate, because silently
  refusing those callers would be a second wrong answer rather than a fix.
  Renaming it to say it serves a declared `trend` would make the name false.

  Its companion claim was right, and a sweep for the CLASS found two
  look-alikes it would have been wrong to act on: of the three private
  module-level constants in the package with no reference beyond their own
  definition, one is read by a test written to read it, and one is an
  intentionally empty row in a table of sibling patterns whose emptiness is
  the claim being made. Only the third was dead. No general guard is added
  for this, because a check that is wrong about two of the three things it
  finds is an allowlist wearing a test's name.

### Added — the coupling blocks are checked like every other block

- **A key `temporal:`, `transition:` or `planning:` does not read is now
  reported.** The loader has compared every key an author types on an
  indicator against the set it reads since 0.1.x, and `forecast:` got the same
  treatment one level down. The three blocks that say how a value PROPAGATES
  had none of it, and the comment beside the `forecast:` check said in as many
  words that it was the only nested block with a closed key set — which was
  true when it was written and stopped being true when `temporal:` and
  `transition:` arrived.

  The cost was silent in both directions. Measured on one rule declaring
  `propagation_delay: 120` and `gain_sgima: 0.002`, each a letter from a real
  key: the edge took the engine's DEFAULT 60 s dead time in place of the
  declared 120 s, so `response_fraction(180)` read `0.1813` against the
  declaration's `0.0952` — a response developing at nearly twice the written
  rate for the whole horizon — and `gain_sigma` stayed `0.0`, which removes
  every interval the coupling would have carried, stops `clearance_probability`
  being a probability, and stops a rollout filing anything it can be graded on.
  `unread_fields` was empty, `refused_blocks` was empty, nothing declined.

  That second one is the whole of the band-propagation defect fixed higher up
  this section, reachable again by one transposed letter and with no report at
  all. Rows carry the rule they came from, named the way `model_describe`
  already names one, rather than a list index. `dynamics:` stays exempt: its
  keys belong to the model an author named, not to this engine.

- **`action_templates:` too, for the keys that were silent.** The block is
  mixed rather than uniformly quiet: a mistyped `entity_property` is already
  caught when a rollout runs — the action is refused and counted — but a
  mistyped `settle_s` is caught nowhere. Measured, `settle_s: 300` against a
  60 s step declines `settle_exceeds_step`, which says the actuator is slower
  than the step and the ramp is not modelled; `settl_s: 300` declines nothing
  and returns a trajectory that reads as though the actuator were
  instantaneous. A template's `description` and a parameter's `type` are
  accepted and not acted on — both ship in this package's own worked example,
  so the accepted set is what the loader knows about rather than what changes
  behaviour, exactly as the indicator set has always been.

  **Only templates this engine accepted are checked**, and that gate is the
  substance of the change rather than a detail. `action_templates:` is the one
  block with a COMPETING schema: eleven of the nineteen models in this
  project's own tree declare the orchestrator's richer shape — `params`,
  `risk`, `blast_radius`, `duration` — and `load_templates` already refuses
  each of those whole, by name, with *template is missing applies_to,
  parameters_schema*. That one decline says the real thing. An ungated check
  reported six or seven unknown keys per template on top of it, every one of
  them valid in the schema the author was actually writing, which is the
  bury-the-signal shape this engine refuses elsewhere for an exhausted budget.
  The gate reads the required-key list from the module that enforces it.

  Silent on all 19 models this repository ships — measured before and after
  the gate, at 11 and then 0.

### Fixed — an action is not additive unless it says so

- **Two `set` actions on one property at one instant put it where neither
  asked.** An action is converted to a DELTA so it composes with the
  transitions arriving at the same property in the same step, through the one
  superposition rule the walk already applies. That argument is sound for an
  action meeting a transition and does not cover two ACTIONS meeting each
  other, because only one of the three declared effects is additive.

  Measured on a pump at `1000`, both actions at `t=0`: `set 1500` then
  `set 2000` put it at **2500**, and three settings reached `3300`. The rule
  is `A + B - base`, and it is order-INDEPENDENT — each `set` measures its
  delta from the same pre-step reading and the deltas are then added — which
  is what makes it a systematic artifact rather than a race. `scale 2` then
  `scale 3` gave `4000` where composing the two gives `6000`. Nothing was
  refused and nothing declined in any of them.

  **`plan` reaches it.** With `max_depth: 2` the planner offers every declared
  candidate as a second action, all at `at_s = 0`, so on this package's own
  worked example three of its eight candidates set `pump1.speed_rpm` twice at
  one instant and were ranked on a set-point the pump could never be given —
  objectives of `80.67` and `108.33` beside a true `80.0`.

  **The two cases are not the same and are not treated the same.** Two `scale`
  factors compose by multiplication, which is commutative: there is one answer
  and no ordering is needed to find it, so the engine computes it and stamps
  `scalings_compose_by_multiplication`. Two different `set` values at one
  instant have no answer — `at_s` is the only ordering this engine has, the
  two share it, and list position is an accident of how a caller built the
  sequence — so they are refused as `contradictory_actions` with both values
  in the refusal, and the property is left where it was. Choosing the later
  one would be the engine deciding which instruction the author meant. The
  same setting twice is redundant rather than contradictory and is applied
  once; two settings at DIFFERENT instants are a sequence, not a conflict,
  and both still apply.

  **A mixture of kinds is refused too**, and that case was the first version
  of this fix leaking. Holding back only the non-additive effects meant an
  `add` was summed into the bucket on its way past and still composed by
  addition with whatever was resolved afterwards: `add 100` beside `set 1500`
  on a pump at 1000 came out at **1600**, neither value and unrefused, and
  `add 100` beside `scale 2` came out at 2100 where the two orderings give
  2100 and 2200. The rule is about the SET of effects meeting at one instant,
  so the set is complete before anything is decided. Two effects of one kind
  still compose as above; two kinds at one instant are refused.

- **`contradictory_actions`** joins the simulation decline vocabulary, and
  `deltas_for` now reports which EFFECT produced each property's delta so the
  rollout — the only layer that can see two instances at once — can resolve a
  collision instead of adding through it.

- **A `plan` candidate names the refusal that emptied it.** A candidate whose
  actions were refused ran as though it had none and said nothing about why:
  three depth-2 candidates came back tied with `do_nothing` carrying an empty
  `declines`. The refusals were reported at plan level, so the fact was never
  lost — it was unattributed, which is the harder version of missing for a
  reader comparing rows.

### Removed

- **`clamp_to_bounds` on a `transition:` block.** Parsed onto `Transition`,
  carried in the published schema as a commented line, and read by nothing —
  an author could declare it and believe it. It also cannot be honoured: the
  only bounds this engine holds are `warning:` and `critical:`, which are
  DETECTION lines and not physical limits, so clamping an imagined value to
  them would cap every excursion at exactly the line a simulation exists to
  cross. A tank projected to 130 would report what one projected to 96
  reports, and `plan` ranks candidates on that difference. Declaring it is now
  reported as an unknown key rather than silently stored.

### Fixed — the third reading

A third outside reading of the unreleased tree, again deriving everything from
the source and running nothing. Three findings, all three real, all three
fixed. One of the three proposed a remedy that is wrong in a case it did not
test, and reproducing the other two found two further defects it could not
have seen.

**An offset belongs to a coupling, not to a source property.** The
charge-once rule added one release earlier was keyed `(source, property)`,
which is the right granularity for the same coupling firing twice and the
wrong one for two couplings leaving one property: both are walked in a single
pass, so the first marked the property spent and the second charged nothing,
in that step and every later one. Measured on a source moving `1.0 -> 2.0`
with `offset: 5.0` to one neighbour and `offset: 7.0` to another: the rollout
settled the second at `21.0` while `traverse`, which sets no `offsets_charged`
at all, said `28.0`. The same happened for two `transition:` blocks on one
rule sharing `from:` — measured `21.0` against `28.0` again. The charge is now
keyed by the coupling: source, target, relation type, the transition's
position on the edge, and its endpoints. The relation type and the position
are both in the key because neither is implied by the endpoints — two rules
may join one pair of entities, and nothing stops one rule declaring two
transitions with the same `from:` and `to:`.

**One declared spread is one uncertainty, however many ways it reaches a
value.** Spreads were combined in quadrature everywhere, which is the rule for
INDEPENDENT contributions and was silently applied to one declared number
arriving more than once. Three ways to arrive twice, all measured:

- two movements of one source through one coupling — `+500` then `+100` rpm
  with `gain_sigma: 0.002` settled the tank at `1.0198` where the one declared
  number says `1.2`, and two EQUAL movements were narrow by `sqrt(2)`;
- two paths to one target inside a SINGLE walk — a spread on `S -> A` reaching
  `T` directly and again through `M` gave `14.142` where `T = A + M = 2A` says
  `20.0`. This one was never a rollout defect; `traverse` reported it too;
- a seeded property later pinned by a `set`, whose two movements carry the
  forecast's doubt with opposite signs.

The walk now carries the SIGNED contribution of each independent uncertainty
source rather than one pooled variance, and the squares are taken once at the
end. Two different `gain_sigma:` lines are still two sources and still add in
quadrature — that is what `independent_declared_spreads` has always claimed,
and the stamp is now only that claim rather than also an excuse for the
arithmetic.

**The sign is half of it.** The correct quantity is the absolute value of the
SIGNED sum, not the sum of absolute values; the two agree only when every
movement pushes the same way. A source moved up by 500 and then back down by
500 leaves its target exactly where it started, and it does so for ANY value
of the gain — so the gain's spread cannot reach it and the answer is zero.
Measured before: `1.4142`. Summing absolute values would report `2.0`, further
from the truth than the defect.

**An action on a property that carries a forecast was silently discarded.**
Not reported by the reading. `seed_mode='projected'` overlaid each step's
projection AFTER the actions and re-ran every step, so a property carrying a
`dynamics:` block could not be acted on at all. Measured with a pump SET to
2500 rpm against a 200-sample random walk: `seed_mode='current'` reported the
pump at `2500.000` and the tank at `62.2840`; `seed_mode='projected'` reported
the pump at `1885.798` — its last observation — and the tank at its untouched
baseline of `50.0000`, with `throttle@pump1` in `actions_applied` and nothing
declined. The drift reconciliation then zeroed the action's own movement to
agree with that state, so the decomposition was consistent and consistently
wrong. This module's own comment already says what is wrong with that: an
action that is accepted and silently never applied is worse than one that is
refused. A projection is fitted from history and cannot know about an action
scheduled in the future, so it describes the UNMANAGED trajectory: the
forecast now governs a property up to the instant it is acted on and the
action governs it from there, and the envelope says so: a rollout that
overrode a projection stamps `projection_superseded_by_action`. `plan` was
never exposed — it pins `seed_mode='current'`.

### Corrected — `trend` widens the band and does not point it

`dynamics: {model: trend}` fits a straight line, takes the LEVEL at the last
sample, and carries the SLOPE as process noise, so its median is flat across
every horizon and a steeper fitted slope makes the forecast wider rather than
higher. Three documents said otherwise: this format's own specification said
`trend` "fits a straight line and extrapolates it", the comment beside the
return said `q` "extrapolates the line across the horizon", and an outside
reading reasoned from the word and predicted a ramp. All three describe what
the NAME suggests. The arithmetic was right and is unchanged; the sentences
are now the arithmetic's.

### Fixed — what a plan claims to have measured

Four defects on the planning surface, found by running it rather than by
reading it, and one of them was hiding the next.

**`expected_findings` is summed EXACTLY.** The objective is a sum of
`1.0 / priority_score` -- reciprocals of small integers, of which 1/3 and 1/5
have no binary representation -- so the total depended on how many findings of
which severity arrived in what order. Two consequences. The reported number
was wrong in its last bits on this package's own published example: 24
findings of priorities 1 and 3, exact cost 16, reported `16.000000000000004`.
And TWO PLANS THAT COST THE SAME STOPPED COMPARING EQUAL, which matters
because the planner sorts on `(objective, len(actions))` and its own comment
says fewer actions wins an EXACT tie -- so a tie lost to rounding is not a tie
at all, and the candidate carrying more actions wins on 4e-16 of accumulated
error. Every multiset of at most eight findings over the five reachable
weights was enumerated: 553 of them scored something other than their exact
cost, and 67 exact totals are reachable by more than one float value. The
sharpest pair, `[2,3,3,3,5,5,5,5]` against `[1,2,5,5,5,5]`, are both 23/10 and
came out `2.3` and `2.3000000000000003`. Accumulated as an exact rational and
rounded once at the end. NO TOLERANCE was introduced: deciding how close two
costs must be before the engine calls them equal is a domain question nobody
declared, and the exact total needs no such decision.

**A refused action is no longer reported as applied.** `actions_applied` holds
`template@entity`, which carries neither the parameters nor `at_s`, so two
instances of one template on one entity share a label. The list was appended
to once per INSTANCE and the refusal removed once per DISTINCT label, over a
set, so one occurrence survived a refusal that applied nothing: measured, a
step in which the pump never moved reported `throttle_pump@pump1` as applied,
in the one field a caller reads to find out what happened. Rebuilt per
instance once the refusals are known, so an instance is reported applied when
at least one property it asked for survived -- an action touching two
properties, one of which collided, still happened.

**A plan none of whose actions ran carries no score.** With `max_depth: 2` the
planner offers a second setting of a property already set at the same instant.
The rollout refuses the pair, so nothing is applied and the trajectory is the
do-nothing one -- and the candidate was scored anyway: measured on the shipped
example, three candidates with `transitions_applied: 0` and `objective: 16.0`,
which is exactly `do_nothing`'s cost, under a label naming two actions. An
earlier pass put `contradictory_actions` into those rows, which made the fact
attributable without making the number true. They are now unranked, sort to
the end, and keep their refusal. THIS FIX DID NOT WORK UNTIL THE ONE ABOVE
DID: the planner asks whether anything ran, and the field it asks was saying
yes.

**Every candidate carries its own assumptions.** `score` has always returned
them per candidate -- whether a clearance figure was sampled from a declared
spread or came from a trajectory that had none -- and they were merged into
the plan-level list with the per-candidate fact dropped. One plan carrying
both `deterministic_transitions` and `declared_gain_spread_sampled` left a
reader unable to attribute either, and `interval` does not settle it:
`[0.0, 0.0]` is what a deterministic candidate reports AND what a sampled one
reports when no sample cleared.

### Added — a ranking that says how close the call was

`expected_findings` sums a cost per finding the rollout produced, over the
single trajectory the engine simulated. A finding is a comparison against a
declared line, so the objective is a STEP FUNCTION of values the engine often
knows only to within a declared `gain_sigma:` -- and it is evaluated at the
MEDIAN trajectory, with no part of that spread reaching the figure the ranking
uses. Measured on the shipped example, throttling to 800 rpm against a
`warning: 85`:

    starts at settles at objective
      88.8 84.812 14.000
      88.9 84.912 14.333
      89.0 85.012 16.000

A tenth of a point of level moves the ranking by 12 %, while the declared
spread on that value at that step is 0.3988 -- four times the distance that
flipped it. The candidate's `interval` was `None` throughout: the doubt was
computed, carried and reported per step, then not carried into the number the
plan is ranked on.

Two additions, and NEITHER CHANGES A RANKING. A ranked plan stamps
`objective_evaluated_at_median`, so a reader of the ENVELOPE -- not only of
the guide -- knows where the figure was taken. And every candidate carries
`margin_sigmas`: the closest any imagined value came to a line it was judged
against, in units of that value's own declared spread. On the case above the
winning candidate reports `0.027`, which is the number that tells a reader
whether 14.333-against-16.000 is two findings apart or one coin flip apart.
`None` when nothing declared a spread that reached the trajectory: a distance
in units nobody declared is not a measurement.

**What this deliberately does NOT do is make the objective an expectation.**
That needs the probability of each of eight axioms firing over a trajectory,
not just a threshold crossing, and inventing it would be the engine answering
a question nobody declared. `clearance_probability` is the objective that
samples the declared spread, and it already returns an interval.

### Fixed — a coupling is graded on its own projections

`model_describe` reports, beside every declared coupling, how its own
projections fared, and its docstring is emphatic about why the denominator
travels with the figure: *a confirm rate over two graded records is not the
same statement as one over two hundred*. Two things made that denominator the
wrong number, and both were measured on the surface an AUTHOR reads about
their own declaration.

**It counted records the coupling never drove.** A value prediction is filed
per entity and property; the report resolved the entities of the rule's TARGET
TYPE and matched on the target property alone, so two rules into one property
each claimed ALL of the records. Measured with four records on
`tank1.level_pct`: `Pump-feeds->Tank` reported `graded 4, falsified 4` and
`Heater-warms->Tank` reported `graded 4, falsified 4` -- four records
producing eight attributions, with neither coupling able to say whether it was
responsible. Measured end to end, a heater whose source never moved claimed
all twelve of a pump's projections.

**It counted one trajectory as many.** A rollout files one record per step, so
twelve steps driven by one declared gain against one mirror confirm or falsify
together. Measured: `graded 12, confirmed 0, confirm_rate 0.0` from a single
rollout, while the ledger's own `episodes_n` correctly said 1. The author was
told *0 of 12 projections this coupling drove were confirmed* -- which reads
as twelve contradictions of a datasheet number and is one.

A filed value now records WHICH COUPLINGS DROVE IT, taken from the per-source
spread breakdown the walk already computes, so it costs nothing to derive and
cannot drift from what actually contributed. The report counts only its own
records, adds `episodes`, and the remedy says what it rests on -- *0 of 12
projections. from 1 trajectory*. A value driven by two couplings still
belongs to both; that is a membership test, not an equality one. Records with
no attribution are COUNTED AND NAMED under `unattributed` rather than claimed
by everyone or dropped, which is the shape `entity_type_unattributed_n`
already uses in the same ledger.

**The remedy's TRIGGER is deliberately unchanged.** Deciding how much evidence
is enough before doubting a declaration is a domain question, so the engine
reports the evidence and the author weighs it -- the same line every other
learned quantity in this package sits on.

### Fixed — a calibration that says how many trajectories it saw

A rollout files one value prediction per step per property, so a 12-step
rollout of one coupled property files 12 records. They are ONE trajectory: the
same declared gain drives every step, the predicted values come off one curve,
and the mirror either tracks it or does not. Measured against a mirror in
which the tank never moved, `confirmed 12, falsified 0, confirm_rate 1.0,
brier 0.0025`; against one drifting 2.0 per step, `confirmed 0, falsified 12,
confirm_rate 0.0, brier 0.9025`. All or nothing both times, because there was
only ever one trial -- and a reader given `1.0 over 12 records` reads twelve
successes.

`confirm_rate` and `brier` are the figures that answer whether this engine's
projections can be trusted, and the ledger is otherwise emphatic about exactly
this class of mistake: *coverage_90 over four records and over four thousand
are different statements*. It already carried the field that fixes it.
`PredictionRecord.traversal_id` means THE EPISODE THIS CAME FROM, and
`record_impacts` has always used it that way -- one id per traversal, shared
by every impact. The rollout passed none, so a fresh uuid was minted per
record and twelve steps of one trajectory looked like twelve unrelated
episodes. The same call let `predicted_at` default to the moment each row
happened to be written rather than the instant the rollout was run for.

A rollout now stamps one episode id on everything it files, and
`calibration()` reports `episodes_n`: how many distinct episodes its graded
records came from. It is an UPPER BOUND on independence and not a claim of it
-- two rollouts of one entity over overlapping horizons are two episodes and
still correlated -- but it rules out the case that is purely an artefact of
how the engine files. `None` rather than 0 when nothing has been graded, on
the same rule every other aggregate there follows.

### Documented — when two spreads add, and how

The rule was implemented one release earlier and stated nowhere. Contributions
from the SAME declared number add LINEARLY and with their signs: one coupling
walked at two movement instants, or one spread reaching a target by two paths.
Contributions from DIFFERENT declarations add in quadrature, which is what
`independent_declared_spreads` has always meant. Two pumps feeding one tank
under one rule are two couplings and two gains -- the datasheet tolerance
describes a population and each pump is its own draw from it -- so they
combine in quadrature; the same pump throttled twice is one gain, so its
contributions add.

### Compatibility

All of the above are patch-legal under COMPATIBILITY.md: counts that were
wrong become right, a decline fires where the engine was silent, and
`horizon_s`, `gain_sigma:` and `file_predictions` are additive with their
previous behaviour as the default. **One behaviour does change rather than
extend**: `value_mode="projected"` and `seed_mode="projected"` now refuse an
indicator with no `dynamics:` instead of curve-fitting it. That is a silent
wrong answer becoming a named refusal, which COMPATIBILITY.md allows a patch
to do — and the refusal is the one the `project` verb has always made on the
same question. No verb, envelope key or `problem_type` was
removed or renamed.

**The second reading's two fixes also change answers rather than extend
them**, and both are the same permission: a wrong number becoming the right
one. A rollout that moves one property twice at different instants returns a
different trajectory, and it is the declared one. A rollout seeded from a
forecast whose median equals the live reading now runs its declared couplings,
carries the forecast's band to their targets, and counts the seed as driven
rather than filing it as its own prediction — so `transitions_applied`,
`values_driven`, `predictions_filed` and `values_without_tolerance` can all
move for an unchanged model. The calibration figure read off that ledger moves
with them, and moves toward being about the engine's forecasts rather than
about `project`'s.

An earlier draft of this paragraph said a model declaring no `gain_sigma:` and
a caller not asking to file got byte-identical answers to 0.2.4's. That was
true when it was written and both of the fixes above falsify it, since neither
needs a declared spread to bite. It is corrected rather than deleted: this
file's own subject is claims that stop being true while nobody re-reads them.

**Retiring `clamp_to_bounds` is patch-legal, and the reason is that it never
did anything.** No behaviour changes, because nothing read it; what changes is
that declaring it now appears in `unread_fields` instead of being stored and
forgotten, which is *a check firing where the engine was silent*. The YAML key
is the surface that mattered, and it was documented only as a commented line.
The dataclass attribute went with it: `Transition` is not one of the fourteen
curated exports and is reachable only on a deep path, so a consumer reading
`transition.clamp_to_bounds` was reading an engine internal that was already
telling them nothing. Removing an INDICATOR field still waits for a major
release; this is not one, and the distinction is the wire shape rather than
the word *field*.

---

**The third reading.** All patch-legal, and two of them change answers rather than adding anything.

A model that declares an `offset:` on more than one coupling from one property
gets a different number from a rollout than it did, and the new one is the one
`traverse` was already reporting. A model that declares a `gain_sigma:` gets a
different spread wherever the same declaration reached a value more than once:
WIDER when the movements agree in sign, narrower or zero when they oppose. A
model whose rollout sets a property that carries a `dynamics:` block gets an
answer where it previously got its own baseline back. In all three the
previous number was wrong, and no model that declares none of those things
moves at all.

`TraversalResult` gains `imagined_spread`, the per-source breakdown
`imagined_sigma` is the root of the sum of the squares of. It is additive, and
its keys are opaque and only ever compared for equality.

**The planning surface.** All patch-legal. A model using `expected_findings`
gets an objective that differs in its last bits from the one it got before,
and the new one is the exactly-rounded value; where that changed a ranking it
changed it toward the documented tie-break rather than away from it. A
candidate whose actions were all refused now reports `objective: null` where
it reported a number it had not measured, and `PlanCandidate` gains an
`assumptions` list, which is additive.

**The ledger.** `calibration()` gains `episodes_n`, which is additive, and a
rollout's filed records now share one `traversal_id` and one `predicted_at`
instead of carrying one each. Nothing that reads a record by id or grades one
changes: the maturity window is `predicted_at + horizon_s`, and the instants
differed by microseconds.

**The coupling report.** Additive and patch-legal. A coupling's `projections`
block gains `episodes` and `unattributed`; `PredictionRecord` gains
`couplings`, which a rollout fills and every other filer leaves empty. A
coupling that never drove a record stops reporting that record's verdict as
its own -- a number that was wrong becoming absent rather than wrong.

**The ranking.** Additive. `PlanCandidate` gains `margin_sigmas` and a ranked
plan on `expected_findings` gains one assumption stamp. No objective value and
no candidate order changes.

## [0.2.4] — 2026-09-18

### Fixed

- **The MCP server raised at construction whenever the SDK was installed.**
  `rollout` and `plan` were added to `TOOL_SPECS` and to `_HANDLERS` in 0.2.3
  and not to the wrapper table, so `build_server()` hit its own guard —
  *TOOL_SPECS declares ['plan', 'rollout'] with no wrapper to register* — and
  the `mcp` extra was unusable for the whole of 0.2.3. `dispatch` served both
  verbs correctly the entire time; only the transport could not.

  **The guard was right and fired too late.** Constructing a server needs the
  optional SDK, so the only lane that could reach it was the one installing the
  extra: every other lane skipped the transport test and reported green. 0.2.3
  was verified locally at 1660 passed / 14 skipped and was red in CI at 1668
  passed / 5 skipped. The skip COUNT was the only available signal and nothing
  compares it across lanes.

  `test_every_declared_tool_has_a_wrapper.py` now reads the wrapper table with
  the AST instead of importing it, so a declared tool with no wrapper fails on
  EVERY lane without the SDK present. Installing the extra everywhere would
  have made an optional dependency required in all but name, which is the
  measured two-dependency claim this package keeps.

---

## [0.2.3] — 2026-09-18

**The first MINOR, and it is not numbered 0.2.0.** `arbiter-engine` stayed on
`0.1.x` by decision through eighteen patch releases; `rollout` and `plan` are
new verbs on `api`, and COMPATIBILITY.md has always said that is a minor.

**0.2.0, 0.2.1, 0.2.2 and 0.3.0 were all skipped because all four are
unavailable**, not because anything was wrong with any of them — see
[Version numbers that do not exist](#version-numbers-that-do-not-exist). PyPI
permanently reserves any filename it has ever served and had deleted, including
under an earlier owner of the name, so an upload returns `400 This filename was
previously used by a file that has since been deleted`. The same reason the
sequence runs 0.1.1 to 0.1.4.

That section predicted this release and named the wrong number: it said *the
version that first breaks compatibility cannot BE 0.2.0. so it will be
0.2.1.* 0.2.1 was an INFERENCE from three measured numbers, and it was wrong —
as were 0.2.2 and 0.3.0 after it. Three uploads were refused before one landed,
and the reserved set turned out NOT to be contiguous: 0.3.0 is taken and 0.2.3
was free. An upload is the only oracle — a 404 does not mean a filename is
free — so no amount of reading could have ordered these, and nothing shorter
than trying them would have found it.

Every consumer pinning `<0.2` must move its ceiling to `<0.3` to see this —
that is the ceiling doing its job, not breaking.

**A design note proposing a world model, reproduced before any of it was
built.** The note is a five-stage proposal; every claim it makes about current
behaviour was re-derived against the tree first. Sixteen were confirmed. Three
defects it did not know about were found by running the paths it describes, and
two of those would have made its own Stage 1 unreachable from the published
surface.

### Fixed

- **A declared floor was invisible to `traverse`.** `lower_warning:` and
  `lower_critical:` are schema, read by `UnifiedAxiomReasoner`, and were never
  read by the topology builder — so they never reached the traversal's
  `AxiomState.evidence` and the traversal had nothing to compare against.
  Measured on the shipped `water_tank.yaml`: `check` on a pump below its stall
  floor reported `below_critical_threshold:speed_rpm`; `traverse` on the same
  entity reported nothing, while its `checked.invariants` said two invariants
  had been evaluated. One declaration, two verbs, opposite answers, and the
  denominator asserting the check had happened. An internal ruling fixed this shape for
  the ceiling half and left the floor half in it.

- **Every declared `temporal:` block was dropped on the published surface.**
  There are two topology builders; the one `api` uses did not read
  `relationship_rules`. Measured on a rule declaring 120s / 600s / 0.9: the
  edge carried 60.0 / 60.0 / 1.0 — three silent defaults — and reported
  `EdgeSource.AUTO_DISCOVERY`, the engine telling a reader that nobody had
  declared an edge the author had declared. An author could write a temporal
  block, traverse through `api`, and get the same answer as an author who
  wrote nothing. Third instance of the shape and each fixed
  one parameter of.

### Added

- **`transition:` on a relationship rule** — which property drives which, and
  by what steady-state gain, with the provenance of the number. `traverse` in
  a value mode now reports what a downstream value BECOMES rather than only
  which entities are reachable. All four keys are required and a partial block
  is refused by name, never completed with a default.

- **`rollout`, a tenth verb on `api` and a thirteenth MCP tool** — the model
  stepped forward under actions, with the eight axioms evaluated over every
  imagined state and an imagined history written as it goes, so the temporal
  axioms can be asked. The clone is private: no imagined observation reaches
  the session. A rollout carrying actions reports `tier: 3` and never
  dispatches.

- **`action_templates:` in the open schema** — the effect model only. Which
  entity property a parameter writes, and whether it sets, adds or scales. The
  policy gate and the approval chain stay outside the open engine.

- **`plan`, an eleventh verb and a fourteenth MCP tool** — candidate actions
  ranked by rolling each one forward, against an objective the MODEL declares
  under `planning:`. Without a declaration every candidate is still evaluated
  and none is ranked. Doing nothing is always a candidate, ties break toward
  fewer actions, and nothing is dispatched.

- **`candidates:` on an action parameter** — what values a planner may try.
  Declared, because sweeping a range the author never wrote would be the
  engine choosing the operating envelope.

- **A durable prediction ledger.** `SqlitePredictionLedger` subclasses the
  in-memory one and changes exactly one thing: where records live between
  processes. This closes the boundary README.md names — *treat calibration as
  out of reach until the ledger is persistent* — so a one-shot process can now
  file predictions and a later one can grade them. The ring cap still applies
  to the file, deliberately: a store that kept everything would make the
  calibration denominator depend on when the process started.

- **`gain: estimate` and fitted gains as proposals.** An author declares the
  COUPLING and withholds the number; the engine fits it and reports it under
  `model_describe.proposed_transitions` with `n`, r-squared and an interval. A
  transition carrying it projects nothing and declines `gain_not_adopted`
  until a number is adopted. Where a gain IS declared and the interval
  excludes it, the disagreement is reported with both numbers and the
  declaration is not touched. The engine never searches for which properties
  are coupled.

- **`payload.simulation`** — the simulation's own denominators beside the
  generic legs and never summed into them: transitions attempted against
  applied, steps requested against completed, the values with their provenance
  and the edges they came through, and the engine's assumptions stamped.

- **A `simulation` decline vocabulary**, including `missing_dynamics` for an
  edge that declares no transition and `budget_exhausted`, which is reported
  ONCE carrying the count of what it skipped.

- **`not_a_producers_submission`, a `shadow` decline.** Records carrying a
  `source` are not a producer's submission, so the eight axioms do not run
  over them. That exclusion is correct and was the one silent skip in
  `shadow_entities` — every other files a decline. A batch that was entirely
  stamped therefore produced `checked {entities: 0}` beside `not_checked []`:
  a zero denominator with nothing saying why, which a reader cannot
  distinguish from a clean run. Reported ONCE with the count and the SOURCE
  NAMES, on the `budget_exhausted` precedent — the engine stamps its own
  projections every cycle, and a per-record decline would bury the
  interesting case under them. The names are what matter: a bridge author
  finds their own `model_id` in the list and learns why their shadow leg is
  empty. Patch-legal; a check that speaks where it was previously silent.

### Changed

- **A warning-severity finding is reported on every surface that reports
  findings.** `DetectionResult` carries findings in two legs, `problems` and
  `warnings`; `check` has summed them since it was written, and three readers
  in the published cut took the first only. Measured: a model declaring
  `warning: 80` and `critical: 95`, given a forecast of 98, produced
  `forecast_threshold_exceeded`; given a forecast of 85 it produced NOTHING,
  with no decline saying why. The shadow pass — *the eight axioms over the
  forecast itself* — was checking one severity. `forecast/shadow.py` and
  `twin/monte_carlo_predictor.py` are both fixed. Patch-legal: a check that
  fires where it was previously silent, and the silence was a defect.

- **Findings drawn from imagined values are prefixed `imagined_`.** See
  COMPATIBILITY.md; this is patch-legal and is the rule that stops a
  simulated breach reading as a live one.

- **A declared transition is no longer pruned by an undeclared reachability
  probability.** `propagation_probability` is P(target fails | source fails)
  and is 0.3 when nothing has been learned; a transition is a declared
  coupling between two values. Multiplying them silenced a declared gain three
  hops out — 0.3³ = 0.027 against a `min_probability` of 0.05 — with nothing
  said. Undeclared edges prune exactly as before.

### New public constants, on deep paths

Named here because `release_note_surface.py` requires it and the requirement is
the point: these are importable, so a reader can come to depend on one, and
COMPATIBILITY.md says a deep path may move without a major version. A name that
moved and was never written down leaves that reader with a `NameError` and
nothing to search for.

- `twin.topology.REQUIRED_TRANSITION_KEYS`, `twin.topology.ESTIMATE_SENTINEL` —
  the four keys a `transition:` block must carry, and the token that declares a
  coupling while withholding its magnitude.
- `twin.traverser.IMAGINED_PREFIX` — what a finding drawn from an imagined value
  is prefixed with.
- `twin.actions.EFFECTS`, `twin.actions.REQUIRED_TEMPLATE_KEYS` — the three
  effect kinds an action template may declare, and its required keys.
- `twin.rollout.MIN_STEP_S` — the floor under a rollout step.
- `twin.planner.OBJECTIVES`, `twin.planner.DEFAULT_MAX_DEPTH`,
  `twin.planner.DEFAULT_MAX_ROLLOUTS` — the two objectives a model may declare
  and which direction each is optimised in, and the search bounds.

---

## [0.1.18] — 2026-09-18

**A fourth static review, reproduced item by item before anything was changed.**
Eight findings and eight trivia, all sixteen confirmed. One claim in the report
was refuted and it was not a finding: the report recorded 0.1.17 as absent from
PyPI at 05:50Z and 06:05Z, and the files had been live since **05:18:08Z** — the
project page it fetched was stale for the better part of an hour, which is the
same surface-disagreement this project has measured four times and the reason a
single endpoint is never evidence that a release is or is not live.

Two of the sixteen were worse than filed, and both are about a test rather than
the engine: the `discover` half of the 0.1.17 history fix passed against a
*total* revert to the raw store, not merely a partial one, and the published
"typo" turned out to be produced by the scrub rather than written by anyone.

### Fixed

- **A discipline that raised came out of the verb.** `subenvelope.py` carries
  `internal_error` in all five vocabularies on the argument that *a discipline
  that raises where it could have declined turns one unanswerable cell into an
  unanswerable pass*. Nothing produced it: measured on `project`, `discover`,
  `check`, `entail` and `infer`, an exception inside the discipline propagated
  straight out. Each verb now has a boundary returning a sub-envelope with
  `source: unavailable` and one `internal_error` decline carrying `repr(exc)`.
  The axiom layer already did this (`checker_error`), and so did `traverse`
  after 0.1.16; this is that rule applied one level up.

- **Six decline reasons had no producer.** `no_tolerance`, `unobservable_state`,
  `filter_not_converged`, `stale_observation` and `horizon_exceeds_validity`
  are **withdrawn**, with the note the file already uses twice for the same
  reason — *a member no input can reach makes the set a worse instrument.* Four
  of them named a state this filter does not compute; `no_tolerance` named a
  point prediction, and a `mean` with no `sigma` is refused by the forecast
  contract before any decline exists. `internal_error` is the sixth and is
  wired instead of withdrawn. A test now derives the check: every member of
  every vocabulary must have a producer somewhere in the package.

- **`alignment()` had no reader, and MODELING.md promised what it computes.**
  The guide says a too-tight `align_tolerance` is distinguishable from an
  operand feed that stopped, because *the decline says how many points each
  operand had and how many survived*. Measured: both produced byte-identical
  `insufficient_samples` declines with `n: 0`. The figures now ride on the
  declines in `run_projection`, `run_discovery` and — through
  `sampling_context`, which all four temporal axioms already call — the axiom
  layer. A 1s tolerance against operands 30s apart now reports
  `operands {inlet_c: 40, outlet_c: 40}, aligned 0`; an operand never fed
  reports `outlet_c: 0`.

- **`checked.engine_projections` counted a caller's rows as the engine's.** The
  split shipped in 0.1.17 alongside the change that let a caller stamp a
  `source`, and the two were written against each other: anything sourced that
  was not the random walk was called an engine projection. Measured: a session
  in which `project` never ran reported `engine_projections: 1`. All three
  counts are now source-scoped and **partition** `reference`, with
  `caller_references` added for the third population rather than folding it in.

- **An empty `source=` made a caller a producer.** `str(source) if source else
  None` folded `""` to `None`, and `None` is the producer predicate — so a
  falsy source silently put a caller's rows back into the population the
  parameter exists to keep them out of, judged by the shadow axioms and able to
  raise an audit's exit code. Now `is not None`.

- **A replay counted names the store cannot hold.** `readable_properties()`
  answers *what does the model read*, which correctly includes a derived
  indicator's own name; the replay loop asks the narrower *what can be
  restored*, and a derived name is never in the store by construction. It
  counted `absent` once per entity per step, against a floor nobody could
  reach.

- **The derived join parsed its expression once per point.** Cheap while one
  reader took that path; 0.1.17 put five on it.

### Added

- **`api.ingest_forecasts`, `api.feed_model_figures`, `api.model_figures` and
  `api.as_of`.** `api` is one of the fourteen supported names;
  `arbiter_engine.forecast` and `arbiter_engine.clock` are not, and the README
  says a deep path may move without a major version. The first bridge built on
  this engine reached through both, because the flagship example is about a
  forecast arriving from outside and there was no supported spelling for
  sending one. Re-exported, not moved: the deep paths keep working.

- **BRIDGES.md documents the forecast ingest path** — the record shape, the
  three distribution forms, `source=`, the full `raced` vocabulary, the
  history-before-ingest ordering, and what a one-shot process cannot reach.
  None of it was documented on any published surface: `issued_at`, `horizon_s`
  and `quantiles` appeared in no `.md` outside this file.

### Changed

- **The scrub closes a mixed punctuation seam.** Removing an internal reference
  from *(the scope ruling holds the platform, per CD-N; the server holds
  neither)* left `platform,;` in the **shipped 0.1.17 wheel**, where an outside
  reader filed it as a typo. The existing repair collapses a repeat of one mark
  and this is two different ones. Narrow on purpose: `,;` only, because `, :`
  is a numpy slice.

### Corrected

- **`raced` defines seven reasons, not the five the 0.1.17 entry claimed.** All
  seven are now written down in BRIDGES.md, which is the first time the
  vocabulary has appeared anywhere but the code. Two of them —
  `no_entity_or_model` and `no_such_indicator` — are unreachable through
  `ingest_forecasts`, which resolves both before filing.

- **The shipped example's `margin_requirement` comment, for the third time.**
  0.1.17 replaced one false mechanical claim with another: that declaring the
  indicator is what carries the series, lets a replay restore it, and gives
  `unconsumed_observations` a denominator. Measured with and without the
  declaration — the store holds the same readings, `readable_properties`
  contains it either way (0.1.17's own fix put it there as a threshold source),
  the replay restores the same value, and neither report mentions it. What it
  actually buys is the line above it: an entry in `model_describe`, which is a
  statement of intent and not a mechanism.

- **Three stale counts.** The MCP shim's docstring said *all five tools* while
  registering twelve; `api.py`'s own section heading said *the five tools* over
  nine verbs. Both now name the thing instead of counting it, and the README's
  tool count, verb count and spelled-out name split are derived by tests —
  the count test matched digits only, and the same paragraph states the split
  in words.

## [0.1.17] — 2026-09-18

**A third static review, reproduced item by item before anything was changed.**
Thirteen findings, all thirteen confirmed, four worse than filed, none refuted.
The previous round refuted two of nineteen; this one refuted none, and it also
withdrew a finding of its own from the round before — which is the first time a
report here has corrected itself.

### Fixed

- **Four verbs read the feed; `check` read the model.** `project`, `discover`,
  `traverse` and the random walk filed beside an ingested forecast took
  `session.history` directly, so a declared `calendar:` and a `derived:`
  indicator changed the answer for one verb and not the others. Measured on a
  three-day series at 10:30 inside a 09:30–16:00 session: `lookback: 4h` reached
  06:31 through the store and the previous afternoon through the view. On a
  derived indicator the gap was total — `project` declined `insufficient_samples`
  with `evidence {"n": 0}` while the view could join 200 readings, so the
  evidence was not a shortfall but a false count. All five readers now take
  `EngineSession.reading_history()`.
- **A partially resolved band was projected against and not declined.**
  BOUNDEDNESS and the shadow breach check decline whenever ANY declared bound
  fails to resolve; `project` declined only when NONE did. An indicator with a
  literal `critical` and an unresolvable `{from_property:}` floor therefore got
  breach probabilities against the ceiling and silence about the floor. Now all
  three readers decline together, in the resolver's own words. This is the
  *decline where a guess was previously answered* clause of the compatibility
  policy, and the measurement is the reason.
- **Three reports disagreed about which properties a model reads.**
  `unread_properties` counted indicator names, derived operands and
  `{from_property:}` sources; `unconsumed_observations` counted only the first,
  so one report called a fed bound-source `undeclared_property` while its
  sibling counted it as read. `sync_current_from_history` iterated indicator
  specs, so **a replay never advanced a per-instance floor at all** — every step
  after the first checked a moving balance against step one's bound, silently,
  because the bound still resolved. One definition now
  (`EngineSession.readable_properties`) feeds all three.
- **A caller's own reference forecaster was judged as a producer.**
  `ingest_forecasts` now takes `source=`; a record filed with one is kept out of
  the producer counts and out of the shadow axiom pass, as the engine's own
  projections already were. Measured downstream on `margin-book-audit`: a clean
  three-account book exited 0 with `findings 0`, and 1 with `findings 6` — three
  of them `forecast_below_critical_threshold` at severity **critical** — purely
  because a reference forecaster was switched on.
- **`forecast:` block keys were not validated.** A misspelled `expected_from`
  reported `missing_property` on `forecasts_expected`, sending the author to look
  at their feed for a figure their model had caused to be absent. The block's
  keys are now checked like an indicator's, with `did_you_mean`. `dynamics:` is
  deliberately still not checked this way: its keys belong to the model.

### Added

- `checked.baselines` and `checked.engine_projections` in the forecasts leg.
  `checked.reference` counts both and its name reads as though it counted
  yardsticks only; it keeps its meaning and its value, because renaming a key a
  reader is already looking up is not something a patch release may do.
- `raced` in the `ingest_forecasts` report: one row per filed forecast saying
  whether it got a yardstick and, when it did not, which of five reasons.
  `baselines: 4` out of six told a desk the shortfall and not which two, nor
  whether to declare a `lookback:`, feed more history, or read a fit failure.
- A test deriving the README's supported-name count from `arbiter_engine.__all__`
  — **the README has claimed since 0.1.16 that this test existed, and it did
  not.** The count was right only because someone had retyped it.

### Documentation

- **The prediction ledger is in-memory, and the README now says so where the
  limit bites.** `grade_matured` scores a record only if it is still in the live
  session's ledger when its horizon passes, so a one-shot process cannot answer
  *did it beat a random walk* — and feeding already-matured forecasts is declined
  `stale_forecast`, because the leg asks whether a producer is current and cannot
  tell late from here-to-be-scored. Stated rather than fixed: a durable ledger is
  a new public surface with its own compatibility promise.
- **`.github/PUBLISH_FROM_CI` described a publish path the releases did not
  take.** It read *no API token is stored anywhere; the index mints a short-lived
  one per run*. PyPI's own file metadata shows 0.1.14, 0.1.15 and 0.1.16 uploaded
  without Trusted Publishing, by `twine` from a maintainer's machine, because the
  reviewed environment gate had not been clicked. The file now separates the path
  that exists from the path those releases took; the guard behind them is
  `verify-tag-artifact.yml` comparing the index against the tag after the fact,
  which is a real check and a weaker one.
- The README's MCP sentence read *the same five … not part of the eleven*: the
  server exposes twelve tools and the package exports fourteen names.
- `clock.py`'s docstring still described the lower-bound-only window 0.1.16 fixed;
  the schema's description said `dropped_declarations` comes from `check` only,
  which 0.1.16 also changed; and the shipped `margin_book.yaml` explained its
  `axioms: []` indicator as existing so a bound had somewhere to be read from,
  which was never true — it was a workaround for the two reports above.

## [0.1.16] — 2026-09-17

**Everything below was found by RUNNING 0.1.15, against a static review of it
that ran nothing.** That is worth stating once because of what the two passes
found: the review's five high-severity items were all real, three of them were
worse than filed, one more defect turned up only when the first fix was
executed, and its headline claim -- that the published 0.1.15 cannot start its
MCP server -- was false, because the tag was re-cut at the fixed commit and the
wheel on PyPI matches it byte for byte. Reading found the defects; running is
what settled which of them existed.

### Fixed

- **A forecast check that refused to answer said nothing.** `run_forecasts`
  composed the shadow run, took its `findings`, and dropped its `checked`, its
  declines and its questions on the floor. Through `check` a consumer therefore
  never saw `no_threshold`, `no_report_probability`, `tail_not_declared`,
  `undefined_for_values`, the `missing_property` for a forecast with no median,
  or any axiom decline raised on a forecast. Measured on a model with no
  `dynamics.report_above`: the shadow run declined twice and
  `check(...)["forecasts"]["not_checked"]` was the empty list -- which reads as
  *the forecast was compared against its bound and nothing was wrong*, when
  nothing had been compared. The shadow sub-envelope is now mounted whole, as
  `payload["shadow"]`, beside the forecasts leg. The two vocabularies stay
  separate; the findings still climb into `forecasts`, so a reader written
  against the old shape keeps working.

- **`project` could not read a `{from_property:}` bound, and neither could the
  forecast axioms.** The projection runner read the four literal threshold
  slots, which a per-instance declaration leaves `None` -- so every entity
  declined `no_threshold` with the sentence *no declared line says what would
  count as breaching it*, which is false of a model that declares one.
  `examples/margin_book.yaml` declares exactly that shape, so the flagship
  example could never report a `projected_breach` for any account. Both now
  resolve through `effective_thresholds` and decline in the resolver's own
  words when a declared bound cannot be found.

  The second half was found by running the first fix. The shadow check already
  called the resolver, and called it against the SYNTHETIC entity, which carries
  forecast medians and nothing else -- so one cycle produced a correct breach
  probability and a refusal to judge the same declaration. The RESOLVED NUMBER
  now travels onto the shadow entity rather than the source property: copying
  the property across would put an observed present value on a forecast entity,
  judged by its own axioms and reported under the `forecast_` prefix as though
  somebody had predicted it.

- **A window ended NOW only at one end, so every replay step saw its own
  future.** `get_values` and `get_states` in both stores computed
  `now_utc() - window` and applied that cutoff alone. The replay recipe in this
  file -- feed the history once with real timestamps, then step the clock --
  therefore handed each step every reading stamped after it. The threshold
  axioms answered as-of the step while STABILITY, HOMEOSTASIS's baseline,
  MONOTONICITY, CONSERVATION over a series and every `project` lookback saw the
  whole run, and the step looked entirely plausible. Four tests asserted the
  lower cutoff follows the clock; none placed a reading after the frozen
  instant.

- **The engine's own forecasts were judged as if a producer had sent them.**
  `project` files under `<model>:<source>` and its reference under
  `baseline_rw`, and the `forecasts` leg read every distribution record as an
  outside submission. A model declaring `models:` therefore declined
  `model_unknown` for the engine's own two records, and once past `max_age`
  declined `stale_forecast` too. Worse, and invisible by reading: those records
  also counted as ARRIVED, so a pair whose forecaster sent nothing reported
  `expected: 1, received: 1` and no `forecast_missing`. An expectation nobody
  met read as met -- the one shape that leg exists to refuse, produced by the
  leg itself. `PredictionRecord` now carries `source`, set by the filer, and the
  split is by that field rather than by the shape of an id.

- **`calendar:` was declared, parsed, stored and read by nothing.**
  `MODELING.md` says declaring one makes `window: 1h` mean an hour of OPEN
  time. It did not: `CalendarHistory` existed, was exported, and nothing joined
  it to the session, so the promise held only for a caller who built the
  wrapper themselves -- which needed the domain parsed a second time, because
  `load_model` runs after the session is constructed. `unread_fields` did not
  report it either, so the engine's own reachability report said the
  declaration was read. `_history_for` now wraps the store when the model
  declares a calendar, inside the derived view so operands and joins share one
  clock.

- **`model_describe` did not carry `dropped_declarations`.** `check` has
  carried it since it was added; the verb whose entire question is *did my
  model load the way I wrote it* did not -- so a reader proofreading a
  generated model through the describe payload got a clean answer from a key
  that was never there. Measured on a downstream bridge: its read-back looked
  for exactly this and reported nothing dropped for a model with a misspelled
  axiom AND for one with an unreadable `{from_property:}` mapping.

- **A `{from_property:}` source counted as a property nobody reads.**
  `unread_properties` built its readable set from indicator names and derived
  operands and not from `threshold_sources`, so an author feeding the bound's
  source was told nothing reads it. The only way to silence that was to declare
  the source as its own `axioms: []` indicator -- which both the shipped example
  and the margin-book bridge were doing. A report that trains authors around
  itself is not a report.

- **A forecast of a DERIVED indicator was always `ungradeable`.** `check`
  handed `grade_matured` the bare store rather than the view the axioms had
  just read, and a derived series exists only through the view. Every such
  record matured with nothing to score against, so the producer looked
  unscoreable rather than unscored.

- **The changelog over-stated the Granger bug's reach**, and the entry under
  0.1.15 now says so: no published release contained any Granger code.

- **The README's supported-name count said 11 for a release with 14**, eight
  paragraphs below the list of fourteen.

### Added

- **A random walk is now filed beside a forecast that arrives from OUTSIDE**,
  not only beside the engine's own projections. *Does it beat a random walk* is
  the question a forecast is judged by, and the yardstick was being kept for
  the one kind of forecast nobody needs it for. It is fitted under the
  producer's own `issued_at`, so the reference sees what the producer could
  have seen and not one reading more -- fitted to the present it would be shown
  the outcome it is being compared on, and would win. `ingest_forecasts`
  reports how many it filed, because a pair with too little history gets none
  and *this model did not beat a random walk* must not read the same as
  *nothing ran a random walk*.

- **`checked.reference` on the `forecasts` leg**, counting the engine's own
  records now that they are excluded from `received`, `graded` and `pending`.
  Excluding them silently would leave *no reference was filed* and *references
  were filed and hidden* reading identically.

- **`PredictionRecord.source`, and `SOURCE_ENGINE` in
  `projection.projector`.** The filer says who issued a forecast, because
  nothing can recover it afterwards and the alternative was reading a naming
  convention as a fact: `project` files under `<model>:<source>` and its
  reference under `baseline_rw`, and matching on the shape of those strings is
  the name-heuristic class removed from three axioms. `source` is `None` for
  every caller that predates the field, which is what they all were: outside.

- **`forecast: {expected_from: [...]}`, an OBLIGATION list.** `models:` is an
  allow-list and was being read as an obligation, so `forecasts_expected` on
  the forecaster charged every PERMITTED producer with every subject. Measured
  on `examples/margin_book.yaml`, which permits two models for six accounts:
  both were reported 50% and 83% short of a debt nobody had declared, at
  severity `high`. A desk naming five permitted models would have had four of
  them delinquent by construction. Without `expected_from:` the figure is
  absent and CONSERVATION declines `missing_property` -- *nobody said who owes
  a forecast* is reported instead of a number invented to fill the gap. This
  is the engine's own rule arriving on its own doorstep, and a wrong finding is
  worse than a missing one.

- **`$defs/sub_envelope` in the envelope schema**, and a section in
  COMPATIBILITY.md describing it. The shape shipped in 0.1.15 with neither, so
  a downstream reader had nothing to validate against.

- **A test that loads and runs every shipped example.** Nothing did. Five files
  ship as the documentation of how to write a model, two of the defects above
  live in `margin_book.yaml`'s own declared shape, and every unit test around
  them passed -- because they call the internal functions directly, and each of
  these defects lives in the composition.

## [0.1.15] — 2026-09-17

**The largest release in this line, and the one that finishes the shape.** Four
disciplines now sit beside the eight axioms, each with its own denominator and
its own closed vocabulary of refusals; the engine forecasts, scores forecasts
that arrive from outside, and judges the forecaster by the same eight axioms as
anything else. A declared bound can differ on every instance, which ends the
one-entity-type-per-unit workaround three shipped surfaces still described as
forced.


### Added

- **`project`, a sixth primitive, and the `projection` sub-envelope it reports
  in.** The eight axioms judge what has been observed; this forecasts a declared
  numeric indicator forward and reports the probability it crosses a declared
  line. It rides as a payload key beside the legs rather than inside them,
  because a discipline's refusals have no axiom to name and the top-level
  `not_checked` record requires one. Its denominator — `series_seen`,
  `forecasts_issued`, `observations_assimilated` — is counted in units
  projection owns and is never summed with `checked.invariants`, which this verb
  reports as 0.

- **`dynamics:`, `horizon:` and `lookback:` on an indicator.** `dynamics:` names
  the model and carries its parameters; the other two say how far ahead to
  forecast and how much history to fit on, falling back to the caller's horizon
  and the indicator's own `window:`. Read by `project` and by no axiom, which is
  why declaring one does not oblige you to declare an axiom that reads it.

- **Two models, `local_level` and `trend`, named by `LocalLevel.name` and
  `TrendCurve.name`.** `local_level` is a random walk seen through measurement
  noise: declare `q` (variance per second) and `r` (variance of one reading), or
  omit both and they are estimated from the series, in which case the forecast
  carries `source: estimated_parameters` instead of `declared_model`. `trend`
  fits a straight line and extrapolates it — available by name, and deliberately
  NOT the default, because extrapolating a fitted line states a direction for a
  series that may have none. `SOURCE_DECLARED`, `SOURCE_ESTIMATED` and
  `SOURCE_CURVE` are the three values that field takes.

- **`report_above`, and the rule that there is no finding without it.** The
  engine will compute that a series has a 31% chance of breaching, and it will
  not decide whether 31% is worth acting on — that depends on what a breach and
  a false alarm each cost, which are facts about the engagement. Without
  `dynamics.report_above` the probability is measured, reported on the decline
  that says why no verdict was reached, and filed for grading; no finding is
  invented. This is *a floor is a specification, not a guess*, applied to a
  probability.

- **Three `projection` decline reasons beyond the shared ones**:
  `no_report_probability`, `no_lookback` and `model_missing`. Each names a fact
  the author can supply. `MINIMUM_SAMPLES` and `NIS_BAND` are the two thresholds
  the projector refuses on — the sample floor, and the innovations band outside
  which the declared parameters do not describe the series. Both decide only
  whether the engine REFUSES, never what it asserts, and the measured value
  rides in the decline.

- **`arbiter_engine.subenvelope`**, the four-leg shape one level down, with a
  closed decline vocabulary per discipline. Shipped now because `projection` is
  its first producer.

- **A per-session prediction ledger**, `EngineSession.ledger`, unconditional and
  isolated rather than the environment-gated process singleton; distributional
  records scored by pinball loss and 90% coverage, with `by_model` and
  `by_horizon` strata. Every rate is reported beside the count it was computed
  from, and is `None` rather than `0` before anything has been graded — a zero
  there reads as perfectly calibrated for a model nobody has looked at.

- **`EngineSession(history=...)`**, because the default is a seven-day ring and
  a replay needs longer.

- **`arbiter_engine.clock.as_of`**, which reads every window, retention cut-off
  and grading deadline in the engine as a fixed instant for the duration of a
  block. A context variable rather than a module global, so freezing the clock
  for a backtest does not move a concurrent caller's windows.

- **`TOOL_SPECS` gains `project`**, which takes an optional `horizon_s`.

- **`discover`, a second discipline, and the `discovery` sub-envelope.** Tests
  which declared numeric series PRECEDES which, challenges the edges the model
  already declares, and counts what the budget left untested. `alpha` is the
  corrected p-value at which a result counts as support; WITHOUT IT there are no
  findings and no proposals, on the same rule as `project`'s `report_above`.
  `DEFAULT_LAGS`, `DEFAULT_BUDGET_PAIRS` and `MINIMUM_PAIRED_SAMPLES` are the
  lag family, the pair budget and the paired-sample floor.

- **`EngineSession.adopt_io_relationships`, and `proposed_io_relationships`.**
  Discovery proposes; only adopting changes what gets checked. This is the first
  producer of the `IORelationship` in `types`, whose consumer -- RESPONSIVENESS's
  `check_io_pair` arm -- has had none.

- **`stationary` and `lead_lag`**, with `VARIANCE_RATIO_BAND` and
  `TREND_T_LIMIT`, deciding whether a series is testable at all.

- **`entail`, a third discipline, and `rules:` / `closure:` on a domain.** A rule
  composes declared edges into a new one — `exposed_to(A, C)` from
  `holds(A, B), clears_at(B, C)` — and `entail` evaluates every rule once,
  reporting what it derived and what it refused. `MAX_BODY_ATOMS` is three and
  the head predicate may not appear in its own body: two bounds that are one
  bound, and what makes evaluation a polynomial-time join. **A body MAY quantify
  its join variable**; that is allowed for exactly this reason, and the
  modelling guide's structural-constraint section has been corrected to say so
  rather than forbidding it in the shorthand.

- **`closure:`, which is where absence becomes evidence.** A rule that finds no
  binding may be false, or may be a rule nobody supplied the facts for. Naming a
  predicate in `closure:` states the feed for it is complete; for everything
  else, an entity with no fact under it is reported `open_world_undecidable`
  rather than treated as a no.

- **`BINDING_BUDGET`.** Polynomial is not the same as affordable: three atoms
  sharing no variables is the full cross product, and 196 facts under one
  produced 7.5 million bindings. A rule that reaches the budget is declined by
  name instead of being left to not return.

- **Derived facts carry their proof.** Each one names the rule and the facts it
  came from, and adopting writes it into the graph as `source: inferred` so a
  later CONNECTIVITY check can count an edge nobody fed in — and anyone reading
  the finding can trace it back. Deriving and adopting are separate calls.

- **`derived_exceeds_cardinality:<relation>`**, where the rules and the bounds —
  both declared by the same author, in the same file — contradict each other.

- **`infer`, a fourth discipline, and `relationship_rules` on the model.** Exact
  inference by variable elimination over the edges the author declares
  `edge_direction: causal`, with noisy-OR strengths. `relationship_rules` has
  been in the format since the twin builder read it and was reachable from no
  public verb — `traverse` builds its topology from the relationship graph,
  which never sees those declarations. It is carried on the model now.

- **`do` is an INTERVENTION, not a filter.** The intervened node's incoming
  edges are cut before the query is answered, which is what separates *what if
  I forced this* from *what if I saw this*. On a fixture with a declared
  confounder the two differ by a factor of two: 0.748 observed against 0.345
  intervened. `traverse(value_mode="hypothetical")` computes neither and is
  unchanged; this is the verb that answers the question properly.

- **A weight nobody declared stops the answer.** `cpt_missing` names the edges.
  `SOURCE_DECLARED` / `SOURCE_LEARNED` / `SOURCE_DEFAULT` ride on every weight
  and the count of each rides in every answer, because a posterior is a product
  of edge strengths and one the engine chose makes the number partly a
  statement about the engine with no way to tell which part. `DEFAULT_WEIGHT`
  and `DEFAULT_LEAK` are what it would have assumed, published so the question
  can be answered, and refused on any path the query depends on.

- **An entity the check could not evaluate is UNOBSERVED, never clean**, and the
  count rides in the answer: a posterior with six of ten nodes unseen is not the
  same claim as one with all ten. `ROOT_PRIOR` is the one default that cannot
  yet be declared away, so every answer names it.

- **Four refusals**: `cycle_unsupported` naming the loop, `not_identifiable`
  naming the declared latent that opens a backdoor under an intervention,
  `evidence_conflict` when the declared model gives the observations
  probability zero, and `treewidth_exceeded` when exact elimination would need
  an intermediate factor wider than `FACTOR_VARIABLE_LIMIT`. As with the
  entailment join, bounding the worst case does not make it affordable, and
  the engine says which it hit.

- **`SqliteObservationHistory`, a store that outlives the process.** The shipped
  history is a seven-day ring, which is right for a collector and wrong for
  *what would you have said last Tuesday* — asked about an evicted span it
  answers `insufficient_samples`, which reads exactly like a quiet feed. One
  table, one index, `sqlite3` from the standard library, and no eviction: a
  file the caller chose for durability should not drop its oldest rows. Numbers
  and text are stored in separate columns, because a numeric series read back
  out of a TEXT column compares as text and 9 exceeds 10.

- **`SessionCalendar` and `CalendarHistory`: windows in OPEN time.** On the
  first morning of a week a one-hour window spans the closed days, so a series
  sampled once a minute during the session looks like one sampled once every
  three days and the sample floor fires on data arriving perfectly well.
  Declared as `calendar:` on the domain — sessions with days, open, close and a
  zone, plus holidays. **A domain that declares none is always open and behaves
  exactly as before.** Named for sessions rather than for any one domain's word
  for them: the same shape is a factory's shifts and a clinic's opening hours.

- **`replay` and `sync_current_from_history`.** Feed the history once with real
  timestamps, then step the clock. **The clock moves the windows and not the
  data**: temporal axioms read history and follow `as_of` for free, while the
  threshold axioms read `Entity.properties`, which follows nothing — so a
  replay that moved only the clock would check today's snapshot against last
  Tuesday's windows, with every leg of the envelope still populated and nothing
  saying the answer was about two days at once. `replay` yields one envelope
  per step with the instant and the sync counts; `absent` is the denominator
  that makes a step readable, and the curve worth plotting from the output is
  declines per reason over time.

- **`derived:` — indicators the engine computes rather than receives.** An
  expression over other properties of the same entity, parsed against an
  arithmetic allowlist and never evaluated as code. **This is why there is no
  ninth axiom**: a parity residual, an arbitrage-free condition, a spread, a
  conservation gap are each a derived value plus an axiom that already exists —
  declare the difference, give it HOMEOSTASIS with a setpoint, and departures
  are reported without the engine learning any of those words.

- **`align_tolerance:`, because the two read sites fail differently.** The
  current value is missing when an operand is; the SERIES is missing when the
  operands were never sampled close enough together to count as one moment. Two
  feeds are not sampled on the same tick, and subtracting a reading from one
  taken a minute later is a different quantity from the one declared. Declared
  too tightly, every operand is present and the joined series is empty — so the
  report says how many points each operand had and how many survived.

- **`underived`, a third payload key on `check`**, on the argument the second
  one used. A derived indicator whose operand is missing declines on a property
  NOBODY FEEDS: the reason is right and the name is a dead end, and an author
  told `missing_property: drop_c` goes looking for a feed that was never
  supposed to exist. This names the operand. A stale value under the derived
  name is removed rather than judged as current.

- **References resolve one level, flat.** An operand that is itself derived, a
  self-reference, and an expression that is not arithmetic are each refused at
  load and reported in `unreachable_declarations` with a remedy — because a
  chain has an evaluation order nobody declared and a cycle has none at all.

- **An operand counts as READ.** Without that, feeding both operands to a model
  whose only use of them is the derivation reports both as read by nobody,
  which would send an author to delete the feed the indicator depends on.

- **`via:` — CONSERVATION and CONSISTENCY may reach across a declared edge.**
  A balance whose two halves live on different entities, and a reading that must
  agree with the same reading taken elsewhere, were declarable only while every
  property sat on one entity — which is the rare case. `output_properties` and
  `agrees_with` now accept `{via: <relation>, property: <name>}` beside the bare
  property names they always took. One shared resolver serves both, so the two
  cannot disagree about which failure is a decline.

- **Only the agreement needs `aggregate:`.** A balance sums its output side by
  definition; an agreement compares, and several readings are several candidate
  answers. With more than one peer and no `aggregate:` the check declines
  `missing_config` rather than picking — the choice decides the verdict, and on
  identical data a point agrees with the smallest of two readings and disagrees
  with the middle one.

- **`loss_absolute:`**, a fixed allowance for a loss that does not scale with
  the input. Declared beside `loss_margin:` rather than instead of it, and the
  LARGER allowance wins: an author who declares both has said either is
  acceptable, and taking the smaller would make declaring a second allowance
  tighten the check.

- **An absent peer is not a zero.** An edge reaching nobody declines
  `precondition_unmet` and targets carrying no such property decline
  `missing_property`. The engine already knew that summing an absent output as
  zero turns a wrong property name into a 100% deficit reported as a system
  fault; across an edge there is one more way to be absent, and it is the one
  most likely to mean the model is unfinished.

- **Forecasts from outside, and the books kept on them.** A forecasting model
  IS domain knowledge, so the engine carries none: what it adds is what
  forecasters lack -- a denominator, declines, and calibration stratified by
  something other than the whole population. `detection/forecast` parses one
  contract in three shapes. `quantiles` are taken as given; `samples` are
  reduced to empirical quantiles, which is arithmetic on what was sent; `mean`
  with `sigma` is expanded under a NORMAL assumption, and because that is the
  engine choosing a shape the producer never named, `GAUSSIAN_STAMP`
  (`gaussian_from_mean_sigma`) is written into the record's assumptions. A
  score turning on an assumption nobody recorded is what this package refuses
  everywhere else. `REQUIRED_QUANTILES` names the two levels a distributional
  record cannot be scored without.

  Two shapes in one record is refused rather than merged: two shapes are two
  claims, and choosing silently would score a producer against something they
  may not have meant to say.

- **`forecast:` on an indicator, and the denominator it makes possible.**
  `forecast: {expected: true}` says an outside forecaster is supposed to supply
  one, which is what makes a MISSING forecast reportable -- *371 received* is
  not a measurement until something says out of how many. Optional `models:`
  and `max_age:` enable `model_unknown` and `stale_forecast`; without them
  there is no check, because refusing every unseen id would refuse the first
  forecast any producer sends, and how old is too old is a minute for a quote
  and a day for a balance. A model declaring nothing gets a question rather
  than a confident zero.

- **The `forecasts` leg on `check`, and the shadow run behind it.** The eight
  axioms run a second time over the forecast itself, so a forecast bid above a
  forecast ask and a forecast count below zero are caught before any
  observation exists to refute them. Findings carry `SHADOW_PREFIX`
  (`forecast_`), and they do NOT climb into the envelope's own findings: those
  are about the present, and merging would put *your prediction is impossible*
  beside *your system is breaking* in one list. A shadow entity carries the
  forecast medians and nothing else -- inheriting unforecast readings from
  today would let a balance close on a side that is not a forecast at all.

  P(breach) is piecewise linear between declared levels and a BOUND outside
  them: a line beyond `q95` supports at most 0.05, which settles a reporting
  line of 0.1 and settles nothing at 0.01, so the undecidable case declines
  rather than answering *no breach*.

- **`random_walk`, the reference every forecaster is measured against.**
  `RandomWalk` is parameter-free on purpose -- `local_level` is also a random
  walk plus noise, but it estimates its parameters and is a MODEL, and a
  yardstick that can be tuned lets a poor comparison be explained away by
  tuning it. Filed under the reserved `BASELINE_MODEL_ID` (`baseline_rw`) on
  the same series and the same horizon as the forecast it judges, and tagged
  `SOURCE_BASELINE` so a reader can tell a reference from a real forecast
  without matching on a name. `DERIVED_LEVELS` names the levels produced when
  expanding or reducing.

- **A bound that is not the same for every instance.** All four BOUNDEDNESS
  threshold keys, RESPONSIVENESS's two and HOMEOSTASIS's `setpoint:` and
  `tolerance:` accept `{from_property: <name>}` instead of a number, and read
  it off each entity at check time. A margin requirement, a contracted ceiling
  and a regulatory floor are timestamped numbers owned by another system and
  different per instance; as literals they claim every entity of a type shares
  one line, and the only way to say otherwise was one entity type per instance.
  Resolution order is stated and reported: an instance bound, then the
  property, then the literal, with the origin carried out of
  `effective_thresholds` rather than inferred.

  **A bound declared and not arrived is not no bound.** It declines
  `no_threshold` naming the property, as does a value that is not a finite
  number -- which matters most for `NaN`, where accepting one would pass a
  whole book in silence. A mapping the loader cannot read reaches
  `dropped_declarations` rather than leaving an indicator that looks like it
  never declared a bound.

- **`session.set_declared_thresholds(entity, indicator, **bounds)`** -- one
  entity's own band, with no model edit, reaching indicators whose model
  declares a literal or nothing. Passing `None` removes it. Stored under
  `DECLARED_THRESHOLDS_KEY`, deliberately NOT the axiom-keyed table
  `set_threshold_override` writes: that one retunes an axiom's calibration
  parameter and says in its own docstring that it does not touch a declared
  bound. `model_describe` gains `instance_thresholds`, a summary of how much
  of the judging is against bounds not in the model, and
  `unread_declared_thresholds`, the bounds no check will consult.
  `THRESHOLD_FIELDS` names the four keys, and the loader imports it rather
  than keeping a second copy.

- **`consistency: {grid: <step>}` -- a value between the steps it can take.**
  A quantised quantity has values it cannot hold, and one of those is not high
  or low, it is impossible; no `warning:` or `critical:` can express that.
  Declared as a number rather than implied by a role name, so it says the same
  thing for a tick, a lot or a dial position in any domain.

- **`consistency: {ordered_below: <property>}` -- impossible in company.** A
  floor under a ceiling, a start before an end. Both readings may be plausible
  alone and contradictory together, which single-value plausibility cannot see
  by construction. Takes a bare property name or the same
  `{via:, property:, aggregate:}` form the other cross-entity references take.

  Neither key needs a `role:` beside it, and both join `agrees_with` in the
  remedy `unreachable_declarations` prints. That remedy, and the load-time
  reachability report behind it, are generated from `UNGATED_CONSISTENCY_KEYS`
  -- one list, so the sentence cannot name fewer ways than exist.

- **A forecaster is an ordinary entity.** `feed_model_figures(session, <your
  type>)` puts each model into the session carrying six figures --
  `forecasts_issued`, `forecasts_expected`, `graded_n`, `coverage_90`,
  `pinball_loss` and `forecast_age_s` -- and files each as an observation, so
  the eight axioms judge a forecaster the way they judge anything else. A model
  that is miscalibrated, one that skips subjects and one that delivers late are
  BOUNDEDNESS, CONSERVATION and RESPONSIVENESS; there is no ninth axiom.
  `model_figures` returns the same figures without writing them.

  **The type name is the caller's, and the package does not contain one.** A
  type name compiled into a domain-free core would be a domain word in the one
  place this project refuses to put one, so the caller passes it and the model
  declares it.

  **Both surfaces are written, or CONSERVATION says nothing.** BOUNDEDNESS and
  RESPONSIVENESS judge the current value; CONSERVATION reads the series. An
  entity carrying the figures as properties alone declines
  `insufficient_samples` and reports no imbalance at all, which is the silent
  outcome this pairing closes. A figure no graded record supports is left out
  rather than defaulted -- a `coverage_90` of 0.0 for a model that has never
  been scored reads as catastrophic miscalibration, and an axiom would fire
  on it.

- **`examples/margin_book.yaml`, a fifth worked example**, and the first that
  declares work the engine has not been handed yet: an outside forecaster is
  expected to supply a prediction, the engine keeps the books on whether it
  did, and the forecaster is then judged by the same eight axioms. It is also
  the first with ONE entity type for a fleet -- one `Account` for a book whose
  every account carries its own requirement -- which is what `{from_property:}`
  made possible. Ships at `examples/` and inside the package, like the other
  four, and the modelling guide now declares the forecaster block it uses.

### Fixed

- **`loss_margin: 0` could never report.** CONSERVATION computed a finding's
  confidence as `min(1.0, deficit_ratio / margin)`, and every path reaching
  that line had already passed `deficit_ratio > margin` -- so the quotient
  exceeded one whenever it could be computed at all, and the clamp returned 1.0
  every time. The division had exactly two reachable effects: produce a number
  that was then discarded, or raise. Against a zero allowance it raised, the
  checker errored, and a real imbalance surfaced as `checker_error` -- so the
  strictest declaration an author can make was the only one that was silent. A
  balance of counts, forecasts expected against forecasts issued, is precisely
  where zero is meant. The confidence is now the constant it always was.

- **Three published surfaces described a closed gap as open.**
  `factory_line.yaml` explained its one-type-per-machine shape as forced by a
  declared threshold that could not vary per instance; the README pointed at it
  for exactly that lesson; and `axiom_thresholds.py` said a consumer needing
  per-instance bounds still could not express one. `{from_property:}` and
  `set_declared_thresholds` close that in this same cut. The example's header
  also never described the example: its three station types declare no
  thresholds at all and are separate because they measure different things.

- **A test named the modelling guide and never opened it.** The check that the
  monitor's figures are named as the guide declares them asserted against a set
  literal typed into the test -- a second copy of the fact -- so it passed
  while the guide declared none of the six. It now reads the guide.


- **THE F DISTRIBUTION WAS NOT THE F DISTRIBUTION.** `f_sf` (formerly
  `GrangerCausalityTester._f_distribution_sf`) computed the exact survival
  function for two degrees of freedom and applied it at every number of them.
  Measured at the true 5% critical value with 250 denominator degrees of
  freedom, it returned 0.145 at df1=1, 0.049 at df1=2, 0.004 at df1=5 and
  0.0001 at df1=10 -- correct at two, three times too conservative at one, five
  hundred times too liberal at ten. Replaced with the regularized incomplete
  beta, which agrees with a reference implementation to 3e-13 across 1,120
  points. `_normal_sf` was a `tanh` stand-in is now the error function.

  **What it did to a result**: on series with NO relation, where a test claiming
  5% should reject 5%, the measured false-positive rate was 0.3% at lag 1, 6% at
  lag 2 and 25% at lag 5. The test was not slightly miscalibrated; it was a
  different function of the lag.

  **Nobody needs to re-read a published result, and the first wording of this
  entry said they did.** No release before this one contained any Granger code
  at all -- the `causal/` package is new here, and at 0.1.14 the word appears
  only in the `IORelationship` field names. The bug lived in unreleased
  development and shipped already fixed. Corrected because a changelog that
  over-states a defect's reach spends the same credit as one that under-states
  it, and the sentence sent readers to audit results that do not exist.

- **A lag search reported as a single test.** Taking the smallest p across a
  family of lags is several chances to be surprised reported as one; uncorrected
  it rejected independent series 14% of the time. `lead_lag` applies a Sidak
  correction over the family and reports the raw and corrected figures side by
  side; the corrected rate measures 5%.

- **The stationarity trend test used an ordinary standard error on
  autocorrelated residuals**, which inflates |t| by roughly the square root of
  (1+r)/(1-r) and refused HALF of all strongly autocorrelated series for a trend
  they did not have. Corrected by the same factor: false rejection falls from
  50% to 8% at an autocorrelation of 0.8, while a real trend is still caught
  every time.

- **A NaN reading passed every check silently.** `NaN` compares false against
  everything, so no threshold was breached, no count was negative and no
  setpoint was departed from: the cell produced no finding and no decline, and
  a clean pass is the one answer a broken sensor must never get. An infinity
  was worse than silent -- it compares fine, so BOUNDEDNESS reported
  `threshold_exceeded`, sending a reader to look at a quantity rather than at
  the instrument. A numeric property that is not finite now declines
  `undefined_for_values` on every axiom, before any checker runs.


## [0.1.14] — 2026-09-14

**A PATCH release, and the `Removed — BREAKING` heading below needs a sentence
beside it.** `HomeostasisChecker` is not among the names the README lists as the
public API, and COMPATIBILITY.md places any deeper import outside the contract at
any version. The heading is a warning to anyone who was importing it anyway --
which is worth giving -- and not a version ruling. Everything else here is named
by that document as patch-level: adding a `not_checked[].reason`, adding an
envelope key, and making a check fire where its silence was a defect.

### Added

- **`no_rule_for_role`, a thirteenth `not_checked[].reason`.** A model that
  declares `role: count` on an indicator and asks CONSISTENCY about it has
  declared correctly and gets an answer; ask RESPONSIVENESS and there is no rule
  for counts, so the pair does not evaluate. That state used to report
  `missing_role`.

  **The two are opposites on the axis this vocabulary was split along** -- who
  owes something. An indicator with no role owes a declaration. One whose
  declared role an axiom has no rule for owes nothing: the model is right and
  the axiom does not cover that kind of quantity. Reporting the second as
  `missing_role` sent an author who had already declared a role looking for one,
  and only the decline `detail` said otherwise -- a field this policy declares
  unsupported for matching, which is what made it the vocabulary's problem
  rather than the reader's.

  **A consumer counting `missing_role` will see the count fall**, with the
  difference arriving under the new member. `not_applicable` is unchanged and
  was not reused: it means no checker was registered for the axiom, and pointing
  this at it would report a broken engine where none is.


- **`partially_checked`, a fourteenth `not_checked[].reason`.** An axiom with
  more than one arm can have one arm with nothing to judge against while another
  arm runs and reports a real violation. `MONOTONICITY` does exactly that: with
  a direction block and no rate, one envelope carries `monotonicity_reversal` in
  `findings` and a decline about the same indicator in `not_checked`. That state
  used to report `no_threshold`.

  **Reported from outside, and the consequence was in a consumer's floor
  table.** `no_threshold` usually means somebody owes a declaration, so a bridge
  routing by reason floored the run at could-not-complete -- a correct model
  reporting a genuine reversal, scored as a run that could not be made. Only the
  prose `detail` told the two apart, and `detail` is declared unsupported for
  matching.

  **A consumer counting `no_threshold` will see the count fall**, with the
  difference arriving under the new member. An indicator with nothing at all to
  judge against still reports `no_threshold`.

- **`not_checked[].arms_checked`**, a list naming the arms of a multi-armed
  axiom that DID produce a verdict. Present only when some did. Beside the
  reason above it is what a floor table needs without reading a sentence.

- **`binder_must_supply`, a decorator a check uses to declare the arguments it
  decides by.** A platform that binds a declared check calls it with the entity,
  and with the history when that is the second parameter; everything else keeps
  its default forever. A check whose answer depends on one of those extras is
  declarable, bindable, callable, and unable to do its job -- with every layer
  reporting success.

  **No signature separates that from a knob**, which is why this is declared
  rather than inferred. In this package `check_config_drift(entity,
  desired_config=None)` cannot work without its second argument and
  `check_replica_mismatch(entity, tolerance_seconds=60.0)` is correct with its
  default: same shape, opposite meaning, and no rule over names, types or
  defaults tells them apart. Only the author of the method knows, so the author
  says it, and a binder that reads the attribute can refuse the declaration at
  load and name the parameter.

  `check_config_drift` carries it. Nothing in the package reads the attribute --
  the binder that does is not part of this distribution -- so this is a
  contract a consumer's own binder can honour, not a behaviour change here.

### Changed

- **RESPONSIVENESS fires AT a declared threshold, not past it.** It read the
  same `warning:` and `critical:` keys BOUNDEDNESS reads and compared them with
  `>` where all four of BOUNDEDNESS's bounds use `>=`, so `critical: 600` meant
  *600 is already critical* on one axiom and *600 is still fine* on the other.
  Reported from outside by an author transcribing published limits, who had no
  way to tell which rule applied to the number being written down.

  **Inclusive was chosen in both directions of the argument.** Four of the six
  comparators involved were already inclusive, as is every other threshold in
  that module. And the two directions are not equally safe: this makes a finding
  APPEAR at exactly the bound, where moving BOUNDEDNESS instead would have made
  one DISAPPEAR there -- a tool that stops reporting a breach it used to report
  is the worse failure.

  **A model with a latency indicator whose value lands exactly on its threshold
  will report one finding where it reported none.** `MODELING.md` now states
  what a declared number means, which it did not: the words *inclusive*,
  *exclusive* and *at or* appeared in it zero times.

### Removed — BREAKING

- **`HomeostasisChecker.check_all` no longer accepts `desired_config`.** It
  forwarded the value nowhere. Its only reader was the hardcoded fallback that
  0.1.13 removed, so passing one has changed nothing since that release --
  while the signature went on saying otherwise. A caller who passes it now gets
  a `TypeError` rather than a silent no-op, which is the whole reason to take it
  off rather than leave it.

- **Drift detection is no longer offered through a domain declaration.**
  0.1.13 made this state audible: a declared `config_drift` bound, was called,
  and declined `missing_config` every time, because extensions are called with
  an entity and its history, there is no third slot, and nothing in the loader,
  the core or the domain schema declares a specification to compare against.
  That entry called the wider gap open. It is now closed by withdrawal rather
  than by building a declaration surface for it -- **the same call, and for the
  same reason, as `check_capacity_ratio` in 0.1.12**: a format addition is far
  harder to withdraw than a method is to restore, and no consumer has asked for
  one.

  **`check_config_drift` is unchanged and stays.** A caller holding a
  specification of their own passes it directly and gets exactly the comparison
  it always did. What is withdrawn is the claim that a domain file could supply
  one. If a model arrives that needs to declare a desired configuration, that
  declaration is the design to do -- not this path to re-enable.

## [0.1.13] — 2026-09-07

### Fixed

- **Four axiom checks no longer refuse an entity type their domain file
  declared.** `check_replica_mismatch`, `check_oscillating_recovery`,
  `check_slow_startup` and `check_health_probe_failures` each compared the
  entity's type against a hardcoded list of Kubernetes type names, on top of the
  scope the domain file's `domain_checks` entry already declares and the platform
  already applies. A domain naming a type the literal omitted was accepted at
  load, bound, called, and got nothing back -- silently.

  **This is a fire-where-it-was-silent change.** A model declaring one of these
  four for a type outside the old literal will now see findings it did not see
  before. Four of the eight checks a shipped domain file declares never carried
  such a literal, which is what showed the other four's to be redundant rather
  than load-bearing.

- **A decline recorded by a registered domain check now survives.**
  `run_domain_checks` collected results under `if result:`, and a result carrying
  only declines is falsy -- it is a list of problems holding none -- so the whole
  outcome was skipped and the record with it. Nothing shipped had ever returned
  one, so no released version lost a real decline; the entry below is the first
  path that would have.

### Changed

- **`config_drift` declines `missing_config` where it used to return nothing.**
  Asked whether an entity has drifted from a specification when no specification
  was supplied, it answered with an empty list, which in this engine reads as
  *evaluated, nothing wrong*. It now says which of the two it means.

  **A consumer reading `not_checked` will see one more record**, of a reason
  already in the published closed vocabulary. No schema version moves.

  **The wider gap is open and is not fixed here**: nothing in the loader or the
  domain schema supplies a desired configuration at all, so this decline is what
  a domain file declaring `config_drift` gets today, every time. Reporting that
  honestly is a smaller thing than making it work, and it is what changed.

## [0.1.12] — 2026-09-07

### Added

- **A state the model declares as bad is now a finding.** `bad:` on a STATE
  indicator loaded, landed on the spec, and was read by nothing: a model saying
  `bad: [Failed]` about an entity whose phase was `Failed` produced an envelope
  byte-identical to declaring nothing. Not a decline, not a dropped declaration --
  silence, from a key the loader accepts. STABILITY now reports
  `declared_bad_state` at HIGH when the current value is in the declared set.

  **This is the policy's fire-where-it-was-silent case and is listed here for that
  reason.** Any model already declaring `bad:` on a STATE indicator whose entities
  are in one of those states will see findings it did not see before. Eleven such
  declarations across three shipped domain files.

  **Removing the key was the other candidate and the measurement ruled it out:**
  twenty-nine STATE indicators across six domain files, so the vocabulary is in
  use and means what it says.

  **`normal:` is deliberately NOT checked against.** A value in neither list is not
  a fault -- the shipped pod-phase vocabulary leaves `Pending` and `Succeeded` in
  neither and both are ordinary -- so a rule firing on *not in normal* would be
  noise on the majority. It is reported instead: `model_describe` gains a `states`
  key on indicators that declare one, and the finding's evidence carries it beside
  the state that fired.

### Changed

- **`checker_error` is emitted. It was in the decline vocabulary from the start
  and no path had ever produced it.** The vocabulary is closed and published as
  the list of reasons this engine can refuse to judge -- a bridge author reads it
  as their requirements document. A reason on that list that nothing emits is,
  from outside, indistinguishable from one that cannot happen, and this one had
  been in that state since the vocabulary existed.

  It now carries the case the entry above describes: a check supplied by a
  registered extension raised, so it produced nothing, and *produced nothing*
  and *found nothing* are different answers. The record names the check and
  carries the error.

  **Who sees a new decline: only a caller with a registered extension whose
  check raises.** Measured against the previous release on a model with no
  extension, the envelope is byte-identical -- same `checked`, same
  `not_checked`. If you register nothing, nothing changed.

  **A second, quieter repair came with it.** Building a plain list from a
  `CheckOutcome` keeps the problems and drops the declines, because that is what
  `list()` does -- so a record written inside a helper was discarded at the
  method's return line. That seam was documented as a known limitation and is
  now closed in both checkers that had it. The README's published count of
  decline call sites moves from 35 to 37 for the two new ones; that number is
  derived from the checkers by a test rather than transcribed, which is how the
  change was noticed.

- **A domain check that cannot run now says so.** Extensions supply callables and
  this engine runs them inside a `try`, so that one bad extension cannot take out
  the others in the same pass. That part is unchanged and deliberate. What
  changed is where the failure went: a debug line, which in production is
  indistinguishable from the check having run and found nothing.

  *Ran, found nothing* is a result. *Could not be called* is a check that is not
  happening, and a caller who registered it has every reason to believe it is.
  The message is now a warning and names which check failed and why.

  **This was measured, not imagined.** A check shipped here took a second
  required argument that the calling convention does not supply, so it raised on
  every entity and the exception vanished into that debug line. It had been
  declared and unrunnable for as long as both existed, and no surface said
  anything. That check's second argument is now optional and it returns nothing
  when there is no desired state to compare against -- *has this drifted from a
  specification* has no answer when there is no specification, and that is not an
  exception. Supply one and the comparison is exactly as it was.

  **What this still cannot do, stated because a log level is a poor place for
  it.** The function returns a plain list and has no decline channel, so the
  distinction between *found nothing* and *could not run* currently lives only in
  the logs. Putting it in the envelope, where the rest of this engine puts
  refusals, is the right home and is not done here.

- **No axiom checker decides anything by asking which domain it is in.** Two of
  the eight carried a block of Kubernetes-shaped checks behind a comparison of
  the entity's domain id against a literal. `BRIDGES.md` states the rule those
  broke -- and states it as a check a reader should run against the version they
  pin -- so the package now passes its own litmus rather than documenting it.

  **Who this changes anything for: almost nobody, and the exception is
  specific.** The checks were reachable only by an entity carrying
  `metadata={"domain_id": "kubernetes"}`, and nothing in this package ever
  writes that key -- `EngineSession.add_entity` gives no way to set it. So a
  caller had to construct `Entity` themselves and stamp it. If you did that and
  relied on the RESPONSIVENESS ones -- slow startup, health-probe failures,
  request timeout -- they no longer fire. **The five HOMEOSTASIS ones were never
  reachable at all**: the method holding them had no caller anywhere in the
  package, in any release that shipped it.

  **What replaced it is what should have been carrying it.** Domain-specific
  checks belong to a domain, and there is already a registry that scopes them by
  the domain the entity declares. The removed block was a second implementation
  of the same eight checks and the weaker one: it scoped them with a single flat
  set of entity type names, where a declaration scopes each check to its own.
  Nothing was moved out of this package; a duplicate was deleted.

  **The registry is not on the supported surface** -- it is a deep import, and
  COMPATIBILITY.md puts those outside the contract at any version. Read that as
  the honest position rather than an oversight: shipping one domain's checks in
  an engine that claims to have none was the defect, and a supported API for
  doing it again is not the fix.

- **This engine no longer invents indicators for a type you did not declare.** An
  entity type with no declared indicators fell back to a hardcoded Kubernetes set,
  keyed on the type's NAME. A model declaring a domain with nothing to do with
  Kubernetes, carrying a type called `Pod`, `Node`, `Service` or `Deployment`, was
  judged against indicators it never declared.

  **This is the policy's stop-where-it-was-firing case, and it is the inverse of
  the one above.** If your model declares one of those four type names WITHOUT an
  indicator block, you will see fewer findings than before and a smaller
  `checked.invariants`. Both numbers were wrong: measured, a proposals domain
  received a finding on `restartCount`, and a denominator of seven where the model
  declared one.

  **The denominator is the worse half and the reason this is listed as a change
  rather than a fix.** A false finding is visible and arguable. `checked` is the
  count this engine publishes to show what it did not skip, and six of those seven
  invariants were never asked for by anyone. All four names inflated it; only one
  of them also produced a finding, so the visible half understated the defect.

  The seed is now opt-in: `UnifiedAxiomReasoner(builtin_k8s_indicators=True)`
  restores it for a caller who genuinely wants it. Nothing else changes -- a
  declared indicator is evaluated exactly as before, and a type name that never
  collided was never affected.

  **Why it lasted.** Every example model that ships here avoids all four names, so
  every fixture agreed with the engine. The collision is with ordinary nouns: a
  factory line has a `Node`, an engagement has a `Service`. The fixtures were
  lucky rather than representative, and
  `tests/test_the_engine_invents_no_indicators.py` now asserts the outcome --
  the denominator equals what the model declared -- so a seed returning by any
  mechanism is caught.

- **`gaps` is priority-ranked on one scale, and was not before.** It merges two
  populations: structural gaps the builder finds at the entity, and gaps a walk
  discovers. Structural ones carried a flat `0.5`, so the type weights applied to
  none of them -- a missing edge and a missing property ranked identically.
  Traversal ones were multiplied by the edge's `propagation_probability`, which is
  fault-propagation dynamics and defaults to `0.3`.

  **Measured, a `missing_node` two hops out scored `0.03` and sorted last**, below
  every structural gap, while carrying the highest weight in the table -- the type
  that says the topology itself is wrong.

  A discovery question is not a fault forecast: how much it is worth asking about a
  dangling reference does not depend on how strongly disturbances travel the edge
  that led you to it. That factor is gone. What remains is **the type's weight,
  decayed by how far the walk went**, and a structural gap is scored at hop zero
  because that is where it was found. The same dangling reference now scores
  `0.333`, and `1.0` when it is the start node.

  Values are rounded to three places: this is a ranking key, not a measurement.
  **The ORDER of `questions` remains outside the compatibility contract** -- sort
  them yourself if you need determinism -- and these numbers are calibration in the
  sense `AxiomParameters` defaults are.

  `README.md` and `BRIDGES.md` state this scale; both described the previous
  one, having been written to document it a few days before it changed.

- **`agrees_with` declines instead of guessing a tolerance.** The block accepts
  `tolerance:` (relative) or `tolerance_absolute:`. Declared neither, it used to
  fall back to a global 5% and answer. **Now it declines `missing_config`,** naming
  the block to write.

  **Five percent is a wide silence** wherever the two numbers are money, counts of
  record, or a measurement and its check. Measured on a blind run: two statements
  of one contract total 1.9% apart -- ninety thousand on four point eight million
  -- and this arm answered *they agree*, with no finding and no decline to read.
  How close two readings must be is a fact about the modelled system, which is the
  same reason a HOMEOSTASIS setpoint without a tolerance does not get a guessed one.

  **The policy's decline-where-it-guessed case**, listed here as it requires. What
  it does not do is go quiet: the cell still counts in `checked.invariants`, and
  **every other rule on that indicator still runs and still reports** -- a value of
  150 on a `role: percentage` indicator is still `impossible_value` whatever the
  agreement arm could not judge. Withdrawing a working check to report a missing
  one would be the worse trade.

  `AxiomParameters.consistency_agreement_tolerance` is removed with it. That field
  had exactly one reader and the reader was the guess; left in place it would have
  been accepted, carried and read by nothing.

- **Every sample-floor decline now says whether the floor can ever be met.**
  `observations 0 of 10` reads as *collect more data*, and on a series sampled
  sparser than the window that is permanently wrong. HOMEOSTASIS and MONOTONICITY
  already carried the window, the total and the median interval;
  **CONSERVATION and STABILITY declined with the bare counts**, so one starved
  input produced an interpretable answer or an uninterpretable one depending on
  which axiom reached it first. Both now carry the full set, and
  `floor_unreachable_at_this_rate` states the conclusion with a remedy naming both
  ways out.

  **Each axiom counts against a different window and the decline reports its own.**
  STABILITY reads the indicator's `window:`; CONSERVATION its own accounting
  window; HOMEOSTASIS a baseline in days. A window copied from the wrong source
  would be a precise wrong number, worse than the silence it replaced. CONSERVATION
  also reports against the INPUT property rather than the indicator's, because the
  input series is the one being counted.

  **`sampling_context` learned to see a state series.** It reads numeric values
  first, and STATE observations are stored apart from them -- so the state arm of
  STABILITY would have reported `total_observations: 0` about a property with a
  full history. It falls back to the state series rather than reporting a zero.

  Unchanged: the helper still declines to guess. Fewer than two observations
  yields no interval, and `floor_unreachable_at_this_rate` stays False, which is
  the right default for a claim about impossibility.

### Documentation

- **`BRIDGES.md` said this engine contains no domain noun, which certifies a tree
  rather than stating the division.** That guide's own opening refuses to carry
  measurements of engine behaviour, on the ground that a behaviour written into
  prose is a second copy of a fact and second copies drift. That sentence was one,
  and it drifted: an engine extracted from a running deployment can carry
  checkers, written before the extraction, that still decide behaviour by
  comparing a domain identifier against a constant.

  **So the sentence is gone rather than corrected to a smaller number.** *The
  division* now says where domain nouns belong. The *Engine litmus* says the
  document certifies no tree, names that shape, and tells the reader to run the
  check against the version they pin -- which is what a litmus was always for. A
  count would expire on the next site added or removed; the shape does not.

  The litmus itself is unchanged and already distinguished the case that is not a
  violation: a domain identifier used as a lookup key a caller supplied is not a
  branch, and one axiom resolves thresholds that way.

- **The `questions` leg of the envelope, which shipped undocumented.** It is a
  required member of every envelope and the thing `gaps` exists to fill: what the
  model is MISSING. The distinction it carries is the one `not_checked` cannot --
  a decline says the model asked for something this run did not have, and a
  question says the model never asked.

  **It was named in `schema/envelope.schema.json`, and in one line of
  COMPATIBILITY.md about ordering, and in no prose in this repository.** The
  README's envelope section listed three legs where the schema requires five, so
  a reader learning this engine from its documents could not find the surface at
  all. It surfaced while someone was drawing up what a new vertical would have to
  build, and registered a capability that ships as one that was missing -- which
  is the cost exactly: a shipped surface no document names is indistinguishable
  from one that does not exist, and the reader who cannot find it pays for it
  twice, once by not using it and once by building it again.

  `README.md` now names the leg beside the other three and says which verb fills
  it; `BRIDGES.md` carries what a bridge author does with it. And
  `tests/test_the_envelope_legs_are_documented.py` derives the required members
  from the schema and goes red if the README stops naming one, so a fifth leg
  cannot arrive the same way this one did.

- **How a CONNECTIVITY check is declared.** The axiom table has listed CONNECTIVITY
  since this guide's first version while the format for declaring one appeared
  only in `water_tank.yaml`, so the only way to write one was to find the example
  and copy it. A new *Relationship indicators* section covers `target_type`,
  `relation_type`, `min_cardinality`, `max_cardinality`, `required_property` and
  `violation_severity`.

  **Including which of the three findings the declared severity reaches**, which is
  one of them. `missing_relationship` takes it; `excess_relationships` and
  `dangling_relationship` are `MEDIUM` by a deliberate distinction -- a missing edge
  is a fault in the system, an excess or dangling one a complaint about the model.
  No severity changed; the scope is now stated where an author reads it rather than
  discovered from an unexpected report.

  **Five further keys the loader accepts remain undocumented on purpose**, each with
  its reason held in `tests/test_the_indicator_keys_are_documented.py` rather than
  in a comment: `plausible_range` was withdrawn from the guide deliberately and
  teaching it again would reopen what that withdrawal closed; `normal` and `bad`
  are read by nothing in the package; `transient` and `timeout` are read and
  unreachable, because the check needs a state history the public feeder cannot
  supply. That test derives the key set from the loader's own
  `_KNOWN_INDICATOR_KEYS` and fails in both directions -- on a key that is neither
  documented nor exempt, and on an exempt key the guide starts teaching.

- **The `stability:` block, which a model could declare and the modelling guide
  did not name.** Five per-axiom configuration blocks load from a domain model.
  `MODELING.md` documented four. The missing one is the only one that is OFF until
  declared -- the other four tune a check that runs anyway -- so a model author who
  could not learn the key could not reach the slow-oscillation detector at all. It
  shipped that way, working, and a period-8 cycle at 20% amplitude reports
  correctly the moment the key is written.

  The guide now carries the block, both tuning keys (`min_amplitude`, default 0.05
  and relative to the window's largest absolute value; `min_crossings`, default 4)
  and the six-sample floor below which the arm returns without reporting, because
  the period-2 arm has already declined on a starved input.

  **Guarded against the class rather than the instance.**
  `tests/test_the_config_blocks_are_documented.py` derives the block set from the
  indicator spec's own `*_config` fields, checks the guide names each, and
  separately feeds each derived key through the loader -- so a documented key that
  loads nothing fails too. Second instance of one shape in a week; the envelope's
  `questions` leg was the first.

- **The engine described a role inference it no longer performs, in the package
  itself.** The rule that read a role from an indicator's NAME was removed earlier
  in this cycle; a comment in `consistency.py` went on calling it *the fallback*,
  in the checker it misdescribes, and shipped that way in 0.1.11. Two checkers also
  carried a branch keyed on a role source the engine had stopped producing --
  neither could fire, so no test could go red on either, and each logged that the
  axiom had applied via a role read from the indicator's name.

  **Nothing behaves differently.** The branches were unreachable and the comment is
  prose. Both are gone because a package asserting a mechanism it does not have is
  read as a specification by whoever writes against it, and this one was asserted
  in three places a reader reaches before the code. With no `role:` declared the
  axiom declines `missing_role` and reads nothing from the name, exactly as it
  already did.

### Removed

- **`BoundednessChecker.check_capacity_ratio`.** The deep import path
  `arbiter_engine.ontology.axioms.boundedness.BoundednessChecker.check_capacity_ratio`
  no longer resolves. It computed a used/limit ratio and **nothing in the package
  called it** -- only its own tests did, which is why it read as covered.

  It held this checker's only call to `resolve_axiom_threshold`, so a per-entity
  BOUNDEDNESS override was accepted and then ignored. The exported constant
  `OVERRIDE_DECLARED_BUT_UNREACHABLE` said so, and **that constant is now empty**:
  BOUNDEDNESS has moved to `OVERRIDE_NOT_CONSULTED`, which is a true statement
  about the code rather than a promise about it. The constant stays, empty, because
  an empty group is a checkable claim that no axiom is in that state.

  **Deleted rather than wired, and the reason is the interesting half.** Wiring
  means designing a declaration channel, a loader change, documentation and tests
  for a capability no consumer has asked for -- a format addition, far harder to
  withdraw than a method is to restore. The capability is wanted and is recorded as
  wanted: a `capacity:` block naming the used and limit properties, declared and
  never inferred from names. If a domain arrives needing it, that is the design to
  do, not this method to bring back.

---

## [0.1.11] — 2026-09-04

### Added

- **`dropped_declarations`**, on `check`: the values this engine read out of your
  model, did not recognise, and therefore did not apply. Each entry names the
  field, the value, the valid set and — where one is close — what you probably
  meant.

  **A misspelled axiom name used to be invisible here.** `axioms: [BOUNDEDNES]`
  on an indicator with a `critical:`, and an entity reading past it, produced an
  envelope byte-identical to declaring no axioms at all: no finding, no decline,
  `invariants: 0`. The check you wrote never ran and the result could not say so.
  Four of the five tools were silent; only `model_describe` reported it, and a
  caller who runs `check` does not necessarily run that.

  **A payload rather than a decline, and the schema chose it.**
  `not_checked[].axiom` is a closed enum of the eight axiom names, so a cell
  declined for `BOUNDEDNES` cannot be written down without moving the wire
  contract. This is the same trade `unread_properties` made in 0.1.10, one field
  further in.

  It is narrower than the describe report it draws from: only values that were
  REJECTED, not fields whose consuming axiom was never declared. Reported from
  outside, in a verification of the released 0.1.10 artifact.

- **A fourth worked model, `examples/factory_line.yaml`** — a discrete
  manufacturing cell. It is the first example whose vocabulary shares no nouns
  with the others, and it shows why a fleet of near-identical units ends up
  with one entity type per unit: a declared `BOUNDEDNESS` threshold lives on
  the entity type, and the per-entity override does not reach it.

### Changed

- **`RESPONSIVENESS` declines instead of passing when no deadline is declared.**
  An indicator carrying `role: latency` and neither `warning:` nor `critical:`
  used to return nothing at all — no finding, no decline — at any latency. The
  envelope was byte-identical to a check that ran and held, which is the one
  distinction this engine exists to make. It now reports `no_threshold`, and the
  `detail` names the keys to write.

- **A `RESPONSIVENESS` threshold of zero is no longer read as absent.** A
  declared `critical: 0` -- *any latency is a breach* -- was compared with a
  falsy test, so it was skipped and the check reported clean at every reading.
  Unusual but legal, and anyone who declared one has had clean envelopes for as
  long as the axiom has existed. Both arms now test for absence explicitly.
  Reported from outside, in a verification of the released 0.1.10 artifact; it
  was fixed in the same commit as the entry above and, until this line, had no
  sentence of its own.

- **`MONOTONICITY`'s rate arm declines instead of judging against a default.**
  `rate_warning:` and `rate_critical:` carried engine-chosen defaults of 0.1 and
  0.5, so a model declaring neither had its rate measured against numbers nobody
  wrote down. Undeclared, that arm now reports `no_threshold`. The reversal arm
  beside it is unaffected and its findings still report.

**Both of these change envelopes you are already getting.** A leg that was silent
now carries a decline, so anything composing an exit code from `not_checked` gets
a different answer on an unchanged model. Two downstream programs were measured
against these before release and moved differently — one from clean to findings,
one from clean to could-not-complete. Decide what `no_threshold` means to yours
before you upgrade.

### Removed

- **The natural-language LLM fallback is no longer in this distribution.**
  `NLTraversalTranslator` carried an `NL_LLM_FALLBACK_ENABLED` env gate whose
  path imported a module the package does not ship, and the failure was
  swallowed -- so setting it true and leaving it false were indistinguishable:
  no error, no log, no difference. A feature that cannot report its own absence
  is worse than one that is missing. The deterministic `translate()` is
  unchanged and needs no client; `TopologyTraverser` is untouched.

---

## [0.1.10] — 2026-09-03

**Read this one before upgrading.** Two rules that used to be read out of a
property's SPELLING are gone, so a check you have been getting without declaring
it will stop. Both changes say so at runtime — one as a decline, one as a report
— and neither goes silent. The [Removed](#removed) section names the exact
declaration to add.

Most of this release came from outside: a reader applying `BRIDGES.md` to their
own vertical, whose method document and probes found eight of the entries below.

### Added

- **`unread_properties`**, on `model_describe`, `gaps` and `check`: the numeric
  entity properties you send for which no indicator is declared. It reports what
  arrived and does **not** judge the value, because deciding what a number means
  needs a rule and this engine takes rules from your model.

  It exists because a removal made the gap visible. The engine already reported
  the mirror — declarations that can never fire — and had nothing for the
  inverse, data carrying something the model never mentions. An author cannot
  declare a property they do not know they are sending.

  Numeric only, and booleans are excluded. A mistyped STATE property is not
  reported, because telling a state from a label is a question about your domain.

- **`precondition_unmet`**, a twelfth member of `not_checked[].reason`. A
  topology check can be gated on the entity carrying some property; when the gate
  skipped the cell, the cell was counted in `checked.invariants` and appeared in
  no row — byte-identical to a cell that evaluated and found nothing. Twenty
  healthy entities beside five gated ones made the arithmetic read twenty-five
  and no reader could separate the populations.

  The reason states the precondition and stops. A deliberate exemption and a
  mistake look the same from here, so claiming which one it is would assert
  knowledge the engine does not have.

- **`arbiter_engine.__version__`**, read from installed distribution metadata,
  `None` when running from a source tree. A consumer recording which engine
  produced a result had to reach for `importlib.metadata` themselves or write the
  number down twice.

- A third reason in the unread-fields report, `unknown_value`: a key the engine
  reads, carrying a value it does not recognise. An earlier release inverted the
  KEY check, so `directon` is caught; nothing compared VALUES, so
  `direction: hihger` fell through the same gap one level down. Seven resolvers
  have a closed vocabulary and all seven now report what they rejected, each
  carrying its own valid set so the report holds no second copy of them.

  `type` is why this exists. It was silent at every level and substituted
  `numeric`, so `type: numric` produced an indicator typed wrongly, evaluating
  the wrong axioms, in a model that loaded clean. Loading behaviour is
  unchanged — refusing would be the tool deciding an author's roadmap — but it
  no longer does it without saying. Found from outside.

- Two decline reasons, splitting `not_applicable`, which was three answers under
  one name. `missing_role` -- the model never declared what an indicator IS to
  `CONSISTENCY` or `RESPONSIVENESS`, so somebody owes a declaration.
  `undefined_for_values` -- the axiom applies and its quantity has no value on
  the data present, a ratio against a zero total or a deviation against a zero
  spread, so nobody owes anything and it may evaluate tomorrow.
  `not_applicable` now means only what is left: no checker was registered for
  the axiom.

  The axis is whether an obligation exists, which is the one a bridge author can
  act on. It was previously recoverable only from `detail`, which this document
  declares unsupported for matching -- so a bridge needing the split had to keep
  a private copy of wording a patch may move, and fail silently when it did.

  Additive, and the same shape as `no_current_value` in 0.1.6: a closed enum
  missing a member does not raise, it reclassifies into the nearest one and
  reports it with confidence. Reported from outside.

- **Three guards in the shipped `tests/`**, so the claims they hold can be
  checked by whoever is holding the package rather than only by us.

  `test_no_identifier_names_a_private_record.py` walks the installed package and
  fails on any name citing a tracker record — the rule 0.1.9 stated for one
  constant, now enforced for all of them, including the string constants a name
  can hide in.

  `test_the_readme_decline_count_is_derived.py` recomputes the README's decline
  call-site count from the axiom enum. The number was previously held by a
  weekly job that installs from the index: that job answers whether the INDEX
  matches the claim and cannot answer whether the tree you are holding does.

  `test_the_rename_table_names_real_things.py` reads the rename table in this
  file and checks every name in it against the package — the new ones present,
  the old ones gone. A release note that renames things is a set of
  instructions, and nothing here had ever held one to the code it describes.

  The tag workflow also now compares the **wheel** against the tag, not only the
  sdist. `pip install` resolves the wheel, so checking the other file was
  checking the copy most readers never receive. Reported from outside.

### Removed

- **The raw-property walk.** `CONSISTENCY` used to read every entity property,
  recognise a word in its name — `pct`, `count`, `ratio` — and range-check the
  value whether or not your model asked. A key spelled `saturation_pct` carrying
  150 raised `impossible_value` at HIGH; `retry_count` at -4 raised it at
  CRITICAL. **Those findings are gone.**

  **To keep them, declare the indicator** with a `role:` of `percentage`, `count`
  or `ratio` and `CONSISTENCY` in its `axioms:`. That is the whole migration, and
  `unread_properties` lists the properties you are missing one for.

  Two reasons, and the second is the load-bearing one. It derived an
  interpretation fact from a spelling: two identical declarations were treated
  differently because of their names, and no surface said which had happened.
  And its findings sat OUTSIDE the denominator — they were produced off the
  per-declaration loop, so the envelope reported problems against cells it never
  claimed to have attempted, and `checked.invariants` could not account for them.

  Measured before removing, across six model packs: 31 property keys reached the
  walk, 11 fired, 6 of those were real, and three shipped packs were relying on a
  rule they had never declared.

  **Removing it exposed a defect it had been hiding**, which is the best argument
  for the removal: one pack declared `role: percentage` correctly and one of the
  two YAML loaders never read the field, so the check had been passing on the
  property's spelling for as long as the field has existed. See Fixed, below.

- **`ontology.axioms.roles.name_word_tokens`**, the helper that split an
  indicator's name into words so the walk above could recognise one. It has no
  caller once nothing reads a spelling for meaning, and it is named here because
  it was a public function on a deep path: the removal is invisible until an
  import fails.

  Found late, by differencing the public names of 0.1.9 against this tree. That
  comparison needs two releases and only one of them is here, so it runs where
  releases are prepared and is not part of this package. **What does ship is the
  test that holds the table below to the package**: every name it tells you to
  use has to exist, and every name it says is gone has to be.

  The first version of this paragraph cited that comparison as though you could
  find it. You could not, and a reader said so.

### Changed

- **A role is no longer inferred from an indicator's name.** `CONSISTENCY` and
  `RESPONSIVENESS` are about a KIND of quantity — a latency, a count, a
  percentage, a ratio — and the engine used to guess which from a substring of
  the indicator's name. `error_count` had a rule applied; `errors`, identical in
  every declared respect and given identical values, declined. Nothing on any
  queryable surface said which had happened.

  Unlike the walk above, **this one declines**: the cell reports `missing_role`
  and the `detail` names the declaration to write, and the load-time warning
  lists every pair that can never fire. So a model relying on the guess is told,
  at load and in the envelope, rather than quietly losing a check.

  Measured across the shipped packs before removing: eleven `(indicator, axiom)`
  pairs relied on the guess and none declared a role. All eleven declare one now
  and no coverage changed. Reported from outside.

- The did-you-mean that fires on an unrecognised word was **case-sensitive**,
  while every closed vocabulary it serves folds case on the way in. So a
  suggestion appeared only when your spelling's case happened to match the set's,
  and which case that was varied per key with nothing telling you. Measured
  across all seven vocabularies: every one asymmetric, five losing the suggestion
  on upper case and two on lower.

  It was worst at the key site, where case genuinely matters: `WARNING:` really
  is unread, lower-casing it is the entire fix, and that made it the one input
  the suggester had nothing to say about. Both sites now fold case to match and
  print the CANONICAL spelling.

- `CONSERVATION` no longer reports an unobserved output side as a system fault.
  The balance summed each declared output property and treated an absent one as
  zero, so a block naming a property the model does not supply produced
  `conservation_violation` at HIGH severity with a 100% deficit -- while the
  fault was the property name. Absent is not a measurement of zero.

  When **no** declared output property was observed in the window, the check now
  declines `missing_property` and names them. That is the mirror of the
  zero-input exit already in this checker: a deficit ratio has no value against a
  zero total, and a deficit has no value against an output side nobody observed.
  **Partial** absence deliberately still produces the finding, because it cannot
  be told from a legitimately sparse channel; it names what contributed nothing
  in the finding's reason.

  A check that answered from a guess now declines, which this document lists
  among the things a patch release may do. Found by probing which obligations the
  engine actually guards, after an outside method document asked the question.

- `BRIDGES.md` now says that a sample floor is a count taken inside a window, in
  the two places it previously spoke only of corpus size. Sizing a corpus past
  the floor is not sufficient: samples spread wider than the window never
  present it, so the corpus stays inside `insufficient_samples` and any fault
  injected into it is invisible. The guidance was reported incomplete from
  outside, by a reader who reproduced the omission faithfully in their own
  method document -- which is the evidence that the gap was ours and not theirs.

- `COMPATIBILITY.md` gains a bullet for the case this release hit: a check with
  no cell to decline on may be withdrawn if the envelope says so some other way.
  The test is that a withdrawn check must leave the envelope distinguishable from
  a clean pass — a report satisfies it, and a release note does not, because
  nothing reads a release note at runtime.

- The README's `The envelope` section named `problems`, `not_evaluated` and
  `evaluations_attempted`. Those are attributes of an internal result object that
  this distribution does not export; the envelope emits `findings`, `not_checked`
  and `checked.invariants`. All three are corrected, along with the same name in
  `SECURITY.md`. Also reported from outside, following the same review.

- **Forty-four names in this package cited a private tracker record; none do
  now.** Thirty-one begin with an underscore and are outside the contract at any
  version. **Thirteen do not**, and they are named here because a deep import of
  one gets a `NameError` and nothing to search for. Six are a field on a frozen
  record, so a constructor keyword and an attribute read move with them.

  | Was | Is | On |
  |---|---|---|
  | `emit_policy_per_cd1075` | `emit_policy` | `ProductionRCACandidate` |
  | `emit_policy_per_cd1098` | `emit_policy` | `ProductionAxiomVerdict` |
  | `emit_policy_per_cd1109` | `emit_policy` | `ProductionObservation` |
  | `emit_policy_per_cd1120` | `emit_policy` | `ProductionTemporalEdge` |
  | `emit_policy_per_cd1212` | `emit_policy` | `ProductionPrediction` |
  | `emit_policy_per_cd1277` | `emit_policy` | `ProductionTraversal` |
  | `classify_escalation_tier_per_cd1280` | `classify_escalation_tier` | `twin.traverser` |
  | `classify_escalation_tier_per_cd1291` | `classify_escalation_tier` | `twin.hypothesis_generator` |
  | `compute_traversal_severity_per_cd1282` | `compute_traversal_severity` | `twin.traverser_production` |
  | `severity_tier_for_traversal_severity_per_cd1282` | `severity_tier_for_traversal_severity` | `twin.traverser_production` |
  | `severity_tier_for_confidence_per_cd1293` | `severity_tier_for_confidence` | `twin.hypothesis_production` |
  | `severity_tier_for_pareto_per_cd1304` | `severity_tier_for_pareto` | `twin.optimization_production` |
  | `severity_tier_for_pipeline_per_cd1317` | `severity_tier_for_pipeline` | `twin.pipeline_production` |

  **None of the thirteen is on the eleven-name public API**, and the README
  places every deeper path outside what a version promises — so this is not a
  breaking change and is stated anyway. The reason is 0.1.9's, applied where it
  was not noticed rather than only where it was: a name citing a record you
  cannot read is the one claim on this surface that cannot be checked. Having
  given that reason once, doing the rest of it silently would have made the
  first entry a courtesy rather than a practice.

  They landed across two commits and neither wrote this entry. It is here
  because the omission was reported from outside, in a verification of the tree
  rather than of a release.

- `COMPATIBILITY.md`'s list of what is outside the contract said *anything whose
  name starts with an underscore* and nothing about depth. That is the document a
  pin points at, and by its own letter the thirteen names above were inside the
  contract while the README said they were not. The deep-path rule now appears in
  both, stated once and cross-referenced rather than copied, because the eleven
  names written down twice is the drift this repository keeps finding.

### Fixed

- **`traverse` raised `KeyError` on an unrecognised `direction`.** The argument
  went straight into an enum lookup, so a word the engine does not know left the
  library as an uncaught exception — naming an upper-cased token you never typed.
  Its sibling `value_mode` has always declined into an envelope. Both now do,
  and the refusal names what would have worked.

  **Both arguments also fold case now.** `direction` always accepted any
  spelling, as an accident of the same lookup; `value_mode` accepted only lower
  case. Nothing that worked before stops working — `value_mode` is the one that
  widens — and both answer in the canonical spelling.

  The valid directions are `forward`, `reverse` and `bidirectional`. If you were
  passing something else, you were getting an exception, not a traversal.

- **`role:` declared on an indicator was dropped by one of the two YAML
  loaders.** The model loaded clean, the field vanished, and until this release
  the name-guess supplied a rule anyway — so a model that declared the role
  correctly got the right answer for the wrong reason, and would have silently
  lost the check on upgrade. Both loaders now resolve the field through the same
  function. This is the defect the walk was hiding.

- **A mistyped `required_property` retired a check.** A topology statement can
  gate its cardinality check on a property the entity must carry, and the gate
  could not tell *the entity does not carry this property* from *it carries it
  falsy*. The second is what the gate is for; the first is a property name your
  model got wrong. So a typo turned a real cardinality violation into an empty
  result, reported as a clean pass, while `checked.invariants` counted the cell
  as attempted. It now resolves the name against the population — a name your
  model supplies resolves on somebody, a typo resolves nowhere — and declines
  `precondition_unmet` instead of passing.

- **`MONOTONICITY` answered with silence where its seven siblings decline.**
  Handed an indicator type it cannot reason about, it returned an empty list
  while every other axiom on the same shape reported something. Fixed with the
  sibling form verbatim, since the asymmetry was the whole defect, and pinned as
  a property over the axiom enum rather than as a case — so an axiom added later
  is covered without anyone remembering to add it.

- One cell could carry **two contradictory records in one envelope**: a finding
  applying the percentage rule, which IS a role, beside a decline saying no role
  could be inferred. `checked.invariants` counted the cell once while two records
  referenced it. Never released in that state; it existed between the two
  removals above and is recorded because the envelope's arithmetic is a claim
  this project makes.

---

## [0.1.9] — 2026-08-31

### Fixed — added 2026-09-02, after release

- **This entry was incomplete when it shipped.** One fix went out in 0.1.9 and is
  not in the notes below: the published override-reachability constants said
  `RESPONSIVENESS` accepts a per-entity threshold override and never reads it,
  and the runtime read it. `OVERRIDE_DECLARED_BUT_UNREACHABLE` is an exported
  name whose only purpose is telling you whether declaring an override is worth
  the trouble, so a wrong entry costs precisely the readers who consulted it —
  anyone who skipped an override that would have worked. `RESPONSIVENESS` now
  sits in `OVERRIDE_CONSULTED_BY`, which is where the runtime always had it, and
  a test drives each named path instead of restating the table.

  **It is recorded here rather than under a later version because it corrects
  something this project had already published.** A retraction filed under the
  next release reads as new behaviour, which is the wrong sentence for someone
  who acted on the old claim. If you removed a `RESPONSIVENESS` override on the
  strength of that constant, it works; put it back.

  Reported from outside, in a verification of this release.

### Added

- Every envelope's `meta` now carries `engine_version`: the version of the
  installed `arbiter-engine` distribution that produced it. It is **read from
  installed metadata, not written down** — a version literal here would be a
  second copy of the one in `pyproject.toml`, and a number written twice drifts.
  It is `null` when the engine runs from a source tree with no distribution
  installed: the envelope says it does not know rather than inventing a version,
  and the key is always present so a reader can branch on it.

  `schema/envelope.schema.json` gains the key as **optional**, and
  `schema_version` does **not** move. An envelope from an engine predating this
  key still validates, and a reader that ignores the key still works — which is
  the condition that revision number exists to signal.

- `BRIDGES.md`: how to write the program that feeds this engine, derived from the
  reasons it refuses to answer. The two worked implementations it points at are
  by this author, and it says so.

### Changed — BREAKING

- The module-level constant `CD508_ENTITY_PROPERTY_KEY` in `axiom_thresholds` is
  renamed to `AXIOM_THRESHOLD_OVERRIDES_KEY`, and the property key it holds
  changes from `__cd508_axiom_thresholds__` to `__axiom_threshold_overrides__`.
  **Both spellings are gone; there is no alias.** The old name cited a private
  tracker record, which is the one claim on this surface a reader could not
  check.

  Neither was on the supported eleven-name API, and no released consumer imports
  either — but a deep import of the constant, or code typing the old property key
  into `Entity.properties` directly, will break. **Use
  `EngineSession.set_threshold_override(entity_id, indicator, axiom, warning=…,
  critical=…)`**, which is the documented way to set a per-entity override and has
  been since 0.1.8.

### Fixed

- The load-time warning for `(indicator, axiom)` pairs that cannot evaluate under
  any input printed one blanket remedy — *declare a `role:` on the indicator* —
  for every pair. A `role:` does nothing for CONSERVATION, where the missing
  `conservation:` block is the fix. `unreachable_declarations()` had the right
  remedy per pair the whole time, so the two surfaces disagreed about one
  condition in a single process and the printed one was wrong. The warning now
  prints what the report computed.

- Piping `python3 -m arbiter_engine.scripts.benchmark_check` into a reader that
  stops early printed `Exception ignored` and a traceback over a benchmark that
  had in fact completed. It now exits with the conventional broken-pipe status.

- Comments and docstrings throughout this package cited an internal record by
  number. The step that removes those citations replaced each one with a stock
  phrase, which left sentences no reader could parse — *the established pattern
  native 2nd-landing*, and sixty more like it — and in three module docstrings
  the citation had been the grammatical SUBJECT, so removing it left a sentence
  opening on its own verb. That shape is described rather than quoted here: the
  check that now catches it cannot tell an erratum from the mistake it corrects.
  Every one of them now names the thing rather than the record.
  The description of `meta.source` in the published schema was the same defect
  in the one document a consumer validates against.

- Eight of those citations were not replaced at all and shipped intact,
  including one section heading in `evidence/`. The rule that removes them
  reads a single line, so a citation wrapped across two lines, or written with
  a hyphen, went straight through it.

---

## [0.1.8] — 2026-08-24

### Added

- **`homeostasis: {setpoint: N, tolerance: N}` on any numeric indicator.**
  Scores against a declared target instead of a learned baseline, with
  `tolerance_critical` defaulting to twice `tolerance`. A setpoint without a
  tolerance is refused and falls back — how far is too far is a fact about your
  system, not one the engine may invent.

  **Why it exists.** The learned baseline is a mean and spread over a window
  that *contains* the deviation, so a fault that persists walks the mean toward
  itself and inflates the spread; the score decays on both terms and the axiom
  goes quiet on a fault still running. Measured against the shipped example: a
  tank 30 points off its baseline fired at 5.4 sigma after two samples, 2.4
  after ten, and **nothing from about fifteen — no finding and no decline**. A
  declared target cannot be absorbed, and still fires at 240.

  **It also needs no history**, which removes the widest sample floor in the
  format: the learned path wants thirty observations inside a seven-day window,
  so a series sampled less often than roughly every six hours could never reach
  it.

- **`homeostasis: {must_return_within: <duration>}`**, which builds the baseline
  from samples older than that span — *did this come back inside my deadline*.
  **Its limit is documented rather than hidden**: it moves the absorption
  horizon out by the span, it does not remove it. Use it when you have a
  deadline and no target.

- **`monotonicity: {reversal_tolerance: N}` and `{reset_tolerance: N}`.** How
  many backward moves, and how many excused counter resets, before the axiom
  says anything. Both default to 3 — the value that was already in force —
  so nothing already written changes.

  **Why it exists.** That 3 was a global engine number: no model could state it,
  no document named it, and no envelope mentioned it, so an indicator declared
  `expected_direction: increasing` carried a silent allowance of **two backward
  moves**. A single counter rollback produced no finding and no decline.
  BOUNDEDNESS is correctly quiet at 84 against a declared `warning: 85`; the
  difference is that somebody declared the 85. Declare `reversal_tolerance: 1`
  for a counter where one rollback is a fault.

- **`flow: in` / `flow: out` on any numeric indicator.** Tells the traversal
  kernel which side of a balance a quantity sits on when it walks a flow cycle
  through the topology. The kernel holds no indicator spec, so it cannot read
  the `conservation:` block; before this it read the property NAME instead.
  Undeclared means the cycle balance is not computed, and the omission is
  reported as a `missing_declaration` gap naming the properties a name scan
  would have offered — surfaced, and asserted by nobody.
- **`missing_declaration` in `gaps[].gap_type`.** The model does not say
  something a check needs, and no amount of collecting data will supply it.
  Distinct from `missing_property`, which is answered by feeding the value.

### Changed

- **CONSERVATION no longer infers the other half of a balance from the property
  name.** An indicator declaring CONSERVATION with no `conservation:` block used
  to have an `_in` / `_received` / `_requests` / `input_` marker in its name
  rewritten to `_out` / `_sent` / `_responses` / `output_`, and was balanced
  against whatever property that produced. It now declines `missing_config` and
  names the block to write.

  **This makes a check stop firing, so here is the measurement behind it.**
  Across the shipped domain packs, nine indicators reached that path and
  **three of the nine named a partner property that does not exist in their own
  model** — no observations, so the balance fell into a bare return with no
  finding and no decline. A third of the time the inference produced the silent
  clean pass this engine exists to make impossible; the rest were correct by
  luck of an English naming convention. A model that wants the check declares
  the pairing, which every affected model could already have done.

- **`model_describe` reports CONSERVATION-without-a-block under
  `unreachable_declarations`.** It could not before: while the name fallback
  existed the pair *might* evaluate, so nothing could say in advance that it
  would not. An author now learns at load time rather than at cycle 1.

- **A conservation input total of zero declines instead of passing.** Same shape
  as the exit above it, found in the same function: the samples are present and
  a deficit ratio is undefined against a zero total, which is `not_applicable`
  and not a clean bill of health.

- **A HOMEOSTASIS baseline with zero spread declines instead of passing.** Third
  instance of that same shape, found the same way — by reading the function
  around the defect being fixed. A z-score is undefined when every baseline
  observation is identical; that is `not_applicable`, and whether a motionless
  series is itself a fault remains STABILITY's question via
  `expect_variation`.

- **The benchmark has a second axis, and the cost table has three rows of
  numbers instead of one.** Reported from outside as issue #8: *"How fast is
  it"* measured `check()` only, and a consumer's wall clock was dominated by
  getting the model in. Session construction was one `build` figure mixing a
  cost that is flat in the entity count with one that is linear; worse, loading
  scales with the size of the MODEL, an axis the benchmark did not have at all.
  `--model-sizes` adds it. On the development machine `load_model()` runs
  0.20 ms at 4 indicators and 11.6 ms at 360.

  **The parse is now measured beside the load, and it is the larger cost by
  more than an order of magnitude.** `load_model()` takes a mapping, so a
  consumer holding a YAML file pays `yaml.safe_load` first — at 180 indicators
  that is 164 ms against the load's 4.8 ms. Cache the parsed mapping rather than
  only the session, and use `yaml.CSafeLoader` where libyaml is installed: same
  result, 8.9x faster on this machine.

### Documentation

- **`agrees_with` now says redundancy is a claim about the system, not an
  inference from naming.** Reported from outside as issue #9 by an integrator
  who caught the trap in review: a part exposing `Name` and `Name1` may be
  reporting its own die and an external diode, which differ by tens of degrees
  on a healthy board. Pairing them by suffix makes the engine faithfully report
  disagreement between readings that were never supposed to agree — a false
  finding on every working machine, produced by a configuration rather than a
  fault. In the README beside the field, and in `MODELING.md`. **If a rule can
  generate the pairs, it does not know the pairs.**

---

## [0.1.7] — 2026-08-19

### Added

- **`lower_warning:` / `lower_critical:` on any numeric indicator.**
  `BOUNDEDNESS` takes a floor as well as a ceiling, and declaring both pairs on
  one indicator gives a band. Findings read `speed_rpm is below critical
  threshold` and carry `bound: lower` in their evidence, so a consumer needing a
  floor no longer feeds a negated property and translates the finding text back.
  A band whose floor sits at or above its ceiling is declined once as
  `missing_config` rather than firing on every reading forever.
- **`consistency: {agrees_with: [...]}` — redundant-signal agreement.**
  `CONSISTENCY` gains a second rule: two readings the model declares redundant
  must match, within `tolerance:` (relative) or `tolerance_absolute:`. It runs
  regardless of `role:`, because a redundant pair of temperature sensors carries
  no role. A declared peer the entity does not carry is reported in
  `not_checked`, never skipped.
- **Timestamped observations.** `add_observations` accepts
  `[(when, value), ...]` alongside the existing bare-reading form. `when` may be
  a `datetime` (naive or aware) or a POSIX timestamp; **aware values are
  converted to UTC, not stripped**. Mixed shapes in one call raise rather than
  being guessed between.
- **`stability: {detect_slow_oscillation: true}`.** The shipped oscillation
  detector is period-2 by construction, so a controller hunting on a four-, six-
  or eight-sample period scored zero and read as maximally stable. The new arm
  counts mean-crossings across the whole window and reports the period it
  measured. Opt-in, because a day/night thermal swing and a duty-cycled
  compressor are correctly periodic.
- **Three MCP feeder tools** — `load_model`, `add_entity`, `add_observations` —
  and a `--model` argument on the server. The five existing tools were a read
  surface over a session nothing could fill, so every one of them answered
  `no domain model loaded` forever unless the operator wrote a custom launcher.
- **`meta.schema_version` in every envelope**, and a JSON Schema for the shape
  at `schema/envelope.schema.json`.
- **This file, and `COMPATIBILITY.md`.**
- **Two more worked models.** `examples/kubernetes_node.yaml` is the smallest
  domain where a band matters; `examples/battery_pack.yaml` one where nearly
  every bound is a floor somebody published. Both ship at the tree root and
  under the package, as `water_tank.yaml` does.
- **A scale benchmark**, `arbiter_engine.scripts.benchmark_check`. No public
  number existed for `check()` latency, so a consumer sizing an integration had
  to guess.

### Changed

- `EngineSession.set_threshold_override` and `unread_threshold_overrides` (added
  0.1.6, see below) are unchanged; the reachability table they document now
  ships beside the resolver.
- The modelling guide's rule *BOUNDEDNESS is for upper bounds only* is replaced
  by *a floor is a specification, not a guess*. The advice it was giving survives
  — do not invent a floor for a metric where nobody published one — but its
  mechanism was the engine's limitation rather than the modelling principle.
- One test file in the sdist is renamed. Its name ended in an internal ticket
  number, which should never have reached this repository; the tooling that
  strips such references from file CONTENT reads bytes out of files and never
  reads their names. No importable name changed.

### Fixed

- `BOUNDEDNESS` no longer declines `no_threshold` for an indicator declaring
  only a floor, which would have been a finding and a decline in one pass.

---

## [0.1.6] — 2026-08-16

### Added

- `EngineSession.set_threshold_override`, so per-entity axiom calibration is
  reachable without knowing an undocumented sentinel property name, and
  `unread_threshold_overrides`, which names any override nothing will read.
- `role:` on an indicator, replacing name-token guessing for `CONSISTENCY` and
  `RESPONSIVENESS`. Inference from the name is kept for existing models and now
  announces itself.
- `expect_variation:` and the `frozen_series` finding — a live measurement that
  has stopped moving previously produced an envelope byte-identical to a healthy
  one.
- `unread_fields` and the `unknown_key` leg in `model_describe`, so a field
  nothing will read is reported at load rather than discovered at cycle one.
- `no_current_value` as a distinct decline reason.

### Fixed

- The documented quickstart raised `FileNotFoundError` for every installing
  reader: the second code block opened `examples/water_tank.yaml` on a relative
  path that exists in a clone and not in a wheel. Live since the install line
  stopped saying `git clone`, and shipped in two releases.
- The README's Status section said *Not published to any index yet* a hundred
  lines below its own `pip install` line.
- Ten subjectless clauses, nineteen dedented docstring lines and a corrupted
  code literal, all from the scrub that produces the public tree.
- The README's decline call-site count, from 15 to 24.

---

## [0.1.5]

Released. The record for this version is thin — see the note at the head of this
file. What is documented is what it carried WRONG, because the next release's
notes are where those were written down: the broken quickstart, the *not
published to any index* line, and the scrub-seam damage listed under 0.1.6.

---

## [0.1.4]

Released. Same provenance note as 0.1.5.

---

## [0.1.1]

### Fixed

- `[project.urls]`, `authors` and `keywords` were absent, so a visitor who found
  the package **could not reach the repository from it**. The link was
  one-directional: GitHub to PyPI worked, PyPI to GitHub did not.
- The README described the package as an extraction from an earlier stage of this package,
  and quoted that tree's file count.
- The README's Status line stated an import count that a paragraph below
  described as the count that had been wrong.

None of these could reach 0.1.0: **PyPI metadata and files are immutable per
version**, and yanking hides a release rather than freeing the number. That is
the whole reason 0.1.1 exists.

---

## [0.1.0]

First upload. Eight axiom checkers, the five-verb API, the three-part envelope,
topology traversal, an MCP transport, a YAML domain-model loader; `numpy` and
`pyyaml`, with `rdflib`, `scipy` and `mcp` as extras.

---

## Version numbers that do not exist

**0.1.2, 0.1.3, 0.2.0, 0.2.1, 0.2.2 and 0.3.0 are permanently unavailable** and
were never published by this project. The set is NOT a contiguous range and
cannot be extrapolated: 0.2.3 was free while 0.3.0 was not. PyPI reserves any filename that has ever been used and
deleted, including from an earlier owner of the name, so an upload under those
numbers returns `400 This filename was previously used by a file that has since
been deleted`. The sequence runs 0.1.1 to 0.1.4, and 0.1.18 to 0.2.3, for that
reason and no other.

**0.2.1, 0.2.2 and 0.3.0 were added to this list by trying them**, and that is
the point worth keeping. Until 2026-09-18 this paragraph named three numbers and
then predicted a fourth: *the version that first breaks compatibility cannot BE 0.2.0 — the number
is unavailable — so it will be 0.2.1.* The three were measured; the fourth was an
inference from them, and the release that needed it found it false at the upload.

**There is no way to check a filename except by uploading.** A 404 does not mean
free, the JSON and `/simple/` surfaces list only what is live, and a deleted
release leaves no trace either serves. So a number in this list was measured and a
number predicted from it was a guess wearing the same sentence — which is why the
prediction is gone rather than re-pointed at the next number.

**This matters to anyone pinning `<0.2`.** That ceiling stops at 0.1.18 and does
not resolve the 0.2 series at all. Move it to `<0.3` deliberately; a tool or a
human reading the gaps in this list should not conclude that a 0.2.0 or a 0.2.1
exists somewhere.
