---
name: Bug report
about: The engine reported something you believe is wrong
title: ''
labels: bug
assignees: ''
---

## Before you write it up: read the declines

`check()` returns four legs, and the answer is in `not_checked` more often than
in `findings`. An axiom that declined did not fail — it reports a
machine-readable reason for why it could not run, and that reason is usually the
whole story.

Three that account for most surprises:

- **`not_applicable`** — `CONSISTENCY` and `RESPONSIVENESS` apply to a KIND of
  quantity, and the model says which by declaring `role:` on the indicator. With
  no `role:`, the engine falls back to reading the name — `count`,
  `percent`/`pct`, `ratio` for one; `response` or `latency` for the other. If an
  indicator you expected to be checked was not, declare its role rather than
  renaming it. The fallback is for models written before the field existed.

  **If no role fits your quantity, that is the answer rather than a puzzle.**
  The vocabulary is `count`, `percentage`, `ratio`, `latency`; a temperature is
  none of them, and declaring one anyway makes the check run and assert
  something untrue about your units. `CONSISTENCY` is a single-value
  plausibility check, so an indicator whose plausible range is not one of those
  four has nothing for it to test. Note it does **not** compare one indicator
  against another — to check that two readings agree, compute the difference in
  your adapter and give the engine that.
- **`no_current_value`** — the value is present, in the store this checker does
  not read. Threshold axioms read the entity's `properties`; temporal axioms read
  observation history. The decline names the observation count it can see.
- **`insufficient_samples`** — the floor is per-axiom, and the decline states
  both the count it had and the count it needed.

If the decline explains it, you may not have a bug. Please open the issue
anyway if the *reason* was unclear — a decline nobody can act on is a defect in
its own right.

## What happened

<!-- One sentence. -->

## What you expected

<!-- Including which axiom you expected to fire, or to stay quiet. -->

## The model

<!-- The smallest domain YAML that shows it. Trim to the one entity type and
     the one indicator if you can. -->

```yaml

```

## How the session was fed

<!-- Threshold axioms read the entity's `properties`; the temporal axioms read
     observation history. Feeding only one is the commonest cause of a check
     that reports nothing while a value is plainly out of range — so please
     show both. -->

```python

```

## The envelope

<!-- ALL FOUR LEGS of check(). `not_checked` especially, verbatim. -->

```json

```

## Environment

- `arbiter-engine` version or commit:
- Python version:
- OS:
- Optional extras installed (`scipy`, `rdflib`, `mcp`): <!-- these change which
  modules import, so a difference here can change what you see -->

## Anything else

<!-- When it started, a workaround you found, a related issue. -->

---

**Security vulnerabilities do not belong here.** Use the private channel in
[SECURITY.md](../../SECURITY.md).
