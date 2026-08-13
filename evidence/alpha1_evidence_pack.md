# Alpha-1 Evidence Pack — Sustained AI/ML-Serving Substrate Observation

**Date**: 2026-06-12 (Alpha Day-11 of 11; closure 2026-06-13)
**Scope**: Detection-cascade observations from the Alpha — an 11-day (2026-06-03 → 06-13 inclusive) compressed observation window against a public LLM-serving deployment under sustained adversarial load + scheduled fault windows.
**Audience**: Strategic partners assessing the Operational Reasoning System (Arbiter) for potential pilot engagement.
**What this pack is NOT**: Alpha-1 evidence covers detection-cascade observations only. Closed-loop action-outcome evidence (the second product criterion — the system not only detects but acts) accrues during the second evaluation round (target close 2026-07-04) and lands as a separate the second evaluation round evidence pack.

---

## Executive summary

Over 11 days (Days 1-11, 2026-06-03 → 06-13 inclusive), Arbiter's substrate ran a closed observation loop against a public AI/ML serving deployment (LLM proxy with content moderation, rate limiting, blocklist auto-escalation) hosted on a small EU-region VM. A separate load generator (the "the load generator" instance) emitted realistic + adversarial traffic at 6× normal intensity to compress the equivalent of a ~60-day observation window into the 11-day window. Six scheduled fault windows (Days 2-7) tested specific cascade behaviors; Days 8-10 sustained-observation tested behavior absent active stimulus (Day-11 = final review + closure).

The substrate produced **18 catalogued diagnostic signatures** (the T1 library), promoted **3 fault-scenario patterns** to load-bearing status (the Pattern N family: throughput-clamp / 403-cascade / 502-cascade), and surfaced **16 cumulative L5 "surprises"** — observations that the planned probes had not anticipated. The most demo-worthy of these is a 502→403 cascade-succession dynamic in which upstream-timeout rejections (502) transitioned into rate-limit rejections (403) as the auto-blocklist absorbed the affected source — with asymmetric recovery: 502 self-clears within ~48h via upstream stabilization (Day-10 confirmation upgrades the claim to **96h-stable** (under the Alpha-1 baseline-traffic regime with the documented tuning recipe: MAX_TOKENS_DEFAULT=64 + 90s timeouts + cpuset pin,. [CLM-016]) at 96h horizon) while 403 persists at homeostatic equilibrium until manual intervention or sustained quiescence.

No closed-loop actions were exercised against the deployment during Alpha-1; the substrate ran in observe-only mode. Action-loop closure is the second evaluation round's surface.

---

## Substrate at a glance

| Field | Value |
|---|---|
| Observation window | 2026-06-03 → 2026-06-13 (10 days; 6× compression) |
| Deployment target | Public LLM-serving proxy on EU-region VM (the hosting provider serving VM, 8 GB) |
| Load-generator | Separate VM (the load generator) emitting sustained + adversarial traffic |
| Fault windows | 6 scheduled events Days 2-7 (durations 30-240 min; multipliers 1-6× adversarial density) |
| Substrate axes exercised | 14 (per-axis ring buffers in Core: observation / axiom verdict / RCA / explanation / LLM invocation / action / privacy / audit / tenant-context / 6 more) |
| the established pattern endpoints surfaced | 18 (cross-pillar attestation + per-axis evidence) |
| Diagnostic signatures catalogued | 18 (T1 library; auto-applied at session start) |
| L5 surprises observed | 16 cumulative across Days 1-11 (Alpha-1 closure) |
| Pattern N family | 3-branch: N.a sleep-clamp / N.b 403-cascade / N.c 502-cascade — all PROVEN (2+ instances each) |
| Closed-loop actions exercised | 0 (out of Alpha-1 scope; the second evaluation round surface) |

---

## Days 1-10 highlights (compact retrospective)

| Day | Window | Substrate focus | Notable observations |
|---|---|---|---|
| 1 (2026-06-03) | Baseline | Substrate boot + first pre-fault T0 | Scraper unrun gap (silent-fall-through); substrate-callsite gap surfaced + fixed inline |
| 2 (2026-06-04) | 30-min `pre_lunch_burst` | Pattern N candidate identification | N.a (throughput-clamp via sleep-loop) 1st instance; T1 catalog seeded (5 entries) |
| 3 (2026-06-05) | 120-min `mid_day_chaos` | Fault retrospective + operator T-1 question | 5-CD substrate cascade surfaced via operator question "5 problems / 0 actions normal?" — Problem→Action recommendation pipeline gap; landed end-to-end same day. T1 catalog at 11 entries |
| 4 (2026-06-06) | 90-min `tenant_scope_drift` | Pattern N retraction-and-re-promotion | Day-4 retracted Pattern N candidate (bug-occluded test stimulus instrumentation flaw); Pattern N candidate re-promoted Day-5 against clean rejection path |
| 5 (2026-06-07) | 60-min `latency_amplifier` | Cascade-equilibrium observation | Auto-blocklist persistent at size=2; ~4059 `blocklist:auto` outcomes since rebuild |
| 6 (2026-06-08) | 240-min `dispatch_overload` | Pattern N N.a → PROVEN | N.a `tenant_scope_drift` confirmed throughput-clamp universality |
| 7 (2026-06-09) | 240-min `pre_deadline_stress` | Pattern N N.b → proven + 502→403 cascade L5 | N.b 403-cascade promoted; cascade-succession L5 surface (most demo-worthy single observation of Alpha — see "Cascade L5 finding" below) |
| 8 (2026-06-10) | Sustained observation | Pattern N.c → proven + sustained equilibrium | 502 cascade persistent at 91.4% rate over 2h horizon; auto-block + auto-clear in homeostatic equilibrium |
| 9 (2026-06-11) | Sustained observation | Pattern N.c 48h-bound self-recovery + 502→403 asymmetric recovery | 502 rate dropped 30% from llama-cpp upstream stabilization; 403 rate ROSE 30% as retry-suppression unclamped — L5 #14 "asymmetric-recovery" sub-pattern |
| 10 (2026-06-12) | Sustained observation — FINAL | Pattern N.c upgrades to **96h-stable** (under the Alpha-1 baseline-traffic regime with the documented tuning recipe: MAX_TOKENS_DEFAULT=64 + 90s timeouts + cpuset pin,. [CLM-016]) + HOMEOSTASIS-decoupling L5 | 502 stays 0 across 96h horizon (Day-7 fault-end → Day-10 19:03 UTC); HOMEOSTASIS warning reappears on ModelEndpoint but decoupled from 502 cascade (Day-9 prediction falsified) — L5 #15 "axiom-decoupling" sub-pattern. SECOND-LIVE-EXERCISE PASS; cascade rate hold at -11.2% drift within ±20% noise band |

Day-11 (2026-06-13) reserves Alpha-1 evidence pack final review + partner-materials consistency sweep + status transition; checkpoints at `~/w/run/g603-alpha/dayN_checkpoint_*.md` Days 5-10.

Full per-day detail lives in the Day-2 through Day-5 fault-watch notes, with Days 6-10 in the daily hypothesis log. Held in the source repository, cited for provenance and NOT published.

---

## T1 diagnostic-signature catalog (18 entries)

The T1 catalog is a library of diagnostic signatures matched at session start to reduce re-investigation cost (~30-60 minutes saved per signature match). Catalog covers symptom-side patterns surfaced during Alpha-1; new entries promote via T5 codification at session end. Selected entries:

| # | Signature | Source CD | Use |
|---|---|---|---|
| 5 | `scraper unrun >N days` (silent gap) | | Pre-flight T0 check; catches scraper-not-firing before per-axis work |
| 11 | `clinic/brief problem_count = 0 despite metric anomaly` | | Detects upstream-substrate-callsite gap (substrate wired, callsite doesn't iterate) |
| 14 | `auto-blocklist persistent at size > 0` | | Indicates cascade-equilibrium state; partner-pitching evidence of cascade-detection |
| 17 | `Pattern N.b 403-cascade dispositive` | | Identifies rate-limit cascade in adversarial-density regime |
| 18 | `Pattern N.c upstream-timeout-502-cascade-bound` | | Identifies upstream-stability cascade (distinct mechanism from N.b) |
| 25 | `delta > 0 AND blocklist_size = 0` (phantom-healthy) | | Detects partner-misleading dashboard state (oscillatory TTL window) |

Full T1 catalog with diagnostic algorithm + reference CDs lives in the alpha-recursive-examination memory body (load-bearing for internal tooling skill execution).

---

## Pattern N family — 3-branch fault-scenario-throughput taxonomy

Pattern N is a META-pattern stabilizing at 3-branch / reference architecture as of 2026-06-12 (codification). Branches are distinguished by the mechanism that limits effective throughput under adversarial stimulus:

| Branch | Mechanism | 1st instance | Universality |
|---|---|---|---|
| N.a — throughput-clamp via sleep-loop | scenario's adversarial-density multiplier compounds with per-request sleep, clamping effective rate | Day-2 `pre_lunch_burst` | PROVEN (Days 2 + 6) |
| N.b — 403-cascade via rate-limit short-circuit | adversarial density triggers rate-limit responses (~50ms 403 returns) without per-request sleep — effective throughput dispositive of N.a's clamp pattern | Day-7 `pre_deadline_stress` | PROVEN (Days 5 + 7) |
| N.c — 502-cascade via upstream-timeout | upstream LLM service emits 5xx; proxy returns 502 without invoking rate-limiter — different cascade mechanism than N.b | Day-8 sustained | PROVEN (Days 8 + 9) |

**Asymmetric-recovery sub-pattern** (codified, Day-9 evidence; **upgraded to 96h-stable claim Day-10** (under the Alpha-1 baseline-traffic regime with the documented tuning recipe: MAX_TOKENS_DEFAULT=64 + 90s timeouts + cpuset pin,. [CLM-016])): N.c self-recovers within ~48h via llama-cpp upstream stabilization (Day-10 confirmation extends the stability window to 96h horizon: Day-7 fault-end → Day-10 19:03 UTC = 96h+; 502 stays 0 throughout), while N.b persists indefinitely at homeostatic equilibrium until manual intervention. Day-9 evidence: 502 rate dropped 30% as upstream stabilized; 403 rate ROSE 30% as N.c's retry-suppression unclamped → N.b's rate rebounded to native throughput. The two cascades interact via the retry-suppression mechanism.

Methodological precedent: META Pattern N is the reference architecture for distinguishing throughput-bound vs rejection-path-bound semantics in adversarial-density regimes; partner deployments where one cascade is suspected can use the N.x triage signature to identify the active mechanism.

---

## L5 surprises — 16 cumulative across 4 clusters

L5 surprises are observations that the planned probes had not anticipated. Each entry was logged at the day's session-end codification audit in the daily hypothesis log, which is held in the source repository and NOT published. Clustered into 4 thematic families (closure verdict; canonical numbering matches `l5_surprise_synthesis.md`):

**Detector anchor — read this with the count above.** *Not anticipated by the probe design* is a statement about what the designers foresaw. It is not a statement about what the detector caught, and that result is unfavourable: **0 of the 16 were machine-surfaced at the time** — a human found all sixteen (the replay verdict, held in the source repository, source repository only, not published). The 2026-07 replay qualifies it without overturning it: on day-1 partner-plausible flow instrumentation, **3 of the 16** (#11, #12, #14) plus both post-Alpha Cluster-E world-model surprises would have been machine-flagged before the operator noticed — 5 of the 22 cumulative. The stronger licensed wording does not unlock on this evidence.

| Cluster | Count | Representative | Day |
|---|---|---|---|
| A — Cascade-equilibrium dynamics | 4 | #13 phantom-healthy blocklist_size under active equilibrium (Day-8); #14 502→403 asymmetric cascade-recovery (Day-9); #11-#12 pre-fault 502-cascade + tier-succession (Day-7) | Days 7/8/9 |
| B — Methodology-substrate gaps | 4 | #2 scraper unrun 13 days silent fall-through (Day-2); #4 operator-T-1-diagnostic-question-substrate-cascade (Day-3 5-CD landing..1354); #6 content-moderation classifier scope (Day-4); #10 cascading-substrate-interaction-with-test-driver (Day-7 META Pattern N branching) | Days 2/3/4/7 |
| C — Axiom-family dynamics | 5 | #5 rate-of-change axiom container-restart false-positive (Day-3); **#15 HOMEOSTASIS-warning decoupled from 502 cascade (Day-10; Day-9 prediction falsified)**; #16 axiom-set self-quiescence over 24h horizon (Day-11) | Days 3/5/6/10/11 |
| D — Phantom-instrumentation | 3 | #1 scenario-aspiration-vs-implementation false-coverage (Day-1); #3 tenant_scope_drift as rate-multiplier not tenant-logic (Day-3); #8 vacuous-non-event from unapplied test stimulus (Day-5) | Days 1/3/5 |

Cluster #1 (cascade-equilibrium) is the most demo-worthy externally because it surfaces substrate observations that partner-side monitoring tools would not produce. Cluster #2 (methodology-substrate) is the most demo-worthy internally because it surfaces the operator-T-1-diagnostic-question framing — a recurring T-1 surfacing mechanism distinct from the planned T0..T5 framework.

---

## Cascade L5 finding (single most demo-worthy observation)

**Day-7 → Day-9 502→403 cascade succession with asymmetric recovery**

**Setup**: the load generator emits sustained adversarial mix (5% adversarial × 4× multiplier = 20% rejection-rate target). Substrate is in active observation mode; no closed-loop intervention.

**Day-7 observation**: under sustained stimulus, the substrate observed Pattern N.b 403-cascade (~91.4% rate). Within the same fault window, an upstream LLM service stability event produced overlapping Pattern N.c 502-cascade. The two cascades stacked: 502s ABSORBED requests that would otherwise have triggered 403s. Visible cascade-succession; substrate correctly identified both via separate ring-buffer entries on the 502 endpoint vs 403 (blocklist:auto reason) endpoint.

**Day-9 observation**: 48h later (sustained observation, no fault stimulus), 502 rate had dropped ~30% (llama-cpp upstream stabilization). 403 rate rose ~30%. **Mechanism**: N.c had been retry-suppressing requests; when 502 unclamped, the retry traffic returned to the normal rate-limiter path and N.b's auto-blocklist absorbed them. Asymmetric: N.c self-resolved within ~48h; N.b would persist until manual clear (or sustained quiescence over the blocklist TTL window — typically ~24h).

**Why this matters for partners**: cascades like this in production systems are typically detected only after customer-impact symptoms compound (queue backup → SLO miss → page). The Alpha-1 substrate detected, distinguished, and time-tracked both cascades simultaneously from observation data alone, with no manual analyst involvement. This is the substrate's central claim: a topology-aware ontology engine plus per-axiom ring-buffer evidence makes cascade-distinguishing diagnoses available at observation-time, not post-mortem.

Detail is in the hypothesis log's Day-7/8/9 entries. A per-day Day-7 fault-watch note was planned and never written, so the Days 2-5 series does not extend to Day 7; the hypothesis log is the only record. Held in the source repository, cited for provenance and NOT published.

---

## Methodology — the recursive-examination framework 5-tier exercise framework

Alpha-1 work was structured by the recursive-examination framework (Recursive Examination as Engine) framework — a 5-tier session-level exercise discipline that generates L5 surprises by repeatedly stressing substrate rather than auditing it (auditing reveals known unknowns; exercising reveals unknown unknowns):

- **T0**: Data-flow probe (every session start; ~60s) — catches silent-fall-through before per-axis work.
- **T1**: Diagnostic-signature library match — 18 catalogued signatures save ~30-60 min per match.
- **T2**: Adversarial probe cycle — 3-5 probes designed to BREAK current substrate; each = candidate L5 surprise.
- **T3**: Diagnostic-Iteration Loop (DIL) — when live-verify fails, iterate diagnostically; 3-iteration limit per session before honest-stop.
- **T4**: Cross-pattern leverage — apply canonical fix templates (e.g. the established pattern substrate-callsite-gap) rather than re-deriving solutions.
- **T5**: Pattern codification (session-end audit) — new signatures join T1; new architectural antipatterns join the feedback memory canon.

**T-1 extension** (operator-diagnostic-question-as-T-minus-1, PROVEN): a single operator diagnostic question after a "clean" T0-T5 closure can surface more substrate gaps than the planned probes. 2026-06-12 codification: invite one such question explicitly at session end before declaring done.

the recursive-examination framework codified in the alpha-recursive-examination memory body; tier-by-tier execution recipes available via the internal tooling skill body.

---

## What this evidence pack is NOT

Per scope discipline (round-3 review guidance 2026-06-12):

- **NOT closed-loop action evidence.** No actions were taken against the deployment during Alpha-1. The substrate observed; it did not act. Closed-loop action-outcome evidence belongs to the second evaluation round (target close 2026-07-04); its evidence pack is held in the source repository and is not published.
- **NOT platform-wide accuracy claim.** Numeric claims of 95.8% technical accuracy elsewhere in Arbiter materials refer specifically to the Stage I OpenBMC reference vertical's technical-support QA pipeline — a different substrate from this Alpha's AI/ML-serving observation. Cross-vertical generalization of any per-vertical stat is not warranted from Alpha-1 evidence alone.
- **NOT a recommendation.** This pack does not propose deployment for a specific partner's environment. Discovery call is the next step; pilot proposal follows discovery call.

---

## Drill-down references

**Published alongside this document** — open these directly:

- `l5_surprise_synthesis.md` (16 Alpha-1 L5 closure verdict; current cumulative 22 with +6 post-Alpha Cluster E)
- `tech_brief.md` (substrate architecture + axiom families)

**Held in the source repository, cited for provenance and NOT published** — named by ROLE, so the
evidence trail stays auditable and each record can be requested unambiguously. There is deliberately
no path here: a path into a repository you cannot read is not provenance, and a placeholder standing
where a path used to be is worse — it makes distinct records indistinguishable.

- the daily hypothesis log — Days 1-10 entries, each with its hypothesis tests and verdicts
- the recursive-examination survey — cumulative L0/L1/L2 sections
- the Day-2 through Day-5 fault-watch notes — Days 6 onward fold into the hypothesis log; no Day-7 file was ever written
- the fault-schedule specification — the 6-fault-window schedule and its canonical cadence
- the replay verdict behind the detector anchor above
- the security brief, covering deployment hardening posture — **dropped from the publish set on
  2026-08-09** rather than held from the start; it was listed above as published alongside this
  pack until then

Two entries were removed rather than relabelled: a sales deck and a competitor-comparison document,
both written for a commercial track retired in 2026-07. Neither is evidence for anything claimed here.

---

## Next step for readers of this pack

**There is no commercial engagement track, and this document no longer offers one.** An earlier
revision invited a discovery call and offered deep-dive access under NDA. Both channels were retired
in 2026-07 along with the partner programme itself; the invitations outlived the thing they invited
people to, which is the failure mode this note replaces.

What the project is doing instead: publishing the engine and its evidence record so the implementation
can be inspected rather than asserted. If you want to go further from here:

- **`tech_brief.md`** — substrate architecture and the axiom families.
- **`l5_surprise_synthesis.md`** — the prose drill-down on the surprises summarised above, including
  the detector anchor that bounds what the automated detection actually caught.

Technical questions belong in the repository's issue tracker. Nothing here is gated, and nothing here
requires an agreement to read.

Alpha-1 closes 2026-06-13 (Day-11). the second evaluation round (closed-loop demo + action-outcome evidence) opens 2026-06-14 with target close 2026-07-04.
