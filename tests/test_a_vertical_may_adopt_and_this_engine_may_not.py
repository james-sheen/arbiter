"""Somebody has to write the fitted number down. An internal ruling rules who.

Phase B2 asked for `adopt <proposal_id>`: a verb that writes a fitted gain
into the model with provenance. This package had refused that twice, in
`_proposed_transitions` and in `causal/discovery.py`, on the grounds that an
engine which replaced a declaration with its own measurement leaves nobody
able to say what the model asserts.

**The ruling does not reverse either refusal.** It separates two things the
request runs together. What was refused is an ENGINE acting on its own
measurement -- a process handed a file to read, rewriting it. What is
permitted is a tool DOWNSTREAM of this one, whose own author maintains the
file, invoked by a person who typed the proposal's name, writing the number
with a basis beside it. The distance is the ruling, and none of it is here.

So this file holds the half that lives in this package: the ruling is
recorded where an internal ruling asked for it, and the engine still writes no model.

WHY THE FIRST HALF READS PROSE AS PROSE. This project has been bitten four
times by a check that greps its own source to prove something about code --
most recently twice in two days -- and the rule that came out of it is to ask
the parse tree instead. That rule is not what is happening here. The
acceptance is *a ruling recorded beside `_proposed_transitions`, either way*:
the deliverable IS a sentence, the docstring IS the artifact a reader meets,
and reading it is the only predicate that can fail when it goes missing. The
second half, which is a claim about BEHAVIOUR, is held by running the surface
and comparing the file -- not by looking for a `write` call in the source.
"""

from __future__ import annotations

import random
from datetime import timedelta

import pytest

from arbiter_engine import api
from arbiter_engine.surprises import load_surprises
from arbiter_engine.twin import transition_learner

MODEL = """
domain:
  id: adoptruling
  name: One declared coupling, fitted and never edited
  entity_types: [Pump, Tank]
  relationship_types: [feeds]
  indicators:
    Pump: [{name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9e9}]
    Tank: [{name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS], warning: 60}]
  relationship_rules:
    - type: feeds
      source_type: Pump
      target_type: Tank
      temporal:
        propagation_delay_s: 0
        time_constant_s: 1
        response_model: step
      transition:
        from: speed_rpm
        to: level_pct
        gain: 0.05
        source: a nameplate figure nothing here may overwrite
"""

CORPUS = {
    "surprises": {
        "domain": "adoptruling",
        "entries": [{
            "id": "tank-high",
            "description": "the tank sat above its warning line",
            "subject": {"entity": "t", "type": "Tank", "property": "level_pct"},
            "window": {"start": "2026-01-01T00:00:00",
                       "end": "2026-01-01T01:00:00"},
            "counts_as_detected_when": {"axiom": "BOUNDEDNESS",
                                        "severity_in": ["warning", "critical"]},
            "confirmed": True,
            "anticipated": False,
            "source": "fixture, not a field record",
        }],
    }
}


def _session(tmp_path):
    path = tmp_path / "m.yaml"
    path.write_text(MODEL)
    session = api.EngineSession()
    session.load_model(str(path))
    session.add_entity("p", "Pump", {"speed_rpm": 1000.0})
    session.add_entity("t", "Tank", {"level_pct": 50.0})
    session.add_relationship("p", "feeds", "t")
    now = api.now_utc()
    rng = random.Random(11)
    speed, level = 1000.0, 50.0
    for k in range(200):
        step = rng.uniform(-50.0, 50.0)
        speed += step
        level += 0.02 * step
        when = now - timedelta(seconds=60 * (200 - k))
        session.add_observations("p", "speed_rpm", [(when, speed)])
        session.add_observations("t", "level_pct", [(when, level)])
    return session, path


def _corpus():
    corpus, declines = load_surprises(CORPUS)
    assert not declines, f"the fixture corpus has unread keys: {declines}"
    return corpus


class TestTheRulingIsRecordedWhereCD2008AskedForIt:
    """`_proposed_transitions` is the surface that publishes the proposals, and
    the place the entry named. A ruling recorded anywhere else is a ruling the
    next reader of this function will not find."""

    @pytest.fixture(scope="class")
    @classmethod
    def block(cls):
        """Whitespace-normalised. A phrase this reads for can be rewrapped by
        the next person who edits the paragraph around it, and a ruling that
        goes missing because a line moved is a check measuring the margin.

        `@classmethod` because a class-scoped fixture declared as an instance
        method is deprecated in pytest 9.1 and removed in 10, and the published
        `pyproject.toml` turns that warning into an error -- so the shipped
        suite would fail at setup on a current runner. The residual lane holds
        that rule for every test in this repository; this file walked into it
        and the lane caught it.
        """
        doc = api._proposed_transitions.__doc__
        assert doc, "`_proposed_transitions` has lost its docstring"
        return " ".join(doc.split())

    def test_it_is_dated_and_named_as_a_ruling(self, block):
        """KEYED ON THE PROSE, NOT ON THE ENTRY ID, and that is deliberate.

        The publication scrub deletes internal identifiers from the built tree
        -- the whole paragraph survives, `,` does not. A guard keyed on
        the id would pass in the tree it is maintained in fail in the one
        it ships to, which is the ship-leg split this project has already paid
        for twice. The date is what a reader of either tree can act on.
        """
        assert "ruled 2026-09-25" in block.lower()

    def test_both_halves_are_stated(self, block):
        """Either half alone is a different ruling. *A vertical may* without
        *this engine may not* reads as a reversal; the reverse reads as the
        refusal that was already there, and would still be open."""
        lowered = block.lower()
        assert "a vertical may" in lowered, (
            "the permission half is missing, so the ruling reads as the "
            "refusal it replaced")
        assert "still may not" in lowered, (
            "the refusal half is missing, so the ruling reads as a reversal")

    def test_it_says_what_makes_the_permitted_case_different(self, block):
        """A permission with no conditions is not a ruling, it is a hole. The
        four the entry turns on: somewhere else, someone else, a named
        proposal, and a recorded basis."""
        for condition in ("separate distribution", "separate command",
                          "named proposal", "recorded basis"):
            assert condition in block, f"the ruling does not name {condition!r}"

    def test_it_names_the_first_writer_so_a_reader_can_go_and_look(self, block):
        assert "bmc-sensor-audit" in block

    def test_the_learner_points_at_it_rather_than_restating_it(self):
        """`transition_learner` makes the strongest version of the refusal in
        this package. A reader who arrives there must not be left with the
        pre-ruling sentence -- and must not meet a second copy of the ruling
        either, because two records of one decision drift."""
        doc = " ".join((transition_learner.__doc__ or "").split())
        assert "ruled 2026-09-25" in doc.lower(), (
            "the module that says a tool rewriting its own input IS the system "
            "does not mention the ruling that qualified it")
        assert "api.py" in doc, "the pointer does not say where the ruling is"
        assert "separate distribution" not in doc, (
            "the ruling has been restated here as well as in `api.py`; one "
            "decision recorded twice is one that will disagree with itself")


class TestTheEngineStillWritesNoModel:
    """The behavioural half. Replay SUBSTITUTES a proposal into the model to
    measure it, so the interesting question is not whether anything calls
    `write` -- it is whether the file a caller handed over is the file they
    still have afterwards."""

    def _fingerprint(self, tmp_path):
        return sorted(
            (p.name, p.stat().st_size, p.stat().st_mtime_ns, p.read_bytes())
            for p in tmp_path.iterdir() if p.is_file())

    def test_the_model_file_is_untouched_by_the_proposal_surface(self, tmp_path):
        session, _path = _session(tmp_path)
        before = self._fingerprint(tmp_path)
        api.model_describe(session).to_dict()
        assert self._fingerprint(tmp_path) == before

    def test_it_is_untouched_by_a_replay_that_actually_substitutes(self, tmp_path):
        """The path that has a reason to write. Without a corpus the replay
        refuses and never touches the gain, so a test that only ran that one
        would pass on an engine that DID write."""
        session, _path = _session(tmp_path)
        payload = api.model_describe(session, _corpus()).to_dict()["model"]
        assert payload["proposed_transitions"]["fitted"], (
            "nothing was fitted, so no replay ran and this asserts nothing")
        replay = payload["proposed_transitions"]["fitted"][0]["replay"]
        assert replay["status"] == "replayed", replay

    def test_the_file_still_reads_back_as_the_author_wrote_it(self, tmp_path):
        session, path = _session(tmp_path)
        before = path.read_text()
        api.model_describe(session, _corpus()).to_dict()
        assert path.read_text() == before
        assert "gain: 0.05" in path.read_text()

    def test_no_sidecar_appears_beside_it(self, tmp_path):
        """A file written NEXT to the model is not the model being edited, and
        it is still this package deciding to put something on somebody's disk
        that they did not ask for."""
        session, _path = _session(tmp_path)
        before = {p.name for p in tmp_path.iterdir()}
        api.model_describe(session, _corpus()).to_dict()
        assert {p.name for p in tmp_path.iterdir()} == before
