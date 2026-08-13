# Extended Fault Scenarios — the second evaluation round+ Expansion Beyond Current 6

**Status**: design doc. Scenario priority and implementation order are undecided; nothing here has been implemented.
**Created**: 2026-06-19 (the second evaluation round Day 6 of 21)
**Scope**: failure-mode candidates NOT covered by current 6-scenario FAULT_SCHEDULE (rate_limit_burst / tenant_scope_drift / adversarial_burst / load_generator_outage_simulation / cost_budget_approach / pre_deadline_stress)
**Goal**: widen substrate coverage by introducing failure modes that exercise capabilities currently unexercised, and produce new L5 surprises beyond the 19 captured in Alpha-1 + reference-VPS-replay. Coverage of unexercised paths is the objective; a scenario that surfaces nothing is still a result.

---

## Coverage gap analysis

Current 6 scenarios all share `category=SCHEDULED_LOAD_MULTIPLIER` shape — they vary `intensity_multiplier` against the existing load generator chat_loop. Failure dimensions NOT yet exercised:

| Dimension | Current scenarios | Gap |
|---|---|---|
| Substrate shape | content + rate + cost + freshness | infra-fail / dep-fail / data-corruption / runtime-fail |
| Detection axiom | BOUNDEDNESS / HOMEOSTASIS / MONOTONICITY / RESPONSIVENESS | CONSERVATION / STABILITY rarely exercised |
| Time scale | minutes-to-hours | sub-second + days |
| Concurrent multi-stream | single the load generator sequential | multi-source / cross-tenant burst (blocked) |
| Adversarial sophistication | known-bad prompt set | DT-poisoning attempts / substrate-mutation attacks |
| Recovery path | self-recover via TTL / restart | manual operator intervention + rollback chain |

---

## 10 new scenario designs

Each scenario: **PRE** (what to set up) / **STIMULUS** (the injected fault) / **EXPECTED** (what substrate should detect + Action propose) / **OBS** (success criteria) / **VALUE** (why the scenario is worth exercising) / **EFFORT** (implementation).

### Scenario 7 — `pod_oom_kill` (hard infra failure)

- **PRE**: the load generator at baseline; the reference deployment nominal; memory budget set to 4 GiB on `ai-ml-llama-cpp` container
- **STIMULUS**: Set llama-cpp `--n-predict 4096` + send a prompt designed to allocate maximum context; cgroup OOM-killer fires; container restarts
- **EXPECTED**: MONOTONICITY axiom fires on `uptime_seconds` discontinuity (per T1 row 11); RESPONSIVENESS axiom fires on dropped requests; Action proposed = `scale_up_replicas` OR `circuit_break_endpoint`
- **OBS**: clinic/brief shows ≥1 axiom firing within 30s; action_planner proposes recovery action; if approved + dispatched, post-action observation shows uptime stabilized
- **VALUE**: K8s-native failure shape, and a common one. Exercises whether the DT detects the failure *pattern* rather than the metric alone.
- **EFFORT**: ~30min (the load generator prompt + scenarios.py entry; uses existing axiom + action templates)

### Scenario 8 — `gateway_down_core_up`

- **PRE**: All services healthy
- **STIMULUS**: SSH the reference VPS → `pkill -STOP -f gateway.app` (suspends gateway process; Core stays up)
- **EXPECTED**: scraper observations fail at gateway proxy layer (502 from non-running upstream); Core's view goes stale; freshness axiom fires after ~60s; Action proposed = `restart_gateway` (would need to be added) OR escalate-alert
- **OBS**: freshness gauge climbs; clinic/brief stops accruing Problems; ≥1 escalation action proposed
- **VALUE**: demonstrates DT robustness to its own dependency failures — the case where the brain's own API gateway is down
- **EFFORT**: ~1h (need to add `restart_gateway` to action templates + executor wiring)

### Scenario 9 — `core_slow_scraper_backs_up`

- **PRE**: Healthy; the load generator baseline
- **STIMULUS**: SSH the reference VPS → `kubectl exec deploy/arbiter-engine-core -- python3 -c "import time; time.sleep(60)"` repeatedly via background loop OR use kernel-level CPU throttling on Core pod
- **EXPECTED**: scraper httpx timeouts accumulate; scraper retries; observation backpressure visible in `ingest/observations` request queue; Core's processing latency MONOTONICITY axiom fires; Action proposed = `throttle_ingest` (new template) OR `scale_up_replicas`
- **OBS**: latency budget exceeded; recovery path verified
- **VALUE**: back-pressure under load is a near-universal failure pattern, so it exercises a path most deployments will hit
- **EFFORT**: ~1.5h (CPU-throttle injection + back-pressure detection wiring)

### Scenario 10 — `malformed_jwt_observation_stream`

- **PRE**: Healthy; scraper authenticated
- **STIMULUS**: scraper sends 10 ingest/observations requests with corrupted JWT (truncated last 4 chars); then resumes correct JWT
- **EXPECTED**: gateway returns 401 on corrupted; gateway log shows surge; Core security axiom (axiom verdict family) fires "unusual auth-failure rate"; Action proposed = `block_ip` OR `escalate_security_review`
- **OBS**: ≥10 401 events recorded; security-axiom fires within 60s of surge; recovery resumes after corruption stops
- **VALUE**: demonstrates DT detects auth anomalies separately from substrate anomalies — shows the 5-tier RBAC + audit infrastructure paying off
- **EFFORT**: ~45min (scraper code path + axiom config)

### Scenario 11 — `slow_memory_leak_in_core`

- **PRE**: Healthy; Core nominal RSS ~200 MiB
- **STIMULUS**: Inject growing pattern: hourly POST to `/api/v1/clinic/scenarios/run` with large fixture body; Core retains references; RSS climbs steadily over 6h
- **EXPECTED**: MONOTONICITY axiom on `core_memory_used_mb` fires after 2-3h; HOMEOSTASIS fires earlier when growth-rate exceeds baseline-deviation; Action proposed = `restart_core` (graceful) OR `scale_up_replicas` OR `clear_cache`
- **OBS**: leak detected before partner-impacting threshold; recovery action verified to bring RSS back to baseline
- **VALUE**: slow-degradation is hardest class to detect; demonstrates DT catches what threshold-alerts miss
- **EFFORT**: ~2h (memory-monitoring metric + leak-injection harness)

### Scenario 12 — `cross_component_cascade_failure`

- **PRE**: Healthy; dispatch path proven
- **STIMULUS**: trigger Pattern N.c (llama-cpp ReadTimeout) WHILE simultaneously injecting Pattern N.b (403-cascade) by spiking adversarial prompt rate
- **EXPECTED**: both cascade types fire; cross-tier-cascade-state interpretation transitions through balanced → cascading → asymmetric_recovery → upstream_dominant; ≥2 distinct Actions proposed (one per cascade); rollback path tested if action proves wrong
- **OBS**: cross_tier_cascade_state correctly identifies the multi-cascade; clinic/brief surfaces ≥2 simultaneous Problems with distinct entity-targets
- **VALUE**: real production failures are RARELY single-cause; demonstrates DT handles multi-cascade composition
- **EFFORT**: ~1h (the load generator prompt orchestration + verify cross-tier-cascade-state correctly composes)

### Scenario 13 — `adversarial_substrate_poisoning`

- **PRE**: Healthy; content moderation enabled
- **STIMULUS**: send a prompt designed to bypass moderation (e.g. encoded in base64, with English wrap-around) that, if processed, would attempt to manipulate downstream substrate via the LLM's response (e.g., emit text matching `ACTION:scale_down_replicas` that Core might naively parse)
- **EXPECTED**: prompt either rejected at moderation (explanation axiom shows reasoning) OR processed but Core's action_planner ignores any LLM-derived action requests (architecture pin: actions come from axiom verdicts not from LLM-output parsing)
- **OBS**: no action gets proposed from LLM output text; if the moderation moves correctly, content_moderation_blocked_total increments
- **VALUE**: the least-exercised path here — whether the DT is resilient to substrate-attacking prompts. Untested; the scenario exists to find out, not to confirm.
- **EFFORT**: ~2h (prompt design + verification path)

### Scenario 14 — `load_generator_dies_mid_fault`

- **PRE**: the load generator in fault window (e.g. rate_limit_burst at peak)
- **STIMULUS**: SSH the reference VPS → `docker stop the load generator` mid-fault
- **EXPECTED**: the reference deployment observation stream stops; freshness axiom fires; cascade rate calculations drop to zero; Action proposed = `restart_traffic_source` (or escalate-alert if no auto-restart capability)
- **OBS**: load-generator-down detected within 60s; the reference deployment sustained-state preserved; recovery on the load generator restart verified
- **VALUE**: traffic generators dying is a real failure shape; demonstrates DT's resilience to gen-side outages
- **EFFORT**: ~30min (the load generator restart wiring + freshness axiom config)

### Scenario 15 — `cross_environment_drift`

- **PRE**: Healthy; ConfigMap-injected patches mounted at known paths
- **STIMULUS**: `kubectl delete configmap core-cd1390-patch` mid-traffic — removes a critical hot-patch ConfigMap; Core's mount goes stale on next subPath access
- **EXPECTED**: Core observes the env-mismatch; substrate self-audit (axiom family) fires "config-drift detected"; Action proposed = `reapply_configmap` OR `rollback_to_baked_image`
- **OBS**: drift detected within 60s; recovery path verified
- **VALUE**: ConfigMap-injected substrate is fragile by design (per the configmap-injection operator-local methodology memo); demonstrates DT catches its own deployment-substrate drift
- **EFFORT**: ~1h (ConfigMap drift detection + recovery template)

### Scenario 16 — `tinyllama_swap_mid_load`

- **PRE**: Healthy; llama-cpp serving Phi-3-mini-Q4 (~4 GiB)
- **STIMULUS**: SSH the reference deployment → swap llama-cpp `--model` flag to TinyLlama-1.1B-Q4 (~700 MiB) + container restart; sustained the load generator load through the swap
- **EXPECTED**: brief downtime detected (RESPONSIVENESS axiom); post-swap, model-version change detected (CONSERVATION axiom — "expected versioning"); behavior shift detected via response-latency distribution (HOMEOSTASIS); Action proposed = `validate_model_change` OR `notify_operator`
- **OBS**: change detection within 60s; sustained-state metrics adjust to new baseline; action proposed appropriately
- **VALUE**: model swaps are routine in practice (Phi-3 / TinyLlama / Qwen are all viable here); exercises whether the DT distinguishes an infrastructure change from an anomaly
- **EFFORT**: ~1.5h (model-versioning detection + multi-model harness)

---

## Implementation order recommendation

Ranked by **(partner-pitch value × novelty) / effort**:

| Rank | Scenario | Value × Novelty | Effort | Score |
|---|---|---|---|---|
| 1 | #13 adversarial_substrate_poisoning | 5 × 5 = 25 | 2h | 12.5 |
| 2 | #12 cross_component_cascade_failure | 5 × 4 = 20 | 1h | 20 |
| 3 | #7 pod_oom_kill | 4 × 3 = 12 | 0.5h | 24 |
| 4 | #8 gateway_down_core_up | 4 × 4 = 16 | 1h | 16 |
| 5 | #14 load_generator_dies_mid_fault | 3 × 4 = 12 | 0.5h | 24 |
| 6 | #11 slow_memory_leak_in_core | 5 × 3 = 15 | 2h | 7.5 |
| 7 | #15 cross_environment_drift | 4 × 4 = 16 | 1h | 16 |
| 8 | #10 malformed_jwt_observation_stream | 3 × 3 = 9 | 0.75h | 12 |
| 9 | #16 tinyllama_swap_mid_load | 3 × 3 = 9 | 1.5h | 6 |
| 10 | #9 core_slow_scraper_backs_up | 3 × 3 = 9 | 1.5h | 6 |

**Recommendation**: ship Scenarios 7 + 12 + 13 + 14 as a Tier-1 cluster (~4h total). Each adds a distinct failure dimension (infra / multi-cascade / adversarial / source-failure). Tier-2 cluster (#8 + #11 + #15) adds another 4h for dependency + degradation + drift coverage.

---

## Cross-references

- Existing 6 scenarios in the load generator's source `FAULT_SCHEDULE`
- Pattern N family closure body in the methodology notes memo
- T1 diagnostic-signature catalog in the alpha-recursive-examination memory Tier 1 section
- the load generator concurrent-burst (deferred; would unblock multi-stream scenarios)
- closed-loop dispatch path + ACTION_INVERSE_MAP rollback
- This doc itself is partner-facing draft — operator-fill placeholders for any partner-name substitution before distribution
