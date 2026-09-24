"""A benchmark that cannot decline grades the store and calls it the detector.

The roadmap item behind this asked one question of every later change: *did the
surprise hit-rate move?* -- on the argument that a test count is not a score.
The instrument that answers it is the one thing in this engine most able to
lie, because its subject is the engine itself and its corpus is written after
the fact by someone who already knows the answer.

THREE WAYS IT COULD LIE, AND WHAT STOPS EACH

**By counting absence as failure.** An entry whose window holds no observation
of its subject was never shown to the engine at all. Scoring it zero measures
whether anyone was recording. It declines `not_replayable` and leaves the
denominator, and the tests below drive that case on purpose rather than hoping
it never arises.

**By counting anything as a hit.** A predicate that declares nothing matches
the first finding of any kind on that entity, so the engine gets credit for
noticing something else. That is refused by name before any replay runs.

**By having no reachable miss.** A corpus of things the engine already does
scores full marks and means nothing. The shipped example carries an entry the
declared model CANNOT reach -- an oscillation inside a threshold band, checked
by an axiom nothing declares -- and this suite asserts it comes back missed.

AND ONE THE TESTS CANNOT STOP. Predicates written after seeing a run can be
drawn tight around whatever the engine emits. Nothing here can detect that; the
defence is that they are declared once and left alone, which is a discipline and
not a mechanism. Said here as well as in the module, because this is where
somebody adjusting a number would be looking.
"""

from __future__ import annotations

import pathlib
from datetime import datetime, timedelta

import pytest

from arbiter_engine.api import EngineSession
from arbiter_engine.surprises import (
    DECLINE_REASONS, ENTRY_KEYS, PREDICATE_KEYS, SUBJECT_KEYS,
    NotASurpriseSetError, SurpriseScore, is_surprise_set, load_surprises,
    score)


def _examples_dir() -> pathlib.Path:
    """Whichever copy this tree has.

    The built package ships `examples/` at its root and again under the
    package; the tree this is maintained in has it under a publication
    directory. Walking for it rather than counting parents asks the question
    that matters in both.
    """
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / "examples",
                      here.parents[2] / "examples",
                      here.parents[2] / "docs" / "publication" / "engine-example"):
        if (candidate / "substation_feeder.yaml").is_file():
            return candidate
    raise AssertionError("no examples directory found in this tree")


MODEL = _examples_dir() / "substation_feeder.yaml"
CORPUS = _examples_dir() / "substation_feeder_surprises.yaml"

#: The shift the worked corpus names. Absolute, and deliberately not derived
#: from the clock: a benchmark whose fixture drifts with today's date stops
#: being reproducible the day after it is written, which has happened here.
SHIFT_START = datetime(2026, 6, 10, 8, 0)
OSCILLATION_START = datetime(2026, 6, 10, 9, 0)


def _session_with_the_shift() -> EngineSession:
    """A store covering the shift the corpus names, and nothing before it.

    The overnight sag the corpus also names is NOT fed, because the entry says
    nobody was recording. That absence is the subject of the headline test and
    has to be real rather than asserted.
    """
    session = EngineSession()
    session.load_model(str(MODEL))
    for entity_id, entity_type in (("sub-1", "Supply"), ("fdr-1", "Feeder"),
                                   ("pnl-a", "Panel"), ("pnl-b", "Panel")):
        session.add_entity(entity_id, entity_type)

    half_hours = [SHIFT_START + timedelta(minutes=30 * i) for i in range(16)]
    # 212 V is inside the band `lower_warning: 216` draws and above
    # `lower_critical: 207`, so every instant in the window warns.
    session.add_observations("pnl-a", "voltage_v", [(t, 212.0) for t in half_hours])
    session.add_observations("pnl-b", "voltage_v", [(t, 230.0) for t in half_hours])
    session.add_observations("sub-1", "voltage_kv", [(t, 11.0) for t in half_hours])
    # Swinging hard and never leaving the declared band.
    session.add_observations("fdr-1", "current_a", [
        (OSCILLATION_START + timedelta(minutes=2 * i), 300.0 if i % 2 else 370.0)
        for i in range(30)])
    return session


class TestTheHeadline:
    """A window with no data is a refusal, not a miss."""

    def test_an_unobserved_window_declines_rather_than_scoring_zero(self):
        session = _session_with_the_shift()
        corpus, _ = load_surprises(str(CORPUS))
        result = score(session, corpus)

        sag = next(o for o in result.outcomes if o.id == "supply-sag-overnight")
        assert sag.verdict == "declined"
        assert sag.decline is not None
        assert sag.decline.reason == "not_replayable"

    def test_the_refused_entry_is_outside_the_denominator(self):
        """The number this protects. `replayable` is what a reader divides by,
        and an entry nobody could replay must not be in it."""
        session = _session_with_the_shift()
        corpus, _ = load_surprises(str(CORPUS))
        result = score(session, corpus)

        assert result.replayable == 2          # not 3: the sag is out
        assert result.declined == 1
        assert result.detected + result.missed == result.replayable

    def test_feeding_the_window_moves_the_entry_into_the_denominator(self):
        """The other side of the same claim, and the one that proves the
        decline is about the DATA rather than about the entry.

        Fed a series the axiom can judge, the same entry stops declining. If it
        declined either way the first test would pass for the wrong reason."""
        session = _session_with_the_shift()
        sag_start = datetime(2026, 6, 9, 2, 0)
        session.add_observations("sub-1", "voltage_kv", [
            (sag_start + timedelta(minutes=10 * i), 10.2) for i in range(6)])
        corpus, _ = load_surprises(str(CORPUS))
        result = score(session, corpus)

        sag = next(o for o in result.outcomes if o.id == "supply-sag-overnight")
        assert sag.verdict == "detected"
        assert result.replayable == 3
        assert result.declined == 0


class TestTheWorkedCorpusReachesEveryVerdict:
    """A corpus in which everything is catchable measures the corpus."""

    @pytest.fixture(scope="class")
    def result(self):
        corpus, declines = load_surprises(str(CORPUS))
        assert not declines, f"the shipped corpus has unread keys: {declines}"
        return score(_session_with_the_shift(), corpus)

    def test_the_declared_breach_is_detected(self, result):
        hit = next(o for o in result.outcomes if o.id == "panel-a-undervoltage")
        assert hit.verdict == "detected"
        assert hit.matched, "a hit that names no finding cannot be checked"

    def test_the_entry_the_model_cannot_reach_is_missed(self, result):
        """The reachable miss. `current_a` declares BOUNDEDNESS and nothing
        else, so an oscillation inside the band is invisible to this model --
        which is a real limitation and must be reported as one."""
        miss = next(o for o in result.outcomes if o.id == "feeder-oscillation")
        assert miss.verdict == "missed"
        assert miss.instants > 0, (
            "a miss with no instants is a decline wearing the wrong label")

    def test_an_unconfirmed_report_is_in_neither_denominator(self, result):
        assert result.unconfirmed == 1
        assert not [o for o in result.outcomes if o.id == "panel-b-flicker"]

    def test_the_counts_reconcile(self, result):
        assert result.entries == 4
        assert (result.detected + result.missed + result.declined
                + result.unconfirmed) == result.entries


class TestBothSensesTravelTogether:
    """One number was ruled a defect here after it happened."""

    def test_there_is_no_single_rate_to_quote(self):
        assert not hasattr(SurpriseScore, "rate")
        assert "rate" not in SurpriseScore().to_dict()

    def test_the_statement_names_both_and_names_its_denominators(self):
        result = score(_session_with_the_shift(), load_surprises(str(CORPUS))[0])
        sentence = result.statement()
        assert "detector performance" in sentence
        assert "design foresight" in sentence
        # Every count a reader would divide by, in the sentence itself.
        assert f"{result.detected} of {result.replayable}" in sentence
        assert "not replayable" in sentence
        assert "unconfirmed" in sentence

    def test_foresight_is_counted_over_confirmed_entries_only(self):
        """An unconfirmed report cannot be evidence that the design missed
        something: there is nothing yet to have missed."""
        result = score(_session_with_the_shift(), load_surprises(str(CORPUS))[0])
        confirmed = result.entries - result.unconfirmed
        assert result.unanticipated == 2
        assert confirmed == 3

    def test_the_two_senses_move_independently(self):
        """The reason they are two columns rather than one number.

        The same corpus with `anticipated: true` on every entry reports a
        foresight column of zero and the SAME detector column. If one figure
        moved the other, reporting both would be theatre."""
        import copy

        import yaml

        raw = yaml.safe_load(CORPUS.read_text(encoding="utf-8"))
        foreseen = copy.deepcopy(raw)
        for entry in foreseen["surprises"]["entries"]:
            entry["anticipated"] = True

        before = score(_session_with_the_shift(), load_surprises(raw)[0])
        after = score(_session_with_the_shift(), load_surprises(foreseen)[0])

        assert before.unanticipated == 2 and after.unanticipated == 0
        assert (before.detected, before.missed, before.declined) == \
               (after.detected, after.missed, after.declined)


class TestRefusalsBeforeAnyReplay:
    """Six things that make an entry unanswerable, each named."""

    def _one(self, session, **overrides):
        entry = {
            "id": "e",
            "subject": {"entity": "pnl-a", "type": "Panel",
                        "property": "voltage_v"},
            "window": {"start": "2026-06-10T08:00:00",
                       "end": "2026-06-10T16:00:00"},
            "counts_as_detected_when": {"axiom": "BOUNDEDNESS"},
        }
        entry.update(overrides)
        corpus, _ = load_surprises({"surprises": {"entries": [entry]}})
        result = score(session, corpus)
        return result.outcomes[0]

    @pytest.mark.parametrize("overrides,reason", [
        ({"subject": {}}, "no_subject"),
        ({"window": {}}, "no_window"),
        ({"window": {"start": "2026-06-10T16:00:00",
                     "end": "2026-06-10T08:00:00"}}, "malformed_window"),
        ({"counts_as_detected_when": {}}, "empty_predicate"),
        ({"subject": {"entity": "nobody", "type": "Panel"}}, "subject_absent"),
    ])
    def test_each_is_refused_by_name(self, overrides, reason):
        outcome = self._one(_session_with_the_shift(), **overrides)
        assert outcome.verdict == "declined"
        assert outcome.decline.reason == reason

    def test_the_budget_refuses_rather_than_sub_sampling(self):
        """Stepping over the instant the engine spoke at would report a miss
        it did not earn, which is worse than reporting nothing."""
        session = _session_with_the_shift()
        corpus, _ = load_surprises({"surprises": {"entries": [{
            "id": "e",
            "subject": {"entity": "pnl-a", "type": "Panel",
                        "property": "voltage_v"},
            "window": {"start": "2026-06-10T08:00:00",
                       "end": "2026-06-10T16:00:00"},
            "counts_as_detected_when": {"axiom": "BOUNDEDNESS"},
        }]}})
        result = score(session, corpus, max_instants=2)
        assert result.outcomes[0].decline.reason == "instant_budget_exhausted"
        assert result.outcomes[0].decline.evidence["budget"] == 2

    def test_every_reason_this_scorer_can_emit_is_in_its_vocabulary(self):
        """A closed set that the code can step outside of is not closed."""
        session = _session_with_the_shift()
        corpus, declines = load_surprises(str(CORPUS))
        result = score(session, corpus)
        emitted = {d.reason for d in result.declines} | {d.reason for d in declines}
        assert emitted <= DECLINE_REASONS


class TestTheCorpusIsParsedStrictly:
    """A key nothing reads is the failure this project keeps finding."""

    def test_an_unknown_key_is_named_with_the_nearest_one_that_is_read(self):
        _, declines = load_surprises({"surprises": {"entries": [{
            "id": "e", "descrption": "typed one letter short",
            "subject": {"entity": "pnl-a", "type": "Panel"},
            "window": {"start": "2026-06-10T08:00:00",
                       "end": "2026-06-10T16:00:00"},
            "counts_as_detected_when": {"axiom": "BOUNDEDNESS"},
        }]}})
        unknown = [d for d in declines if d.reason == "unknown_key"]
        assert len(unknown) == 1
        assert unknown[0].evidence.get("did_you_mean") == "description"

    @pytest.mark.parametrize("block,key,known", [
        ("subject", "entty", SUBJECT_KEYS),
        ("counts_as_detected_when", "axoim", PREDICATE_KEYS),
    ])
    def test_the_nested_blocks_are_checked_too(self, block, key, known):
        """Checking only the top level is how a nested typo reaches nothing.
        Each block below is read by name, so each is compared by name."""
        entry = {
            "id": "e",
            "subject": {"entity": "pnl-a", "type": "Panel"},
            "window": {"start": "2026-06-10T08:00:00",
                       "end": "2026-06-10T16:00:00"},
            "counts_as_detected_when": {"axiom": "BOUNDEDNESS"},
        }
        entry[block] = dict(entry[block], **{key: "x"})
        _, declines = load_surprises({"surprises": {"entries": [entry]}})
        named = [d for d in declines
                 if d.reason == "unknown_key" and key in d.scope["field"]]
        assert named, f"{block}.{key} reached nothing quietly"
        # The suggestion is drawn from THAT block's vocabulary, not from a
        # union of all of them: a nested typo suggested a top-level key once,
        # which sends the author to edit the wrong line.
        assert named[0].evidence["did_you_mean"] in known
        assert named[0].scope["field"].startswith(f"entries[e].{block}.")

    def test_an_unusable_severity_list_is_refused_whole(self):
        """`read_severity_floor`'s own rule, and the reason it is the single
        reader: applying the half that parsed would narrow a predicate to a
        severity the author did not choose."""
        corpus, declines = load_surprises({"surprises": {"entries": [{
            "id": "e",
            "subject": {"entity": "pnl-a", "type": "Panel"},
            "window": {"start": "2026-06-10T08:00:00",
                       "end": "2026-06-10T16:00:00"},
            "counts_as_detected_when": {"severity_in": ["warning", "critcal"]},
        }]}})
        bad = [d for d in declines if d.reason == "unknown_value"]
        assert len(bad) == 1
        assert bad[0].evidence["rejected"] == ["critcal"]
        assert corpus.entries[0].severities == frozenset()

    def test_the_defaults_put_the_burden_on_the_flattering_claim(self):
        """Absent means confirmed, and absent means NOT foreseen. A set that
        does not say is making the ordinary claim, not the favourable one."""
        corpus, _ = load_surprises({"surprises": {"entries": [{
            "id": "e",
            "subject": {"entity": "pnl-a", "type": "Panel"},
            "window": {"start": "2026-06-10T08:00:00",
                       "end": "2026-06-10T16:00:00"},
            "counts_as_detected_when": {"axiom": "BOUNDEDNESS"},
        }]}})
        assert corpus.entries[0].confirmed is True
        assert corpus.entries[0].anticipated is False

    def test_the_entry_vocabulary_is_what_the_parser_reads(self):
        """Derived, not transcribed. A guard narrower than the thing it covers
        reports a clean corpus for a typo."""
        assert "confirmed" in ENTRY_KEYS and "anticipated" in ENTRY_KEYS

    @pytest.mark.parametrize("source", [
        {"domain": {"id": "x", "entity_types": ["A"]}},   # a domain model
        {"surprises": {"domain": "x"}},                   # no entries
        "not a mapping",
    ])
    def test_something_that_is_not_a_surprise_set_is_refused(self, source):
        with pytest.raises((NotASurpriseSetError, ValueError, OSError)):
            load_surprises(source)
        assert is_surprise_set(source) is False

    def test_the_shipped_corpus_is_one(self):
        assert is_surprise_set(str(CORPUS)) is True


class TestTheScorerCanReportAMiss:
    """Falsification. A benchmark that cannot report a miss is a formality."""

    def test_narrowing_the_predicate_past_what_the_engine_says_turns_a_hit(self):
        """The detected entry, asked for a severity the reading cannot reach.

        212 V is in the warning band and not the critical one, so a predicate
        naming only `critical` must come back missed. If it still passed, the
        predicate would not be being read."""
        session = _session_with_the_shift()
        corpus, _ = load_surprises({"surprises": {"entries": [{
            "id": "e",
            "subject": {"entity": "pnl-a", "type": "Panel",
                        "property": "voltage_v"},
            "window": {"start": "2026-06-10T08:00:00",
                       "end": "2026-06-10T16:00:00"},
            "counts_as_detected_when": {"axiom": "BOUNDEDNESS",
                                        "severity_in": ["critical"]},
        }]}})
        assert score(session, corpus).outcomes[0].verdict == "missed"

    def test_a_finding_on_another_entity_does_not_count(self):
        """The entity clause. Without it a benchmark scores a detector for
        noticing something else in the same envelope."""
        session = _session_with_the_shift()
        corpus, _ = load_surprises({"surprises": {"entries": [{
            "id": "e",
            "subject": {"entity": "pnl-b", "type": "Panel",
                        "property": "voltage_v"},
            "window": {"start": "2026-06-10T08:00:00",
                       "end": "2026-06-10T16:00:00"},
            "counts_as_detected_when": {"axiom": "BOUNDEDNESS"},
        }]}})
        # pnl-b reads 230 V and is clean; pnl-a is breaching in the same
        # envelope at every instant.
        assert score(session, corpus).outcomes[0].verdict == "missed"
