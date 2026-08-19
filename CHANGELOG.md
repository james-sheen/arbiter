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

### Changed

- `EngineSession.set_threshold_override` and `unread_threshold_overrides` (added
  0.1.6, see below) are unchanged; the reachability table they document now
  ships beside the resolver.
- The modelling guide's rule *BOUNDEDNESS is for upper bounds only* is replaced
  by *a floor is a specification, not a guess*. The advice it was giving survives
  — do not invent a floor for a metric where nobody published one — but its
  mechanism was the engine's limitation rather than the modelling principle.

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
