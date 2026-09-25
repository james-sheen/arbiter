"""The README's `sixteen ... none` is derived from the alpha record, not typed.

The README quotes the alpha's surprise figures in two senses, and a figure in
prose that nothing re-derives is only true until somebody edits one of the two
files. This counts the record and holds the README to it.

IT SHIPS, AND THAT IS THE POINT OF WHERE IT LIVES. It began in a lane only the
maintainers run, so from the published tree the figure read as prose -- and an
outside verification of this repository said exactly that, asking for the
sixteen to be filed as a corpus so the sentence would be derived. It already
was; the reader could not see the derivation. Both files it reads are in the
published tree (`README.md` and `evidence/l5_surprise_synthesis.md`), so it runs
where it ships and resolves either layout.

WHAT THIS DOES NOT DO. It does not score anything, and the sixteen are not a
surprise corpus. Measured against the corpus format, most of them cannot be
entries at all: four are about the collection pipeline, three about the fault
instrument, three are relations between two endpoints over time with no single
subject property, and four are a false positive, a clear-rate, a family shift
and an ABSENCE of firing. Writing entries for those means inventing subjects,
windows and predicates -- the widened corpus the shipped corpus's own header
refuses. And the observation store that could have scored the two expressible
ones did not survive the alpha. So the figure is held against the RECORD, which
is what the record can support.
"""

import pathlib
import re

import pytest

HERE = pathlib.Path(__file__).resolve()


def _first(*candidates: pathlib.Path) -> pathlib.Path:
    """The published layout first, then the one this is maintained in."""
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise AssertionError(
        f"none of {[str(c) for c in candidates]} is in this tree; the figure "
        f"cannot be derived, and a skip here would read as coverage")


SYNTHESIS = _first(HERE.parents[1] / "evidence" / "l5_surprise_synthesis.md",
                   HERE.parents[2] / "docs" / "partner_materials"
                   / "l5_surprise_synthesis.md")
README = _first(HERE.parents[1] / "README.md",
                HERE.parents[2] / "docs" / "publication" / "README-merged.md")

#: Where the alpha window ends and the post-alpha replay arc begins. The README
#: speaks about the ALPHA; counting the whole file would quote 22.
POST_ALPHA = "## Cluster E"


@pytest.fixture(scope="module")
def alpha_entries():
    text = SYNTHESIS.read_text(encoding="utf-8")
    assert POST_ALPHA in text, (
        f"{SYNTHESIS.name} no longer marks where the alpha ends, so the count "
        f"below would take in the replay arc")
    alpha = text.split(POST_ALPHA)[0]
    return re.findall(r"^\*\*Surprise #(\d+)", alpha, re.MULTILINE)


class TestTheCountComesFromTheDocument:

    def test_the_alpha_window_holds_sixteen(self, alpha_entries):
        assert len(alpha_entries) == 16, (
            f"the synthesis lists {len(alpha_entries)} surprises before "
            f"{POST_ALPHA!r}; the README says sixteen")

    def test_they_are_distinct(self, alpha_entries):
        """A repeated heading would inflate the count while reading fine."""
        assert len(set(alpha_entries)) == len(alpha_entries)

    def test_the_document_states_the_detector_figure_itself(self):
        """The unfavourable half is the one a summary is tempted to soften, so
        it is asserted to be present in the source in the source's own words."""
        text = SYNTHESIS.read_text(encoding="utf-8")
        assert re.search(r"machine-surfaced \*\*0 of the 16\*\*", text), (
            "the synthesis no longer states the detector figure, so the "
            "README's half of it rests on nothing")


class TestTheReadmeAgreesWithIt:

    def test_the_readme_quotes_the_same_denominator(self, alpha_entries):
        text = README.read_text(encoding="utf-8")
        assert f"`0 of {len(alpha_entries)}`" in text, (
            f"the README does not carry `0 of {len(alpha_entries)}`, which is "
            f"the figure the record supports")

    def test_the_readme_keeps_both_senses(self):
        """The two never travel apart, because one is favourable and the other
        is not."""
        text = README.read_text(encoding="utf-8")
        window = text[text.index("Scoring this engine against things"):]
        assert "foresight" in window and "detector" in window
        assert "Both are" in window

    def test_the_readme_says_why_the_detector_column_reads_that_way(self):
        """Without it the figure invites the wrong reading -- that the engine
        was insensitive, rather than that the subjects were not in the model."""
        text = README.read_text(encoding="utf-8")
        window = text[text.index("Scoring this engine against things"):]
        assert "REACH" in window or "reach" in window
        assert "subject is not in the model" in window
