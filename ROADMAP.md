# Arbiter Roadmap

Arbiter is a detection engine that reports what it did not check. This roadmap names what has happened and what is next. Milestones that have passed are marked as such rather than left reading as forthcoming.

## Alpha — closed June 2026

Substrate exercise window. A live LLM-serving endpoint with content moderation, rate limiting, and per-axis observability ran against a synthetic load generator under scheduled fault windows. Findings, cascade behaviour, and substrate gaps informed the closed-loop iteration that followed.

## the second evaluation round — Closed-Loop Alpha — closed July 2026

Detection, planning, and action loops closed end-to-end. Multi-tenant load shaping and cascade dynamics were the focus.

## Open the engine — landed August 2026

`arbiter-engine` is extracted and is what this repository ships: the eight axiom checkers, the domain-model format and its loader, the traversal kernel and its live modes, the gap surface, and the tool surface over them. Apache 2.0, DCO, no CLA.

This section read *"Next — open the engine. The current work is extracting..."* until 2026-08-11, describing as forthcoming the thing a reader had already cloned. Corrected against the rule at the top of this file — *milestones that have passed are marked as such rather than left reading as forthcoming* — which this file stated and then broke. A roadmap is read by people deciding whether the project is alive; one that calls a shipped thing upcoming answers that question wrongly in both directions at once.

## Published to an index — landed August 2026

`arbiter-engine` installs from PyPI with `pip install arbiter-engine`, and six worked domain models ship in `examples/`.

The count above read *five* until 2026-09-20, when the sixth example had already shipped — the same failure a third time, and caught by the release-day tripwire rather than by a reader. It is recorded here on the rule the paragraph below states: dated, not corrected quietly.

Until 2026-08-24 this file carried both of these under a *Next* heading — it denied the package was on any index, and it counted the examples at one. Both were false when they were read: the package had been on the index since 0.1.0, and the third example shipped alongside it. The corrections are dated rather than made quietly, because this is the second time this file has described a shipped thing as forthcoming — the section above records the first — and the pattern matters more than either instance.

A checkable false claim, in the status document of a project whose subject is checkable claims. It survived because the release-day checks that hold `README.md` and `CITATION.cff` to the artifact did not reach this file. They do now — though not here: the check runs in the derivation this repository is published from, so a reader holding only this tree cannot run it and should not take the sentence on trust. It is a plain absence test, which is why the two retired sentences are described above rather than quoted. A quoted correction and the mistake it corrects are the same string to a checker, and a project that files this defect class cannot also be the one whose tripwire fires on its own erratum.

## A declared world model — landed September 2026

The engine carries dynamics an author declares and steps a model forward through them. A `transition:` on a relationship rule says which property drives which and by how much; a `temporal:` block says how long a change takes to arrive and how quickly it settles once it does. `rollout` walks a model across a horizon under scheduled actions and returns the trajectory rather than an endpoint; `plan` ranks declared candidate settings against a declared objective; `model_describe` reports the gains the observations imply. A durable prediction ledger keeps what was projected, so a projection can be graded once the world has caught up with it.

The line here is the one the rest of the engine holds. Nothing fits a coupling nobody declared, a gain the observations imply is a proposal until an author adopts it, and the delays and time constants are read from the model rather than learned from the series. An indicator with no declared model is refused by name instead of having a curve fitted to it.

This section was written the day after the release it describes, rather than months later. That is the entire content of the two corrections recorded above, and it is easier to state as a rule than to keep.

## Next — no date

Cross-time drift for a single unit, now that ingestion carries timestamps; a characterization of what MONOTONICITY does and does not catch, before any scenario asserts a verdict it has not demonstrated; and declared spatial topology, carried by `relationship_types` when its day comes.

No date is given here. Earlier versions of this file named a General Availability window that arrived without the milestone, which is the failure this section is written to avoid — a roadmap that promises a quarter and then quietly keeps promising it says less than one that names the work and no date.

## Stability commitments

The public-facing API surface is pre-1.0 and continues to evolve; breaking changes can land in any release. Long-term API stability is not yet committed.

Historical benchmark figures (95.8% technical accuracy, under-15s P95) belong to the **Stage I OpenBMC reference vertical, measured 2025**. Stage I is archived and not running, so those numbers are history and are not claims about the current engine. `README.md` states the same archived status.

## Public participation

- Issue intake: open (see CONTRIBUTING.md)
- Documentation pull requests: open
- Code pull requests: not yet — one maintainer, no second reviewer; see CONTRIBUTING.md
