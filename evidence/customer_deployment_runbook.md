# Customer-Deployment Runbook — Per-Executor-Option Recipes

**Audience**: infrastructure / platform / SRE engineers responsible for deploying the closed-loop substrate into a target environment.

**Scope**: 5 executor placement options (A: Server-1-embedded / B: Core-orchestrates-via-API / C: Sidecar / D: Operator-curated / E: Webhook) with per-option deployment recipe, verification, rollback, and migration paths. Sourced from the second evaluation round milestone plan Section 2 and the second evaluation round closed-loop evidence pack, both unpublished — named in the provenance list at the end of this document.

**Note (operationalization status)**: Only Topology A/B (Server-1-embedded HTTP path + Core-orchestrates-via-API) are operationalized today; the second evaluation round exercised the Phase-0 agentless HTTP path only (HTTP-record, not real infrastructure mutation). The control-plane wiring beyond Topology A/B — including Option C Sidecar (`kubectl_scale`/`helm_upgrade`/`terraform_apply`), Option E webhook dispatch, and the ACTIVE-mode auto-dispatch paths — is roadmap/aspirational, not yet operationalized. Treat the per-Option recipes below as target-state deployment shapes pending the control-plane build-out.

**Pre-requisites**: reader has read `observability_handoff_guide.md` (monitoring integration), which is published alongside this runbook. Operator has confirmed which Option fits the partner's trust posture + operational shape. The RBAC and auth surface is summarised in section 8.3 below rather than deferred — the separate security brief that previously carried it is not published, so nothing in this runbook depends on a document the reader cannot obtain.

**Note on paths**: relative paths in the recipes below — `deploy/manifests/...`,
`deploy/docker-compose.yml` and similar — refer to the **deployment bundle** supplied for
the engagement, not to this repository. This repository ships the detection engine and does
not ship the deployment bundle, so none of these paths resolve against a clone of it.

---

## 1. Decision tree — which Option fits which customer

```
Q1: Does the customer want the closed loop to close automatically (substrate dispatches actions)
    OR does a human operator stay in the loop for every dispatch?

  AUTOMATIC ──> Q2
  HUMAN-IN-LOOP ──> Option D (Operator-curated dispatch; GRADUAL mode baseline)

Q2: What's the customer's existing infrastructure shape?

  K8s cluster with existing Field Agent ──> Option C (Sidecar — extends Field Agent)
  AI/ML serving cluster (small/mid-tier) ──> Option A (Server-1-embedded) v1; migrate to C
  Trading / exchange-API integration ──> Option B (Core orchestrates via partner API)
  Enterprise ITOps (ServiceNow / PagerDuty / Jira) ──> Option E (Webhook)
  Regulated industry (finance / healthcare) ──> Option D (operator-curated) + optional E
```

The decision is NOT binary — most production deployments end up with a primary Option + an escape hatch (e.g. Option C primary + Option D fallback for high-stakes actions).

---

## 2. Common pre-requisites (all Options)

Before any Option-specific work:

1. **Core deployed**: Arbiter Core reachable from the partner network. Either (a) co-located in partner's K8s cluster (`kubectl apply -f deploy/manifests/core/`), (b) hosted (operator-managed; partner connects to a Core URL), or (c) self-hosted (partner runs `docker-compose up -d` per `deploy/docker-compose.yml`).

2. **Gateway accessible**: Core gateway (`gateway/app.py`) on port 8080 with JWT auth enabled (`CORE_JWT_SECRET` set). Partner SRE confirms `curl <core-url>/health` returns 200.

3. **Admin user provisioned**: operator creates first admin user via `curl <core-url>/api/v1/auth/users` (5-tier RBAC; admin gets all roles).

4. **Detection substrate seeded**: partner's first observations submitted via `POST /api/v1/observations` OR scraper sidecar polling Server-1-shaped metrics endpoint. Verified via `curl <core-url>/api/v1/clinic/brief` returning `problem_count > 0` once observation volume crosses threshold.

5. **Domain YAML matched**: partner confirms `domain_configs/<domain>.yaml` covers their indicator schema. Custom indicators added via the YAML extension pattern (see `tech_brief.md` "YAML-only extensibility evidence" section); no code changes.

Once 1-5 are confirmed, proceed to the Option-specific recipe.

---

## 3. Option A — Server-1-embedded executor

**Fit**: AI/ML serving customers; small/mid-tier deployments; demo-grade closed-loop.

**Architecture**: Action executor endpoints baked into the AI/ML serving proxy (same container as `proxy/main.py`). Core's DecisionEngine dispatches via HTTP POST to `<proxy-host>/actions/execute`.

### 3.1 Deploy recipe

```bash
# 1. Verify proxy container has the executor endpoints (Phase 0 LANDED 2026-06-13 )
curl -s -u <partner-basic-auth-user>:<basic-auth-password> https://<proxy-host>/openapi.json | jq '.paths | keys | .[] | select(startswith("/actions/"))'
# Expected: "/actions/execute", "/actions/rollback-last", "/actions/log"

# 2. Set Core dispatcher env-vars to route to the proxy
export EXECUTOR_URL_AI_ML_SERVING=https://<proxy-host>/actions/execute
export EXECUTOR_BASIC_AUTH_AI_ML_SERVING=<partner-basic-auth-user>:<basic-auth-password>

# 3. Restart Core to pick up env-vars (or kubectl set env / docker compose restart)
kubectl set env deployment/arbiter-engine-core \
  EXECUTOR_URL_AI_ML_SERVING=https://<proxy-host>/actions/execute \
  EXECUTOR_BASIC_AUTH_AI_ML_SERVING=<partner-basic-auth-user>:<basic-auth-password>
kubectl rollout restart deployment/arbiter-engine-core

# 4. Smoke-test the dispatch path
JWT=$(curl -s -X POST <core-url>/api/v1/auth/token -d "username=admin&password=<admin-pass>" | jq -r .access_token)
curl -X POST -H "Authorization: Bearer $JWT" \
  <core-url>/api/v1/recommendations/<rec-id>/approve
# Expected: 202 Accepted with dispatch_id
```

### 3.2 Action primitives supported (Phase 0)

| Action type | Server-1-embedded behavior |
|---|---|
| `deployment_scale` / `scale_up_replicas` | `docker compose up -d --scale proxy=N` OR host-script subprocess; falls back to no-op + log if docker not accessible |
| `circuit_break_endpoint` | Env-var update (`MODERATION_DISABLE_INFERENCE=1`) + container reload |
| `route_to_fallback` | Env-var update (fallback URL) + container reload |
| `roll_back_version` | docker-compose image tag swap + container restart; uses ACTION_INVERSE_MAP per `deploy/ai_ml_serving/proxy/main.py:456` |
| `retrain` | No-op with `status: operator-required` callback (training is offline) |

### 3.3 Verification (5-action smoke per second evaluation round evidence)

the second evaluation round closed-loop demo executed 5 successful dispatches + 1 rollback at avg 431ms per second evaluation round evidence pack. Reproduce against the partner deployment:

```bash
# Pick 5 pending recommendations + 1 to roll back
JWT=$(...)
for rec in $(curl -s -H "Authorization: Bearer $JWT" <core-url>/api/v1/recommendations | jq -r '.[:5][].id'); do
  curl -X POST -H "Authorization: Bearer $JWT" <core-url>/api/v1/recommendations/$rec/approve
done
# Verify: 5 entries in recent_actions with success=True
curl -H "Authorization: Bearer $JWT" <core-url>/api/v1/clinic/brief | jq '.recent_actions | length'
# Expected: 5

# Rollback last
curl -X POST -H "Authorization: Bearer $JWT" <core-url>/api/v1/actions/rollback-last
# Verify: 1 rollback recorded; substrate state reverted
```

### 3.4 Rollback (uninstall path)

1. Unset env-vars: `kubectl set env deployment/arbiter-engine-core EXECUTOR_URL_AI_ML_SERVING-` (note trailing `-`)
2. Restart Core: `kubectl rollout restart deployment/arbiter-engine-core`
3. Recommendations now stay in `pending_recommendations` queue (back to GRADUAL mode); no further dispatches fire.

### 3.5 Known limits

- Coupling: detection-side observations + action-side dispatches share the proxy process. If proxy OOMs, both sides go down.
- Security surface: proxy needs scale/restart privileges — typically requires running container with docker socket mounted OR a host-script bridge.
- Not suitable for multi-tenant proxies where one customer's action could affect another's traffic.

For these constraints → migrate to Option C.

---

## 4. Option B — Core orchestrates via partner API

**Fit**: Trading / exchange-API customers; "Core as managed service" model where partner exposes capability-API and Core invokes it.

**Architecture**: Core's DecisionEngine sends actions to partner-defined admin endpoints. Partner controls exactly which actions are exposed; Core's role is "decide what; partner decides whether/how".

### 4.1 Deploy recipe

```bash
# 1. Partner exposes capability API (partner-side; sample shape):
#    POST <partner-api>/capabilities/<capability-name>/execute
#    Body: { "action_type": "...", "params": {...}, "callback_url": "..." }

# 2. Partner registers capability map with Core (one-time)
JWT=$(...)
curl -X POST -H "Authorization: Bearer $JWT" \
  <core-url>/api/v1/dispatch/capability-map \
  -d '{
    "domain": "trading",
    "actions": {
      "circuit_break_symbol": {
        "endpoint": "https://<partner-api>/capabilities/circuit-break/execute",
        "auth": { "type": "bearer", "token": "<partner-token>" }
      },
      "throttle_order_rate": {
        "endpoint": "https://<partner-api>/capabilities/throttle/execute",
        "auth": { "type": "bearer", "token": "<partner-token>" }
      }
    }
  }'

# 3. Core dispatches via the capability-map at recommendation approval
```

### 4.2 Callback contract

Partner's executor POSTs back to Core at `<core-url>/api/v1/actions/<dispatch-id>/status`:

```json
{
  "status": "success" | "failure" | "rejected" | "deferred",
  "executor_message": "<human-readable result>",
  "applied_at": "2026-07-04T...",
  "rollback_token": "<opaque-token for future rollback>"
}
```

### 4.3 Verification

Smoke per Section 3.3 against partner capability API; replace `<core-url>/api/v1/recommendations/<rec>/approve` semantics with Option B route (capability-map dispatches, not direct executor URL).

### 4.4 Rollback

Delete capability-map entry: `curl -X DELETE -H "Authorization: Bearer $JWT" <core-url>/api/v1/dispatch/capability-map/<domain>` — Core falls back to GRADUAL mode (no auto-dispatch).

---

## 5. Option C — Sidecar executor (Field-Agent-shape)

**Fit**: K8s shops; container-orchestrated environments; partners ready for cross-cluster standardization.

**Architecture**: Small executor process runs alongside customer workload (DaemonSet / Deployment). Subscribes to Core via WebSocket (Field-Agent wire protocol reconciliation envelope). Executes actions locally with full K8s API access.

### 5.1 Deploy recipe

```bash
# 1. Apply Field-Agent sidecar manifest (template at deploy/manifests/sidecar/)
kubectl apply -f deploy/manifests/sidecar/field-agent-sidecar.yaml

# 2. Register the sidecar with Core
SIDECAR_ID=$(kubectl get pod -l app=field-agent-sidecar -o jsonpath='{.items[0].metadata.name}')
SIDECAR_TOKEN=$(kubectl exec $SIDECAR_ID -- cat /var/run/secrets/agent-token)
curl -X POST <core-url>/api/v1/agents/register \
  -d "{ \"agent_id\": \"$SIDECAR_ID\", \"token\": \"$SIDECAR_TOKEN\", \"domain\": \"k8s\" }"

# 3. Verify WebSocket connection established
kubectl logs $SIDECAR_ID | grep "ws.*connected"
# Expected: "ws://core-url/ws/agent/<sidecar-id> connected"

# 4. Verify reconciliation envelope 
curl -H "Authorization: Bearer $JWT" <core-url>/api/v1/agents | jq '.[] | select(.id == "'$SIDECAR_ID'") | .reconciliation_state'
# Expected: "synced"
```

### 5.2 Action primitives (sidecar superset of Option A)

Sidecar implements all Option-A primitives PLUS:

- `kubectl_scale` (full deployment + statefulset + replicaset scaling)
- `kubectl_restart` (pod / deployment restart)
- `helm_upgrade` (Helm chart upgrade with values override)
- `terraform_apply` (Terraform plan + apply if partner approves automation)

Sidecar config controls which primitives are enabled per environment.

### 5.3 Verification

```bash
# Approve a recommendation that triggers kubectl_scale
JWT=$(...)
curl -X POST -H "Authorization: Bearer $JWT" \
  <core-url>/api/v1/recommendations/<rec-id>/approve
# Verify: action dispatched via WebSocket; sidecar logs show "executing kubectl_scale ..."
# Verify: kubectl-side deployment replica count changed
kubectl get deployment <target-deployment> -o jsonpath='{.spec.replicas}'
```

### 5.4 Rollback

1. Kill the sidecar: `kubectl delete -f deploy/manifests/sidecar/field-agent-sidecar.yaml`
2. Sidecar disappears from Core's agent registry (cleanup at WebSocket-disconnect timeout)
3. Recommendations stay pending; no dispatches.

### 5.5 Migration from Option A → C (production maturation path)

For partners starting at Option A and growing toward C:

1. Deploy sidecar in **observation-only mode** (`SIDECAR_DISPATCH_ENABLED=0`) alongside Option-A; both surfaces visible to Core
2. Run shadow-mode for 1-2 weeks; verify sidecar would have dispatched the same actions
3. Switch `SIDECAR_DISPATCH_ENABLED=1` and unset `EXECUTOR_URL_AI_ML_SERVING` on Core
4. Decommission Option-A executor endpoints (or leave them stubbed for fallback)

---

## 6. Option D — Operator-curated dispatch (GRADUAL mode baseline)

**Fit**: Regulated industries (finance / healthcare); high-trust environments; first-month "watch and learn" phase for any deployment.

**Architecture**: Core proposes recommendations into `pending_recommendations` queue. Human operator reviews via Clinic UI; executes via their own toolchain (kubectl / Terraform / ansible / vendor CLI). Operator records outcome back via `POST /api/v1/actions/<id>/manual-status`.

This is the **default mode** when no other Option is configured. The Alpha-1 evidence pack (Alpha-1) operated entirely in this mode.

### 6.1 Deploy recipe

```bash
# 1. Ensure DECISION_ENGINE_MODE=GRADUAL (the default; verify it's not been overridden)
kubectl get deployment arbiter-engine-core -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="DECISION_ENGINE_MODE")].value}'
# Expected: "GRADUAL" or empty (defaults to GRADUAL)

# 2. Operator UI access via Clinic
open https://<core-url>/clinic
# Or curl: curl -H "Authorization: Bearer $JWT" <core-url>/api/v1/clinic/pending-recommendations

# 3. Per recommendation, operator decides → executes via partner toolchain → reports back
JWT=$(...)
curl -X POST -H "Authorization: Bearer $JWT" \
  <core-url>/api/v1/actions/<rec-id>/manual-status \
  -d '{ "status": "applied", "outcome": "scaled to 3 replicas via kubectl", "operator": "<operator-name>" }'
```

### 6.2 Verification

`/api/v1/clinic/brief` `recent_actions` should populate as operators record manual-status. `recently_resolved` should populate as observation re-firms the issue is gone (closed-loop signal even without auto-dispatch).

### 6.3 Rollback

N/A — operator-curated means rollback happens via operator's own toolchain. Core records the rollback the same way as the forward action (manual-status with outcome description).

### 6.4 Notes

- This is the safest Option for first deployment. Many partners stay here for 30-90 days before considering Options A/C.
- Compatible with all other Options as fallback: any Option can be configured to ESCALATE rather than dispatch when confidence is below threshold (see `dispatch_policy.yaml`).

---

## 7. Option E — Webhook + customer-managed dispatcher

**Fit**: Enterprise with existing ITOps (ServiceNow / PagerDuty / Jira); partners who want every action surfacing through their standard incident-response funnel.

**Architecture**: Core POSTs a recommendation envelope to a customer-provided webhook URL. Customer's dispatcher (typically ITOps automation) consumes, decides (auto or human), executes, and reports back to Core's callback URL.

### 7.1 Deploy recipe

```bash
# 1. Configure webhook + callback
JWT=$(...)
curl -X POST -H "Authorization: Bearer $JWT" \
  <core-url>/api/v1/dispatch/webhook-config \
  -d '{
    "domain": "ai-ml-serving",
    "webhook_url": "https://itops.partner.com/api/v1/incidents/create",
    "webhook_auth": { "type": "bearer", "token": "<itops-token>" },
    "callback_url": "https://<core-url>/api/v1/actions/{dispatch_id}/status",
    "delivery": { "retries": 3, "backoff_seconds": 30 }
  }'

# 2. Partner-side dispatcher implements:
#    - POST <webhook-url> handler that creates an incident
#    - Incident resolution triggers callback to <callback-url>
```

### 7.2 Webhook envelope shape

```json
{
  "dispatch_id": "<uuid>",
  "recommendation_id": "<uuid>",
  "domain": "ai-ml-serving",
  "action_type": "scale_up_replicas",
  "params": { "target_replicas": 3 },
  "evidence": {
    "problem_id": "<uuid>",
    "axiom_verdicts": [...],
    "narrative": "<3-paragraph Explains-pillar narrative>"
  },
  "callback_url": "https://<core-url>/api/v1/actions/<dispatch-id>/status",
  "expires_at": "2026-07-04T..."
}
```

### 7.3 Verification

```bash
# Trigger a recommendation approval; verify webhook receives + callback fires
# Webhook delivery log:
curl -H "Authorization: Bearer $JWT" <core-url>/api/v1/dispatch/webhook-deliveries | jq '.[-1]'
# Expected: { "status_code": 200|201, "delivered_at": "...", "retries": 0 }
```

### 7.4 Rollback

Delete webhook-config: `curl -X DELETE -H "Authorization: Bearer $JWT" <core-url>/api/v1/dispatch/webhook-config/<domain>` — Core falls back to GRADUAL mode.

### 7.5 Notes

- Webhook delivery uses at-least-once semantics with idempotency-key headers. Partner-side dispatcher MUST be idempotent on the `dispatch_id`.
- Default 3 retries at 30s + 60s + 120s backoff; configurable.
- For high-cadence environments (SLA tighter than ITOps cycle time), consider Option C primary + Option E for governance-tier actions only.

---

## 8. Cross-Option topics

### 8.1 Action confidence + dispatch-policy gating

Regardless of Option, Core's `dispatch_policy.yaml` controls WHICH recommendations escalate to the executor vs stay in pending:

| Confidence | GRADUAL mode | ACTIVE mode |
|---|---|---|
| HIGH (axiom confidence ≥0.9 + evidence count ≥3) | Auto-dispatch via Option | Auto-dispatch via Option |
| MEDIUM (0.6-0.9) | Stay pending (operator review) | Auto-dispatch via Option |
| LOW (<0.6) | Stay pending; no escalation | Stay pending; no escalation |

Partner SRE chooses the mode via `DECISION_ENGINE_MODE` env-var. Most production deployments start GRADUAL, transition to ACTIVE for HIGH-confidence after 30-day baseline.

### 8.2 Audit trail (all Options)

Every dispatch creates an `AuditLog` entry:
- Pre-dispatch evidence snapshot
- Dispatch envelope (Option-specific)
- Callback outcome + timing
- Rollback (if any)

Retrieval: `GET /api/v1/audit?dispatch_id=<id>` (RBAC-gated; admin + auditor roles only). Forward to partner SIEM per `observability_handoff_guide.md` Section 6.

### 8.3 Security per-Option summary

| Option | Auth between Core and executor | Privilege scope |
|---|---|---|
| A | Basic-auth in `EXECUTOR_BASIC_AUTH_*` env-var | Proxy container's privileges (depends on docker-socket access) |
| B | Bearer token in capability-map | Partner-API-side |
| C | Mutual TLS + WebSocket session token | K8s service account + container privileges |
| D | N/A (operator dispatches via own toolchain) | Operator's existing toolchain auth |
| E | Webhook bearer token + idempotency-key | Customer dispatcher's downstream auth (likely ITOps API tokens) |

The per-Option auth surface above is the published statement of it. A longer threat model exists and is **not published** (the security brief was withdrawn from
publication on 2026-08-09), so it is named here for provenance rather than offered — the table above is complete for the deployment
decision this runbook covers, and does not depend on it.

### 8.4 Rollback patterns (all Options)

Core's ACTION_INVERSE_MAP at `deploy/ai_ml_serving/proxy/main.py:456` (Phase 0 Path B reference) catalogs forward + inverse pairs. The map leads with the proxy-domain pairs the second evaluation round actually exercised (`block_ip`/`rate_limit_tighten`); it is proxy-domain only, not Core:

| Forward action | Inverse action |
|---|---|
| `block_ip` | `unblock_ip` |
| `rate_limit_tighten` | `rate_limit_loosen` |
| `blocklist_add` | `blocklist_remove` |
| `scale_up_replicas(N)` | `scale_down_replicas(N)` |

Triggered via `POST /api/v1/actions/rollback-last` OR per-dispatch-id rollback. Verified end-to-end during the second evaluation round's closed-loop demo: 1 rollback in a 5-action run. The evidence pack for that round is not published.

---

## 9. First 30-day partner adoption sequence

| Week | Activity | Option progression |
|---|---|---|
| 1 | Stand up Core + observation scrape + clinic/brief baseline; operator reviews pending recommendations | Option D baseline |
| 2 | Pick primary Option from decision tree; configure but keep GRADUAL mode | Configure A / B / C / E in dry-run |
| 3 | First 3-5 operator-approved dispatches via chosen Option in GRADUAL mode; verify dispatch + callback + rollback | Option live, mode=GRADUAL |
| 4 | Tune dispatch_policy.yaml confidence thresholds against observed evidence; consider transition to ACTIVE mode for HIGH-confidence only | Option live, mode=GRADUAL+ESCALATE |

Joint 30-day review with operator + partner SRE; sign-off on transition to broader ACTIVE mode usage if appropriate.

---

## 10. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Dispatch attempts return HTTP 502 | Executor URL unreachable (Option A/B/E) OR sidecar disconnected (C) | Curl executor URL from Core host; for C, check WebSocket reconnect logs |
| `recent_actions` empty after approvals | Callback not firing (Options A/B/E) OR operator forgot manual-status (D) | Inspect `audit_log` for callback-fail entries; verify callback URL reachability |
| Sidecar shows `reconciliation_state: drifted` | envelope version mismatch | Restart sidecar; verify Core + sidecar versions match per `tech_brief.md` API surface |
| Multiple rollbacks in short window | Action inverse fired before forward action settled | Check `dispatch_policy.yaml` `rollback_cooldown_seconds` (default 60s); raise if needed |
| Webhook delivery 429 from partner side | Partner ITOps rate-limiting Core | Lower webhook delivery rate via `dispatch_policy.yaml` `webhook_rate_per_minute` (default 30) |
| Recommendations stuck in pending for >24h | Confidence below threshold + no operator review | Either operator triages manually OR adjust `confidence_threshold` in dispatch_policy.yaml |

---

## 11. Cross-links

**Published alongside this runbook:**

- Architecture overview: `tech_brief.md` (substrate architecture and axiom families)
- Substrate API reference: `tech_brief.md`
- Observability + monitoring: `observability_handoff_guide.md`
- Security + auth surface: section 8.3 of this runbook

**Cited for provenance, not published** — named so the trail is
auditable; they are not links, and the records themselves are available on request:

- Closed-loop demo evidence: not published
- Second-evaluation-round milestone plan (option-decision rationale): not published; Section 2
- Demo walkthrough: not published

Two entries were removed rather than relabelled — a first-hour onboarding guide and a sales-deck
narrative, both written for a commercial track retired in 2026-07. Neither is a prerequisite
for anything in this runbook.

**Substitution tokens.** Angle-bracket values below — `<core-url>`, `<proxy-host>`, `<partner-api>`, `<basic-auth-password>` and similar — are for the reader to replace with their own deployment's values. They are templating, not unfilled blanks.
