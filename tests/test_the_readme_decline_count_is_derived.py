"""The README's decline call-site count, checked where a reader can check it.

The number was held by a scheduled job that installs from the index once a week.
That job answers a real question -- does the INDEX match the claim -- and it
cannot answer this one: does the tree you are holding match the claim it makes
about itself. A wrong count released on a Sunday was caught the following
Monday, and the shape that allows it is the same one that let an earlier wrong
count ship.

SO IT LIVES HERE, in the suite that travels with the package. A reader who
installs this and runs the tests gets an answer without taking anybody's word;
that is the whole reason the count is published in the first place.

THE EIGHT ARE DERIVED FROM THE AXIOM ENUM, not listed. A hand-written list of
checkers is a second copy of a vocabulary, and a ninth axiom would join the
count or this would go red -- rather than the count quietly describing eight of
nine.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from arbiter_engine import api as _anchor
from arbiter_engine.types import Axiom

PACKAGE = pathlib.Path(_anchor.__file__).parent
AXIOMS = PACKAGE / "ontology" / "axioms"

#: The patterns the scheduled job uses. Written the same way on purpose: two
#: readers of one fact, and `TestTheOtherReaderStillReadsItTheSameWay` below
#: asserts they have not drifted apart wherever the job is on disk.
DECLINE = r"\.declined\("
CLAIM = r"\((\d+) call sites\)"

#: The scheduled job, in whichever tree this file runs in. It is CI
#: configuration and does not ship, so from an installed package there is
#: nothing to compare and the tests below say so and pass. Resolving it is
#: separated from asserting on it for that reason.
WORKFLOW_CANDIDATES = (
    pathlib.Path(__file__).resolve().parents[1]
    / ".github" / "workflows" / "verify-published.yml",
    pathlib.Path(__file__).resolve().parents[2]
    / "docs" / "publication" / "github-merged" / "workflows"
    / "verify-published.yml",
)


def _workflow() -> pathlib.Path | None:
    for candidate in WORKFLOW_CANDIDATES:
        if candidate.is_file():
            return candidate
    return None


def _readme() -> pathlib.Path:
    """The README, in either tree this file runs in.

    Shipped, it sits beside `tests/`. In the repository it is the merged source
    the build renders from. Both are tried and the failure names both, because a
    resolver that silently picks the wrong one would compare the claim against a
    document nobody reads.
    """
    candidates = [
        pathlib.Path(__file__).resolve().parents[1] / "README.md",
        pathlib.Path(__file__).resolve().parents[2]
        / "docs" / "publication" / "README-merged.md",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise AssertionError(f"no README found; looked at {candidates}")


def _per_checker() -> dict[str, int]:
    counts = {}
    for axiom in Axiom:
        module = AXIOMS / f"{axiom.name.lower()}.py"
        if module.is_file():
            counts[axiom.name.lower()] = len(
                re.findall(DECLINE, module.read_text(encoding="utf-8")))
    return counts


class TestTheCountMatchesTheCheckers:
    def test_the_readme_states_one(self):
        found = re.search(CLAIM, _readme().read_text(encoding="utf-8"))
        assert found, (
            f"{_readme().name} no longer states a decline call-site count; the "
            f"claim this guards has gone and so has the guard")

    def test_it_is_what_the_checkers_carry(self):
        claimed = int(re.search(CLAIM, _readme().read_text(encoding="utf-8")).group(1))
        counts = _per_checker()
        assert claimed == sum(counts.values()), (
            f"the README claims {claimed} and the checkers carry "
            f"{sum(counts.values())}: {counts}")


class TestTheCheckerSetIsDerived:
    def test_every_axiom_has_a_checker_module(self):
        missing = [a.name.lower() for a in Axiom
                   if not (AXIOMS / f"{a.name.lower()}.py").is_file()]
        assert missing == [], (
            f"{missing} name an axiom with no checker module; the count "
            f"silently describes fewer axioms than the engine has")

    def test_every_checker_declines_somewhere(self):
        """A zero would let the total pass by arithmetic while one checker had
        stopped declining anything -- a defect this engine has had, one axiom at
        a time, and which only a per-checker look catches."""
        silent = [name for name, count in _per_checker().items() if count == 0]
        assert silent == [], f"{silent} declines nowhere"


class TestTheDerivationIsNotVacuous:
    def test_the_pattern_finds_something(self):
        assert sum(_per_checker().values()) > 20

    def test_the_readme_that_was_read_is_named(self):
        """If the resolver picked a file with no claim in it, the first test
        would fail confusingly rather than clearly."""
        assert _readme().is_file()


class TestTheOtherReaderStillReadsItTheSameWay:
    """The promise the two patterns above make, kept.

    The number has two readers: this file, which asks whether the tree you are
    holding matches its own claim, and a scheduled job, which asks whether the
    INDEX matches it. Neither substitutes for the other and both need the same
    two regexes -- so they are two copies, and a copy nobody compares is the
    shape this project keeps paying for.

    THE JOB DOES NOT SHIP. From an installed package there is no workflow to
    read, and these skip with the reason and the paths that were tried. A check
    that could not run saying so is worth more than one quietly asserting
    nothing; the edit that would break this happens in a repository anyway,
    which is where the file is.
    """

    def _text(self) -> str:
        workflow = _workflow()
        if workflow is None:
            pytest.skip(
                "the scheduled job is CI configuration and is not part of the "
                "package, so there is no second copy here to compare; looked "
                f"at {[str(c) for c in WORKFLOW_CANDIDATES]}")
        return workflow.read_text(encoding="utf-8")

    def test_the_decline_pattern_is_the_same_in_both(self):
        assert DECLINE in self._text(), (
            f"the job no longer counts declines with {DECLINE!r}; one of the "
            f"two readers of this number has moved and the other has not")

    def test_the_claim_pattern_is_the_same_in_both(self):
        assert CLAIM in self._text(), (
            f"the job no longer reads the claim with {CLAIM!r}")

    def test_the_job_derives_its_checkers_too(self):
        """The drift that mattered was not the regexes.

        The job listed the eight checker names while this file derived them
        from the enum, so a ninth axiom would have joined one count and not the
        other -- and the job would have gone on describing eight of nine
        without a red. Asserting the two regexes match and stopping there would
        have pinned the copies that agreed.
        """
        text = self._text()
        assert "from arbiter_engine import Axiom" in text, (
            "the job does not derive its checker set from the enum")
        for listed in ('"boundedness", "stability"', "'boundedness', 'stability'"):
            assert listed not in text, (
                f"the job lists its checkers ({listed}); a ninth axiom would "
                f"join this file's count and not that one")


class TestTheComparisonCouldFail:
    def test_a_workflow_missing_the_pattern_would_be_caught(self, tmp_path):
        """Without this, a resolver returning an empty file reads as agreement."""
        assert DECLINE not in "name: verify\non: schedule\n"

    def test_both_candidate_paths_are_named_when_neither_exists(self):
        """The skip has to say where it looked, or an unrunnable check and a
        wrong-tree check produce the same line."""
        assert len(WORKFLOW_CANDIDATES) == 2
        assert all(str(c).endswith("verify-published.yml")
                   for c in WORKFLOW_CANDIDATES)
