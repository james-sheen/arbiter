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
