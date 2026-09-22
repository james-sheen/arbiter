"""The seven sub-envelope decline vocabularies, and the table that publishes them.

and the same shape as one vocabulary over. `COMPATIBILITY.md`
grants a patch release permission to add a member to a discipline's decline
vocabulary, and warns in the entry above that the sets are SEPARATE and that
reading a reason from one against another is how a closed enum stops being
closed. Neither the guide nor the schema said what any of them contains, so
that advice could not be followed: ninety-three names across seven frozensets
in `subenvelope.py`, published nowhere.

WHAT IT COST, MEASURED. An outside comparison reproduced every vocabulary this
project had published -- fourteen decline reasons, six gap types, eight raced
outcomes, twenty assumption stamps -- by exact membership, and its own table of
the engine's closed vocabularies then listed five sets and none of these seven.
Three members of `simulation` appeared in its prose instead, beside a gap type,
in a list read against the fourteen. The mistake COMPATIBILITY forbids, made by
the most accurate reader this project has had.

SO THE TABLE IS DERIVED AND THIS PINS THE DERIVATION. A table written by hand
beside a frozenset is a second copy of one closed set, which is the drift
`subenvelope.py` itself refuses when it folds one vocabulary into another
rather than re-listing it. The guide gets the same discipline one level out.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from arbiter_engine import subenvelope
from arbiter_engine.types import NotEvaluatedReason

#: Only the number words this table can currently produce. A total that grows
#: past them fails here rather than passing on a stale word -- which is the
#: point: a number written in two places drifts, so the prose copy is checked
#: against the code and not against the last time somebody looked.
NUMBER_WORDS = {5: "five", 7: "seven", 8: "eight", 93: "ninety-three"}

FOLDABLE = {"the fourteen": lambda: {r.value for r in NotEvaluatedReason},
            "`projection`": lambda: set(subenvelope._PROJECTION_VOCABULARY)}


def _guide() -> str:
    """The bridge guide, from whichever copy this tree has.

    RAISES rather than skips when neither exists. A guide check that skips
    when it cannot find the guide is a green that means nothing, and the
    published tree is the one where this pin matters most.
    """
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / "BRIDGES.md",
                      here.parents[2] / "docs" / "publication"
                      / "bridge-guide.md"):
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    raise AssertionError("no bridge guide found to check against")


def _section() -> str:
    text = _guide()
    start = text.find("## 2a.")
    assert start != -1, (
        "the bridge guide has no Sec. 2a. The discipline vocabularies are "
        "published there and nowhere else; removing the section un-publishes "
        "a set COMPATIBILITY.md permits growing.")
    end = text.find("\n## ", start + 4)
    return text[start:end if end != -1 else len(text)]


def _rows():
    """(name, declared size, folded-in labels, own members) per table row."""
    rows = {}
    for line in _section().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 4 or not cells[0].startswith("`"):
            continue
        name = cells[0].strip("`")
        size = int(cells[1])
        folds = [] if cells[2] == "--" else [f.strip() for f in cells[2].split(",")]
        own = set() if cells[3] == "--" else set(
            re.findall(r"`([a-z_0-9]+)`", cells[3]))
        rows[name] = (size, folds, own)
    return rows


class TestTheTableIsTheVocabulary:
    def test_every_vocabulary_has_a_row_and_every_row_a_vocabulary(self):
        assert set(_rows()) == set(subenvelope.VOCABULARIES)

    @pytest.mark.parametrize("name", sorted(subenvelope.VOCABULARIES))
    def test_the_row_reconstructs_the_set_exactly(self, name):
        """What it folds in PLUS what is its own must be the whole set.

        Not a count check. A count agrees while two members swap, and a
        reader who takes a name from this table and finds the engine never
        emits it has been misled in the direction that matters most.
        """
        size, folds, own = _rows()[name]
        rebuilt = set(own)
        for label in folds:
            assert label in FOLDABLE, f"{name} folds in an unknown set: {label}"
            rebuilt |= FOLDABLE[label]()
        actual = set(subenvelope.VOCABULARIES[name])
        assert rebuilt == actual, (
            f"{name}: the guide and the code disagree. "
            f"only in the guide: {sorted(rebuilt - actual)}; "
            f"only in the code: {sorted(actual - rebuilt)}")
        assert size == len(actual), (
            f"{name}: the guide says {size} members and the set has "
            f"{len(actual)}")

    def test_a_set_is_named_as_folded_in_only_when_it_is_whole(self):
        """A partial overlap is not an inheritance. Naming one as though it
        were hides every member that does not come from it -- which is how
        `projection` reads as an empty row if you take the overlap for the
        set."""
        for name, (_, folds, _) in _rows().items():
            members = set(subenvelope.VOCABULARIES[name])
            for label in folds:
                assert FOLDABLE[label]() <= members, (
                    f"{name} claims to fold in {label} and does not contain "
                    f"all of it")

    def test_the_totals_in_the_prose_are_the_measured_ones(self):
        section = _section()
        # The SUM of the seven sets, not the union. Members repeat across
        # sets on purpose -- `internal_error` is in six of them -- and the
        # claim the prose makes is about how many names a reader has to be
        # able to receive, which is the sum.
        total = sum(len(v) for v in subenvelope.VOCABULARIES.values())
        for value in (total, len(subenvelope.VOCABULARIES)):
            word = NUMBER_WORDS.get(value)
            assert word is not None, (
                f"{value} has no spelling in this test's map; add it "
                f"deliberately rather than dropping the check")
            assert word in section.lower() or str(value) in section, (
                f"the section does not state {value} ({word}) anywhere, so a "
                f"count in the prose has drifted from the sets")


class TestTheGuardCouldFail:
    """A guard that cannot fail is a comment."""

    def test_a_missing_member_is_caught(self, monkeypatch):
        thinned = dict(subenvelope.VOCABULARIES)
        thinned["forecasts"] = frozenset(
            set(thinned["forecasts"]) - {"stale_forecast"})
        monkeypatch.setattr(subenvelope, "VOCABULARIES", thinned)
        with pytest.raises(AssertionError, match="only in the guide"):
            TestTheTableIsTheVocabulary().test_the_row_reconstructs_the_set_exactly(
                "forecasts")

    def test_an_added_member_is_caught(self, monkeypatch):
        grown = dict(subenvelope.VOCABULARIES)
        grown["forecasts"] = frozenset(set(grown["forecasts"]) | {"invented"})
        monkeypatch.setattr(subenvelope, "VOCABULARIES", grown)
        with pytest.raises(AssertionError, match="only in the code"):
            TestTheTableIsTheVocabulary().test_the_row_reconstructs_the_set_exactly(
                "forecasts")

    def test_a_new_vocabulary_with_no_row_is_caught(self, monkeypatch):
        grown = dict(subenvelope.VOCABULARIES)
        grown["invented"] = frozenset({"whatever"})
        monkeypatch.setattr(subenvelope, "VOCABULARIES", grown)
        with pytest.raises(AssertionError):
            TestTheTableIsTheVocabulary(
            ).test_every_vocabulary_has_a_row_and_every_row_a_vocabulary()
