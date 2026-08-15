# Digital Twin Substrate — Engineering Tech Brief

**Document type**: Engineering reference — architecture overview + integration topologies + extensibility evidence + onboarding path + observability + API surface.
**Date**: 2026-05-31.
**Status**: a dated record, not current documentation — see `README.md` in this directory. Landed 2026-05-31; framing corrected and content re-checked 2026-08-06 — axiom-checker count matches the pinned manifest, no stale domain counts, and the claims cited resolve in the registry. The draft-status marker it carried until then was stale rather than a live review item.
**Audience**: engineering / SRE / platform / ML-infra readers, at the time of writing, evaluating substrate fit.

---

## What of this ships, and what does not

**This brief describes the whole substrate. The published package is one
component of it.** Of the components named below, `TopologyTraverser` and the
eight axiom checkers are in `arbiter_engine`; the rest — the decision engine,
the action planner and dispatcher, the posterior estimator, the goal-alignment
monitor, the field-agent collectors and the RBAC surface — are **not published**.

That split is the same one the repository README states: the engine is open, the
knowledge and the operations are not. It is stated concretely here because a
reader holding only the engine would otherwise have to discover it by looking for
a class that is not there.

Nothing below is an instruction. Where the text describes extending the system —
adding a collector subclass, wiring a new vertical — it is describing how the
full substrate was extended, not a path available in this package.

---

## Substrate architecture (1-minute summary)

The Digital Twin substrate is a 4-pillar closed-loop architecture: **Mirrors → Predicts → Acts → Learns**. Each pillar is a substrate module with explicit interfaces; together they form an operational loop where detection commits to remediation, dispatch tracks outcomes, and outcomes update the next cycle's posterior.

- **Mirrors**: collector subclasses (K8sFieldAgent / WebsocketFieldAgent / PollingHTTPFieldAgent / KafkaConsumerFieldAgent) ingest partner observation streams; the Digital Twin topology builds a typed entity graph (entities + relationships + indicator timeseries) per partner-supplied YAML schema.
- **Predicts**: the Cognizer runs 8 axiom checkers (STABILITY / BOUNDEDNESS / CONNECTIVITY / CONSISTENCY / RESPONSIVENESS / HOMEOSTASIS / CONSERVATION / MONOTONICITY) plus domain-specific consistency rules against the observation stream; emits Problems with per-axiom severity verdicts.
- **Acts**: DecisionEngine binds Problems to ActionTemplates per the domain YAML; ActionPlanner sequences multi-step remediation; the ACTIVE-mode policy engine gates each proposed action (auto-approve / route-to-review / reject); ActionDispatcher executes against partner infrastructure via the same collector substrate.
- **Learns**: OutcomeFeedbackLoop records dispatched-action → observed-outcome pairs; Bayesian posterior re-fit (`BayesianPosteriorEstimator`); GoalAlignmentMonitor flags policy-drift vs operator-stated goals.

The BayesianPosteriorEstimator + cross-domain posterior propagation make the Learns pillar load-bearing — every closed dispatch updates priors for the next dispatch. (Scope: Phase-0 agentless HTTP path under the second evaluation round run conditions — HTTP-record-only, not real infrastructure mutation; closure rests on maintainer-gated confirmation. [CLM-015])

All four pillars share substrate (entity graph, observation history, axiom registry, policy registry, audit log, RBAC). Adding a new vertical = new YAML + new collector subclass; the four pillars and their substrate stay untouched.

## Integration topologies

Three deployment modes, ordered by partner-side commitment:

### Topology A — Passive Observer

Partner streams metrics + events to a `PollingHTTPFieldAgent` (HTTP pull) or `KafkaConsumerFieldAgent` (event stream). Substrate runs as a sidecar / out-of-cluster service; no partner-side dispatch wiring. Operator reviews recommendations via the dashboard surface (`/dashboard`, `/findings`, `/about/architecture`); action dispatch is maintainer-gated via existing ticket / playbook flow.

- **Setup time**: 1-2 weeks (most of which is partner's metrics-endpoint authorization + network egress allowlisting).
- **Operator-side change**: dashboard URL + Explains-pillar narratives consumed via existing oncall workflow.
- **Risk**: zero (read-only; no infrastructure mutation by substrate).

### Topology B — Proxy Mode

Substrate proxies a subset of partner traffic. The Phi-3 demo is this shape: FastAPI proxy with input-moderation + output-rewriting, llama.cpp upstream, per-request observation flow, in-line policy decisions visible at `/dashboard-data`.

- **Setup time**: 4-6 weeks including operator approval workflow.
- **Operator-side change**: traffic-routing change (DNS / load-balancer rule) to direct subset traffic through the proxy.
- **Risk**: moderate (substrate is in the request path; HA + fallback wiring required for production traffic).

### Topology C — Control-Plane Orchestrator (roadmap / aspirational — NOT operationalized; only Topology A/B are live today)

Substrate dispatches ActionTemplates against partner serving infrastructure: route-to-fallback rewrites endpoint config; circuit_break_endpoint patches partner's load balancer; scale_up_replicas triggers partner-side HPA scaling; trigger_retrain enqueues a partner-side job; roll_back_version updates partner-side deployment manifest.

- **Setup time**: 12-16 weeks including security review + partner-side dispatch wiring (each ActionTemplate's `parameters_schema` maps to partner's CRD / control-plane API).
- **Operator-side change**: per-action multi-step approval chain configured via UserStore RBAC; SLA-bound policy registration.
- **Risk**: HIGH (substrate mutates partner infra); HIGH-risk action templates default to `route_to_review` policy verdict — operator manually approves first dispatch for each action template.

Partners typically progress A → B → C over 4-6 months as trust accumulates. The 6-stage drill is the operationalized progression.

## YAML-only extensibility evidence

The `domains/ai-ml-serving.yaml` file is 994 lines of pure schema — no Python edits required to ship this vertical. Concretely:

| Substrate component | YAML key | AI/ML serving count |
|---|---|---|
| Entity types | `entity_types:` | 6 (ModelEndpoint, ModelVersion, InferenceRequest, DriftWindow, ServingReplica, InferenceClient) |
| Relationship types | `relationship_types:` | 6 (serves, replicaOf, tracks, consumes, handles, REFERENCES) |
| Indicators (axiom-bound timeseries) | `indicators:` | 25 across 6 entity types |
| Consistency rules | `consistency_rules:` | 3 (endpoint_drift_floor, accuracy_above_floor, endpoint_cost_within_budget) |
| Action templates | `action_templates:` | 5 (route_to_fallback, trigger_retrain, scale_up_replicas, circuit_break_endpoint, roll_back_version) |
| Chaos scenarios | `chaos_scenarios:` | 13 (drift floor breach, accuracy below floor, p99 latency critical, queue overflow, GPU saturation, error storm, replica memory exhaustion, impossible token count, rollout percentage overflow, cost budget cascade, schema drift, network partition latency storm, drift window cumulative) |
| Active-mode policy | `active_mode_policy:` | Risk-tiered auto-approval gates (LOW auto; MEDIUM route; HIGH multi-step approval) |
| Approval chains | `approval_chain:` | Per-action templates; multi-step operator review chains |

Cross-domain validation: the same YAML schema shipped K8s (`domains/k8s.yaml`) and trading (`domains/trading.yaml`); 7 more shipped as substrate-proof verticals (bms, consulting, dcim, docker, electronics_constraints, network, k8s_constraints). The schema accommodates 10+ verticals today; the substrate is genuinely YAML-driven, not vertical-fork-driven.

Adding a new vertical: write a YAML file matching the schema; subclass `BaseFieldAgent` (contract) if no existing collector covers the partner's metrics endpoint; ship. Typical new-vertical effort: 1-3 weeks for the YAML; 1-2 weeks for the collector subclass (zero if partner exposes Prometheus / HTTP metrics).

## Partner-onboarding 6-stage runbook

the full system implements the pre-flight drill. Each stage emits a structured envelope with `status: pass | fail | warn` + remediation hints when needed.

1. **Connectivity**: verify partner's metrics endpoint reachable + auth working. Failure mode: network egress rules / auth header misconfiguration.
2. **Schema validation**: parse partner-supplied YAML against substrate schema; surface missing required keys + invalid axiom bindings.
3. **Observation flow**: collector ingests 60 seconds of live partner data; verify entity-graph builds + indicators populate.
4. **Detection sanity**: run axiom checkers against ingested data; surface any baseline-violation Problems (often partner's monitoring already knows about these — useful cross-check).
5. **Action template fit**: validate each action template's `parameters_schema` against partner's control-plane API surface; surface dispatch-side wiring gaps.
6. **End-to-end policy-gated dispatch**: in partner-staging environment, dispatch one MEDIUM-risk action template through the full pipeline (detection → planner → policy gate → dispatcher → outcome observation). Operator confirms or rejects each step.

Most partners clear Stages 1-3 in the first week of engagement; Stage 4 surfaces 1-3 baseline observations worth a follow-up call; Stages 5-6 land in weeks 3-6 depending on partner-side dispatch wiring readiness.

## Observability surface

- **Prometheus metrics**: 14+ substrate-instrumented metrics emitted on `/metrics` (request counts per indicator, axiom-checker fire counts, action dispatch counts, policy gate decisions, posterior re-fit cycles,...).
- **Traces**: per-decision narrative trace via Explains pillar — each policy-gated dispatch carries a 3-paragraph operator-trustworthy narrative (Trigger / Decision / Evidence) accessible via `/dashboard-data` (per-decision drill-down).
- **Dashboards**: `/dashboard` (operator real-time view), `/findings` (closed-loop event log), `/about/architecture` (4-pillar reference page with deep-links to decision-CDs).
- **Audit log**: every action-dispatch + policy-decision recorded in `AuditLog` table; RBAC-gated retrieval API at `/audit/*`.
- **Cognitive-depth narratives**: 8 PROVEN pillars (Explains / Plans / Reasons / Negotiates / Wonders / Self-audits / Designs / Forgets) each surface operator-trustworthy LLM-generated narratives via dedicated explainer modules under the full system + `plan_explainability/` + `reasoning_explainability/` + 5 more sibling modules (~4,340 LOC total).

## API surface

REST surface (FastAPI-based; OpenAPI auto-generated at `/openapi.json`):

- `POST /api/v1/observations` — ingest entity-state observations (collector-side)
- `POST /api/v1/observations/batch` — batch ingest with `BatchSetResult` per-entity error context
- `GET /api/v1/problems` — query current Problems with axiom-verdict filters
- `GET /api/v1/recommendations` — query pending recommendations (operator review surface)
- `POST /api/v1/approvals/{recommendation_id}` — multi-step operator approval flow
- `GET /api/v1/audit` — RBAC-gated audit log retrieval
- `GET /dashboard-data` — operator real-time view backing data
- `GET /endpoints` — substrate endpoint inventory (44+ the established pattern endpoints in-tree; 59 instances live on the demo deployment as of 2026-06-21)
- `POST /agents/register` — WebSocket Field Agent registration (Tier C control-plane partners)

WebSocket surface:

- `/ws/agent/{agent_id}` — bidirectional Field Agent ↔ Core wire protocol (reconciliation envelope)

LLM surface (unified factory):

- 6 providers supported (OpenAI / Anthropic / Bedrock / Cohere / Together / Local-Ollama)
- Per-provider `LLMClient` ABC + cost-tracked Cached + Fallback + Retrying decorators
- Default provider: OpenAI; `LLM_PROVIDER=anthropic` opts in

## Failure-mode posture

The substrate is designed to fail loud, not silent. Specifically:

- Collector failures emit per-error structured envelopes (no silent observation drops)
- Policy gates default to `route_to_review` on any unresolvable verdict (no silent auto-approval)
- ActionDispatcher TIMEOUT records persist for the retention window (default 1 hour) — operator sees terminal-state actions in `/recommendations` for the grace period before reap
- Cache eviction emits sample-capped WARN logs — operators see activity without log-bombing
- Wire-protocol drift between Field Agent and Core surfaces reconciliation envelopes (no silent message-loss)

The 8 cognitive-depth pillars (Explains / Plans / Reasons / Negotiates / Wonders / Self-audits / Designs / Forgets) each surface their own audit gates — every LLM-generated narrative passes a 3-heuristic mechanical audit (validity / no-hallucination / coverage) before reaching operator review. the established pattern (substrate-API-discovery-before-test) gives us 215 consecutive first-run-green pin tests across the cognitive-depth substrate.

### Cascade-recovery evidence (Alpha-1 closure 2026-06-13)

The Alpha-1 substrate-exercise window (Days 1-11 / 10-day compressed at 6× intensity) produced empirical cascade-dynamics evidence partners can reference for failure-mode SLA negotiation:

- **Pattern N family** stabilized at 3-branch META reference architecture: N.a throughput-clamp via sleep-loop + N.b 403-cascade via rate-limit short-circuit + N.c 502-cascade via upstream-timeout. Each branch identifies a distinct cascade mechanism; per-axiom ring-buffer evidence distinguishes which is active.
- **Pattern N.c 96h-stable upgrade (Alpha-1 baseline-traffic regime)**: 502 upstream-timeout cascade self-recovers within ~48h via upstream stabilization; Day-11 evidence confirms recovery stability holds at 96h+ horizon (Day-7 fault end → Day-11 sustained-observation; zero 502 responses across the full window). **Scope qualifier (2026-06-20)**: claim is verified under baseline-traffic regime (~1 req/min/tenant, mixed cache hits). Compression-D 6h 48× sustained-rate replay 2026-06-19 surfaced a residual gap: 128-token completions at empirically-measured 1.19 sec/token exceeded 90s timeouts within the run, producing in-window 502s that did not auto-resolve. An internal ruling closed the gap via `MAX_TOKENS_DEFAULT=64`; the production claim now applies when operator provisions per the documented tuning recipe (`MAX_TOKENS_DEFAULT=64` + 90s timeouts + cpuset pin). The 96h-stable cascade-recovery claim holds (under the Alpha-1 baseline-traffic regime with the documented tuning recipe: MAX_TOKENS_DEFAULT=64 + 90s timeouts + cpuset pin,. [CLM-016]). See the Compression-D replay grade of 2026-06-19, unpublished, for evidence + the Pattern N.c claim-scope memo body in the methodology notes memory.
- **Asymmetric-recovery sub-pattern (most demo-worthy single observation)**: N.c self-clears 48h-bound while N.b persists at homeostatic equilibrium until intervention. When N.c resolves, retry-suppression unclamps → N.b rate rebounds. The two cascades interact via retry-suppression mechanism, not just additively.
- **16 cumulative L5 surprises during Alpha-1** across 4 thematic clusters (cascade-equilibrium-dynamics / methodology-substrate-gaps / axiom-family-dynamics / phantom-instrumentation) **+ 6 post-Alpha replay-arc surprises in Cluster E (Compression-B/C/D/E) = 22 cumulative** — partner-pitching narrative at `l5_surprise_synthesis.md`.

**Drill-down.** Published alongside this brief: `alpha1_evidence_pack.md`, `l5_surprise_synthesis.md`.
Cited for provenance only, not published: the daily hypothesis log, Days 1-11, and the Compression-D replay grade of 2026-06-19.

## Scaling characteristics (run observation)

The Phase B the hosting provider deployment is intentionally small (the serving VM: 2 dedicated AMD Milan vCPU, 8 GB RAM, ~$12/month). Phi-3-mini-Q4 served via llama.cpp sustains ~5-20 requests/sec depending on prompt length. The substrate proxy + content_moderation stack on the serving box adds ~5-15ms p99 latency overhead. (Note: since the 2026-06-15 migration, Core runs on a separate reference VPS host — it is NOT co-located on this reference deployment / the serving VM serving box; the proxy on the serving box reports to Core over the network.) Substrate metrics emission adds <1% CPU overhead.

Production-scale partner deployments would scale horizontally (collector subclasses are stateless; Core is single-tenant per partner today, multi-tenant via UserStore RBAC; observation history is TimescaleDB-backed for cardinality). The substrate has not been load-tested above 1000 req/sec sustained; that's the next observation gate as Tier-C partner engagements land.

