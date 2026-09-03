# Arbiter

**A detection engine that reports what it did not check.**

Most checkers answer one question: *what is wrong?* When they return nothing, you cannot tell
whether they looked and found nothing, or never looked at all. Those two results are printed
identically, and only one of them is good news.

Arbiter separates them. Every evaluation that declines to run is recorded — with a machine-readable
reason — alongside the findings, and every pass reports how many evaluations it attempted. A clean
result means *these invariants were tested and held*, and it is distinguishable from *nothing was
testable*.

## The envelope

A detection pass returns findings, declines, and a denominator:

```
findings              what was found
not_checked           what was NOT evaluated, and why
checked.invariants    how many (axiom, entity, indicator) evaluations were tried
```

**Every envelope carries `meta.schema_version`.** It names the WIRE SHAPE, not the package
version, and it moves only when a reader that worked stops working — adding a key does not move it.
[`COMPATIBILITY.md`](COMPATIBILITY.md) says what a patch release may change and what waits, and
[`schema/envelope.schema.json`](schema/envelope.schema.json) is the shape machine-readable. The
reason all three exist: the describe payload's nesting moved once between releases with no signal at
all, and a consumer who had written against the earlier layout got `None` back from a lookup — which
reads as *this engine does not support that* rather than *this moved*.

`not_checked` entries carry a reason from a closed vocabulary of twelve — `not_applicable`,
`insufficient_samples`, `missing_property`, `no_current_value`, `missing_config`,
`missing_entity_type`, `missing_role`, `no_threshold`, `precondition_unmet`,
`undefined_for_values`, `wrong_indicator_type`, `checker_error` — so a decline is data,
not a log line.

Three of them will account for most of what you see. `insufficient_samples` reports both the
count it had and the count it needed, so it tells you how much longer to collect.
`missing_role` means an axiom needed to know what KIND of quantity an indicator is — a count, a
percentage, a ratio, a latency — and the model never said. Declare `role:` on the indicator. The
engine does not guess it from the indicator's NAME, so this decline is about the declaration and
never about the spelling.

`no_current_value` is the newest and the reason it exists is worth stating. A threshold axiom reads
`Entity.properties`; a temporal axiom reads observation history. Feed only the second and the value
is genuinely present and genuinely unreadable by the checker that wants it — and until 2026-08-16
that said `missing_property`, which told a caller holding sixty observations of a property that
there was no value for it. It now names the count and which store it is in. **That was reported
from outside**, and the vocabulary was the thing at fault: a closed set missing a member does not
raise, it reclassifies the case as the nearest member and reports it with confidence.

**Why the denominator matters.** Findings and declines do not sum to the total: an evaluation that
ran and found nothing appears in neither. Without `checked.invariants`, the statement *checked N
invariants* has no honest value of N — and an envelope reporting a fabricated denominator is the
exact failure the envelope exists to prevent.

All eight axiom checkers emit declines (35 call sites). This is not a property of one checker that
the others aspire to.

## The eight axioms

Declared per-indicator in a domain model, not in code:

| Axiom | Asks |
|---|---|
| `BOUNDEDNESS` | does this stay inside its bounds? |
| `STABILITY` | does it settle, or oscillate? |
| `HOMEOSTASIS` | does it return to baseline after disturbance? |
| `MONOTONICITY` | does it move only in the permitted direction? |
| `CONSERVATION` | does what goes in come out? |
| `CONNECTIVITY` | is the topology intact? |
| `CONSISTENCY` | is this value possible, and does it match its declared twin? |
| `RESPONSIVENESS` | does it react within its deadline? |

**`BOUNDEDNESS` takes a floor as well as a ceiling.** `warning:` and `critical:` are ceilings;
`lower_warning:` and `lower_critical:` are floors, and declaring both pairs on one indicator gives
you a band. A fan that must not stop declares `lower_critical: 1000` and gets back *speed_rpm is
below critical threshold* with the reading it was given — no negated property, no translation layer.
Whether you should declare a floor at all is a different question, and
[`MODELING.md`](MODELING.md) answers it: transcribe one when a datasheet or a contract gives you the
number, and reach for `HOMEOSTASIS` when nobody has.

**`CONSISTENCY` answers two separate questions.** By default it range-checks a value against what
its `role:` permits — a count is not negative, a percentage is within 0-100 — and that rule reads
one indicator and nothing else. Declaring `consistency: {agrees_with: [other_property]}` adds the
second: two readings the model says are redundant have to match, within a `tolerance:` (relative) or
`tolerance_absolute:`. Redundancy is declared because nothing about two numbers reveals that they
measure the same thing. A named peer the entity does not carry is reported in `not_checked` rather
than skipped.

**Redundancy is a claim about the system, not an inference from naming — and populating `agrees_with`
from a naming convention is the way this check fails.** Two channels of one part are the tempting
pair and often the wrong one: a temperature sensor exposing `Name` and `Name1` may be reporting its
own die and an external diode, which differ by tens of degrees on a healthy board. Pair them and the
engine will faithfully report disagreement between two readings that were never supposed to agree —
a false finding on every working machine, produced by a configuration rather than by a fault. The
same is true of consecutive record numbers, matching suffixes, and anything else derivable from a
string: **if a rule can generate the pairs, it does not know the pairs.** They have to come from
someone who knows the system, and they should be versioned and pinned like any other declaration.
This is not hypothetical — it was reported by an integrator who caught the suffix rule in review
before it shipped.

```yaml
- name: cpuUsageNanoCores
  type: NUMERIC
  axioms: [STABILITY, BOUNDEDNESS, HOMEOSTASIS]
  warning: 3
  critical: 10
  window: 1h
```

An empty `axioms: []` is meaningful — the values flow into observation history without a per-cycle
check. Silence is a declaration here, not an omission.

### `role:` — two axioms need to know what kind of quantity they are reading

`RESPONSIVENESS` and `CONSISTENCY` carry rules about a **quantity**, not about an entity: a deadline
applies to a latency, and `0 <= x <= 100` applies to a percentage. Declare which:

```yaml
- name: setpoint_error_pct
  role: latency            # latency | count | percentage | ratio
  axioms: [RESPONSIVENESS]
  warning: 5
  critical: 12
```

Leave it out and the axiom declines `missing_role`, whatever the indicator is called. The engine
used to infer one from the **name** — `response`/`latency` for the first, `count`/`percent`/`pct`/
`ratio` for the second — and that was a guess about English: two indicators identical in every
declared respect were treated differently because of their spelling, and no surface said which had
happened. Worse for a reader, the ABSENCE of the decline was not evidence a role had been supplied.
It was evidence about the name. An indicator called `pulldown_error_c` could declare
`RESPONSIVENESS`, be accepted, be listed by `model_describe`, and never once evaluate.

**You do not have to run a cycle to find that out.** `model_describe` reports
`unreachable_declarations` — every declared `(indicator, axiom)` pair that cannot fire under any
input, each with the remedy — and the loader logs the same list. An empty list is the target.

### `expect_variation:` — a reading that stopped moving is not a reading

A sensor frozen at its last value passes every threshold it is under, and `STABILITY` measures
oscillation, so a flat line scores as the most stable input there is. Until 2026-08-16 a dead sensor
and a live one produced **byte-identical envelopes**. Declare that a quantity should move:

```yaml
- name: speed_rpm
  axioms: [STABILITY, BOUNDEDNESS]
  expect_variation: true
  window: 30m
```

Then a series that never changes across the window is a finding, `frozen_series:<indicator>`, naming
the value and the count.

**`STABILITY` in that `axioms:` list is load-bearing, and the field is inert without it.** STABILITY
is the axiom that reads the series, so an indicator declaring `expect_variation: true` alongside
only threshold axioms gets no finding and no decline — which is indistinguishable from a healthy
sensor, and is the thing this field exists to end. Copying the block above works; editing an
indicator you already have is where it bites. **`model_describe` names it**: `unread_fields` lists
every declared field whose consuming axiom is absent, with the remedy. That check exists because
this was reported from outside the day after the field shipped.

**It also names a key the engine does not read at all**, which is the case that catches a typo. Each
row carries a `reason`: `axiom_not_declared` for the above, and `unknown_key` for a key that is not
in the schema — with a `did_you_mean` where one is close. `expect_variaton: true` is accepted by
YAML, read by nothing, and would otherwise leave exactly the silence the field was added to end.

**And it names properties you send that nothing reads.** `unread_properties` lists numeric entity
properties for which no indicator is declared. It reports what arrived; it does not judge the value,
because deciding what a number means needs a rule and this engine takes rules from your model rather
than from the property's name. Earlier versions did guess: a key spelled `*_count` or `*_pct` was
range-checked whether or not you asked. That is gone — declare `role:` and the axiom to get those
checks — and this report is how you find the properties that declaration is missing from.

**`check` carries that report too, and the reason is the guess it replaced.** Removing the guess
withdrew a check: a value that used to raise `impossible_value` off its property's spelling now
raises nothing. A withdrawn check that says nothing is indistinguishable from one that passed, which
is the single thing [`COMPATIBILITY.md`](COMPATIBILITY.md) forbids a patch release from doing — so the
population rides on `check` as well, and a run whose faults moved into undeclared properties reads
as a run with something unlooked-at rather than as a clean one. It is a report, not a decline:
a decline record names an indicator and an axiom, and a property nobody declared has neither.

**Leave it out and nothing is reported, and that silence is the design rather than a gap.** Whether a
constant series is a fault is a question about your domain and not about the number: a CPU
temperature that never moves is broken, and a replica count, a nominal setpoint and a switched-off
pump are all correctly flat. The engine cannot tell those apart and does not try. You can.

The axioms reading the value are **not** suppressed when this fires. A sensor frozen above its
critical threshold still raises that alarm; you get both, and can judge the threshold verdict
knowing the input behind it is dead.

## Quickstart

```bash
pip install arbiter-engine          # requires numpy and pyyaml, and nothing else

python3 -c "
from importlib.resources import files
from arbiter_engine.api import EngineSession, model_describe

s = EngineSession()
s.load_model(files('arbiter_engine').joinpath('examples/water_tank.yaml').read_text())
print(model_describe(s).to_dict()['checked'])"
```

The example is read out of the INSTALLED PACKAGE rather than off a relative path, and that detail is
load-bearing rather than stylistic. A wheel ships only what lives under the package directory, so
the copy at `examples/` in this repository reaches the source distribution and **not** the wheel.
This block used to open `examples/water_tank.yaml` directly: correct from a clone, and
`FileNotFoundError` for anyone who installed the package instead — a failure that could not appear
until the install line above stopped saying `git clone`. Both copies are here, written from one
source: `examples/` for reading, the packaged one for running.

That prints `{'invariants': 0, 'entities': 3, 'declared_invariants': 11}` — three entities, eleven
declared invariants, and **zero evaluated**, because no observations have been supplied yet. The
zero is the point: it is reported rather than left for you to infer from an empty finding list.

**Everything above is on the supported surface.** Until 2026-08-11 this example imported
`load_domain` from a deep module path — which works, and which this same README calls importable and
unsupported three sections down. The first thing a reader runs should not be the one thing the
document tells them not to depend on.

`examples/water_tank.yaml` is a deliberately synthetic two-tank water system that **declares all
eight axioms in one file**, so it doubles as the schema reference. It is not one of the curated
domain models, which are not published — and neither `kubernetes_node.yaml` nor `battery_pack.yaml`
is one of those either, though all three ship here — and reading it is
the fastest way to learn the shape. `kubernetes_node.yaml` and `battery_pack.yaml` are the same kind
of thing on domains where a floor and a band carry the weight.

**Dependencies are two, and that was measured rather than assumed.** `numpy` and `pyyaml` are
required. `scipy` and `rdflib` are extras (`[confidence]`, `[rdf]`) because they are reached only
through two deep modules that the public API never touches — so the naive reading of the import list
says four, and the measurement says two.

## The public API

**11 names.** Everything else in the package is importable and **unsupported** — reaching for a deeper
path is legitimate and unpromised, and those paths may move without a major version.

```python
from arbiter_engine import (
    TopologyTraverser,          # the kernel: problem-solving as graph traversal
    UnifiedAxiomReasoner,       # evaluates axioms, produces the envelope
    DomainModel,                # your YAML, loaded
    InMemoryObservationHistory, # a concrete history, so it runs without a store
    Entity, Problem, RelationshipGraph, Observation, Axiom, Severity,
    api,                        # the tool surface — see below
)
```

**Ten of those are types and the kernel; the eleventh is a module, and the split is deliberate.**
`arbiter_engine.api` is the tool surface: five verbs over a session, each returning the envelope above.

```python
from importlib.resources import files
from arbiter_engine.api import EngineSession, model_describe, check, traverse, gaps, attest

session = EngineSession()
session.load_model(files("arbiter_engine").joinpath("examples/water_tank.yaml").read_text())
model_describe(session)   # what is declared: entity types, indicators, axioms
check(session)            # evaluate the declared invariants over supplied observations
gaps(session)             # what the model says should exist and nothing has been observed
```

Read out of the installed package again, for the reason given above. **This block opened the
relative path until 0.1.6, which is the failure that paragraph describes, forty lines further down
the same document** — so 0.1.5 ships a project page whose second code block raises
`FileNotFoundError` for anyone who installed it. Found by running the README that shipped inside the
wheel, from a directory with no repository in it, rather than a rewritten version of it.

**Three kinds of input, one feeder each.** A session takes the current value of a property, the
series behind it, and the edges between entities — and every axiom reads one or both of the first
two, except `CONNECTIVITY`, which reads only the third.

```python
session.add_entity("pump1", "Pump", properties={"speed_rpm": 2900})
session.add_observations("pump1", "speed_rpm", [2900, 2905, 2890, ...])
session.add_relationship("pump1", "feeds", "header")   # source, relation, target
```

The first two are easy to conflate and worth separating deliberately: threshold checks read the
entity's current `properties`, and the temporal axioms read observation history. **Supplying one
and not the other is the commonest way to get a clean result over a value that is plainly out of
range** — the threshold checker never saw it, because the current value lives on the entity.

Omit the third and `CONNECTIVITY` will report a missing relationship, which is correct: a model
that declares a pump must feed a tank is asserting something, and an absent edge falsifies it. That
finding is not a complaint that you forgot to load edges — the engine cannot tell those apart, so
it reports what the model asserted and lets you decide which it was.

They are a supported contract, and they are listed here as **one name rather than six** because they
serve a different caller: an agent invoking tools, not a library user composing objects. `check` is not
a peer of `Entity`, and flattening them into one namespace would say it was. The module is the promise;
its membership is documented here and does not change inside a minor version.

The same five are exposed over MCP by `arbiter_engine.mcp.server`, which is a thin transport over
exactly these functions and needs the optional `mcp` extra. That module is a deep path — importable,
and not part of the eleven.

## What is not here, and why

The engine is open. The knowledge and the operations are not.

- **Domain models.** The engine reads them; the curated packs are not published. The mechanism is
  the contribution — the models are the accumulated work. The three files in `examples/` are
  synthetic teaching models, deliberately not among them.
- **The operator half.** Clinic, planning, the Kubernetes executor, the introspection layer. These
  are welded to a running deployment and are not v0.1.
- **Two lazy imports reach outside the cut, and they behave differently.** One root-cause wiring
  module and an LLM client are imported lazily and are not shipped, so the package still imports
  cleanly. The root-cause wiring **degrades to a no-op** — its callsite is guarded and the feature it
  reports is optional telemetry. The LLM path **raises**, with a message saying so; it is reachable
  only through `NLTraversalTranslator`, which is not part of the supported surface, and the
  deterministic `translate()` needs no client. Both measured by running them, not read off the
  imports.

## Status

**v0.1.** 61 Python files, 59 modules importing on the declared dependencies alone, 11 supported
names — **counted in this repository**, which is the package you are holding.

That basis is stated because it is easy to get wrong in a way nobody notices. The build adds one
`__init__.py` per package level, so a count taken before the build is smaller than the package you
are holding — and this line published the smaller figure until 2026-08-12, where any reader could
falsify it with `find . -name '*.py' | wc -l`. A checkable false claim, in the Status section of a
project whose subject is checkable claims. Count the artifact, never an earlier stage of it.

The import figure carries the same hazard one layer down, and it depends on what you have installed. Sweeping the package where `scipy` happens to be present imports 60; on the declared dependencies alone it is the 59 above, because `propagation.lp_confidence` is the one module that needs `scipy` and it is a deep path outside the supported surface. Count the artifact **in the state the reader will have it**, not in the state the person measuring happens to be standing in — this line quoted the with-`scipy` figure until 2026-08-12, which no reader installing normally could reproduce.

**And the count is of SUBMODULES: the root package is not one of them.** Walking `arbiter_engine` for what it contains gives 59; adding the package you imported to reach them gives 60. Both are honest and they are answers to different questions, so a reader who recounts and gets one more has not found a defect — they have used the other convention. Stated because someone did exactly that from outside, and a number published without its predicate can only be agreed with or disagreed with, never checked.

Honest boundaries, stated because you would otherwise find them yourself:

- **PREDICT is plumbed but unfed.** The traversal mode exists and nothing produces projected values
  outside a test. It is not a working forecast.
- **Three worked examples ship, not a library of them.** Modelling a real system is your work.
- Stage I and Stage II of this project are **archived, not running**. Anything describing them as
  production is out of date.

## How fast is it

Measured on this project's development machine, so treat the shape of the curve as the claim and
the absolute numbers as an illustration:

| entities | evaluations | `check()` | per evaluation |
|---:|---:|---:|---:|
| 10 | 60 | 12 ms | 198 us |
| 100 | 600 | 86 ms | 143 us |
| 1000 | 6000 | 831 ms | 139 us |

Four indicators per entity across five axioms, 40 observations per series, five runs per size,
median reported. **It is linear in evaluations, and the per-evaluation cost does not degrade with
scale** — that is the part worth knowing, and it is the part that does not depend on the machine.

Getting a model and its data in is excluded from that table, and it is three costs on two axes.
**Feeding entities scales with the entities:**

| entities | feed | per entity |
|---:|---:|---:|
| 10 | 15 ms | 1535 us |
| 100 | 146 ms | 1463 us |
| 1000 | 1546 ms | 1546 us |

**Loading a model scales with the model, and the parse in front of it is the larger cost:**

| indicators | invariants | `yaml.safe_load()` | `load_model()` |
|---:|---:|---:|---:|
| 4 | 8 | 4 ms | 0.20 ms |
| 40 | 80 | 38 ms | 1.23 ms |
| 180 | 360 | 164 ms | 4.77 ms |
| 360 | 720 | 327 ms | 11.61 ms |

Three things follow, and the third is the one that saves anybody time. The feed is paid for whatever
data is added, so a consumer re-feeding every cycle pays it every cycle. `load_model()` is flat in
the entity count, so a session held across cycles pays it once — but it is *not* flat in the model,
and quoting it from a four-indicator fixture is how it gets called negligible. And **`load_model()`
takes a mapping, not a file**: at 180 indicators the YAML parse in front of it costs about thirty
times the load, so a consumer paying a quarter-second to get a generated model in is mostly paying
PyYAML. Cache the parsed mapping rather than only the session, and use `yaml.CSafeLoader` where
libyaml is installed — same result, several times faster.

Re-derive it rather than trusting the tables. The two axes are separate arguments, because they are
separate questions:

```bash
python3 -m arbiter_engine.scripts.benchmark_check --sizes 10,100,1000 --model-sizes 4,40,180,360 --repeat 5
```

## Documentation

| File | Answers |
|---|---|
| [`MODELING.md`](MODELING.md) | how to write a domain model, and the rule that is easy to get wrong |
| [`BRIDGES.md`](BRIDGES.md) | how to write the program that feeds one, starting from the reasons this engine refuses to answer |
| [`CHANGELOG.md`](CHANGELOG.md) | what changed, and which version numbers do not exist |
| [`COMPATIBILITY.md`](COMPATIBILITY.md) | what a patch release may change, and what waits |
| [`schema/envelope.schema.json`](schema/envelope.schema.json) | the response shape, machine-readable |

Three worked models ship in `examples/`: `water_tank.yaml` declares all eight axioms and doubles as
the schema reference, `kubernetes_node.yaml` is the smallest domain where a band matters, and
`battery_pack.yaml` is one where nearly every bound is a floor somebody published.

**Built on this engine**: [`bmc-sensor-audit`](https://github.com/james-sheen/bmc-sensor-audit)
audits firmware sensor coverage; [`fleet-sensor-baseline`](https://github.com/james-sheen/fleet-sensor-baseline)
aggregates its output across a fleet. Both are by this author rather than independent adopters, so
take them as worked examples of the shape in `BRIDGES.md` and not as evidence anyone else has done it.

Evidence and technical write-ups live in `evidence/` — architecture, deployment runbook,
fault-scenario catalogue, and the observation logs from the closed-loop alpha, including the
findings that went against us.

## Licence

**Apache License 2.0.** See `LICENSE` and `NOTICE`.

`TRADEMARK.md` is separate and narrower: Apache Section 6 withholds any trademark grant, and that
file says what use of the name *is* permitted. *Arbiter* is a project name, not a licence grant.

## Contributing

See `CONTRIBUTING.md`. Adversarial findings are the most useful thing you can send: if the engine
reports a clean pass over something it did not actually evaluate, that is the bug this project most
wants to hear about.
