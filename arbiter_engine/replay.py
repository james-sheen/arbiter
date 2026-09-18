"""Replaying a model over history: the clock moves, and so must the data.

WHY THIS IS NOT A VERB IN `api`

The five primitives and the four discipline verbs each ANSWER a question about
a moment. This answers none: it drives `check` across many moments and hands
back what it said at each. Putting it beside them would make the supported
surface mean two different things, and the surface test refused it -- which is
what that test is for.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, Sequence

from .api import EngineSession, check
from .clock import as_naive_utc, as_of

__all__ = ["replay", "sync_current_from_history"]


def sync_current_from_history(session: EngineSession, at: datetime,
                              lookback: timedelta = timedelta(days=30)
                              ) -> Dict[str, Any]:
    """Set every declared property's CURRENT value to the last observation at
    or before `at`, and report how many had none.

    THE CLOCK MOVES THE WINDOWS AND NOT THE DATA. The temporal axioms read
    history and follow `as_of` for free; the threshold axioms read
    `Entity.properties`, which is a snapshot somebody fed in and does not
    follow anything. A replay that moved only the clock would check TODAY's
    values against last Tuesday's windows -- and would look entirely
    plausible, because every leg of the envelope would still be populated.

    `absent` is the number of declared properties with no observation in
    range, and it is the denominator that makes a replay step readable: eight
    findings out of ten synced properties is a different statement from eight
    out of ten thousand. `lookback` is reported beside it, because a property
    whose last reading is older than the search is indistinguishable from one
    that was never fed unless the span is stated.
    """
    at = as_naive_utc(at)
    synced: Dict[str, Any] = {"set": 0, "absent": 0,
                              "lookback_s": lookback.total_seconds()}
    if session.model is None:
        return synced
    # EVERY NAME THE MODEL READS, not only the indicators' own. A bound
    # declared `{from_property: margin_requirement}` is resolved off the
    # entity at check time, so a replay that advances the balance and not the
    # requirement checks every later step against the FIRST step's floor --
    # silently, because the bound still resolves. Derived operands are the same
    # argument: the join reads them, so a replay must move them.
    readable = session.readable_properties()
    for entity in session.entities.values():
        observations = session.history.get_observations(
            entity.id, at - lookback, at)
        for name in sorted(readable.get(entity.type, set())):
            latest = None
            for observation in observations:
                if observation.property_name != name:
                    continue
                if latest is None or observation.timestamp > latest.timestamp:
                    latest = observation
            if latest is None:
                synced["absent"] += 1
                continue
            entity.properties[name] = latest.value
            synced["set"] += 1
    return synced


def replay(session: EngineSession, timestamps: Sequence[datetime],
           lookback: timedelta = timedelta(days=30)) -> Iterable[Dict[str, Any]]:
    """Run `check` at each instant, as the engine would have answered then.

    Yields one envelope per step with a `replay` key carrying the instant and
    the sync counts. A GENERATOR rather than a file writer: nothing else in
    this package touches the filesystem, and a caller who wants the JSONL that
    a backtest reads writes it in one line --

        for step in replay(session, bars):
            out.write(json.dumps(step) + chr(10))

    Feed the history ONCE, with real timestamps, before calling this. Each step
    then moves only the clock and the current values; the model is parsed once
    and the observations are not re-fed, which is what makes a long replay
    affordable.

    **The curve worth plotting from the output is declines per reason over
    time.** Findings tell you what the engine said; the decline curve tells you
    whether it was looking at anything, and a backtest where nothing was
    checked produces a clean-looking run either way.
    """
    for instant in timestamps:
        with as_of(instant) as frozen:
            synced = sync_current_from_history(session, frozen, lookback)
            step = check(session).to_dict()
            step["replay"] = {"at": frozen.isoformat(), **synced}
            yield step
