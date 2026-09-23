"""The newest dated section says whether a reader can install it.

`## [0.2.5] — 2026-09-20` was formatted exactly like every released
section above it -- bracketed version, em-dash, date -- and no `v0.2.5` tag was
ever cut and no artifact was ever uploaded. Four surfaces disagreed at once:
PyPI served 0.2.4, the newest tag named 0.2.4, this file announced 0.2.5, and
`pyproject.toml` read 0.2.6.dev0.

WHY IT MATTERED MORE THAN A STALE NUMBER. The 0.2.5 section opens by addressing
a 0.2.4 user and telling them the simulation surface they have is wrong in ways
their envelope cannot show them. 0.2.4 is what PyPI serves. The one section
written to reach those readers was the one they could not get.

AN OUTSIDE REPORT FOUND IT, not a check here. It cloned the repository, ran
`git describe`, and recorded the gap between what this file says shipped and
what a reader can install -- neutrally, as a fact about the snapshot, in a table
of facts about the snapshot.

THIS IS A PIN, and it says so rather than pretending to derive. Whether a
version exists is a question about a tag and an index, and neither is readable
from inside the suite: a lane that fetches with depth one has no tags at all, a
gotcha this project has already paid for once. So the marker is held in place,
and the two conditions that should end it are made to fail loudly instead of
rotting:

  - The release gets cut. Then the marker and this file are removed together, as
    one step of the release, and the section becomes true as written.
  - A LATER version ships first. Then the newest dated section is no longer this
    one, the second assertion fires, and somebody has to decide what the marker
    on a section now buried in the middle of the file is still claiming.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from arbiter_engine import api as _anchor

#: Any dated release heading. `[Unreleased]` deliberately does not match -- it
#: carries no date and makes no claim about being installable.
DATED = re.compile(r"^## \[(\d+\.\d+\.\d+)\][^\n]*\n", re.MULTILINE)

MARKER = "**PREPARED, NOT PUBLISHED.**"

#: The section the marker belongs to today. Written down because this is a pin.
PREPARED = "0.2.5"


def _changelog() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / "CHANGELOG.md",
                      here.parents[2] / "docs" / "publication"
                      / "engine-changelog" / "CHANGELOG.md"):
        if candidate.is_file():
            return candidate
    pytest.skip("no CHANGELOG.md in this tree, so there is no section to hold")


def _sections() -> list:
    """Every dated section, newest first, as (version, body)."""
    text = _changelog().read_text(encoding="utf-8")
    found = list(DATED.finditer(text))
    return [(m.group(1), text[m.end():(found[i + 1].start()
                                       if i + 1 < len(found) else len(text))])
            for i, m in enumerate(found)]


class TestASectionSaysWhetherYouCanInstallIt:

    def test_the_prepared_section_carries_the_marker(self):
        bodies = dict(_sections())
        assert PREPARED in bodies, (
            f"no {PREPARED} section in the changelog; if it was released and "
            f"renumbered, this pin goes with it")
        assert MARKER in bodies[PREPARED], (
            f"the {PREPARED} section no longer says it was never published. "
            f"Remove this test in the same commit that cuts the release, not "
            f"before -- the marker is the only thing telling a reader that the "
            f"date above it is not a date they can install")

    def test_it_is_still_the_newest_dated_section(self):
        """The trigger. A later release shipping while this marker stands means
        the marker is claiming something about a section nobody reads first."""
        newest = _sections()[0][0]
        assert newest == PREPARED, (
            f"{newest} now sits above {PREPARED}, which still carries "
            f"{MARKER!r}. Decide what that marker means now and either remove "
            f"it or move it")

    def test_no_released_section_carries_it(self):
        """Two-sided. A marker appearing on sections that DID ship would make
        it decoration, and decoration is what a reader learns to skip."""
        wrong = [version for version, body in _sections()
                 if MARKER in body and version != PREPARED]
        assert not wrong, (
            f"these sections claim they were never published: {wrong}")
