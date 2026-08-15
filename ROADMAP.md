# Arbiter Roadmap

Arbiter is a detection engine that reports what it did not check. This roadmap names what has happened and what is next. Milestones that have passed are marked as such rather than left reading as forthcoming.

## Alpha — closed June 2026

Substrate exercise window. A live LLM-serving endpoint with content moderation, rate limiting, and per-axis observability ran against a synthetic load generator under scheduled fault windows. Findings, cascade behaviour, and substrate gaps informed the closed-loop iteration that followed.

## the second evaluation round — Closed-Loop Alpha — closed July 2026

Detection, planning, and action loops closed end-to-end. Multi-tenant load shaping and cascade dynamics were the focus.

## Open the engine — landed August 2026

`arbiter-engine` is extracted and is what this repository ships: the eight axiom checkers, the domain-model format and its loader, the traversal kernel and its live modes, the gap surface, and the tool surface over them. Apache 2.0, DCO, no CLA.

This section read *"Next — open the engine. The current work is extracting..."* until 2026-08-11, describing as forthcoming the thing a reader had already cloned. Corrected against the rule at the top of this file — *milestones that have passed are marked as such rather than left reading as forthcoming* — which this file stated and then broke. A roadmap is read by people deciding whether the project is alive; one that calls a shipped thing upcoming answers that question wrongly in both directions at once.

## Next — no date

Not on a package index yet, and the domain-model library is one worked example rather than a set. Both are named here without a date, for the reason the section below gives.

No date is given here. Earlier versions of this file named a General Availability window that arrived without the milestone, which is the failure this section is written to avoid — a roadmap that promises a quarter and then quietly keeps promising it says less than one that names the work and no date.

## Stability commitments

The public-facing API surface is pre-1.0 and continues to evolve; breaking changes can land in any release. Long-term API stability is not yet committed.

Historical benchmark figures (95.8% technical accuracy, under-15s P95) belong to the **Stage I OpenBMC reference vertical, measured 2025**. Stage I is archived and not running, so those numbers are history and are not claims about the current engine. See `README.md`.

## Public participation

- Issue intake: open (see CONTRIBUTING.md)
- Documentation pull requests: open
- Code pull requests: not yet — one maintainer, no second reviewer; see CONTRIBUTING.md
