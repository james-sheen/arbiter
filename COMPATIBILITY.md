# Compatibility

What a release of `arbiter-engine` may change, and what waits.

A consumer pinning `>=0.1.7,<0.2` is making a statement about the **wire shape** —
the envelope every tool returns and the YAML every model is written in. This
document says what that pin is worth.

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
| **Package version** | anything ships — a fix, a docstring, a new axiom parameter | `arbiter-engine==0.1.7` |
| **`meta.schema_version`** | a reader that worked stops working | `envelope["meta"]["schema_version"]` |

They are separate because tying them would make every patch release look like a
contract change, and a version field that cries wolf is one people stop reading.
Most releases move the first and not the second.

The schema itself is at [`schema/envelope.schema.json`](schema/envelope.schema.json).

## What a PATCH release may change

- **Add a key** to any envelope leg, to `meta`, or to a tool's payload. Every
  reader here is a lookup, and additive keys are the normal way this envelope
  grows — `unread_fields`, `unconsumed_observations` and
  `unread_threshold_overrides` all arrived this way.
- **Add a member to `not_checked[].reason`.** Read that enum as three-valued: a
  member you do not recognise means this engine is newer than your reader, not
  that the record is malformed. A reader that switches exhaustively over it and
  raises on the default will break, and that is the reader's bug — the set has
  grown four times.
- **Add an axiom, an indicator field, or a nested config block.** A model
  written before the field keeps its behaviour; that is a rule this project
  enforces on itself, not a courtesy.
- **Change a `problem_type` that did not exist in the previous release.**
- **Change finding text, decline `detail` text, and evidence values.** These are
  for humans and for logs. Matching on them is understandable and unsupported —
  if you need to branch, branch on `axiom`, `severity`, or the part of
  `problem_type` before the colon.
- **Make a check FIRE where it was previously silent**, when the previous
  silence was a defect. Every such change is listed in the changelog. This is
  the one that will surprise people, and it is deliberate: an engine whose
  product is *did you look* cannot treat closing a blind spot as a breaking
  change, or the blind spots become permanent.

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
- **Renaming or removing a tool**, or making an optional argument required.
- **Raising the minimum Python version.**

## What is NOT part of the contract, at any version

- Anything whose name starts with an underscore.
- `evidence` dict *contents* beyond the keys the schema names. Evidence is what
  the engine happened to know when it fired.
- Log output, log levels, and the exact wording of any message.
- The order of `findings`, `not_checked` or `questions`. Sort them yourself if
  you need determinism.
- `AxiomParameters` defaults. They are calibration, they are tuned against real
  data, and a release that improved one would otherwise be breaking.

## A number you cannot have

**0.2.0 is permanently reserved on PyPI** and was never published by this
project — the index reserves any filename that has ever been used and deleted,
including from an earlier owner of the name. The first release that breaks
compatibility will therefore be **0.2.1**.

A pin of `<0.2` still does exactly what you intend. Nothing will ever be
published as 0.2.0, so nothing can slip under such a pin.

## If something breaks anyway

Open an issue with the envelope, its `meta.schema_version`, and the version you
came from. A break that this document says should not have happened is a defect
in the release, not in your reader — and the report is worth more to this project
than the workaround is to you.
