"""how long `check()` takes, at sizes nobody had measured.

No public number existed for this. A consumer sizing an integration had to
guess, and the guess mattered: a per-instance threshold used to force an entity
TYPE per sensor, which is a shape that puts hundreds of types in front of the
loader rather than hundreds of entities. Whether that was affordable was
unanswerable.

Run it:

    python3 -m arbiter_engine.scripts.benchmark_check
    python3 -m arbiter_engine.scripts.benchmark_check --sizes 100,1000 --repeat 5

The imports below name the engine by the path the packaging step rewrites, the
same convention the shipped test suite uses. That is what lets this file be RUN
in the tree it is maintained in -- a benchmark that only executes after a build
is one whose numbers nobody checks before publishing them.

WHAT THIS MEASURES, AND WHAT IT DOES NOT

It measures one `check()` over N entities of one type, with a fixed number of
observations each, on synthetic data shaped so that a known fraction of the
entities breach. It is a scaling curve, not a throughput claim: the numbers
depend on this machine, this Python, and the model below.

It does NOT measure the engine warm. Every run builds a fresh session, because a
consumer's cycle does too — an in-process cache would flatter the second
iteration and no deployment gets that.

THE MODEL IS PART OF THE MEASUREMENT. Six indicators across five axioms, chosen
so the expensive paths are exercised rather than skipped: the two series axioms
read the whole window, and CONSISTENCY's cross-signal rule reads a second
property. A benchmark over one thresholded indicator would report a number an
order of magnitude better and mean nothing.
"""

from __future__ import annotations

import argparse
import logging
import statistics
import sys
import time

MODEL = {
    "domain": {
        "id": "benchmark",
        "name": "Benchmark domain",
        "entity_types": ["Unit"],
        "relationship_types": [],
        "indicators": {
            "Unit": [
                {"name": "level_pct", "type": "NUMERIC", "role": "percentage",
                 "axioms": ["BOUNDEDNESS", "CONSISTENCY", "HOMEOSTASIS"],
                 "warning": 85, "critical": 95, "window": "1h",
                 "consistency": {"agrees_with": ["level_pct_redundant"],
                                 "tolerance": 0.02}},
                {"name": "level_pct_redundant", "type": "NUMERIC",
                 "axioms": [], "window": "1h"},
                {"name": "speed_rpm", "type": "NUMERIC",
                 "axioms": ["BOUNDEDNESS", "STABILITY"],
                 "lower_critical": 900, "lower_warning": 1200,
                 "warning": 2800, "critical": 3200, "window": "1h",
                 "expect_variation": True},
                {"name": "run_hours_total", "type": "NUMERIC",
                 "axioms": ["MONOTONICITY"], "window": "24h",
                 "monotonicity": {"expected_direction": "increasing",
                                  "allow_reset": False}},
            ],
        },
    }
}


def build(entities: int, observations: int, breach_fraction: float):
    """A fresh session with `entities` units, a `breach_fraction` of them bad."""
    from arbiter_engine.api import EngineSession

    session = EngineSession()
    session.load_model(MODEL)
    breaching = max(1, int(entities * breach_fraction))
    for i in range(entities):
        bad = i < breaching
        session.add_entity(f"unit/{i}", "Unit", {
            "level_pct": 99.0 if bad else 40.0,
            # A redundant reading that disagrees only on the bad ones, so the
            # cross-signal rule does real work on some entities and is
            # correctly quiet on the rest.
            "level_pct_redundant": 60.0 if bad else 40.2,
            "speed_rpm": 700.0 if bad else 2000.0,
            "run_hours_total": float(observations),
        })
        session.add_observations(
            f"unit/{i}", "speed_rpm",
            [2000.0 + (j % 7) for j in range(observations)])
        session.add_observations(
            f"unit/{i}", "level_pct",
            [40.0 + (j % 3) for j in range(observations)])
        session.add_observations(
            f"unit/{i}", "run_hours_total",
            [float(j) for j in range(observations)])
    return session


def measure(entities: int, observations: int, repeat: int,
            breach_fraction: float) -> dict:
    from arbiter_engine.api import check

    build_times, check_times, findings, declines, attempted = [], [], 0, 0, 0
    for _ in range(repeat):
        start = time.perf_counter()
        session = build(entities, observations, breach_fraction)
        build_times.append(time.perf_counter() - start)

        start = time.perf_counter()
        envelope = check(session)
        check_times.append(time.perf_counter() - start)

        payload = envelope.to_dict()
        findings = len(payload["findings"])
        declines = len(payload["not_checked"])
        attempted = payload["checked"]["invariants"]
    return {
        "entities": entities,
        "observations_each": observations,
        "build_median_s": statistics.median(build_times),
        "check_median_s": statistics.median(check_times),
        "check_min_s": min(check_times),
        "evaluations": attempted,
        "findings": findings,
        "declines": declines,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="benchmark_check",
        description="Time check() across entity counts.")
    parser.add_argument("--sizes", default="10,100,1000",
                        help="comma-separated entity counts (default 10,100,1000)")
    parser.add_argument("--observations", type=int, default=40,
                        help="observations per series per entity (default 40)")
    parser.add_argument("--repeat", type=int, default=3,
                        help="runs per size; the median is reported (default 3)")
    parser.add_argument("--breach-fraction", type=float, default=0.1,
                        help="fraction of entities that breach (default 0.1)")
    args = parser.parse_args(argv)

    # The engine warns when an axiom fires unusually often, which is exactly
    # what a benchmark makes it do on purpose. Left on, the table arrives under
    # a few hundred lines of correct-but-irrelevant warnings and reads as a
    # broken run -- and this output is meant to be pasted into a README.
    logging.disable(logging.WARNING)

    try:
        sizes = [int(s) for s in args.sizes.split(",") if s.strip()]
    except ValueError:
        print("--sizes takes integers, comma separated", file=sys.stderr)
        return 2

    rows = [measure(n, args.observations, args.repeat, args.breach_fraction)
            for n in sizes]

    # Markdown, so the output can go straight into the README table this
    # exists to fill.
    print(f"| entities | evaluations | check (median) | per entity | "
          f"per evaluation | findings | declines |")
    print("|---:|---:|---:|---:|---:|---:|---:|")
    for row in rows:
        per_entity = row["check_median_s"] / row["entities"]
        per_eval = (row["check_median_s"] / row["evaluations"]
                    if row["evaluations"] else float("nan"))
        print(f"| {row['entities']} | {row['evaluations']} | "
              f"{row['check_median_s'] * 1000:.1f} ms | "
              f"{per_entity * 1e6:.0f} us | {per_eval * 1e6:.0f} us | "
              f"{row['findings']} | {row['declines']} |")

    print()
    print(f"{args.observations} observations per series, "
          f"{args.repeat} runs per size, median reported. Session construction "
          f"is excluded from the timing and reported separately below, because "
          f"a consumer feeding an existing session pays it once and a consumer "
          f"rebuilding per cycle pays it every time.")
    for row in rows:
        print(f"  build {row['entities']:>6} entities: "
              f"{row['build_median_s'] * 1000:.0f} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
