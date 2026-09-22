"""A `transition:` block the loader refused is a question, not a silence.

`_build_transitions` refuses a block that does not carry all of
`REQUIRED_TRANSITION_KEYS` and files a `MISSING_DECLARATION` gap naming the
keys that were absent. Its docstring says why: *a block that names `from` and
`to` and forgets `gain` is an author who meant to declare a coupling, and
silently building an edge without one turns that into a value nobody projects
and nobody asks about.*

The gap was filed onto `edge.gaps` and `api.gaps` never read it. Measured on a
Pump-feeds-Header model whose transition omits `source`:

    topology.gaps []
    topology.get_unresolved_gaps() [('missing_declaration', 'p1->h1')]
    api.gaps(session).questions 0 <- with meta.source: live

An empty `questions` leg beside `meta.source: live` is the engine saying *I
looked, and nothing is missing*. It is the clean-pass-over-something-not-
evaluated shape CONTRIBUTING names as the report this project most wants, and
it sat on the one verb whose entire job is naming what is missing.

WHY IT SURVIVED. `DigitalTwinTopology.get_unresolved_gaps()` already collects
the topology-level list plus every node-level and edge-level gap. `api.gaps`
iterated the raw `topology.gaps` attribute instead, so it saw the first
population and neither of the others. The comment above that loop documents
this exact class of bug being fixed once, for the topology-level list, in the
words *nothing anywhere read that list* -- and the fix stopped one level short
of the sibling instance it was describing.

It also survived because no shipped example contains a refused block, so the
path was never exercised by the models the suite loads. That is the reason this
file builds its own.

WHAT IS NOT WRONG, so the fix is not oversold. A value-mode traversal and
`rollout` both reported the refusal the whole time, as a `missing_declaration`
decline, and they distinguish it from `missing_dynamics` on purpose: reporting
*no transition declared* for a block sitting in the author's file would send
them looking for something that is already written. That split is preserved
here by the last class in this file.
"""
from __future__ import annotations

import pathlib
import tempfile

import pytest

from arbiter_engine import api

MODEL = """
domain:
  id: refused_coupling
  name: A coupling the loader refused
  entity_types: [Pump, Header]
  relationship_types: [feeds]
  indicators:
    Pump:
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 1e9}
    Header:
      - {name: pressure_bar, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9.5}
  relationship_rules:
    - type: feeds
      source_type: Pump
      target_type: Header
      temporal: {propagation_delay_s: 0, time_constant_s: 1,
                 response_model: step}
%(transition)s
"""

COMPLETE = """      transition:
        from: speed_rpm
        to: pressure_bar
        gain: 0.0012
        source: datasheet
"""
NO_SOURCE = """      transition:
        from: speed_rpm
        to: pressure_bar
        gain: 0.0012
"""
NO_GAIN = """      transition:
        from: speed_rpm
        to: pressure_bar
        source: datasheet
"""
NO_FROM = """      transition:
        to: pressure_bar
        gain: 0.0012
        source: datasheet
"""
NO_TO = """      transition:
        from: speed_rpm
        gain: 0.0012
        source: datasheet
"""
#: Every key spelled the way a reader would guess from the prose rather than
#: from `REQUIRED_TRANSITION_KEYS`. None of the four lands, so the whole block
#: is refused -- which is the same path as a missing key, reached differently.
MISSPELLED = """      transition:
        source_property: speed_rpm
        target_property: pressure_bar
        gain: 0.0012
        provenance: datasheet
"""
ABSENT = ""


def _session(transition_block):
    path = pathlib.Path(tempfile.mkdtemp()) / "model.yaml"
    path.write_text(MODEL % {"transition": transition_block})
    session = api.EngineSession()
    session.load_model(str(path))
    session.add_entity("p1", "Pump", {"speed_rpm": 1000.0})
    session.add_entity("h1", "Header", {"pressure_bar": 8.7})
    session.add_relationship("p1", "feeds", "h1")
    return session


def _questions(transition_block):
    envelope = api.gaps(_session(transition_block)).to_dict()
    assert envelope.get("meta", {}).get("source") == "live", (
        "the premise: the engine has a topology and is answering from it. "
        "An `unavailable` envelope would make every assertion below vacuous")
    return envelope.get("questions") or []


def _refusals(transition_block):
    return [q for q in _questions(transition_block)
            if q.get("gap_type") == "missing_declaration"]


class TestThePremise:
    """If a complete block stops loading, this file is measuring something
    other than what it says."""

    def test_a_complete_block_still_declares_its_coupling(self):
        declared = api.model_describe(_session(COMPLETE)).to_dict()[
            "model"]["transitions"]["declared"]
        assert len(declared) == 1

    def test_and_a_complete_block_asks_nothing(self):
        assert _refusals(COMPLETE) == []


class TestEveryRequiredKeyNamesItselfWhenAbsent:
    """`REQUIRED_TRANSITION_KEYS` is the whole contract, so each member gets a
    case. A test that only removed one key would pass against a fix that
    special-cased that key."""

    @pytest.mark.parametrize("block,missing", [
        (NO_SOURCE, "source"),
        (NO_GAIN, "gain"),
        (NO_FROM, "from"),
        (NO_TO, "to"),
    ])
    def test_a_missing_key_is_one_question_that_names_it(self, block, missing):
        refusals = _refusals(block)
        assert len(refusals) == 1, (
            f"a transition declared without `{missing}` produced "
            f"{len(refusals)} questions; the author wrote a coupling and the "
            f"engine did not build one, which is exactly one thing to say")
        question = refusals[0]
        assert question.get("location") == "p1->h1"
        # The wire field is `question`; `TopologyQuestion.question_text` is
        # the attribute behind it and `description` is not serialised at all,
        # which is how the key name came to be computed and then dropped.
        text = str(question.get("question") or "")
        assert missing in text, (
            f"the question is {text!r}, which does not name `{missing}` -- "
            f"the key the author has to add is the whole content of the "
            f"answer")

    def test_keys_spelled_the_way_a_reader_guesses_are_refused_too(self):
        """The shape an outside brief published as a worked example: four
        plausible names, none of them the declared ones."""
        assert len(_refusals(MISSPELLED)) == 1


class TestTheQuestionIsRankedLikeEveryOther:
    """`gaps` documents itself as priority-ranked. A population merged in at a
    constant would make the ranking not one -- the defect this same function
    already carries a comment about."""

    def test_a_refusal_carries_a_priority_from_the_weight_table(self):
        question = _refusals(NO_SOURCE)[0]
        priority = question.get("priority")
        assert isinstance(priority, (int, float)) and priority > 0.0, (
            f"priority is {priority!r}; a structural gap is scored the way a "
            f"traversal gap at hop zero is scored, not with a constant")


class TestAnEdgeThatDeclaresNothingIsStillADifferentClaim:
    """The distinction the traverser makes on purpose, pinned here so a fix to
    `gaps` cannot quietly collapse the two populations into one.

    An edge with no `transition:` at all has not refused anything -- there is
    nothing to refuse. It is a gap in the model that already has its own name,
    and it is raised when a caller asks for a value across that edge rather
    than when the model is described.
    """

    def test_no_transition_block_raises_no_refusal(self):
        assert _refusals(ABSENT) == [], (
            "an edge that declares no transition has refused nothing; "
            "reporting `missing_declaration` here would send the reader "
            "looking for a block that was never written")

    def test_and_the_two_reasons_are_not_the_same_string(self):
        from arbiter_engine.twin.topology import GapType
        assert GapType.MISSING_DECLARATION.value != GapType.MISSING_DYNAMICS.value


def _examples_dir() -> pathlib.Path:
    """Whichever copy this tree has; never an absolute path -- one names a
    directory that exists only where this file was written, and this file ships."""
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / "examples",
                      here.parents[2] / "docs" / "publication"
                      / "engine-example"):
        if candidate.is_dir() and list(candidate.glob("*.yaml")):
            return candidate
    raise AssertionError("no examples directory found in this tree")


class TestNoShippedExampleStartsAskingThis:
    """The blast-radius guard.

    Reading a wider gap population could have turned every model into a
    question list. Measured before the change and again after it: the question
    count on all six shipped examples is unchanged, because the collector
    returns roughly twice as many raw gap objects and they dedup onto the keys
    the traversal already reported.

    Pinned as a PROPERTY rather than as six counts. The numbers move whenever
    an example gains an entity type, and a count written twice drifts; what
    must not change is that no shipped model declares a coupling it then
    refuses. If one ever does, this fails and the example is the thing to look
    at -- which is also the reason the defect survived, since a suite whose
    models never exercise a path cannot report on it.
    """

    def test_no_example_declares_a_coupling_it_then_refuses(self):
        import yaml
        offenders = {}
        for path in sorted(_examples_dir().glob("*.yaml")):
            document = yaml.safe_load(path.read_text())
            domain = document.get("domain", document)
            session = api.EngineSession()
            session.load_model(str(path))
            types = domain.get("entity_types") or []
            indicators = domain.get("indicators") or {}
            for index, etype in enumerate(types):
                properties = {
                    spec["name"]: 1.0
                    for spec in (indicators.get(etype) or [])
                    if isinstance(spec, dict) and spec.get("name")}
                session.add_entity(f"{etype.lower()}{index}", etype,
                                   properties)
            for rule in (domain.get("relationship_rules") or []):
                source, target = rule.get("source_type"), rule.get(
                    "target_type")
                if source not in types or target not in types:
                    continue
                session.add_relationship(
                    f"{source.lower()}{types.index(source)}",
                    rule.get("type"),
                    f"{target.lower()}{types.index(target)}")
            refused = [q for q in (api.gaps(session).to_dict().get("questions")
                                   or [])
                       if q.get("gap_type") == "missing_declaration"]
            if refused:
                offenders[path.name] = refused
        assert offenders == {}, (
            f"shipped examples now ask a refusal question: {offenders}. "
            f"Either an example declares a partial coupling, or this "
            f"population has started firing where nothing was refused")


class TestTheFixDoesNotFireWhereNothingIsDeclared:
    """The negative case. Reading a wider gap population must not turn every
    model into a question list."""

    def test_a_model_with_no_relationship_rules_gains_no_refusal(self):
        text = """
domain:
  id: no_rules
  name: Nothing coupled to anything
  entity_types: [Pump]
  indicators:
    Pump:
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 1e9}
"""
        path = pathlib.Path(tempfile.mkdtemp()) / "model.yaml"
        path.write_text(text)
        session = api.EngineSession()
        session.load_model(str(path))
        session.add_entity("p1", "Pump", {"speed_rpm": 1000.0})
        questions = api.gaps(session).to_dict().get("questions") or []
        assert [q for q in questions
                if q.get("gap_type") == "missing_declaration"] == []
