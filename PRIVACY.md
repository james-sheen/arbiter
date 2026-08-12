# Privacy Policy

This document describes what data the Arbiter Project collects through its public-facing components (currently a demo deployment), how that data is used, and what choices users have. It reflects current practice for the Alpha stage and will be updated as the project evolves.

## Scope

This policy covers:

- The public demo deployment of the Arbiter AI/ML serving substrate (basic-auth gated; URL published in [README.md](README.md) when available).
- This repository and its documentation.

It does NOT cover:

- Third-party services that the demo depends on (LLM providers, hosting infrastructure). Their respective privacy policies apply to data they receive.
- Forks, derivatives, or independent deployments of Arbiter code. Operators of such deployments are responsible for their own privacy posture.

## What the demo collects

The demo deployment processes the following:

- **Request data**: HTTP requests to API endpoints (e.g., `/v1/chat/completions`). Includes prompt content, model parameters, source IP, timestamps, and basic-auth identifiers (shared demo account; no individual user accounts).
- **Moderation outputs**: classifier outputs and rejection reasons for prompts flagged by content moderation. Rejected prompts may be retained in the project's abuse log for research purposes (see "Adversarial-finding research" below).
- **Operational telemetry**: request rates, error rates, latency, cost-per-hour gauges, blocklist statistics. Exposed via `/metrics` in Prometheus format and via `/dashboard-data` in JSON.
- **Rate-limit state**: per-source request counters used to enforce demo rate limits. Retained for the rate-limit window then aged out.
- **Auto-blocklist entries**: source identifiers flagged for repeated abuse. Retained for the blocklist TTL then aged out.

The demo does NOT collect:

- Individual user account information (the basic-auth gate uses a shared demo account).
- Payment information.
- Persistent identifiers beyond rate-limit or blocklist windows.
- Profile data, contact information, or any user-provided identity data beyond what appears in submitted requests.

## How collected data is used

- **Operational purposes**: enforcing rate limits, content moderation, demo availability monitoring.
- **Research purposes**: aggregate statistics about demo usage, classifier performance, and adversarial-input patterns may be summarized in project documentation, research outputs, partner materials, and future publications. Aggregated statistics do not identify individual users.
- **Adversarial-finding research**: per the project's invitation in [.github/ISSUE_TEMPLATE/adversarial_finding.md](.github/ISSUE_TEMPLATE/adversarial_finding.md), the demo intentionally surfaces classifier behavior under adversarial inputs. Submissions intended as security disclosures should follow [SECURITY.md](SECURITY.md); submissions intended as observation of classifier behavior are welcomed as public research input.

## Retention

- **Operational telemetry**: rolling windows (typically minutes to a few hours for rate counters, up to 24 hours for blocklist) then aged out automatically.
- **Abuse log**: retained for analysis; specific prompts may be cited in research outputs with source identifiers removed.
- **Server logs**: retained for operational debugging; not currently exposed publicly. Will be subject to additional policy if exposed.

## User choices

For the Alpha demo:

- **You may choose not to use the demo**. There is no user account; choosing not to use the demo means no demo-side data collection.
- **You may submit findings via SECURITY.md or the adversarial-finding template**. Public submissions are public; private findings via SECURITY.md are kept confidential per that policy.
- **You may request removal of specific abuse-log entries** by contacting the project via SECURITY.md's private channel. Removal will be made if technically feasible without prejudicing security investigations.

## GDPR

The demo is hosted in the European Union (the hosting provider, Germany at present). To the extent personal data is processed (source IP captured in operational telemetry; prompt content submitted by users; basic-auth identifier of the shared demo account), the EU General Data Protection Regulation (GDPR) applies.

- **Data controller**: James Sheen, the project's primary author and current maintainer (see [AUTHORS.md](AUTHORS.md)).
- **Legal basis**: legitimate interest in operating the demo, security monitoring (rate limit + abuse log), and research on classifier behavior (Article 6(1)(f)).
- **Data-subject rights**: requests to access, rectify, erase, restrict processing, port, or object to processing of personal data — use the private channel described in [SECURITY.md](SECURITY.md). Response within 30 days per Article 12(3).
- **Data minimization**: the demo retains only what is operationally necessary for the windows described in "Retention" above; aggregated research output strips source identifiers.
- **Cross-border transfers**: the demo is EU-hosted; no transfers to third countries are made by the demo itself. LLM provider routing is third-party and governed by their own policies.

## Other jurisdictions

Users in other jurisdictions with stricter privacy regimes (CCPA, etc.) should treat the GDPR-aligned practices above as the operational floor — the data-minimization measures described in this policy are intended to satisfy that floor by default. The project does not currently process data subject to additional regulatory regimes (HIPAA, PCI-DSS, etc.); users should not submit data of those types via the demo.

## Updates

This policy is updated when demo data-collection practices materially change. Routine code changes that do not affect data collection do not require updates.

## License of this file

This PRIVACY file is part of the Arbiter Project documentation and is covered by the project's [Apache License 2.0](LICENSE). See also [TRADEMARK.md](TRADEMARK.md) for Arbiter Project name-use policy.
