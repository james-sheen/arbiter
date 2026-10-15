"""`hypothesize` builds once what every candidate's inference shares, and answers as it did.

Each candidate cause is scored by its own `run_inference`, and each built
again what is the same for all of them: the causal subgraph the walk had already
built, every node's evidence from the last check, and -- where the model declares
no strength -- a question for every edge the answer depends on, which the ranking
then kept once per edge. It also serialized every candidate's whole answer to read
two fields of it. A unit with 165 declared causes paid that 165 times a walk: most
of a late month's 1.3 to 1.5 s on a fast machine. Now the walk's subgraph, the
graph's cycle, the evidence and the questions asked are built once and handed to
each inference, and the envelope is the same, field for field.

A hub with many spokes, each with a feeder of its own: weighted and not, a delay
declared and not, read while two spokes and the hub are over their lines.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from arbiter_engine import api
from arbiter_engine.inference import causal, hypothesis, runner

SPOKES = 24
AT = datetime(2026, 1, 31)

MODEL = """
domain:
  id: hub-and-spokes
  name: Hub and spokes
  entity_types: [Hub, Spoke, Feeder]
  relationship_types: [part_of, feeds]
  causal: {evidence_severity: [warning, low, medium, high, critical], max_hops: 3}
  indicators:
    Hub:
      - {name: load, type: NUMERIC, axioms: [BOUNDEDNESS], warning: 80, critical: 95}
    Spoke:
      - {name: load, type: NUMERIC, axioms: [BOUNDEDNESS], warning: 80, critical: 95}
    Feeder:
      - {name: flow, type: NUMERIC, axioms: [BOUNDEDNESS], warning: 80, critical: 95}
  relationship_rules:
    - type: part_of
      source_type: Spoke
      target_type: Hub
      edge_direction: causal
{part_of}
    - type: feeds
      source_type: Feeder
      target_type: Spoke
      edge_direction: causal
{feeds}
"""
WEIGHT = "      causal: {weight: 0.6, leak: 0.01}"
DELAY = "      temporal: {propagation_delay: 1d}"


def _session(part_of: str = "", feeds: str = "") -> api.EngineSession:
    session = api.EngineSession()
    session.load_model(MODEL.replace("{part_of}", part_of).replace("{feeds}", feeds))
    session.add_entity("hub", "Hub", {"load": 99.0})
    for i in range(SPOKES):
        session.add_entity(f"s{i}", "Spoke", {"load": 90.0 if i in (3, 7) else 40.0})
        session.add_entity(f"f{i}", "Feeder", {"flow": 50.0})
        session.add_relationship(f"s{i}", "part_of", "hub")
        session.add_relationship(f"f{i}", "feeds", f"s{i}")
    with api.as_of(AT):
        api.check(session)
    return session


VARIANTS = {
    "no-strength-declared": {},
    "strengths-declared": {"part_of": WEIGHT, "feeds": WEIGHT},
    "one-channel-weighted": {"part_of": WEIGHT},
    "a-delay-declared": {"feeds": DELAY},
}


def _alone(*args, graph=None, shared=None, asked=None, **kwargs):
    """Each inference as it ran before: nothing shared, nothing already asked."""
    return _run_inference(*args, **kwargs)


_run_inference = runner.run_inference


@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_the_envelope_is_the_one_each_inference_alone_gave(variant, monkeypatch):
    session = _session(**VARIANTS[variant])
    with api.as_of(AT):
        shared = api.hypothesize(session, "hub").to_dict()
    monkeypatch.setattr(hypothesis, "run_inference", _alone)
    with api.as_of(AT):
        alone = api.hypothesize(session, "hub").to_dict()
    assert shared == alone
    assert shared["hypothesis"]["checked"].get("candidates", 0) >= SPOKES


def test_the_subgraph_and_the_evidence_are_built_once_a_walk(monkeypatch):
    session = _session()
    built, read = [], []
    monkeypatch.setattr(causal, "causal_subgraph",
                        lambda *a, **k: built.append(1) or _subgraph(*a, **k))
    monkeypatch.setattr(hypothesis, "causal_subgraph",
                        lambda *a, **k: built.append(1) or _subgraph(*a, **k))
    monkeypatch.setattr(runner, "causal_subgraph",
                        lambda *a, **k: built.append(1) or _subgraph(*a, **k))
    monkeypatch.setattr(runner, "node_evidence",
                        lambda *a, **k: read.append(1) or _node_evidence(*a, **k))
    with api.as_of(AT):
        envelope = api.hypothesize(session, "hub").to_dict()
    candidates = envelope["hypothesis"]["checked"]["candidates"]
    assert candidates >= SPOKES
    assert len(built) == 1, f"the causal subgraph was built {len(built)} times for {candidates} candidates"
    # Once for every candidate's inference, and once by the ranking after them, as it always read it.
    assert len(read) == 2, f"the evidence was read {len(read)} times for {candidates} candidates"


def test_each_edge_is_asked_about_once(monkeypatch):
    session = _session()
    written = []
    monkeypatch.setattr(runner, "_question", lambda *a, **k: written.append(a[1]) or _question(*a, **k))
    with api.as_of(AT):
        envelope = api.hypothesize(session, "hub").to_dict()
    assert written, "no question was asked: the model was meant to declare no strength"
    assert len(written) == len(set(written)), "an edge was asked about twice"
    assert len(envelope["hypothesis"].get("questions") or []) == len(written)


_subgraph = causal.causal_subgraph
_node_evidence = runner.node_evidence
_question = runner._question
