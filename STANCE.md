# Who counts as a producer, and what this engine owes one

This page answers one question, because one question kept being answered in
private. A bridge author, deciding what to put in `ingest_forecasts`, has to know
what a **submission** is — and the engine's behaviour was readable only from a
decline reason's name and from a comment in somebody else's repository.

It is deliberately narrow. **It does not restate the declared-versus-learned
argument**: `README.md` makes that case under *Is this a world model?* and this
page would be a second copy of it, which is the failure mode this project files
most often. It does not restate the mechanics either — `BRIDGES.md` documents the
record shape, `source=`, the `raced` vocabulary and the ordering they require.
What follows is the part neither of them states: the rule, and the obligation.

## The seam

A producer predicts. This engine keeps the books. `ingest_forecasts` is the seam
between them, and it runs in one direction only — predictions come in, and no
number ever goes back out into a model as a value somebody did not write.

Above the seam anything may predict: a fitted model, a vendor's API, a planner, a
person with a spreadsheet. The engine has no opinion about what produced a number
and no way to form one. Below it, everything is audit.

## What a submission is

**A submission is a forecast filed as a claim to be audited.** That is the whole
definition, and it is a statement about the FILER'S INTENT rather than about the
number, its accuracy, or what computed it.

`source=` withdraws that claim. A record filed with one is bookkeeping: kept,
graded, and not audited.

**Measured, this is the only thing `source=` changes.** The same record filed both
ways is filed identically, gets a random-walk baseline fitted beside it
identically, and is recorded in the ledger identically — two rows either way, the
forecast and its baseline. What differs is one thing:

| | filed as a submission | filed with `source=` |
|---|---|---|
| record filed | yes | yes |
| baseline fitted beside it | yes | yes |
| entered in the ledger and graded | yes | yes |
| **the eight axioms run over it** | **yes** | **no** |
| a breach becomes a finding | yes | no |

So `source=` is not a label, a category, or a hint. It is the switch that decides
whether the engine judges the number or merely keeps it.

## What the engine owes a submission

Five things, and they are obligations rather than features:

1. **To run the eight axioms over it, as over a reading.** A forecast that crosses
   a declared line is a finding before the world gets there.
2. **To fit a parameter-free baseline beside it that the producer did not choose.**
   A random walk, on the history available when the forecast was issued. A score
   with no opponent is a number about nothing.
3. **To grade it once the world has caught up** — pinball loss, a CRPS
   approximation, interval coverage, reported beside the coverage a
   well-declared spread should have had.
4. **To treat its ABSENCE as a finding**, where the model made it an obligation.
   `expected_from` is the author saying a forecast is owed; silence then is a
   result, not a gap.
5. **To refuse by name when it cannot judge**, rather than scoring what it could
   not read. An unknown producer, a stale forecast, a record it cannot place.

## What the engine does not owe one

**Belief.** A submission is evidence about a producer, never about the world. No
forecast changes a value in the model.

**Adoption.** A number the engine FITS — a `gain: estimate`, a discovered edge, a
learned transition — is a proposal until an author writes it down. Producers are
subject to the same rule, and there is no route by which a good score becomes a
declaration.

**A ranking.** The engine scores each producer against the baseline and against
its own stated spread. It does not order producers, recommend one, or carry a
reputation between sessions.

## The reference producer, which gets none of the above either

The package ships one: `arbiter_engine.producers.baseline_learner`, a
damped-trend exponential smoother. It exists because the engine's own baseline
is a **random walk** — it predicts the last value and widens with the horizon —
and a random walk is the right floor and a poor opponent. Anything that notices
a series is going somewhere beats it, so *beats the baseline* against a random
walk alone says almost nothing.

**It is a producer, not a feature.** It reads a session through
`reading_history()`, the accessor this engine tells every reader to use, and
files ordinary records through `ingest_forecasts`. It imports no checker, is
handed no privilege an outside forecaster would be refused, and is scored by
exactly the rules above — including `not_a_producers_submission` if its records
carry a `source`. A baseline with access the competition lacks is not a
baseline, and the suite asserts its import surface as well as its score.

**It refuses rather than guessing.** A series shorter than its minimum gets no
forecast, and one whose points are not ordered in time is refused rather than
sorted — re-ordering a series nobody gave you that way is how a producer comes
to score well on data it invented.

## Why the engine sets its own records aside

The engine is a producer too. `rollout` files what it projected; every
`ingest_forecasts` fits a random walk. Those are stamped `source: engine` — by
the same mechanism a bridge uses for a control, and for the same reason.

**Grading your own arithmetic is not grading.** An engine that ran its own axioms
over its own projections would report the agreement of one calculation with
itself. So it withdraws them from the audit and keeps them in the ledger, where
they are scored against the same baseline as everyone else under
`calibration.own_projections`.

This is why **`not_a_producers_submission` fires on a perfectly clean run.** It
carries the count and the sources it set aside, and the engine's own is almost
always among them. `BRIDGES.md` states the operational consequence: look for your
own `model_id` in that list, because a non-empty list is normal and yours being in
it is not.

## An action somebody took

**Recording an execution is not dispatching one.** A rollout under actions files
nothing, because it describes a world nobody has brought about. `file_action` is the
one door through which an action's trajectory reaches the ledger: the caller records
that a declared action took effect at an instant, and says in `basis` who or what
took it. The engine files two of its own forecasts from that instant, with the
action and without it, and reports them under `calibration.executions`, apart from
every other figure, so that an action which worked is not scored as a model that
failed. Nothing in the engine causes, schedules or approves the action. A false
`basis` is caught the way any wrong forecast is, by the readings that follow it.

## The case this rule was written against

A bridge auditing a book runs a reference forecaster as a CONTROL — a deliberately
simple model, present so that the audit's verdict on a clean book can be checked.
Filed as a submission, the eight axioms ran over the control's own predictions and
turned a clean book's exit code red over accounts whose real balances were fine.

**A reference that can fail the audit it is a control inside is not a control.**
Filing it with `source=` is the correct use of the rule above, not a way around
it: the bridge is saying *this is not a claim, it is an instrument*, and the
engine keeps and grades it accordingly.

The judgement about which of a bridge's own feeds are claims and which are
instruments belongs to the bridge. What the engine owes is that the distinction be
declarable, visible in the envelope, and never made silently — which is what the
decline is for.
