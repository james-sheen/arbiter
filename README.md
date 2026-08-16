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
problems              what was found
not_evaluated         what was NOT evaluated, and why
evaluations_attempted how many (axiom, entity, indicator) evaluations were tried
```

`not_evaluated` entries carry a reason from a closed vocabulary of nine — `not_applicable`,
`insufficient_samples`, `missing_property`, `no_current_value`, `missing_config`,
`missing_entity_type`, `no_threshold`, `wrong_indicator_type`, `checker_error` — so a decline is
data, not a log line.

Three of the nine will account for most of what you see. `insufficient_samples` reports both the
count it had and the count it needed, so it tells you how much longer to collect.
`not_applicable` means the checker decided the axiom does not apply to that indicator at all —
worth reading closely, because it can be decided from a declared `role:`, and inferred from the
indicator's NAME when no role is declared.

`no_current_value` is the newest and the reason it exists is worth stating. A threshold axiom reads
`Entity.properties`; a temporal axiom reads observation history. Feed only the second and the value
is genuinely present and genuinely unreadable by the checker that wants it — and until 2026-08-16
that said `missing_property`, which told a caller holding sixty observations of a property that
there was no value for it. It now names the count and which store it is in. **That was reported
from outside**, and the vocabulary was the thing at fault: a closed set missing a member does not
raise, it reclassifies the case as the nearest member and reports it with confidence.

**Why the denominator matters.** Findings and declines do not sum to the total: an evaluation that
ran and found nothing appears in neither. Without `evaluations_attempted`, the statement *checked N
invariants* has no honest value of N — and an envelope reporting a fabricated denominator is the
exact failure the envelope exists to prevent.

All eight axiom checkers emit declines (24 call sites). This is not a property of one checker that
the others aspire to.

## The eight axioms

Declared per-indicator in a domain model, not in code:

| Axiom | Asks |
|---|---|
| `BOUNDEDNESS` | does this stay within its bounds? |
| `STABILITY` | does it settle, or oscillate? |
| `HOMEOSTASIS` | does it return to baseline after disturbance? |
| `MONOTONICITY` | does it move only in the permitted direction? |
| `CONSERVATION` | does what goes in come out? |
| `CONNECTIVITY` | is the topology intact? |
| `CONSISTENCY` | do related values agree? |
| `RESPONSIVENESS` | does it react within its deadline? |

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

Leave it out and the engine infers a role from the indicator's **name** — `response`/`latency` for
the first, `count`/`percent`/`pct`/`ratio` for the second — so models written before this field
existed behave exactly as they did. That inference is a guess about English, and when it misses, the
axiom declines `not_applicable` and the cycle stays green: an indicator called `pulldown_error_c`
could declare `RESPONSIVENESS`, be accepted, be listed by `model_describe`, and never once evaluate.

**You do not have to run a cycle to find that out.** `model_describe` reports
`unreachable_declarations` — every declared `(indicator, axiom)` pair that cannot fire under any
input, each with the remedy — and the loader logs the same list. An empty list is the target.

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

That prints `{'invariants': 0, 'entities': 3, 'declared_invariants': 10}` — three entities, ten
declared invariants, and **zero evaluated**, because no observations have been supplied yet. The
zero is the point: it is reported rather than left for you to infer from an empty finding list.

**Everything above is on the supported surface.** Until 2026-08-11 this example imported
`load_domain` from a deep module path — which works, and which this same README calls importable and
unsupported three sections down. The first thing a reader runs should not be the one thing the
document tells them not to depend on.

`examples/water_tank.yaml` is a deliberately synthetic two-tank water system that **declares all
eight axioms in one file**, so it doubles as the schema reference. It is not one of the curated
domain models — those are not published — and reading it is the fastest way to learn the shape.

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
from arbiter_engine.api import EngineSession, model_describe, check, traverse, gaps, attest

session = EngineSession()
session.load_model("examples/water_tank.yaml")
model_describe(session)   # what is declared: entity types, indicators, axioms
check(session)            # evaluate the declared invariants over supplied observations
gaps(session)             # what the model says should exist and nothing has been observed
```

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
  the contribution — the models are the accumulated work. `examples/water_tank.yaml` is a synthetic
  teaching model, deliberately not one of them.
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

**v0.1.** 57 Python files, 55 modules importing on the declared dependencies alone, 11 supported
names — **counted in this repository**, which is the package you are holding.

That basis is stated because it is easy to get wrong in a way nobody notices. The build adds one
`__init__.py` per package level, so a count taken before the build is smaller than the package you
are holding — and this line published the smaller figure until 2026-08-12, where any reader could
falsify it with `find . -name '*.py' | wc -l`. A checkable false claim, in the Status section of a
project whose subject is checkable claims. Count the artifact, never an earlier stage of it.

The import figure carries the same hazard one layer down, and it depends on what you have installed. Sweeping the package where `scipy` happens to be present imports 56; on the declared dependencies alone it is the 55 above, because `propagation.lp_confidence` is the one module that needs `scipy` and it is a deep path outside the supported surface. Count the artifact **in the state the reader will have it**, not in the state the person measuring happens to be standing in — this line quoted the with-`scipy` figure until 2026-08-12, which no reader installing normally could reproduce.

Honest boundaries, stated because you would otherwise find them yourself:

- **PREDICT is plumbed but unfed.** The traversal mode exists and nothing produces projected values
  outside a test. It is not a working forecast.
- **Not published to any index yet**, so installation is from a clone.
- **One worked example ships, not a library of them.** Modelling a real system is your work.
- Stage I and Stage II of this project are **archived, not running**. Anything describing them as
  production is out of date.

## Documentation

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
