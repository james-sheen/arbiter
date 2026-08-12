# Security Policy

The Arbiter Project takes security seriously. This document describes how to report security vulnerabilities and what to expect in return.

## Supported versions

Arbiter is in **Alpha stage** (see [README.md](README.md) status banner). We do not yet maintain multiple release branches. Security fixes are applied to the current `master` branch only. Once we cut versioned releases, this section will be updated to enumerate supported versions.

## Reporting a vulnerability

**Preferred channel: GitHub Private Vulnerability Reporting.**

Open a private report at: [https://github.com/james-sheen/arbiter/security/advisories/new](https://github.com/james-sheen/arbiter/security/advisories/new)

This routes the report only to the maintainers and is not visible to the public. It is the fastest path for us to acknowledge, triage, and fix.

If GitHub PVR is unavailable to you, you may instead reach out by opening a public issue that asks for a private contact — do **not** include vulnerability details in the public issue itself.

### What to include

A useful report typically contains:

- A short description of the vulnerability and its impact.
- Steps to reproduce (input, command, prompt, or HTTP request).
- The version / commit SHA observed.
- Any proof-of-concept code or output (kept private).
- Optional: a suggested fix or mitigation direction.

You do not need to provide all of the above — a description plus reproduction steps is enough to start triage.

## What to expect

- **Acknowledgement**: within 5 business days of report receipt.
- **Initial triage verdict**: within 14 days (in-scope vs. out-of-scope; severity estimate).
- **Fix timeline**: depends on severity and complexity; we will keep you updated.
- **Coordinated disclosure**: we prefer to release a fix before public disclosure. We will work with you on a disclosure timeline; the default is 90 days from report unless severity warrants faster or slower.
- **Credit**: with your permission, we will credit you in the advisory and release notes. Anonymous reporting is also fine.

## Scope

In scope:

- Code in this repository (`master` branch).
- Documentation that materially affects security posture (e.g., misleading deployment guidance).
- Dependencies pinned by this repository.

Out of scope:

- Third-party services or dependencies maintained by others — please report to the respective upstream.
- Social engineering attacks against project members.
- Denial-of-service via resource exhaustion against demo deployments (the demo is intentionally rate-limited and treats abuse as observation data; see [`.github/ISSUE_TEMPLATE/adversarial_finding.md`](.github/ISSUE_TEMPLATE/adversarial_finding.md)).
- Issues that require physical access to a system running Arbiter.

## Adversarial findings vs. security vulnerabilities

For **non-sensitive adversarial findings** (model jailbreaks, classifier bypasses observed against the public demo, content-moderation gaps), please use the [adversarial finding issue template](.github/ISSUE_TEMPLATE/adversarial_finding.md) — those are research output we actively want to collect in public.

For **security vulnerabilities** (anything that lets an attacker compromise the integrity, confidentiality, or availability of a deployment), use the private channel above.

If you are unsure which category a finding falls into, default to the private channel and we will move it to public if appropriate.

## Safe harbor

We support good-faith security research. If you make a good-faith effort to comply with this policy, we will not pursue legal action against you for the research itself. Good-faith effort includes:

- Using the private reporting channel for security-impacting findings.
- Not exfiltrating data beyond the minimum needed to demonstrate the vulnerability.
- Not degrading the demo for other users.
- Giving us a reasonable window to fix before public disclosure.

## License

This security policy is part of the Arbiter Project documentation and is covered by the project's [Apache License 2.0](LICENSE). See also [TRADEMARK.md](TRADEMARK.md) for name-use policy.
