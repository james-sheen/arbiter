"""A sentence the changelog says it closed is not still in the README.

The 0.2.3 entry for `SqlitePredictionLedger` records that it *closes
the boundary README.md names*, and then quotes the boundary verbatim: *treat
calibration as out of reach until the ledger is persistent*. The class shipped.
The sentence stayed. For four days and two releases the README told every reader
that a feature PyPI was already serving did not exist, and the correction naming
that feature sat in the same repository, one file over.

THE QUOTE IS THE ORACLE, which is what makes this cheap. An entry of this shape
has already done the hard half: it identified the sentence it invalidates and
wrote the sentence down in a form a program can search for. Nothing searched.
Anything of the same shape written from here on is checked on the day it ships,
which is the day somebody can still act on it.

WHAT THE PATTERN REQUIRES, and why each part earns its place. A closing verb
first, so an entry merely MENTIONING the README is not read as invalidating it.
Then the filename, so the target is named rather than inferred. Then an italic
quotation of at least ten characters, because the short italics in this file are
emphasis and headings -- *What is not here* is a heading that is SUPPOSED to
still be there, and a check flagging it would have been noise on its first run.

THE NON-VACUITY TEST IS NOT DECORATION. Every other assertion here quantifies
over whatever the pattern found, and all of them hold of an empty set. Released
sections of this changelog are never tidied, so the 0.2.3 entry is permanent and
the count cannot legitimately fall to zero. If it does, the pattern broke rather
than the corpus, and the guard would go quiet in exactly the way it exists to
prevent.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from arbiter_engine import api as _anchor

#: A closing verb, the filename, then the sentence being closed. The bound on
#: each gap keeps the three parts inside one claim rather than letting a verb on
#: one line pair with a quotation several paragraphs later.
CLOSED = re.compile(
    r"\b(clos(?:es|ed)|remov(?:es|ed)|retir(?:es|ed)|supersed(?:es|ed))\b"
    r"[^.]{0,120}?README\.md[^*]{0,60}?\*([^*]{10,240})\*",
    re.IGNORECASE)


def _flat(text: str) -> str:
    """One space for any run of whitespace.

    Both documents are hard-wrapped, so the quotation spans a newline in the
    source and matches nothing until the wrapping is taken out. The first cut of
    this pattern excluded newlines from the quotation and found zero entries --
    passing, against a corpus containing the defect it was written for.
    """
    return re.sub(r"\s+", " ", text)


def _in_either_tree(shipped: str, source: tuple) -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    candidates = [here.parents[1] / shipped, here.parents[2].joinpath(*source)]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    pytest.skip(f"neither {shipped} nor its source is in this tree; "
                f"looked at {[str(c) for c in candidates]}")


def _changelog() -> pathlib.Path:
    return _in_either_tree(
        "CHANGELOG.md", ("docs", "publication", "engine-changelog", "CHANGELOG.md"))


def _readme() -> pathlib.Path:
    return _in_either_tree(
        "README.md", ("docs", "publication", "README-merged.md"))


def _closures() -> list:
    """Every (verb, quoted sentence) the changelog claims to have closed."""
    text = _flat(_changelog().read_text(encoding="utf-8"))
    return [(m.group(1), _flat(m.group(2)).strip()) for m in CLOSED.finditer(text)]


class TestASentenceTheChangelogClosedIsGone:

    def test_the_readme_no_longer_carries_it(self):
        readme = _flat(_readme().read_text(encoding="utf-8"))
        still_there = [quote for _, quote in _closures() if quote in readme]
        assert not still_there, (
            "the changelog says these README sentences were closed and the "
            f"README still carries them: {still_there}")

    def test_there_is_something_to_check(self):
        """Non-vacuity. The assertion above passes against an empty corpus, and
        an empty corpus is what a broken pattern produces."""
        found = _closures()
        assert found, (
            "no changelog entry names a README sentence it closed; the entry "
            "that motivated this check is in a released section and released "
            "sections are not tidied, so finding none means the pattern stopped "
            "matching rather than the corpus changing")

    def test_a_quotation_is_a_sentence_and_not_a_heading(self):
        """The length floor is the part doing the work, so it is pinned. A
        heading like *What is not here* is italicised the same way and belongs in
        the README; matching it would report the correction as the defect."""
        for _, quote in _closures():
            assert len(quote) >= 10, quote
            assert len(quote.split()) >= 3, (
                f"{quote!r} is too short to be the sentence an entry closed")
