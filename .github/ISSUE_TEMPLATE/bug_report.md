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

Two that account for most surprises:

- **`not_applicable`** — some axioms decide whether they apply by reading the
  indicator's name. `CONSISTENCY` wants `count`, `percent`/`pct` or `ratio` in
  it; `RESPONSIVENESS` wants `response` or `latency`. This is a known rough
  edge, not a rule you were supposed to infer.
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
