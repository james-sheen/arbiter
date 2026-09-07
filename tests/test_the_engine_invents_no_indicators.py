"""The engine judges what the model declared, and nothing else.

 inverted `builtin_k8s_indicators` to default `False`. This is the
behavioural half of that ruling: the other pins read source text, and source
text cannot see a seed that returns by another mechanism.

WHAT WENT WRONG. An entity type with no declared indicators fell back to a
hardcoded Kubernetes set, keyed on the type's NAME. A model declaring a domain
that has nothing to do with Kubernetes, carrying an entity type called `Pod`,
`Node`, `Service` or `Deployment`, was judged against indicators it never
declared -- measured, a finding on `restartCount` in a domain about proposals,
and `checked.invariants` reporting seven where the model declared one.

THE DENOMINATOR IS THE WORSE HALF. A false finding is visible and arguable. An
inflated `checked` is the number this engine publishes to show what it did NOT
skip, and six of those seven invariants were never asked for by anyone.

WHY THIS SURVIVED. The three non-Kubernetes example models happen to use none of
the four seeded names, so every shipped fixture agreed with the engine. The
collision is with ordinary nouns -- a factory line has a `Node`, a consulting
engagement has a `Service` -- so the fixtures were lucky rather than
representative.

THE ASSERTION IS THE OUTCOME, NOT THE MECHANISM. It counts what the model
declared and requires the envelope to match, so it holds whatever the engine
does internally and whatever the seed table happens to contain. A test naming
the seeded types would go quiet the day that table is edited, which is the day
it most needs to speak.
"""
from __future__ import annotations

import pytest

yaml = pytest.importorskip("yaml")

from arbiter_engine.api import EngineSession, check  # noqa: E402

# Names that collided with the built-in seed. Written down because the point is
# that they are ORDINARY, not because the engine is expected to know them: each
# is a noun a non-Kubernetes vertical would reach for unprompted.
COLLIDING = ["Pod", "Node", "Service", "Deployment"]


def _model(extra_type: str) -> str:
    return yaml.safe_dump({"domain": {
        "id": "proposals", "name": "proposals",
        "entity_types": ["Clause", extra_type],
        "relationship_types": ["refers_to"],
        # One declared invariant in the whole model, and it is not on the
        # colliding type. That type declares NOTHING, which is the state the
        # seed used to fill in.
        "indicators": {"Clause": [
            {"name": "length", "type": "NUMERIC",
             "axioms": ["BOUNDEDNESS"], "critical": 9000}]}}})


def _session(extra_type: str) -> EngineSession:
    session = EngineSession()
    session.load_model(_model(extra_type))
    session.add_entity("c0", "Clause", {"length": 12}, "c0")
    # Properties named for the seeded indicators, so a seed that fires has
    # everything it needs to produce a finding. If nothing fires, it is because
    # nothing was declared -- not because the data was missing.
    session.add_entity("x0", extra_type,
                       {"restartCount": 99, "cpuUsage": 0.99,
                        "readyReplicas": 0, "hasEndpoints": False}, "x0")
    return session


@pytest.mark.parametrize("colliding", COLLIDING)
class TestAnUndeclaredTypeIsJudgedOnNothing:
    def test_no_finding_names_an_indicator_the_model_never_declared(self, colliding):
        envelope = check(_session(colliding)).to_dict()
        invented = [f for f in envelope.get("findings", [])
                    if "length" not in str(f.get("problem_type", ""))]
        assert not invented, (
            f"entity type {colliding!r} declares no indicators, and the engine "
            f"produced {[f.get('problem_type') for f in invented]} against it")

    def test_the_denominator_counts_only_what_was_declared(self, colliding):
        """`checked` is the engine's claim about what it attempted. One declared
        (indicator, axiom) pair means one, whatever the type is called."""
        envelope = check(_session(colliding)).to_dict()
        assert envelope["checked"]["invariants"] == 1, (
            f"the model declares one invariant; the envelope reports "
            f"{envelope['checked']['invariants']} for a model whose second "
            f"entity type is {colliding!r}")


class TestTheProbeCouldHaveFailed:
    """Non-vacuity. Every assertion above is a negative, and negatives pass
    against an engine that evaluated nothing at all."""

    def test_a_declared_indicator_is_still_checked_and_still_fires(self):
        session = EngineSession()
        session.load_model(_model("Pod"))
        session.add_entity("c0", "Clause", {"length": 999999}, "c0")
        envelope = check(session).to_dict()
        assert envelope["checked"]["invariants"] == 1
        assert envelope["findings"], (
            "a value far above its declared critical produced no finding; this "
            "engine is not evaluating, so the negatives above prove nothing")
