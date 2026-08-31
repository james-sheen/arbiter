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
import os
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


def scaling_model(indicators: int) -> dict:
    """A model with `indicators` declared indicators and nothing else varying.

    `load_model` scales with the size of the MODEL, which is a
    different axis from every other figure this script reports -- and measuring
    it at one model size is how a cost gets called negligible on the strength
    of a four-indicator fixture. The report that asked for this figure was
    holding a generated model over vendored declarations, 360 invariants deep,
    so the honest answer is a curve and not a number.
    """
    return {
        "domain": {
            "id": "benchmark-load",
            "name": "Load-scaling domain",
            "entity_types": ["Unit"],
            "relationship_types": [],
            "indicators": {
                "Unit": [
                    {"name": f"indicator_{i}", "type": "NUMERIC",
                     "axioms": ["BOUNDEDNESS", "STABILITY"],
                     "warning": 85, "critical": 95, "window": "1h"}
                    for i in range(indicators)
                ],
            },
        }
    }


def measure_load(indicators: int, repeat: int) -> dict:
    """`load_model()` at one model size, with the YAML parse measured beside it.

    THE PARSE IS NOT PART OF `load_model` AND USUALLY DOMINATES IT. This
    function loads an in-memory mapping, which is what the API takes; a consumer
    holding a YAML file pays `yaml.safe_load` first, and on this machine that is
    tens of times the load. Reporting the load alone answers *is the engine's
    loader expensive* when the question asked was *what does it cost me to get a
    model in* -- and sends a consumer to cache the wrong artifact.
    """
    import yaml

    from arbiter_engine.api import EngineSession

    text = yaml.safe_dump(scaling_model(indicators))
    parse_times, load_times = [], []
    for _ in range(repeat):
        start = time.perf_counter()
        parsed = yaml.safe_load(text)
        parse_times.append(time.perf_counter() - start)

        session = EngineSession()
        start = time.perf_counter()
        session.load_model(parsed)
        load_times.append(time.perf_counter() - start)
    return {
        "indicators": indicators,
        "invariants": indicators * 2,
        "parse_median_s": statistics.median(parse_times),
        "load_median_s": statistics.median(load_times),
    }


def build(entities: int, observations: int, breach_fraction: float):
    """A fresh session with `entities` units, a `breach_fraction` of them bad.

    Returns the session and the two halves of its construction cost SEPARATELY.
    They were one number until, and the number was unreadable: loading
    the model is flat in ENTITY count -- it loads a model, not entities -- while
    the feed is linear, so a single `build` figure hides which half a consumer
    pays again on the next cycle. That is the question the cost table gets
    asked, and one number could not answer it.
    """
    from arbiter_engine.api import EngineSession

    session = EngineSession()
    start = time.perf_counter()
    session.load_model(MODEL)
    load_s = time.perf_counter() - start

    start = time.perf_counter()
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
    return session, load_s, time.perf_counter() - start


def measure(entities: int, observations: int, repeat: int,
            breach_fraction: float) -> dict:
    from arbiter_engine.api import check

    load_times, feed_times = [], []
    check_times, findings, declines, attempted = [], 0, 0, 0
    for _ in range(repeat):
        session, load_s, feed_s = build(entities, observations, breach_fraction)
        load_times.append(load_s)
        feed_times.append(feed_s)

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
        "load_median_s": statistics.median(load_times),
        "feed_median_s": statistics.median(feed_times),
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
    parser.add_argument("--model-sizes", default="4,40,180,360",
                        help="comma-separated indicator counts for the load "
                             "curve (default 4,40,180,360). A separate axis "
                             "from --sizes: loading scales with the model, "
                             "checking scales with the entities.")
    args = parser.parse_args(argv)

    # The engine warns when an axiom fires unusually often, which is exactly
    # what a benchmark makes it do on purpose. Left on, the table arrives under
    # a few hundred lines of correct-but-irrelevant warnings and reads as a
    # broken run -- and this output is meant to be pasted into a README.
    logging.disable(logging.WARNING)

    try:
        sizes = [int(s) for s in args.sizes.split(",") if s.strip()]
        model_sizes = [int(s) for s in args.model_sizes.split(",") if s.strip()]
    except ValueError:
        print("--sizes and --model-sizes take integers, comma separated",
              file=sys.stderr)
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
          f"is excluded from the table above and reported below, because it is "
          f"three costs on two different axes and only one of them is paid "
          f"again on the next cycle.")
    print()
    print("| entities | feed | feed per entity | `load_model()` |")
    print("|---:|---:|---:|---:|")
    for row in rows:
        print(f"| {row['entities']} | "
              f"{row['feed_median_s'] * 1000:.0f} ms | "
              f"{row['feed_median_s'] / row['entities'] * 1e6:.0f} us | "
              f"{row['load_median_s'] * 1000:.2f} ms |")
    print()
    print("The feed is linear in the entity count and is paid for whatever data "
          "is added, so a consumer re-feeding every cycle pays it every cycle. "
          "`load_model()` is FLAT there, because it reads a model and not "
          "entities -- which is why the column above says nothing useful about "
          "it, and why the table below exists.")

    load_rows = [measure_load(n, args.repeat) for n in model_sizes]
    print()
    print("| indicators | invariants | `yaml.safe_load()` | `load_model()` |")
    print("|---:|---:|---:|---:|")
    for row in load_rows:
        print(f"| {row['indicators']} | {row['invariants']} | "
              f"{row['parse_median_s'] * 1000:.0f} ms | "
              f"{row['load_median_s'] * 1000:.2f} ms |")
    print()
    print("Loading scales with the size of the MODEL. The parse is measured "
          "beside it because it is not part of it and is the larger of the two "
          "by an order of magnitude: `load_model()` takes a mapping, so a "
          "consumer holding a YAML file pays the parse first. **Cache the "
          "parsed mapping, not just the loaded session** -- and if the parse "
          "matters, `yaml.CSafeLoader` is the same result several times faster "
          "where libyaml is installed.")
    return 0


def _run() -> int:
    """`| head` is an ordinary thing to do to a table.

    This script prints a report and a reader that stops reading has said
    something about itself, not about the measurement.

    **There are two failure modes here, not one, and the first version of this
    guard caught only the louder one.** Output long enough to fill the pipe
    buffer raises out of `print`, which the `except` below catches. Output short
    enough to sit in the buffer raises nowhere: `main()` returns cleanly and the
    interpreter flushes on the way out, printing `Exception ignored` and a
    `BrokenPipeError` over a benchmark that had in fact completed, then exiting
    `120`. This table is short, so the untouched mode was the one it actually
    hits — measured by closing a reader against the built package, after the
    docstring above already claimed the fix.

    The flush is therefore INSIDE the `try`, which is the whole repair: it moves
    the failure to somewhere an `except` can reach. Then absorb it, point the
    descriptor at nowhere so the interpreter's final flush cannot raise again,
    and exit with the conventional broken-pipe status rather than pretending the
    whole table was delivered.

    Same family as the audit tool's closed-reader fix, whose own docstring names
    both modes; only one of them had been carried across.
    """
    try:
        status = main()
        sys.stdout.flush()
        return status
    except BrokenPipeError:
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except OSError:                                   # pragma: no cover
            pass
        return 128 + 13


if __name__ == "__main__":
    raise SystemExit(_run())
