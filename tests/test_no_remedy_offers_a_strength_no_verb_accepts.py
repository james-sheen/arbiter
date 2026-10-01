"""A decline's remedy names only a route a caller can take.

`cpt_missing` told the author to declare `causal.weight` "or supply learned
weights", and `infer`'s docstring said the strengths are the ones declared "or a
learner measured". No verb takes a learned strength, and neither caller of the
causal subgraph passes one, so the second remedy sent people looking for a door
that is not there. The check below is derived from the verbs' signatures: if a
verb ever accepts a learned strength, the remedy may offer it again.
"""

from __future__ import annotations

import inspect
import re

import arbiter_engine.inference as inference_package
from arbiter_engine import api

MODEL = """
domain:
  id: unweighted
  name: Unweighted
  entity_types: [Pump, Tank]
  relationship_types: [feeds]
  indicators:
    Pump:
      - name: speed_rpm
        type: NUMERIC
        axioms: [BOUNDEDNESS]
        warning: 3000
        critical: 3500
    Tank:
      - name: level_pct
        type: NUMERIC
        axioms: [BOUNDEDNESS]
        warning: 85
        critical: 95
  relationship_rules:
    - type: feeds
      source_type: Pump
      target_type: Tank
      edge_direction: causal
"""

VERBS = (api.infer, api.hypothesize)
OFFERS_LEARNING = re.compile(r"learn(ed|er|t)\b[^.]*\b(weight|strength)|"
                             r"(weight|strength)s?\b[^.]*\blearn(ed|er)\b", re.I)


def _a_verb_accepts_a_learned_strength() -> bool:
    return any("learn" in name for verb in VERBS
               for name in inspect.signature(verb).parameters)


def _session() -> api.EngineSession:
    session = api.EngineSession()
    session.load_model(MODEL)
    session.add_entity("P1", "Pump", {"speed_rpm": 1500.0})
    session.add_entity("T1", "Tank", {"level_pct": 99.0})
    session.add_relationship("P1", "feeds", "T1")
    api.check(session)
    return session


def _details(payload: dict, leg: str) -> list:
    return [d.get("detail") or "" for d in (payload.get(leg) or {}).get("not_checked") or []]


def test_the_decline_still_says_what_to_declare():
    payload = api.infer(_session(), "T1").to_dict()
    details = _details(payload, "inference")
    assert any("causal.weight" in d for d in details), details


def test_no_decline_offers_learned_strengths_while_no_verb_takes_them():
    if _a_verb_accepts_a_learned_strength():
        return
    session = _session()
    details = (_details(api.infer(session, "T1").to_dict(), "inference")
               + _details(api.hypothesize(session, "T1").to_dict(), "hypothesis"))
    assert details, "the probe raised no decline to read"
    offering = [d for d in details if OFFERS_LEARNING.search(d)]
    assert not offering, offering


def test_no_docstring_on_the_inference_path_offers_them_either():
    if _a_verb_accepts_a_learned_strength():
        return
    for owner in VERBS + (inference_package,):
        doc = inspect.getdoc(owner) or ""
        assert not OFFERS_LEARNING.search(doc), (owner, OFFERS_LEARNING.search(doc))
