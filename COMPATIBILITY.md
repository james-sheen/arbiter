# Compatibility

What a release of `arbiter-engine` may change, and what waits.

A consumer pinning `>=0.2.4,<0.3` is making a statement about the **wire shape** —
the envelope every tool returns and the YAML every model is written in. This
document says what that pin is worth.

The example pin above read `>=0.1.7,<0.2` until 2026-09-23, which was current
when it was written and had since become the one ceiling this document warns
about at the bottom. It was found by the test that now holds the two ends of
this file together, not by a reader — and a stale pin in the opening line of
the document a pin points at is worth more than the two words it took to fix.

## The motivating incident, stated first

**The describe payload's nesting moved between releases, silently.** A consumer
who had written a reader against the earlier layout got `None` back from a
lookup that had worked, which reads as *this engine does not support that* rather
than *this moved*. They wrote a tolerant reader that tried both locations, which
is the correct defensive move and is also a cost this project imposed by having
no policy and no version field.

Nothing in the package said which shape you had. That is what
`meta.schema_version` fixes, and this document is the sentence it needs beside
it.

## Two version numbers, deliberately

| | Moves when | Where |
|---|---|---|
| **Package version** | anything ships — a fix, a docstring, a new axiom parameter | `arbiter-engine==0.2.4` |
| **`meta.schema_version`** | a reader that worked stops working | `envelope["meta"]["schema_version"]` |

They are separate because tying them would make every patch release look like a
contract change, and a version field that cries wolf is one people stop reading.
Most releases move the first and not the second.

The schema itself is at [`schema/envelope.schema.json`](schema/envelope.schema.json).

## The sub-envelope

A tool that runs a DISCIPLINE — `forecasts`, `shadow`, `projection`,
`entailment`, `inference`, `discovery` — mounts its own report as a payload key
beside the legs,
in the same four-part shape: `checked`, `findings`, `not_checked`, `questions`,
plus a `meta` carrying `source`. The shape is in the schema as
[`$defs/sub_envelope`](schema/envelope.schema.json), so a consumer has
something to validate against rather than a field list read out of the engine's
source.

**`simulation` and `plan` are two more, and this sentence did not say so.** The
six named above are the ones built through the shared type; `rollout` and `plan`
build theirs on another path and arrive in the same four-part shape with extra
keys beside it — `per_step` and `tier` on one, `ranked`, `candidates`, `best`,
`objective` and `direction` on the other, `assumptions` on both. The schema has
declared all of that for two releases, as `$defs/simulation_envelope`,
`$defs/plan_envelope`, `$defs/simulation_step` and `$defs/plan_candidate`, while
this paragraph listed six disciplines and stopped. An outside review read the
gap the way it reads — as the two verbs a consumer reaches `rollout` and `plan`
through being governed by nothing here — and asked for the whole package to be
marked experimental. The package under them is unpromised for the ordinary
reason, two bullets down: it is deeper than the public API. **Their payloads are
not**, they are returned by supported names, and the promises above apply to
them exactly as written. Validate against the schema, which was right first.

**`execution` is the third of that kind**, returned by `file_action`:
the same four-part shape, with the recorded execution's `id`, `action`,
`parameters`, `executed_at` and `basis` beside it, and the ledger's `calibration`.
Its decline reasons are the `simulation` vocabulary's. It is declared as
`$defs/execution_envelope`, and the promises above apply to it as written.
**`case` and `cases` are two more of that kind**: `open_case` and `attach_stage`
return the case as it stands in `case`, and `case_book` returns every case with
its counts in `cases`, declared as `$defs/case_envelope` and
`$defs/case_book_envelope`, with the same vocabulary and the same promises.

Three things about it are promises and not accidents:

- **Its `checked` is never summed with the top-level one.** That counts axiom
  evaluations; a discipline's counts rules, series, queries or forecasts.
  Adding them gives a number that is true of no process.
- **Its `not_checked[].reason` comes from that discipline's own closed
  vocabulary**, not the axiom one. The sets are separate on purpose, and
  reading a reason from one against the other is how a closed enum stops being
  evidence about anything. Each is three-valued in exactly the way the axiom
  enum is: a member you do not recognise means this engine is newer than your
  reader.
- **A leg is present only on the verb that produces it**, and is never
  required. An envelope from an engine that predates a discipline validates.

## What a PATCH release may change

- **Add a key** to any envelope leg, to `meta`, or to a tool's payload. Every
  reader here is a lookup, and additive keys are the normal way this envelope
  grows — `unread_fields`, `unconsumed_observations` and
  `unread_threshold_overrides` all arrived this way.
- **Add a sub-envelope**, on the same argument — `shadow` arrived that way,
  after a release in which the shadow run happened, declined, and had every
  part of its report except the findings discarded before the caller saw it.
- **Add a member to `not_checked[].reason`.** Read that enum as three-valued: a
  member you do not recognise means this engine is newer than your reader, not
  that the record is malformed. A reader that switches exhaustively over it and
  raises on the default will break, and that is the reader's bug — the set has
  grown four times.
- **Add a member to a DISCIPLINE's decline vocabulary**, on the same argument
  and with the same three-valued reading. Spelled out because the entry above
  names the axiom enum and reads as covering only it: the sets are separate,
  and a reader that switches over `payload.shadow.not_checked[].reason` needs
  the same default branch. `not_a_producers_submission` arrived this way,
  turning a zero denominator that had been reported with no reason beside it
  into one that names what it set aside and whose it was.

  - **and the sets this rule permits growing are now published.**
  `BRIDGES.md` Sec. 2a carries all seven, ninety-three names, derived from
  `subenvelope.py` rather than transcribed beside it. Until then this entry had
  the defect that an internal ruling closed one bullet down, and closed first: a consumer told a
  set may grow in a patch release had no baseline to diff the growth against,
  and this one was worse, because the entry above it also tells that consumer
  the sets are SEPARATE and not to read a reason from one against another --
  advice nobody could follow. The outside review that found the stamps found
  this too, in the same way: it listed five closed vocabularies under a heading
  naming the engine's trust surface, and none of these seven were among them.
  The schema stays as it is, declaring no `enum` on a sub-envelope's
  `not_checked[].reason`, for the reason given below -- an enum would make
  every addition this rule permits a change to the wire contract.
- **Add a stamp to an `assumptions` list**, with the same three-valued
  reading as the two entries above. Spelled out because those name enums of
  REASONS and a stamp is a value in a list, so a reader could take the list as
  closed: it is not, and the sets are separate again.
  `time_course_not_declared` arrived this way, naming the one assumption in
  that list a reader can remove by editing their own model -- the engine's own
  60 s dead time and time constant, standing in wherever a `temporal:` block
  was absent or short of a key.

  - **and the list this rule permits growing is now published.**
  `MODELING.md` carries every stamp the engine emits and what each one
  discloses, derived from the engine's own vocabulary rather than transcribed
  beside it. Until then this rule stood alone: a consumer told the list may
  grow in a patch release had no baseline to diff the growth against, and the
  stamps existed only as bare literals at twenty sites in four modules. An
  outside review reproduced all three of this engine's ENUMERATED vocabularies
  exactly and reported this one at nine of twenty. `envelope.schema.json` now
  declares `assumptions` as an array of string and deliberately WITHOUT an
  `enum`, so that this permission stays real -- an enum would make every
  addition a schema change, and could not express the one stamp that carries a
  property name.

- **Add an axiom, an indicator field, or a nested config block.** A model
  written before the field keeps its behaviour; that is a rule this project
  enforces on itself, not a courtesy.
- **Change a `problem_type` that did not exist in the previous release.**
- **Prefix a finding drawn from a value the engine IMAGINED rather than read.**
  Added at 0.2.3 with `imagined_`. A what-if that pushed a reading past a
  declared line used to return the same `problem_type` as a reading that was
  actually past it, so a consumer routing on the type could not tell an
  incident from a simulation. Findings about real readings are untouched, and
  the rule is per-VALUE rather than per-verb: a hypothetical traversal reads
  most of the topology at its current reading, and a finding drawn from a real
  reading stays unprefixed whichever verb found it. `forecast_` is the sibling
  prefix for a forecast a PRODUCER supplied and is deliberately not reused —
  one prefix for both would make `forecast_boundedness:x` mean two different
  things depending on which verb produced it.
- **Change finding text, decline `detail` text, and evidence values.** These are
  for humans and for logs. Matching on them is understandable and unsupported —
  if you need to branch, branch on `axiom`, `severity`, or the part of
  `problem_type` before the colon.
- **Make a check FIRE where it was previously silent**, when the previous
  silence was a defect. Every such change is listed in the changelog. This is
  the one that will surprise people, and it is deliberate: an engine whose
  product is *did you look* cannot treat closing a blind spot as a breaking
  change, or the blind spots become permanent.
- **Make a check DECLINE where it previously answered from a guess**, when the
  guess was unsound. Every such change is listed in the changelog, with the
  measurement behind it. Added 2026-08-24, because the rule above did not cover
  the case and the case arrived: CONSERVATION was pairing properties by
  rewriting a marker in their names, and a third of the models that reached
  that path were being balanced against a property they do not declare.

  This bullet is the same sentence as the one above it, pointing the other way.
  Both say the engine's product is *did you look*, and a wrong answer fails that
  test exactly as a missing one does — a consumer who acts on a finding derived
  from a guessed pairing is worse off than one told the model is incomplete. The
  cost is real and is stated rather than argued away: a model relying on the
  guess loses the check until it declares what balances what, and the decline
  names the declaration to write. **What a patch release may NOT do is go quiet
  — a check withdrawn without a decline is indistinguishable from one that
  passed**, and that is the outcome this whole document exists to prevent.

- **Withdraw a check that has no decline to give, if the envelope says so some
  other way.** Added 2026-09-02, because the rule above was written assuming the
  withdrawn check always has a cell to decline on, and the case arrived where it
  does not. A decline record names an indicator and an axiom; the check this
  applies to judged properties **nobody declared**, which have neither, and
  inventing them would mean reading the axiom out of the property's name — the
  guess being withdrawn. So `check` gained the `unread_properties` report, and a
  reader diffing two releases sees the values move from `findings` into a leg
  that says nothing looked at them. The changelog entry names the release.

  This is a narrower permission than it looks, and the test is the sentence
  above rather than the word *decline*: a withdrawn check must leave the
  envelope **distinguishable from a clean pass**. A report satisfies that. An
  empty envelope does not, whatever else the release documents — and a release
  note is not an envelope, because nothing reads it at runtime.

## What waits for a MAJOR release

- **Removing or renaming an envelope leg**, or any of `checked.invariants`,
  `checked.entities`, `meta.source`.
- **Relocating a value** — the incident above, in one line.
- **Changing what a field MEANS while keeping its name.** `checked.invariants`
  has meant declarations, traversal steps and matched findings in different
  places in this engine's past; each of those was a defect, and each fix was a
  behaviour change a careful consumer would want announced.
- **Removing a member from `not_checked[].reason`**, or from the `severity` /
  `axiom` enums.
- **Removing an indicator field, or changing its default.**
- **Renaming or removing an `AxiomParameters` field.** A model declares them by
  name under `axiom_parameters:`, so a renamed field would turn a declaration
  into an `unknown_key` and quietly restore the default it was written to
  replace. Their default VALUES remain calibration, below.
- **Renaming or removing a tool**, or making an optional argument required.
- **Raising the minimum Python version.**

## What is NOT part of the contract, at any version

- Anything whose name starts with an underscore.
- **Any import deeper than the names the README lists as the public API.** Those
  paths are importable and unpromised, and they may move in a patch release. The
  list lives in the README and is deliberately not copied here: it is a
  vocabulary, and this project has been bitten more than once by a second copy
  of one drifting from the first.

  This bullet is recorded late. A release renamed thirteen deep names that do
  not start with an underscore, which the README permitted and this document —
  the one a pin points at — did not mention. Both documents had the same policy
  and only one of them said so.
- `evidence` dict *contents* beyond the keys the schema names. Evidence is what
  the engine happened to know when it fired.
- Log output, log levels, and the exact wording of any message.
- The order of `findings`, `not_checked` or `questions`. Sort them yourself if
  you need determinism.
- `AxiomParameters` defaults. They are calibration, they are tuned against real
  data, and a release that improved one would otherwise be breaking.

## Numbers you cannot have, and what that does to your pin

**Several version numbers are permanently unavailable on PyPI** — the index
reserves any filename that has ever been used and deleted, including from an
earlier owner of the name. The list is in the changelog, under [Version numbers
that do not exist](CHANGELOG.md#version-numbers-that-do-not-exist), and is
deliberately not copied here for the reason the bullet above gives about the
public API: a second copy of a list drifts from the first.

**This section carried such a copy, and it drifted.** It named one reserved
number and then PREDICTED which version the next breaking release would carry —
an inference from measured numbers rather than a measurement. The release that
needed that number found the prediction false at the upload. The changelog
dropped it; this file kept it, and a pin points at this file, so the stale half
was the half consumers read. The retired sentence is described here rather than
quoted: this project runs absence tests over its own errata, and a correction
that reproduces the string it corrects is the same string to the checker.

**A pin of `<0.2` does NOT do what it looks like it does.** That ceiling stops
at 0.1.18 and never resolves the 0.2 series at all, so a consumer holding it
sees no release made since. If you want the 0.2 line, move the ceiling to
`<0.3` deliberately — and read the changelog list first, because the gaps in it
cannot be extrapolated.

## If something breaks anyway

Open an issue with the envelope, its `meta.schema_version`, and the version you
came from. A break that this document says should not have happened is a defect
in the release, not in your reader — and the report is worth more to this project
than the workaround is to you.
