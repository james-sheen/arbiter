# Privacy

Arbiter is a library. It runs inside your process, on data you supply, and
sends nothing anywhere.

## What this software collects

Nothing. There is no telemetry, no usage reporting, no crash reporting, and no
update check.

That is a checkable claim rather than a promise, and it is worth checking rather
than believing:

```bash
python3 - <<'PY'
import socket, pkgutil, importlib
socket.socket = None                      # any dial-out is now a TypeError
import arbiter_engine
for m in pkgutil.walk_packages(arbiter_engine.__path__, "arbiter_engine."):
    importlib.import_module(m.name)
print("imported the whole package with networking removed")
PY
```

The package declares two dependencies, `numpy` and `pyyaml`, neither of which
opens a network connection on import. The engine writes no files: it reads the
domain model you point it at, holds observations in memory for the life of the
session, and returns results to the caller.

## What you supply, and where it goes

Entity identifiers, indicator values and observation history are passed in by
you and stay in the process you passed them to. They are not persisted by this
package. If you place them somewhere durable — a database, a log line, a
snapshot of an envelope — that is your storage and your policy governs it.

Identifiers are the part worth thinking about. An entity id is free text and
this engine never inspects it, so if you name entities after people, customer
accounts or IP addresses, those names travel through findings, declines and
attestations into whatever you do next. The engine cannot help you there,
because it cannot tell an identifier from a personal name.

## This repository

Contributions and issues are public and hosted on GitHub. Anything you write in
an issue, a pull request or a commit message is published under the same terms
as the rest of the project. GitHub's own privacy practices apply to that
activity and are not something this project controls.

## Deployments built on Arbiter

If you deploy a service that uses this engine, its privacy posture is yours to
state. Nothing here transfers: the licence grants no warranty, and a library
that collects nothing does not make a system built on it collect nothing.

## Changes

This file describes current behaviour. If the software ever collects anything,
that will be stated here and in the release notes before it ships, not after.
