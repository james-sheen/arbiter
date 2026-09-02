# Building a bridge on this engine

This engine judges series and properties it is handed. It has no opinion about
what exists in the world, and it will not invent a fact to fill a gap. Whatever
supplies those facts — enumerates what should exist, models it, feeds it, and
turns verdicts into exit codes and artifacts — is a **bridge**, and it is a
separate program from this one.

This document is for the person writing that program. It is method: what to
build, in what order, and which mistakes have already been paid for. It states
no measurement of this engine's behaviour, because a behaviour written down here
would be a second copy of a fact and second copies drift. Measure the version
you pin (C3 below), and keep the measurement in code that re-runs.

---

## 1. The division

**The engine owns** the axiom set and its mathematics, the closed vocabulary of
reasons it refuses to judge, the schema its results are emitted in, and a small
read surface. It contains no domain noun.

**The bridge owns** what exists, what things are, what is deliberately left out
and why, what only an operator can know, what gets fed and when, and how a
verdict becomes an exit code somebody can act on.

Two tests keep the boundary honest.

**Engine litmus** — the engine decides nothing by asking which domain it is in.
Check it by parsing, not by grepping for vocabulary: a word search over an honest
engine returns hits on its own explanatory comments, and a check that fires on
its own documentation gets switched off. The predicate that works is structural:
an identifier naming the domain, compared against a constant. An opt-in flag a
caller sets is not a domain branch.

**Bridge litmus** — the bridge computes no invariant verdicts of its own. It may
implement presence logic, which is pre-engine. It never re-implements axiom
mathematics. Facts flow in, verdicts flow out, and the only shared language is
the versioned result plus the decline vocabulary below.

---

## 2. The decline vocabulary is your requirements document

Everywhere this engine refuses to judge, it is naming a fact your bridge must
supply — declared with a basis, or reported as explicitly absent with a reason.
There is no third option, and *silently swallow* is not one of them.

So read the whole list before designing anything. Each entry is either something
your vertical will supply, or something your verdict artifact will report as
declined.

| Reason | Emitted as |
|---|---|
| [`checker_error`](#checker_error) | `NotEvaluatedReason.CHECKER_ERROR` |
| [`insufficient_samples`](#insufficient_samples) | `NotEvaluatedReason.INSUFFICIENT_SAMPLES` |
| [`missing_config`](#missing_config) | `NotEvaluatedReason.MISSING_CONFIG` |
| [`missing_entity_type`](#missing_entity_type) | `NotEvaluatedReason.MISSING_ENTITY_TYPE` |
| [`missing_property`](#missing_property) | `NotEvaluatedReason.MISSING_PROPERTY` |
| [`missing_role`](#missing_role) | `NotEvaluatedReason.MISSING_ROLE` |
| [`no_current_value`](#no_current_value) | `NotEvaluatedReason.NO_CURRENT_VALUE` |
| [`no_threshold`](#no_threshold) | `NotEvaluatedReason.NO_THRESHOLD` |
| [`not_applicable`](#not_applicable) | `NotEvaluatedReason.NOT_APPLICABLE` |
| [`precondition_unmet`](#precondition_unmet) | `NotEvaluatedReason.PRECONDITION_UNMET` |
| [`undefined_for_values`](#undefined_for_values) | `NotEvaluatedReason.UNDEFINED_FOR_VALUES` |
| [`wrong_indicator_type`](#wrong_indicator_type) | `NotEvaluatedReason.WRONG_INDICATOR_TYPE` |

12 reasons. The set is closed, and this table is generated from the engine in this repository rather than transcribed -- a guide that disagreed with it would not have been published.

One section per reason follows. Each says what the refusal means and what your
bridge owes because of it.

### `insufficient_samples`

Fewer observations than the axiom needs to answer. Not a failure: a fresh system
that declines everything is making a true and useful statement. Report it as
warm-up rather than suppressing it — but not all of it is warm-up. A floor is a
count taken inside a window, so a corpus can hold many times the floor and still
never present it, and a fault injected into one is invisible. Measure the floor
and the window together, and build the corpus past both.

### `missing_property`

The property was never supplied. This is the belt to your own brace: your walk
should already know the source was not reading. Keep both — defence in depth is
not redundancy to be optimised away.

### `no_current_value`

Distinct from the above, and the distinction is the point. The value was supplied
to a different store than the one this axiom reads. A caller told *no value for
this property* while holding a full history of it has been sent to supply what
they already supplied. If your bridge collapses these two, it will hand an
operator the wrong instruction with confidence.

### `missing_entity_type`

The model refers to a type the telemetry never produced. Not a gap in one
entity's data — a gap between what your model believes exists and what your walk
found. Treat it as a modelling error, not a collection error.

### `missing_config`

A configuration block the axiom needs was never declared. Some invariants cannot
be checked without a structural statement only an operator can make. This is that
statement being absent, and the remedy is a declaration, not more data.

### `no_threshold`

Nothing to bound against. Generating an indicator anyway adds an invariant the
engine can only decline, inflating your denominator with questions nobody asked.
Exclude it in the model and name the exclusion in the manifest — the difference
between *we chose not to watch this* and *we forgot it exists* is the whole value
of an audit.

### `wrong_indicator_type`

The axiom was pointed at a kind of value it cannot reason about. A modelling
mistake, and one worth failing loudly on: an indicator wired to the wrong axiom
produces silence that looks like health.

### `missing_role`

The axiom would apply, and the model never said what this indicator *is* to it.
Somebody owes a declaration, and this is the arm of a decline you can put on a
backlog. Reading it as *the axiom does not apply here* retires a check that was
one line of model away from running.

### `precondition_unmet`

A check declared a gate — the entity must carry some property before the check
means anything — and the entity did not clear it. **The engine does not tell you
which way to read that**, and it cannot: a deliberate exemption and a mistyped
property name look identical from here, and only whoever holds the scan knows
which one it is.

So this is the arm that goes back to a human rather than onto a queue. Route it
to whoever owns the model, not to whoever owns the data: if the exemption is
intended, nothing is owed and the row is the engine confirming the gate works;
if the name is wrong, the check has been retiring itself quietly and the row is
the first thing that would ever have said so.

Do not fold it into `missing_property`. That one says a value the check needed
was absent; this one says the check never became applicable. Counting them
together turns a gate that fired correctly into a data-quality ticket.

### `undefined_for_values`

The axiom applies, the samples are present, and the quantity it computes has no
value on them — a ratio against a zero total, a deviation against a zero spread.
**Nobody owes anything.** It is not insufficient data and more collection does not
address it; the same cell may evaluate tomorrow on different values. Count it, and
do not put it on anyone's list.

### `not_applicable`

No checker was registered for the axiom. Engine-side, and it is the residue left
after the two above were told apart from it — if you are seeing this, the engine
was asked for an axiom it does not implement, which is a fault and not a
statement about your model. Expected declines that are genuinely *this does not
apply* now arrive as one of the two reasons above.

### `checker_error`

The check itself failed. **This is never a clean result.** It is the engine
telling you it could not complete, and anything inferred from a run containing
one is inferred from an unknown.

---

## 3. The exit contract

Adopt this verbatim. It is what makes results from different bridges comparable.

| Code | Meaning |
|---|---|
| `0` | Clean. The leg completed and found nothing. |
| `1` | Findings. The leg completed and found something. |
| `2` | Could-not-complete. The leg did not finish; infer nothing from it. |

- **`2` never reads as clean.** An incomplete measurement is not a passing one.
- **`2` beats `1`.** An incomplete leg can hide findings; findings are knowledge.
- A code outside `{0, 1, 2}` reads as `2`, with the raw value kept beside it.
- Compose as the **maximum over the floors of every leg**. Decide each floor at
  design time; runtime is too late.
- Classify every decline into a small closed set of classes, each with a floor.
  Two anchors that hold: a declared-but-absent source floors at `1`, because a
  broken promise is a finding; an unreviewed declaration or a schema mismatch
  floors at `2`, because the run's foundation is invalid.

Version every artifact format you emit as `<package>/<artifact>/<n>`, and refuse
unknown majors. Validate this engine's result against the schema shipped **inside
the artifact you installed**, never a copy in your own tree.

---

## 4. Nine capabilities, in order

**C1 — Stand alone first.** Your first stage is presence and coverage, and it has
zero dependency on this engine. It answers the question the engine cannot ask:
does the thing exist at all? Classify each expected source three ways — present
and reading, present but not reading, absent — never as a boolean. A bridge that
cannot run its first stage without the engine installed has its layering
backwards.

**C2 — Model and manifest, as a pair.** The model declares what gets fed; the
manifest names everything excluded, with a reason. The second half is not
optional. One entity type per real-world unit; never fold a value into a slot
that means something else; exclude templated names before generation, not after.

**C3 — Measure the engine you pin; do not read it.** Derive what it will judge,
decline, or excuse by running every arm of every relevant axiom against the exact
version you pin. Behaviour no probe covered is neither handled nor unhandled — it
is *unmeasured*, and unmeasured never reads as clean. Write the probes as code
that re-runs, never as a table in a document.

**C4 — An operator-knowledge channel.** Some facts are physics, law, or contract,
and no schema contains them. Carry a channel where an operator states them, and
require every statement to carry a **basis**: what the declarer actually looked
at. Then gate it (Section 5).

**C5 — Ingestion layering.** Feed only what stage one classified as present and
reading. Keep the engine's missing-property decline as the belt to that brace.

**C6 — Result to exit.** Schema-version mismatch is a hard stop. Every decline
lands in its class with its predetermined floor. Compose as the maximum. No
exception path escapes the contract — a traceback delivered as a successful
result is your transport reporting on itself.

**C7 — Verdict to auditable artifact.** Report three ways — checked, declined,
not-established — so silence is impossible. Quote the engine's boundary strings
verbatim; paraphrasing machine output is how two copies of a remedy drift apart.
Record the counts, and name every exclusion via the manifest.

**C8 — Pin and re-measure.** Pin a range, and verify the version a consumer
actually resolves. **A range is a claim about every release inside it**, so
exercise the floor too. On a pin change, the C3 characterisation is re-derived,
not re-read.

**C9 — An evidence ladder climbable without production.** Name every rung:
synthetic corpus, mutated copies, a live-but-safe surface, first contact. Every
rung below the top must be climbable in a box. The top rung is human, and naming
it is what keeps everyone honest about what *we tested it* means.

---

## 5. The review gate

A rule can *propose* an operator-knowledge fact. A rule cannot *know* one.
Deriving a relationship from names, or from two configured values happening to
match, is a guess wearing the costume of a derivation — and matching thresholds
in particular has been refuted by counterexample, because unrelated components of
the same part number carry identical bounds.

So: draft tooling may emit an unreviewed statement and exit clean, because
drafting is legal. Feeding that statement to evaluation must be **refused
mechanically**, naming the file. A statement becomes usable when a person adds a
marker with their own name and the date; both halves required, since a name with
no date is the shape of somebody clearing the gate rather than passing it.

Make the same package do both. A package that emits the unreviewed artifact and
refuses it is a boundary proving itself, rather than a boundary described.

**Test fixtures pass the gate only by disclosing themselves on their face** — a
reviewer field that says it is a fixture. Never by simulating a review. A fixture
that impersonates a reviewer teaches your suite that impersonation works, and the
suite was the thing that was supposed to notice.

---

## 6. The verification battery

Ship your proof as a re-runnable script, not as a transcript. A green recorded in
a session is a claim about a session nobody else was in.

| Leg | The question |
|---|---|
| live | Can a live surface be read at all, and how many sources did it serve? |
| draft | Does draft tooling emit an unreviewed statement and exit clean? |
| gate | Does your own gate then refuse that exact file, by name? |
| clean | Over an uncontaminated corpus, does the pipeline stay quiet? |
| fault | For each fault class, is the injected thing found? |
| absent | Is a declared-but-absent source a finding, not an incompleteness? |
| attest | Does attestation work through the same front door as everything else? |
| pipe | Does a reader walking away change the verdict, or print anything? |
| tool | Is the tool surface closed, and does the binding construct for real? |
| suite | Does the suite pass from a directory that is not the repository? |
| **ship** | Does the **built artifact**, installed clean, still do all of that? |

**The ship leg is the one to protect.** Every other leg runs against a source tree
no consumer will ever have, and it is the easiest to skip because it is slow and
because the others were green. A battery that has only ever run against the
working tree has verified the working tree.

Rules for injecting a fault so the leg means something:

1. **Mutate a copy.** The clean corpus is a fixture with provenance.
2. **Use absolute deltas when a baseline can be zero.** A proportional change to
   zero injects nothing.
3. **Assert the injection took.** An injector that silently no-ops turns a fault
   leg into a green that tested nothing.
4. **Stay outside the engine's excuse boundaries, and write down why.** If a
   behaviour is legitimately excused, a fault landing inside it stays green and
   the engine is *right*. Measure the boundary first.
5. **One fault per copy, expectation declared before the run.** Expectations
   written afterwards are a description of what happened.
6. **Check that a passing fault leg passed for the injected reason.** An exit
   code is a claim about the run, not about your fault. Assert on the finding.
7. **Derive the corpus from the engine's floors — how many samples, and over
   what span.** Do not choose either.

A leg that could not run reports `2` and is **named**. Never skipped: an absent
leg that leaves no trace reads as a leg that passed.

**Where the harness's own dependencies go matters.** Optional extras installed to
make one leg run can pull a transitive major that breaks something the battery
does not look at. Install them into the throwaway environment the ship leg
already builds — the leg then tests the artifact, which is better evidence
anyway. A disposable CI runner is the exception, and only because it is
disposable.

---

## 7. The tool surface, if you build one

A tool server — for an assistant, or any protocol caller — is a **spec table plus
a dispatcher**, and the dispatcher routes through your CLI front door. Never a
parallel code path: a second implementation gets a second suite, and on the day
the two disagree both are still green.

Keep the table and the dispatcher free of any protocol import. The binding is
then thin, its closure test runs where the SDK is not installed, and the
dispatcher the protocol advertises is the one the test walks.

**Every result carries the exit code and a verdict word, explicitly.** A transport
that successfully delivered a message about a run that could not complete has
succeeded at being a transport and done nothing else. Left implicit, `2` is read
as clean by whoever is reading. An unknown tool is `2`, never an empty answer.

Walk the table when you test closure. Testing one entry at a time passes while an
entry that was added and never wired sits there returning nothing.

---

## 8. What no mechanism absorbs

Three things stay human, and building around them does not dissolve them.

**The declarer.** The channel normalises; the endpoint does not. Someone has to
know the fact and put their name to it.

**First contact.** The first credentialed reach into the real system is an act,
not a call. Building on a safe surrogate surface bypasses this; it does not
remove it. Consider leaving it out of any automated tool surface deliberately —
it takes credentials, it touches something real, and a refusal is a better
boundary than a paragraph asking nicely.

**Naming.** Method documents codify the *last* error class. Naming a new one is
the act no checklist performs. This engine's history says the next defect class
is not in this document; when you meet it, the contribution that matters is the
name.

---

## Worked implementations

Everything above is method, and method is easier to agree with than to follow.
These are complete programs built to it, source and tests readable in full:

- [`bmc-sensor-audit`](https://github.com/james-sheen/bmc-sensor-audit) — the
  original bridge. Stage 1 stands alone with no dependency on this engine; Stage
  2 adds it as an optional extra. Carries the declarations channel and its review
  gate, the verification battery, and the tool surface.
- [`fleet-sensor-baseline`](https://github.com/james-sheen/fleet-sensor-baseline)
  — built on the first one's published formats rather than on this engine
  directly, which is the other shape a downstream package takes.

**Both are by this engine's author, and that is a limit on what they prove.**
They are worked examples, not independent adoption, and the method above has not
yet been carried into a vertical that shares no vocabulary with them. If you are
the first to do that, the parts that do not survive contact are worth more to
this document than the parts that do.
