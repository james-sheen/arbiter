"""Shared ground for the engine's own suite.

WHERE THIS RUNS, AND WHY IT IS ONE FILE AND NOT TWO
---------------------------------------------------
These tests are source in this repository and a published artifact in the
engine's. `build-engine.sh` copies them through the same rewrite it applies to
the engine itself -- `arbiter_engine.X` becomes `arbiter_engine.X`
-- so the file below runs against the orchestrator's copy here and against the
installed package there, unchanged.

That is the point rather than a convenience. A transform needs an oracle that
spans it, and a suite that only ever runs on one side of a rewrite cannot tell
you the rewrite preserved behaviour. Anything the cut breaks -- a module left
out of the closure, an import rewritten to a path that does not exist, a name
the public surface stopped exporting -- fails here as an ordinary red test
rather than as a bug report from a stranger.

So: import through `arbiter_engine.<module>` and nothing else. A
bare `from arbiter_engine import detection` has no dotted prefix for the
rewrite to catch and would ship pointing at a package that is not there.

WHAT IS DERIVED AND WHAT IS AUTHORED
------------------------------------
Derived, and therefore incapable of drifting: the axiom set (`Axiom`), the
per-axiom observation floors (`AXIOM_MINIMUMS`), the decline vocabulary
(`NotEvaluatedReason`).

Authored, because a domain model is a written thing and cannot be read out of
the engine: the per-axiom indicator declarations below. Every one of them is
pinned against the derived axiom set by EQUALITY in `test_decline_contract.py`,
not by containment -- a ninth axiom must redden this suite rather than quietly
go untested, which is the failure mode a transcribed list in an enumerating
position produces.
"""

import pytest

from arbiter_engine.api import EngineSession
from arbiter_engine.types import Axiom


#: One entity type per axiom, so a cell can never be answered by a sibling
#: declaration. The engine reads several of these fields only in combination
#: (RESPONSIVENESS and CONSISTENCY need `role:`; CONNECTIVITY needs a
#: RELATIONSHIP indicator; CONSERVATION needs its nested block), so each shape
#: below is the minimum that lets that axiom actually reach a verdict.
INDICATOR_BY_AXIOM = {
    "BOUNDEDNESS": {
        "name": "level_pct", "type": "NUMERIC", "axioms": ["BOUNDEDNESS"],
        "warning": 85, "critical": 95, "window": "1h",
    },
    "STABILITY": {
        "name": "speed_rpm", "type": "NUMERIC", "axioms": ["STABILITY"],
        "window": "30m", "expect_variation": True,
    },
    "HOMEOSTASIS": {
        "name": "temp_c", "type": "NUMERIC", "axioms": ["HOMEOSTASIS"],
        "window": "1h",
    },
    "MONOTONICITY": {
        "name": "run_hours_total", "type": "NUMERIC", "axioms": ["MONOTONICITY"],
        "window": "24h",
        "monotonicity": {"expected_direction": "increasing", "allow_reset": False},
    },
    "CONSERVATION": {
        "name": "inflow_lps", "type": "NUMERIC", "axioms": ["CONSERVATION"],
        "window": "15m",
        "conservation": {
            "input_property": "inflow_lps",
            "output_properties": ["outflow_lps"],
            "loss_margin": 0.05,
        },
    },
    "CONSISTENCY": {
        "name": "fill_pct", "type": "NUMERIC", "role": "percentage",
        "axioms": ["CONSISTENCY"], "window": "15m",
    },
    "RESPONSIVENESS": {
        "name": "settle_latency_ms", "type": "NUMERIC", "role": "latency",
        "axioms": ["RESPONSIVENESS"], "warning": 5, "critical": 12,
        "window": "30m",
    },
    "CONNECTIVITY": {
        "name": "feeds_a_tank", "type": "RELATIONSHIP", "axioms": ["CONNECTIVITY"],
        "target_type": "Sink", "relation_type": "feeds",
        "min_cardinality": 1, "max_cardinality": 2,
        "violation_severity": "HIGH",
    },
}

ENTITY_TYPE = "Unit"
ENTITY_ID = "Unit/one"

#: A value that breaches every threshold declared above. Cells choose data the
#: axiom cannot legitimately pass, so `no finding and no decline` means silence
#: rather than health -- the assertion has to discriminate, and a passing
#: verdict would make it unable to.
BREACHING_VALUE = 10_000.0

#: Axioms for which a FLAT series at `BREACHING_VALUE` is not a violation, with
#: the series that is.
#:
#: Found by running the contract, not by reading the checkers: the flat series
#: below satisfies `expected_direction: increasing`, so MONOTONICITY correctly
#: said nothing and the cell read as engine silence. The engine was right and
#: the test's premise was wrong -- "this data cannot be healthy" has to be true
#: per axiom, because each one is asking a different question of the same
#: numbers. A constant series is a frozen sensor to STABILITY and a
#: well-behaved counter to MONOTONICITY, and both readings are correct.
_DESCENDING = "descending"
UNHEALTHY_SHAPE_BY_AXIOM = {"MONOTONICITY": _DESCENDING}


def unhealthy_series(axiom: str, count: int) -> list:
    """`count` values that the named axiom must not be able to clear."""
    if UNHEALTHY_SHAPE_BY_AXIOM.get(axiom) == _DESCENDING:
        return [BREACHING_VALUE - i for i in range(count)]
    return [BREACHING_VALUE] * count


def model_for(axiom: str, indicator: dict | None = None) -> dict:
    """A domain model declaring exactly one axiom, on one entity type."""
    spec = dict(indicator if indicator is not None else INDICATOR_BY_AXIOM[axiom])
    return {
        "domain": {
            "id": f"contract-{axiom.lower()}",
            "name": f"single-axiom model for {axiom}",
            "entity_types": [ENTITY_TYPE, "Sink"],
            "relationship_types": ["feeds"],
            "indicators": {ENTITY_TYPE: [spec]},
        }
    }


def session_for(axiom: str, indicator: dict | None = None) -> EngineSession:
    session = EngineSession()
    session.load_model(model_for(axiom, indicator))
    session.add_entity(ENTITY_ID, ENTITY_TYPE)
    return session


def declines_for(envelope, axiom: str) -> list:
    """Every `not_checked` record naming this axiom."""
    return [n for n in envelope.to_dict()["not_checked"]
            if str(n.get("axiom", "")).upper() == axiom.upper()]


def findings_for(envelope, axiom: str) -> list:
    """Findings attributable to this axiom.

    Matched on the axiom field where the engine sets one and on the declared
    property name otherwise: a finding's `problem_type` is domain vocabulary
    (`threshold_exceeded:level_pct`, `frozen_series:speed_rpm`), so keying on
    it alone would make this a domain-specific matcher inside a
    domain-agnostic engine's suite.
    """
    out = []
    for f in envelope.to_dict()["findings"]:
        if str(f.get("axiom", "")).upper() == axiom.upper():
            out.append(f)
        elif INDICATOR_BY_AXIOM[axiom]["name"] in str(f.get("problem_type", "")):
            out.append(f)
    return out


@pytest.fixture
def axioms() -> list:
    """The axiom vocabulary, read off its producer."""
    return [a.value for a in Axiom]
