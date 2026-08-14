# Support

## Where to go

| You have | Go to |
|---|---|
| A bug, or a clean pass over something unevaluated | [Open an issue](https://github.com/james-sheen/arbiter/issues) using the bug form |
| A security vulnerability | `SECURITY.md` — private channel, not an issue |
| A question about modelling a domain | An issue is fine; there is no separate forum |

There is no mailing list, chat channel or commercial support offering. If this
page ever says otherwise it will say so plainly rather than implying it.

## Before opening an issue

Read the declines. On this engine `not_checked` is where the answer usually is:
an axiom listed there did not fail, it reported a machine-readable reason for
why it could not run. The two you are most likely to meet are
`insufficient_samples`, which reports both the count it had and the count it
needed, and `not_applicable`, which means a checker decided the axiom does not
apply to that indicator at all.

The other thing worth checking first is how the session was fed. Threshold
checks read an entity's current `properties` and the temporal checks read
observation history, so supplying one and not the other is the commonest way to
get a clean result over a value that is plainly out of range.

## Response times

This is a small project at an early stage. Issues are read, but there is no
response-time commitment and it would be dishonest to publish one.

## Documentation

`README.md` is the front door. `examples/water_tank.yaml` declares all eight
axioms in one file and doubles as the schema reference. Longer technical
write-ups and the observation logs from the closed-loop alpha are in
`evidence/`, including the findings that went against the project.
