# Contributing

The most useful thing you can send is a case where the engine reported a clean
pass over something it did not actually evaluate. That is the failure the whole
design exists to prevent, and it is the bug report this project wants most.

## What is open right now

**Issues: open.** Bug reports, adversarial findings, and questions about
modelling a domain are all welcome. The bug form asks for the things that
actually reproduce a defect here — the smallest domain model that shows it, how
the session was fed, and all four legs of the envelope.

**Documentation pull requests: open.** The README, the worked example and the
domain-modelling docs all take patches. If something in them is wrong, unclear,
or describes behaviour the package does not have, a PR is the fastest route and
it will be merged.

**Code pull requests: not being merged yet, and the reason is capacity.** This is
a one-maintainer project with no second reviewer, and a review queue is the first
thing that would fall behind. Saying so is more useful than the softer version:
the public API is also pre-1.0 and still moving, which is true and is not what is
stopping this — a frozen API would not add a reviewer.

**What ends it**: a second reviewer, or the maintainer's other commitments
closing. Not a version number and not a date, because neither of those is the
thing in the way, and a gate that expires on a milestone nobody controls is a
refusal with a schedule attached.

A pull request template ships anyway, and that is deliberate: if you open a code
PR regardless, the form collects what a reviewer would otherwise have to ask for,
and it will be read even while the merge queue is closed. An issue describing the
change is the faster route to a decision.

## Reporting well

A decline you cannot act on is a defect in the thing this project claims to be
good at. If `not_checked` gave you a reason and you could not work out what to
do about it, that is worth an issue on its own — the reason is supposed to be
actionable, and if it is not then the vocabulary or the documentation is wrong.

Two reasons account for most surprises. `insufficient_samples` reports both the
count it had and the count it needed. `not_applicable` means a checker decided
the axiom does not apply at all, and some of them decide that by reading the
indicator's name — a rough edge rather than a rule you should have to infer.

## Sign-off

Contributions are accepted under the Developer Certificate of Origin. There is
no CLA and no copyright assignment. Sign your commits:

```bash
git commit -s
```

That adds a `Signed-off-by` line asserting you have the right to submit the work
under this project's licence. Everything here is Apache 2.0.

## AI-assisted contributions

They are welcome and much of this repository was written that way; see
`AI_ATTRIBUTION.md`. The requirement is the same as for anything else: you have
read it, you understand it, and you are prepared to stand behind it. Generated
code you have not reviewed is not a contribution, it is a request that someone
else review it for you.

## Conduct

See `CODE_OF_CONDUCT.md`.
