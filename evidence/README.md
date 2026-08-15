# What these documents are

**These are dated records of an evaluation that ran in June and July 2026, of a
larger system than the one in this repository.** They are preserved, not
maintained.

You have the engine: `arbiter_engine`, eight axiom families over a domain model
declared in YAML. The evaluation these documents describe exercised the engine
inside a platform that also had ingestion, a scheduler, an action dispatcher, an
approval surface and a live deployment to observe. **That platform is not
published.** Where a document names a component you cannot find, it is naming
part of that platform, and its absence is the normal case rather than an
oversight.

## Why they are here at all

Because of what they contain. The evaluation produced results that went against
the project, and they were written down at the time rather than afterwards:

- **0 of 16** surprises were surfaced by the detector when they happened. A human
  found all sixteen. A later replay put the machine-flagged count at 3 of 16 on
  instrumentation the platform did not have at the time.
- A performance claim held under one traffic regime and **failed under sustained
  load**, and the record shows it being scope-qualified rather than quietly
  amended.
- Several conclusions are marked as resting on a single run.

An engine whose stated purpose is reporting what it did not check should be able
to show the same discipline applied to itself. That is the reason to read these,
and it is the reason they are not being rewritten.

## How to read them

- **Everything is dated.** Take the date as the claim's scope. Nothing here has
  been re-run since.
- **They address the audience they were written for.** Some open by naming a
  reader who was being evaluated as a partner. That track is closed and this
  repository has no commercial channel; those lines are historical, and where one
  still reads as a live offer it is a defect worth reporting.
- **They cite records that are not published.** Named for provenance so a claim
  can be checked against a specific document on request, not as links.
- **They are not documentation of the engine.** For that, read the top-level
  `README.md` and `examples/water_tank.yaml`.

## What would change this

If the held components are published, these documents stop describing an absent
system and should be re-audited as documentation rather than kept as a record. If
anything in this directory starts being edited for content rather than to correct
a false claim, it has stopped being a record and this preface has stopped being
true.
