# Arbiter use-case catalogue — what you can run today, and how

**Written from the user's chair, 2026-08-11.** Everything in the operation process below was
executed against a clean build of the package on that date, on a domain the engine had never seen.
Where a step has a trap, the trap is recorded because it cost time.

**Scope**: `arbiter-engine` v0.1 as it stands — 8 axioms, 5 verbs, an MCP server, a YAML schema,
`numpy` and `pyyaml`. Not on PyPI; you clone it.

---

## 0. What you get, and what you must bring

The engine answers one question that other checkers do not: **did you look?**

Every pass returns findings, plus a list of evaluations that declined with a machine-readable
reason, plus a denominator of how many were attempted. A clean result means *these invariants were
tested and held* — distinguishable from *nothing was testable*. That is the product.

| You get | You bring |
|---|---|
| 8 axiom checkers | the domain model (YAML) |
| the envelope (findings / declines / denominator) | the observations — there is no collector |
| topology traversal, 3 live value modes | the entity IDs and relationships |
| 5 verbs + an MCP server | scheduling, storage, alerting, UI |

**There is no ingest.** The engine does not scrape, poll, subscribe or connect to anything. You call
`add_entity` and `add_observations`. Every use case below therefore has an *adapter* you write —
usually 30-80 lines — and that adapter is the real integration work.

**History is in-memory.** `InMemoryObservationHistory` is what ships. Persistence across restarts is
yours.

---

## 1. The operation process — one process, verified

This is the same for every vertical. Only the YAML and the adapter change; that is the
domain-agnostic claim, and running it on a domain with no internal pack is what tests it.

### Step 1 — Install

```bash
git clone <repo> && cd arbiter
pip install -e .          # numpy + pyyaml, nothing else
python3 -c "
from arbiter_engine.api import EngineSession, model_describe
s = EngineSession(); s.load_model('examples/water_tank.yaml')
print(model_describe(s).to_dict()['checked'])"
# -> {'invariants': 0, 'entities': 3, 'declared_invariants': 10}
```

The zero is the point: ten invariants declared, none evaluated, because no observations exist yet.
It is reported rather than left for you to infer from an empty finding list.

### Step 2 — Write the domain model

`examples/water_tank.yaml` declares all eight axioms in one file and doubles as the schema
reference. Copy it and replace the nouns. The shape:

```yaml
domain:
  id: your-domain
  entity_types:   [Thing, OtherThing]
  relationship_types: [feeds, controls]
  indicators:
    Thing:
      - name: some_measure
        type: NUMERIC
        axioms: [BOUNDEDNESS, HOMEOSTASIS]
        warning: 85
        critical: 95
        window: 1h
```

**Choosing axioms** — the mapping that matters:

| If the question is | Use |
|---|---|
| is it over a ceiling? | `BOUNDEDNESS` (**upper bounds only**) |
| is it below where it should be? | `HOMEOSTASIS` — *not* BOUNDEDNESS with an inverted threshold |
| does it settle, or hunt? | `STABILITY` |
| may it only ever rise (or fall)? | `MONOTONICITY` |
| does what goes in come out? | `CONSERVATION` |
| must this thing be attached to that thing? | `CONNECTIVITY` |
| do two independent readings agree? | `CONSISTENCY` |
| did it react before the deadline? | `RESPONSIVENESS` |

`axioms: []` is meaningful — the values flow into history without a per-cycle check. Silence is a
declaration, not an omission.

### Step 3 — Supply entities. **Two channels, and this is trap #1.**

```python
s.add_entity("reefer/A", "Reefer", {"product_temp_c": 8.6})
s.add_observations("reefer/A", "product_temp_c", [...40 samples...])
```

- entity **properties** carry the *current* value -> threshold axioms read these
- observation **history** carries the *series* -> statistical axioms read that

Supplying only history means `BOUNDEDNESS` reads `None` and returns quietly. In the first run of the
worked example below, a deliberate excursion to 8.6 C against a critical of 8 produced **zero
findings** for exactly this reason. Supply both.

### Step 4 — Relationships. **Trap #2: the ID convention is load-bearing.**

```python
s.graph.add_relationship("reefer/A", "cooled_by", "compressor/A")
#                         source      RELATION      target      <- relation in the MIDDLE
```

There is no `Relationship` class to construct, and the argument order is not
`(source, target, relation)`.

**`CONNECTIVITY` matches entities by ID prefix, not by declared type.** The checker computes
`target_type.lower() + "/"` and looks for entity IDs starting with it. With IDs like `comp-A`, a
`target_type: Compressor` indicator declines with `missing_entity_type` — *even for entities you
correctly registered as Compressors*. Rename to `compressor/A` and it evaluates.

In the worked example this was the difference between silence and
`missing_relationship:cooled_by_compressor | reefer/B | high`. **Namespace every entity ID as
`<type>/<id>` from the start.**

### Step 5 — Run the five verbs

| Verb | Answers |
|---|---|
| `model_describe(s)` | what vocabulary is loaded — call it first, so an agent cannot invent an entity type |
| `check(s)` | evaluate declared invariants over the observations |
| `traverse(s, [start], value_mode=…)` | the kernel — root cause, impact, what-if as one parameter space |
| `gaps(s)` | DISCOVER — what the model is missing, ranked |
| `attest(s, problem_type)` | the evidence behind a finding: axiom, threshold, values, confidence |

`value_mode='projected'` (PREDICT) needs enough history on **the nodes you start from** to fit a
trend; it refuses rather than silently reading present values.

### Step 6 — Read the declines. **This is the step people skip, and it is the product.**

```
not_evaluated: 8
    4  insufficient_samples
    2  not_applicable
    2  missing_entity_type
```

Each carries a `detail`. Two `not_applicable` details from the worked run are worth quoting because
they are **naming contracts nobody would guess**:

- `CONSISTENCY` — *"no universal rule applies: the indicator name does not tokenise to count,
  percent/pct or ratio"*
- `RESPONSIVENESS` — *"check() only evaluates indicators whose name contains 'response' or
  'latency'"*

So `pulldown_error_c` was never checked for responsiveness, and `product_temp_c_redundant` was never
checked for consistency — **declared in the model, silently inapplicable in the engine, and the
decline is the only reason you find out.** Name the indicator `pulldown_response_c` and it
evaluates. Read the declines on your first run and rename accordingly.

### Step 7 — Wire it into something

The engine is a library. Three shapes:

- **Batch** — cron a script, print the envelope, exit non-zero on critical findings. Smallest useful thing.
- **Service** — wrap `check` in your own HTTP handler, keep one `EngineSession` warm, persist history yourself.
- **Agent** — run the MCP server (`arbiter_engine.mcp.server`) and let an LLM call the five tools.
  This is the differentiated path: the agent gets `model_describe` for grounding and the declines
  keep it honest about what it does not know.

---

## 2. The vertical catalogue

**Legend.** **[P]** = a domain pack for this vertical already exists internally and is held as the
knowledge asset — the shape is proven, you would write your own YAML. **[N]** = novel; nobody has
modelled it yet.

**Fit** is judged on what v0.1 actually does: sampled numeric series over identified entities with
declared invariants. It is not judged on how interesting the vertical is.

---

### Family A — Cloud and platform infrastructure

**A1. Kubernetes cluster health [P] — fit: strong**
Entities: Node, Pod, Deployment, PVC, Service. Indicators: `cpuUsageNanoCores` (STABILITY,
BOUNDEDNESS, HOMEOSTASIS), `restartCount` (MONOTONICITY), replica actual-vs-desired (CONSISTENCY),
Service-to-Pod selector (CONNECTIVITY). Adapter: metrics-server + the API.
**Silent failure caught**: a Service whose selector matches no Pods — every dashboard green, traffic
blackholed. CONNECTIVITY names it; a threshold checker cannot see it.

**A2. Container fleet / Swarm [P] — fit: strong**
As above without the K8s object model. Indicators: container restarts (MONOTONICITY), memory
(BOUNDEDNESS), image drift across replicas (CONSISTENCY).
**Silent failure**: one replica running last week's image. Nothing is *wrong* on any single host.

**A3. AI/ML model serving [P] — fit: strong**
Entities: Endpoint, Model, GPU, Queue. Indicators: `p99_latency_ms` (RESPONSIVENESS — name already
tokenises), `tokens_per_sec` (HOMEOSTASIS, not BOUNDEDNESS — lower is worse), GPU memory
(BOUNDEDNESS), queue depth (STABILITY), requests-in vs responses-out (CONSERVATION).
**Silent failure**: requests accepted and never answered. CONSERVATION catches the imbalance; a
latency SLO computed over *completed* requests never will.

**A4. Network fabric [P] — fit: strong**
Entities: Switch, Interface, Link, BGPSession. Indicators: interface errors (MONOTONICITY), optical
power (HOMEOSTASIS), packets-in vs packets-out (CONSERVATION), session adjacency (CONNECTIVITY).
**Silent failure**: a redundant path that quietly lost its redundancy months ago.

**A5. Data centre facilities / DCIM [P] — fit: strong**
Entities: Rack, PDU, CRAC, UPS. Indicators: rack power draw (BOUNDEDNESS), inlet temperature
(BOUNDEDNESS + HOMEOSTASIS), PDU feed A/B balance (CONSISTENCY), UPS runtime (MONOTONICITY
decreasing), rack-to-PDU (CONNECTIVITY).
**Silent failure**: a dual-fed rack drawing everything from one side. Both feeds healthy; redundancy
gone.

**A6. Server firmware / BMC [P] — fit: good**
Entities: Chassis, PSU, Fan, Sensor. Indicators: fan RPM (STABILITY), PSU input-vs-output
(CONSERVATION), sensor readings vs redundant sensor (CONSISTENCY).
**Silent failure**: a sensor that stopped updating but still returns its last value.

**A7. SIEM detection coverage [P] — fit: good, unusual**
Entities: LogSource, Rule, Asset. Indicators: events per source per hour (HOMEOSTASIS), rule
fire-rate (HOMEOSTASIS), Asset-to-LogSource (CONNECTIVITY).
**Silent failure**: the one every SOC fears — a log source that went quiet. Zero alerts from a
source reads identically to zero threats. CONNECTIVITY plus HOMEOSTASIS separates them, and the
`not_evaluated` leg is the coverage report you could not otherwise produce.

---

### Family B — Industrial and physical

**B1. SCADA / OPC-UA process [P] — fit: strong**
Entities: Tag, Loop, Actuator. Indicators: process variable (BOUNDEDNESS, STABILITY), setpoint error
(RESPONSIVENESS — name it `setpoint_response_error`), totaliser (MONOTONICITY).
**Silent failure**: a control loop oscillating within limits. Never alarms; wears the valve out.

**B2. Building management / HVAC [P] — fit: strong**
Entities: AHU, Zone, Chiller, Valve. Indicators: zone temp (HOMEOSTASIS), chiller kW-per-tonne
(BOUNDEDNESS), supply-vs-return (CONSERVATION), damper response (RESPONSIVENESS).
**Silent failure**: simultaneous heating and cooling in one zone. Both subsystems report success.

**B3. Water and wastewater [N] — fit: strong; this is the shipped example**
`examples/water_tank.yaml` is a two-tank system declaring all eight axioms. Scale it: Reservoir,
Pump, Valve, Meter. Inflow-vs-outflow (CONSERVATION) is leak detection.
**Silent failure**: non-revenue water. Every pump reports healthy while treated volume leaves the
network unaccounted for — the loss is only visible as an imbalance across the system, never at a
single asset.

**B4. Manufacturing line / OEE [N] — fit: strong**
Entities: Station, Robot, Conveyor, Buffer. Indicators: cycle time (STABILITY, BOUNDEDNESS), units
in vs out per station (CONSERVATION), buffer depth (BOUNDEDNESS), part count (MONOTONICITY),
Station-to-Station (CONNECTIVITY).
**Silent failure**: scrap disappearing between stations. Each station reports its own throughput as
fine; only the conservation check across the line sees the loss.

**B5. Cold chain logistics [N] — fit: strong. Worked end-to-end in section 3.**

**B6. Power grid / substation [N] — fit: strong**
Entities: Feeder, Transformer, Breaker, Meter. Indicators: transformer loading (BOUNDEDNESS), oil
temperature (BOUNDEDNESS + HOMEOSTASIS), power in vs out (CONSERVATION — this is technical loss),
tap-changer operations (MONOTONICITY), breaker-to-feeder (CONNECTIVITY).
**Silent failure**: a transformer running hot for its *own* baseline while under nameplate.

**B7. Battery energy storage [N] — fit: strong**
Entities: Rack, Module, Cell, Inverter. Indicators: state of charge (HOMEOSTASIS), cell voltage
spread (CONSISTENCY — the single most valuable check in BESS), cycle count (MONOTONICITY), energy in
vs out (CONSERVATION = round-trip efficiency).
**Silent failure**: one cell drifting from its pack. Pack-level metrics stay nominal until thermal
runaway.

**B8. EV charging network [N] — fit: good**
Entities: Site, Charger, Connector. Indicators: session success rate (HOMEOSTASIS), energy delivered
vs metered (CONSERVATION), time-to-handshake (RESPONSIVENESS), Connector-to-Charger (CONNECTIVITY).
**Silent failure**: a charger that accepts sessions and delivers no energy. Uptime dashboards say
100%.

---

### Family C — Financial

**C1. Trading systems [P] — fit: strong**
Entities: Strategy, Book, Venue, Feed. Indicators: position vs limit (BOUNDEDNESS), PnL deviation
(HOMEOSTASIS — *never* BOUNDEDNESS; lower is worse), order-to-fill (CONSERVATION), fill latency
(RESPONSIVENESS), feed staleness (MONOTONICITY on sequence number), Strategy-to-Venue
(CONNECTIVITY).
**Silent failure**: a strategy silently disconnected from a venue. It reports no errors because it
is doing nothing.

**C2. Settlement and clearing [P] — fit: strong**
Entities: Batch, Instruction, Counterparty, Account. Indicators: instructions in vs settled
(CONSERVATION), unmatched aging (MONOTONICITY), cutoff adherence (RESPONSIVENESS).
**Silent failure**: a batch that partially settled. Both the sent and received counts look
plausible; only the conservation check across the boundary disagrees.

**C3. Payment ledger reconciliation [N] — fit: strong**
Entities: Ledger, Account, Gateway. Indicators: debits vs credits (CONSERVATION), balance
(CONSISTENCY — the name tokenises poorly, call it `balance_ratio`), settlement lag
(RESPONSIVENESS).
**Silent failure**: a rounding drift that nets to nearly zero daily and accumulates annually.

**C4. Treasury and liquidity [N] — fit: good**
Entities: Entity, Account, Facility. Indicators: buffer vs requirement (HOMEOSTASIS), facility
utilisation (BOUNDEDNESS), forecast-vs-actual (CONSISTENCY).

---

### Family D — Life sciences and health

**D1. GMP bioreactor / process [N] — fit: strong, high value**
Entities: Reactor, Probe, FeedPump, Batch. Indicators: dissolved oxygen (HOMEOSTASIS + BOUNDEDNESS),
pH (HOMEOSTASIS), redundant probe agreement (CONSISTENCY), feed in vs mass balance (CONSERVATION),
control response (RESPONSIVENESS).
**Why this vertical is the strongest non-obvious fit**: GMP requires you to demonstrate the process
stayed in a validated state. *"We checked N invariants, these held, these declined and here is
why"* is closer to a batch record than anything a monitoring tool emits. The `not_evaluated` leg is
the deviation report.
**Caveat**: GxP validation of the tool itself is a real programme. Nothing here is validated.

**D2. Clinical trial data integrity [N] — fit: good, unusual**
Entities: Site, Subject, Form, Query. Indicators: enrolment rate (HOMEOSTASIS), query aging
(MONOTONICITY), source-vs-EDC agreement (CONSISTENCY), Subject-to-Site (CONNECTIVITY).
**Silent failure**: a site whose data is *too* clean. HOMEOSTASIS against the multi-site baseline
flags the outlier that no per-site rule can.

**D3. Hospital capacity and flow [N] — fit: good**
Entities: Ward, Bed, Theatre, Queue. Indicators: occupancy (BOUNDEDNESS), admissions vs discharges
(CONSERVATION), wait time (RESPONSIVENESS), staffing ratio (HOMEOSTASIS).

**D4. Medical device fleet [N] — fit: good**
Entities: Device, Site, Consumable. Indicators: self-test results (MONOTONICITY on failure count),
calibration age (BOUNDEDNESS), Device-to-Site (CONNECTIVITY).
**Silent failure**: a device that stopped reporting. Absence of alerts as evidence of health.

---

### Family E — Data and AI engineering

**E1. Data pipeline and freshness [N] — fit: strong, and the easiest first build**
Entities: Source, Job, Table, Dashboard. Indicators: rows in vs rows out (CONSERVATION), watermark
age (BOUNDEDNESS), row count (MONOTONICITY for append-only), null rate (HOMEOSTASIS), job duration
(STABILITY), Table-to-Job (CONNECTIVITY).
**Silent failure**: the canonical one. A pipeline that ran, succeeded, and wrote nothing. Every
orchestrator shows green. CONSERVATION and MONOTONICITY both catch it, and `not_evaluated` tells you
which tables were not covered at all.

**E2. Feature store and model drift [N] — fit: strong**
Entities: Feature, Model, Serving. Indicators: feature distribution (HOMEOSTASIS), training-vs-
serving skew (CONSISTENCY), null rate (BOUNDEDNESS), Model-to-Feature (CONNECTIVITY).
**Silent failure**: training-serving skew. Both pipelines healthy in isolation.

**E3. LLM application guardrails [N] — fit: good**
Entities: Route, Prompt, Provider. Indicators: refusal rate (HOMEOSTASIS), token cost per request
(BOUNDEDNESS), latency (RESPONSIVENESS), provider fallback rate (HOMEOSTASIS).

**E4. Agent tool-call audit [N] — fit: good, and self-referential**
Entities: Agent, Tool, Session. Indicators: calls issued vs results consumed (CONSERVATION), tool
error rate (HOMEOSTASIS), Agent-to-Tool (CONNECTIVITY).
Interesting because the engine ships an MCP server, so an agent can check *another* agent, and the
declines make the audit honest about its own coverage.

---

### Family F — Business operations

**F1. Consulting engagement health [P] — fit: good; proves the domain-agnostic claim hardest**
Entities: Engagement, Workstream, Consultant, Deliverable. Indicators: margin (HOMEOSTASIS —
**never** BOUNDEDNESS, lower is worse), utilisation (BOUNDEDNESS upper + HOMEOSTASIS lower),
milestone slip (MONOTONICITY), scope-in vs delivered (CONSERVATION), Deliverable-to-Owner
(CONNECTIVITY).
**Silent failure**: a deliverable with no owner. Nothing overdue, because nobody is tracking it.

**F2. RFP and bid pipeline [P] — fit: good**
Entities: Opportunity, Requirement, Response. Indicators: coverage ratio (CONSISTENCY — the name
tokenises), response aging (MONOTONICITY), Requirement-to-Response (CONNECTIVITY).
**Silent failure**: an unanswered mandatory requirement. The bid looks complete.

**F3. SaaS customer health [N] — fit: good**
Entities: Account, Seat, Feature, Ticket. Indicators: active seats vs licensed (CONSERVATION), usage
(HOMEOSTASIS), ticket aging (MONOTONICITY), time-to-first-response (RESPONSIVENESS).

**F4. Supply chain and inventory [N] — fit: strong**
Entities: SKU, Warehouse, Shipment, Supplier. Indicators: shipped vs received (CONSERVATION — this
is shrinkage), stock level (BOUNDEDNESS + HOMEOSTASIS), lead time (STABILITY), SKU-to-Supplier
(CONNECTIVITY).
**Silent failure**: single-sourcing you did not know about. CONNECTIVITY with `min_cardinality: 2`
names every SKU with one supplier.

---

### Family G — Public and civic

**G1. Environmental sensor networks [N] — fit: strong**
Entities: Station, Sensor, Region. Indicators: reading (BOUNDEDNESS + HOMEOSTASIS), co-located
sensor agreement (CONSISTENCY), reporting gap (RESPONSIVENESS), Sensor-to-Station (CONNECTIVITY).
**Silent failure**: a stuck sensor reporting a plausible constant. CONSISTENCY against a neighbour
catches it; a range check never will.

**G2. Fleet telematics [N] — fit: good**
Entities: Vehicle, Route, Depot. Indicators: fuel in vs distance (CONSERVATION), odometer
(MONOTONICITY), engine temp (BOUNDEDNESS), Vehicle-to-Depot (CONNECTIVITY).

**G3. Smart metering and utility billing [N] — fit: strong**
Entities: Meter, Feeder, Customer. Indicators: meter sum vs feeder total (CONSERVATION — non-
technical loss, i.e. theft), consumption (HOMEOSTASIS), reading recency (RESPONSIVENESS), register
(MONOTONICITY).
**Silent failure**: meter tampering. Each meter reads plausibly; only the conservation check at the
feeder disagrees.

---

## 3. Worked example, end to end — cold chain [N]

Chosen because no internal pack exists for it, so it tests the claim rather than replaying a
rehearsed demo. Model at `examples/`-style YAML; three entity types, all eight axioms exercised.

**Result of the verified run** (after fixing traps #1 and #2):

```
check   -> invariants: 17 evaluated across 3 entities
   FINDING  threshold_exceeded:product_temp_c        reefer/A       critical
   FINDING  threshold_exceeded:duty_cycle_pct        compressor/A   critical
   FINDING  missing_relationship:cooled_by_compressor reefer/B      high
gaps    -> 8 ranked questions, incl. "What does entity 'reefer/B' connect to?"
attest  -> axiom BOUNDEDNESS, confidence 1.0,
           evidence {indicator, value, threshold, threshold_type}
           boundary: engine-side evidence only; production records are v0.2
```

**What the first run got wrong, and why it matters**: with observations but no entity properties,
the same data produced **zero findings and no error**. With unprefixed IDs, the orphaned reefer was
declined as `missing_entity_type` rather than reported as a missing relationship. Both were
recoverable in minutes *because the declines said so* — which is the product demonstrating itself on
its own onboarding.

---

## 4. Honest limits

- **No collectors.** Every use case needs an adapter you write. This is the bulk of the work.
- **No persistence, scheduler, UI or alerting.** It is a library.
- **PREDICT is plumbed but thinly fed.** `projected` needs fitted trends on the start nodes.
- **`attest` is thin by decision.** Engine-side evidence only; the production attestation trail is v0.2.
- **Some axioms are name-driven.** RESPONSIVENESS and CONSISTENCY consult indicator *names*. Read
  your declines on run one.
- **Not on PyPI.** Clone and `pip install -e .`.
- **Scale is unmeasured.** Nothing here establishes a ceiling on entity or observation count.
- **The domain packs are not published.** The 13 base packs plus 7 constraint sidecars are held as
  the knowledge asset. Every **[P]** above says *the shape is proven*, not *the file is available*.

---

## 5. Where the boundary falls

The open/hold line is visible in this catalogue. The **mechanism** — the axioms, the envelope, the
traversal kernel, the schema — is open, and it is what makes any of these verticals expressible. The
**knowledge** — which indicators matter in trading versus DCIM, which thresholds are real, which
relationships are load-bearing — is the pack, and packs are held.

A reader can build any row above. What they cannot do is skip the modelling, and the modelling is
the expertise.
