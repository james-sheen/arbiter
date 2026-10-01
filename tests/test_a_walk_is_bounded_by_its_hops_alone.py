"""A published walk is bounded by `max_hops`, and by no number nobody declared.

Every edge carries the builder's propagation probability of 0.3, and no model
key can set another. The walk's default floor of 0.05 therefore cut every walk
at its third hop -- 0.3 cubed is 0.027 -- in each direction, and in
`hypothetical` mode wherever no transition is declared, whatever `max_hops`
said. Nothing in the envelope recorded the cut: a six-node chain with every node
over its bound reported three entities at `max_hops: 5`, exactly as a walk that
had looked at everything would. `gaps` asked from a start node had the same cut,
and returned no question at all for a missing node four hops out.
"""

from __future__ import annotations

import pytest

from arbiter_engine.api import EngineSession, gaps, traverse

MODEL = """
domain:
  id: chain
  name: Chain
  entity_types: [Node]
  relationship_types: [feeds]
  indicators:
    Node:
      - name: x
        type: NUMERIC
        axioms: [BOUNDEDNESS]
        warning: 50
        critical: 80
"""

NODES = [f"N{i}" for i in range(6)]


def _chain(value: float = 99.0, ghost_after: str = "") -> EngineSession:
    session = EngineSession()
    session.load_model(MODEL)
    for node in NODES:
        session.add_entity(node, "Node", {"x": value})
    for source, target in zip(NODES, NODES[1:]):
        session.add_relationship(source, "feeds", target)
    if ghost_after:
        session.add_relationship(ghost_after, "feeds", "GHOST")
    return session


def _found(envelope) -> set:
    payload = envelope.to_dict()
    assert payload["meta"]["source"] == "live", payload["meta"]
    return {f.get("entity_id") for f in payload["findings"]}


@pytest.mark.parametrize("direction,start", [
    ("forward", "N0"), ("reverse", "N5"), ("bidirectional", "N2")])
@pytest.mark.parametrize("value_mode", ["current", "hypothetical"])
def test_every_entity_within_max_hops_is_reached(direction, start, value_mode):
    overrides = {start: {"x": 99.0}} if value_mode == "hypothetical" else None
    envelope = traverse(_chain(), [start], direction=direction,
                        value_mode=value_mode, max_hops=5, overrides=overrides)
    assert _found(envelope) == set(NODES), (
        "the walk stopped short of max_hops on a probability no model declared")


def test_the_checked_count_names_every_entity_the_walk_reached():
    payload = traverse(_chain(), ["N0"], max_hops=5).to_dict()
    assert payload["checked"]["entities"] == len(NODES)


def test_max_hops_still_bounds_the_walk():
    assert _found(traverse(_chain(), ["N0"], max_hops=2)) == {"N0", "N1", "N2"}


def test_gaps_from_a_start_node_reaches_a_missing_node_four_hops_out():
    session = _chain(value=10.0, ghost_after="N3")
    located = [q for q in gaps(session, start_node="N0").to_dict()["questions"]
               if "GHOST" in str(q)]
    assert located, "gaps from the head of the chain did not reach the missing node"
