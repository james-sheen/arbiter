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

Nothing yet.

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

**0.1.2, 0.1.3 and 0.2.0 are permanently unavailable** and were never published
by this project. PyPI reserves any filename that has ever been used and deleted,
including from an earlier owner of the name, so an upload under those numbers
returns `400 This filename was previously used by a file that has since been
deleted`. The sequence runs 0.1.1 to 0.1.4 for that reason and no other.

**This matters to anyone pinning `<0.2`.** The version that first breaks
compatibility cannot BE 0.2.0 — the number is unavailable — so it will be 0.2.1.
A pin of `>=0.1.7,<0.2` still does what you want; a tool or a human reading the
gap in this list should not conclude that a 0.2.0 exists somewhere.
