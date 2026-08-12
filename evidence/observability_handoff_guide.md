# Observability Handoff Guide — Partner SRE / Monitoring Team

**Audience**: partner SRE / observability engineers wiring substrate signals into existing dashboards + alerting.
**Status**: rewritten to code-cited truth 2026-07-19 per an internal documentation review (the architecture review channel, Parts 69-71 — archived 2026-07-31 to the internal notes; source repository only, not published). The prior version documented a `source: "production"` value the code never emits, treated the `/dt-*` endpoints as rich live signals (they are warming / placeholder under baseline —), cited a scraper script that does not exist, and used several wrong metric names. **Cleared to ship 2026-08-06** (operator-directed) — technical integration content; no commercial framing.

> Observability entry point: the **Prometheus `/metrics` surface** (real, populated) + the operator-run **the source repository** (emits the live/evidence/warming map). NOT the `/dt-*` semantic endpoints — those return HTTP 200 envelopes but carry no data under baseline traffic today.

---

## 1. The signal that is real today: Prometheus /metrics

the reference deployment emits real counters + gauges for the serving substrate — request outcomes, moderation / blocklist, cost, error ratio, latency, replica health. This is the surface to build dashboards + alerts on.

### 1.1 Prometheus scrape
```yaml
scrape_configs:
  - job_name: ai_ml_serving_substrate
    scrape_interval: 15s
    basic_auth:
      username: <partner-basic-auth-user>
      password: <partner-basic-auth-password>
    static_configs:
      - targets: [ <partner-server1-host>:443 ]
    scheme: https
    metrics_path: /metrics
```
(Datadog: openmetrics adapter on the same endpoint. New Relic: `nri-prometheus` forwarder. Metric names arrive unmodified.)

### 1.2 Metrics worth alerting on (verified names from live /metrics)
`inference_request_outcomes_total`, `inference_endpoint_upstream_error_ratio`, `inference_endpoint_error_rate_per_min`, `content_moderation_blocked_total`, `content_moderation_blocklist_size`, `inference_endpoint_cost_per_request_usd`, `inference_endpoint_cost_usd_per_hour`, `inference_endpoint_p99_latency_ms`, `serving_replica_request_rate_per_sec`, `serving_replica_memory_used_mb`.

---

## 2. The `/dt-*` Pattern-169 endpoints — what they actually return

Each `/dt-<axis>` endpoint returns a bootstrap-aware JSON envelope that never 5xxs. The `source` field is one of:
```
"live" | "warming_up" | "unavailable"
```
(the full system:27-29`). **There is no `"production"` value — do not key alerting on it.**

**Important:** under baseline traffic today these endpoints return `source: live` (reachable) but `count: 0` / `ready_for_action: false` — the cross-pillar composition layer is unwired, so the semantic axes carry no data yet (only `/dt-axiom-verdicts` accrues real volume). **Do not build dashboards or alerts on the `/dt-*` counts** until wires the composition callsite; you would be alerting on zeros. Treat these as a stable-URL surface for future roll-out, not a live signal. To see the current per-endpoint live/warming/placeholder state, run the source repository (GREEN/AMBER/GREY map).

---

## 3. Alert template library (keyed on the real /metrics surface)

### P1 — substrate health (page)
```yaml
- alert: SubstrateAvailability
  expr: up{job="ai_ml_serving_substrate"} == 0
  for: 2m
- alert: UpstreamErrorRatioElevated
  expr: inference_endpoint_upstream_error_ratio > 0.20
  for: 5m
```
### P2 — adversarial / cascade (notify)
```yaml
- alert: AdversarialPromptCascade
  expr: rate(content_moderation_blocked_total{reason=~"input:.*"}[5m]) > 0.5
  for: 10m
```
### P3 — phantom-healthy (documentation-grade; fires while healthy)
```yaml
- alert: PhantomHealthyBlocklistCascade
  expr: |
    rate(content_moderation_blocked_total{reason="blocklist:auto"}[5m]) > 0
    and content_moderation_blocklist_size == 0
  for: 10m
```
(Add-rate matched by clear-rate — SRE visibility, not action.)
### P4 — cost anomaly (info)
```yaml
- alert: CostPerRequestSpike
  expr: inference_endpoint_cost_per_request_usd > avg_over_time(inference_endpoint_cost_per_request_usd[1d]) * 2
  for: 15m
```

---

## 4. Dashboard layout (build on /metrics)
- **Substrate health**: `serving_replica_request_rate_per_sec`, `inference_endpoint_upstream_error_ratio` (threshold 0.20), `inference_endpoint_p99_latency_ms`, outcome decomposition from `inference_request_outcomes_total` (allowed / input_rejected / rate_limited / upstream_error / blocklisted).
- **Cascade trail**: cumulative `content_moderation_blocked_total` by reason + `content_moderation_blocklist_size`.
- A closed-loop / DT-introspection pane is **deferred** until populates the `/dt-*` surface.

---

## 5. Audit-log / SIEM forwarding — roadmap
The prior version described `GET /api/v1/audit` SIEM forwarding with production/unavailable transitions. Core-side audit is **not yet wired** (the full system:589` `audit_logger=None`); the only persisted audit today is the gateway sqlite store (10,000-row cap, the full system:98`). Treat SIEM forwarding of Core audit as roadmap.

---

## 6. FAQ
- **Do I instrument my app code?** No — signals come from the reference deployment's `/metrics`.
- **Why do `/dt-*` endpoints read `warming_up` / count 0?** The composition layer is unwired; they populate once that lands. Use `/metrics` + the probe script meanwhile.
- **Retention?** the reference deployment metrics: partner TSDB default. `/dt-*` ring buffers: `<axis>_RING_CAP` env (once populated). Core audit: gateway 10,000-row cap today (Section 5).

---
**Operator-personalization placeholders**: `<partner-server1-host>`, `<partner-basic-auth-user>`, `<partner-basic-auth-password>`, `<partner-runbook-url>`.
