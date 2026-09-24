"""Score a model against a corpus of confirmed surprises.

The roadmap item this answers asked one question of every later change: *did the
surprise hit-rate move?* Test count is not the score; this is.

Run it:

    python3 -m arbiter_engine.scripts.surprise_benchmark \
        --model examples/substation_feeder.yaml \
        --surprises examples/substation_feeder_surprises.yaml \
        --history observations.db

    python3 -m arbiter_engine.scripts.surprise_benchmark --describe \
        --surprises examples/substation_feeder_surprises.yaml

`--describe` parses the corpus and reports what will not be read, without
touching a store. It is the half that runs when you are writing a corpus; the
run above is the half that needs one.

WHY THERE IS NO DEMO MODE

A `--demo` that generated its own history would be scoring a corpus against
data the same program wrote, which is the one arrangement in which a benchmark
can never fail. The store is an argument, and an absent one is an error rather
than a number.

WHAT THE EXIT CODE MEANS

    0   the corpus was scored; read the two senses it printed
    1   nothing was scored -- every entry declined, or the corpus is empty
    2   the invocation or the corpus could not be read at all

`1` is separate from `2` on purpose. A corpus that parsed and scored nothing has
told you something real: the store does not cover the windows the corpus names.
That is not the same as a typo in the path, and a runner that cannot tell them
apart reports a broken pipeline as an honest zero.

The imports below name the engine by the path the packaging step rewrites, the
same convention `benchmark_check` and the shipped suite use: that is what lets
this file be RUN in the tree it is maintained in, rather than only after a build.
"""

from __future__ import annotations

import argparse
import json
import sys


def _load(model_path, surprises_path, history_path, entities):
    """Build a session over a real store and hand back the parsed corpus."""
    from arbiter_engine.api import EngineSession
    from arbiter_engine.history.sqlite_store import (
        SqliteObservationHistory)
    from arbiter_engine.surprises import load_surprises

    corpus, declines = load_surprises(surprises_path)

    session = EngineSession(history=SqliteObservationHistory(history_path))
    session.load_model(model_path)

    # ENTITIES COME FROM THE CORPUS unless the caller names them, because the
    # store cannot supply them: `SqliteObservationHistory` reads back an empty
    # `entity_type` by construction, and an entity with no type is checked by
    # nothing. An entry whose subject declares no `type:` is left out here and
    # declines `subject_absent` in the scorer -- which is the honest outcome,
    # and names the entry rather than failing the run.
    declared = dict(entities or {})
    for entry in corpus.entries:
        if entry.entity and entry.entity_type:
            declared.setdefault(entry.entity, entry.entity_type)
    for entity_id, entity_type in sorted(declared.items()):
        session.add_entity(entity_id, entity_type)

    return session, corpus, declines


def _describe(surprises_path) -> int:
    from arbiter_engine.surprises import load_surprises

    corpus, declines = load_surprises(surprises_path)
    print(f"domain: {corpus.domain or '<unnamed>'}")
    print(f"entries: {len(corpus.entries)}")
    confirmed = [e for e in corpus.entries if e.confirmed]
    print(f"  confirmed: {len(confirmed)}")
    print(f"  unanticipated (of confirmed): "
          f"{sum(1 for e in confirmed if not e.anticipated)}")
    for entry in corpus.entries:
        clauses = [c for c in (
            f"problem_type={entry.problem_type}" if entry.problem_type else "",
            f"axiom={entry.axiom}" if entry.axiom else "",
            f"severity_in={sorted(entry.severities)}" if entry.severities else "",
        ) if c]
        print(f"  - {entry.id}: {entry.entity or '<no entity>'}"
              f"{'.' + entry.property_name if entry.property_name else ''}"
              f"  [{', '.join(clauses) or 'NO PREDICATE'}]")
    if declines:
        print(f"\nwill not be read ({len(declines)}):")
        for decline in declines:
            print(f"  {decline.reason}: {decline.detail}")
    # A corpus that parses to nothing is not a clean corpus, and the exit code
    # says so: an empty sweep must not read like a passing one.
    return 0 if corpus.entries else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--surprises", required=True,
                        help="the surprise corpus (YAML)")
    parser.add_argument("--model", help="the domain model (YAML)")
    parser.add_argument("--history",
                        help="a SQLite observation store to replay from")
    parser.add_argument("--entities",
                        help="JSON mapping entity id to entity type, for "
                             "subjects the corpus does not type")
    parser.add_argument("--describe", action="store_true",
                        help="parse the corpus and report what will not be "
                             "read; needs no store")
    parser.add_argument("--max-instants", type=int, default=500,
                        help="per-entry replay budget (default: 500)")
    parser.add_argument("--json", action="store_true",
                        help="emit the full score as JSON")
    args = parser.parse_args(argv)

    try:
        if args.describe:
            return _describe(args.surprises)
        if not args.model or not args.history:
            parser.error("--model and --history are required unless "
                         "--describe is given")
        entities = json.loads(args.entities) if args.entities else None
        session, corpus, parse_declines = _load(
            args.model, args.surprises, args.history, entities)
    except (OSError, ValueError) as exc:
        print(f"could not read the corpus or the store: {exc}", file=sys.stderr)
        return 2

    from arbiter_engine.surprises import score

    result = score(session, corpus, max_instants=args.max_instants)
    # The parse-time refusals ride with the run-time ones. A key nothing reads
    # is exactly as invisible in a printed score as an entry that could not be
    # replayed, and separating them by which phase noticed would hide half.
    result.declines[:0] = parse_declines

    if args.json:
        print(json.dumps(result.to_dict(), indent=1))
        return 0 if result.replayable else 1

    print(result.statement())
    print()
    for outcome in result.outcomes:
        detail = (f" ({', '.join(outcome.matched)})" if outcome.matched
                  else f" — {outcome.decline.reason}" if outcome.decline
                  else "")
        print(f"  {outcome.verdict:<9} {outcome.id}{detail}")
    if result.declines:
        print(f"\nnot checked ({len(result.declines)}):")
        for decline in result.declines:
            print(f"  {decline.reason}: {decline.detail}")
    return 0 if result.replayable else 1


if __name__ == "__main__":
    raise SystemExit(main())
