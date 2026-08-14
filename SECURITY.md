# Security Policy

## Reporting a vulnerability

Open a private report through GitHub Security Advisories:
[Report a vulnerability](https://github.com/james-sheen/arbiter/security/advisories/new).

Please do not open a public issue for something that lets an attacker compromise
a deployment. Use the private channel first and we will agree on disclosure
timing together.

What helps most, in rough order:

- The smallest input that reproduces it — a domain model and a session is
  usually enough.
- What an attacker gains. A crash, a wrong answer and a silent pass are three
  quite different problems.
- Version or commit, and which optional extras are installed.

## Supported versions

Pre-1.0. Fixes land on `master` and there are no backports; the supported
version is the current one.

## Scope

In scope:

- Code in this repository.
- The domain-model loader, which parses input that may not be trusted.
- Documentation whose guidance would make a deployment less safe if followed.

Out of scope:

- Dependencies maintained by others — report those upstream. If a dependency
  issue is reachable through this engine in a way the upstream advisory does not
  cover, that part is in scope here.
- Systems built with Arbiter. The operator of a deployment owns its posture.

## A finding this project particularly wants

**A clean pass over something that was never evaluated.**

The engine's central claim is that a result of nothing-found is distinguishable
from nothing-checked. If you can make `check` report a pass while an invariant
silently failed to run — or make `evaluations_attempted` count something the
engine did not attempt — that is the defect this project most wants to hear
about, and it does not need the private channel unless it also exposes a
deployment. A public issue is fine and is the faster route.

That is a correctness bug rather than a vulnerability in the usual sense. It is
named here because it is the failure mode the whole design exists to prevent,
and because a reader deciding where to send it should not have to guess.

## Credit

With your permission we will credit you in the advisory and the release notes.
Anonymous reporting is fine and changes nothing about how the report is handled.
