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
