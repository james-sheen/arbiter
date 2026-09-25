"""Three documents, one subject, and a division that has to be enforced.

`README.md` argues declared against learned. `BRIDGES.md` documents the record
shape and what `source=` does to it. `STANCE.md` says who counts as a producer and
what the engine owes one -- the normative half neither of the others states.

WHY A TEST AND NOT A CONVENTION. The obvious way to write a stance page is to
open it with the declared-versus-learned argument, because that is the natural
first paragraph of anything about this subject. It is also forty-six lines that
already exist on the front page, and **a second copy of a document is the defect
this project files more often than any other** -- a version range copied into a
workflow, a decline set copied into a guide, a measurement copied into prose. Each
was true when written and each drifted. A page whose whole job is to be the one
place a question is answered cannot be allowed to become the second place another
question is answered.

So the assertions below run in BOTH directions: the stance page must carry its own
subject and must NOT carry the others', and the others must keep theirs. A guard
that only checked for presence would pass a stance page that had quietly absorbed
the README's argument, which is precisely the failure it exists to prevent.

WHAT IS NOT PINNED, ON PURPOSE. Not wording, not length, not section order. Those
move when somebody improves the page and a test that objects teaches its reader to
edit the test. What is pinned is the DIVISION OF LABOUR, which is a decision.
"""

from __future__ import annotations

import pathlib
import re

import pytest


def _docs_root() -> pathlib.Path:
    """Wherever this tree keeps the published documents.

    Built and published trees carry them at the root; the tree they are authored
    in keeps them under a publication directory, and the README is under a
    different name there again. Walking rather than counting parents asks the
    question that matters in all three.
    """
    here = pathlib.Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "STANCE.md").is_file():
            return parent
        candidate = parent / "docs" / "publication"
        if (candidate / "STANCE.md").is_file():
            return candidate
    raise AssertionError("no tree above this file carries STANCE.md")


ROOT = _docs_root()


def _read(name: str) -> str:
    """One document, or a skip naming which tree is missing it.

    `BRIDGES.md` and `MODELING.md` are DERIVED at stage time and do not exist in
    the authoring tree, so asserting their presence here would redden a suite for
    running where the file is not built yet. Skipped with the reason, never
    passed silently.

    **THE WALK GOES ALL THE WAY UP, and the first version did not.** It looked in
    two places and skipped otherwise -- so `ROADMAP.md`, which sits one directory
    further out than either, reported *derived at stage time* and the check on it
    never ran. A skip carrying a false reason is worse than a red: it reads as a
    considered exemption. The only files that skip here now are the ones genuinely
    absent from every tree above this one.
    """
    here = pathlib.Path(__file__).resolve()
    for parent in (ROOT, *here.parents):
        candidate = parent / name
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    pytest.skip(f"{name} is not in this tree; it is derived at stage time")


def _readme() -> str:
    """The ENGINE's README, which is not the only file of that name.

    The authoring tree's publication directory holds its own `README.md` -- a
    note about publication drafts -- beside the engine's front page, which lives
    there under a different name until the build renames it. Taking the first
    `README.md` found read the wrong document and failed for the right reason,
    which is how this resolver came to be derived instead of guessed.

    The manifest names the source; in a built or published tree the file is
    already at the root under its final name.
    """
    import json

    for parent in pathlib.Path(__file__).resolve().parents:
        manifest = parent / "docs" / "publication" / "engine-manifest.json"
        if manifest.is_file():
            named = json.loads(manifest.read_text(encoding="utf-8"))[
                "packaging"].get("readme_source")
            if named:
                path = parent.parent / named
                if not path.is_file():
                    path = parent / pathlib.Path(named).name
                if path.is_file():
                    return path.read_text(encoding="utf-8")
    for parent in pathlib.Path(__file__).resolve().parents:
        path = parent / "README.md"
        if path.is_file():
            return path.read_text(encoding="utf-8")
    raise AssertionError("no engine README found in this tree")


STANCE = (ROOT / "STANCE.md").read_text(encoding="utf-8")


class TestTheStancePageCarriesItsOwnSubject:
    """Presence. Each clause is a question the page exists to answer."""

    @pytest.mark.parametrize("subject,pattern", [
        ("what a submission is", r"a submission is"),
        ("what `source=` withdraws", r"`source=`"),
        ("the obligations", r"[Ww]hat the engine owes"),
        ("the refusals", r"does not owe"),
        ("why the engine sets its own aside", r"not_a_producers_submission"),
        ("the seam", r"ingest_forecasts"),
    ])
    def test_the_page_answers(self, subject, pattern):
        assert re.search(pattern, STANCE), (
            f"STANCE.md no longer says anything about {subject}; it is the only "
            f"page that does")

    def test_it_states_the_rule_rather_than_only_the_behaviour(self):
        """`BRIDGES.md` already says what happens. This page has to say what a
        submission IS, or it is a second mechanics guide."""
        assert re.search(r"A submission is a forecast filed as a claim",
                         STANCE), "the definition itself is gone"

    def test_the_obligations_are_enumerated_not_described(self):
        """A list a reader can check off, not a paragraph. Five was the count
        when written; the floor is what matters, not the number."""
        section = STANCE.split("What the engine owes a submission", 1)[1]
        section = section.split("does not owe", 1)[0]
        numbered = re.findall(r"^\d+\. ", section, re.MULTILINE)
        assert len(numbered) >= 4, (
            f"the obligations stopped being an enumerated list ({len(numbered)} "
            f"found); a reader cannot check off a paragraph")


class TestItDoesNotCarryAnotherPagesSubject:
    """Absence, which is the half that stops the drift.

    Each of these is a thing the stance page could plausibly say and must not,
    because another shipped page says it and two copies diverge.
    """

    def test_it_does_not_restate_the_declared_versus_learned_argument(self):
        """The README's section makes this case at length. A stance page opening
        with it would be the second copy, and the one nobody re-reads."""
        offenders = [phrase for phrase in
                     ("network fitted to trajectories",
                      "sampling a learned latent",
                      "dynamics are **declared**")
                     if phrase in STANCE]
        assert not offenders, (
            f"STANCE.md has grown the README's argument: {offenders}. Point at "
            f"it instead -- two copies of one case will diverge, and this page "
            f"is not where a reader looks for it")

    def test_naming_the_other_section_is_a_POINTER_not_a_copy(self):
        """The distinction the check above cannot draw on its own.

        The first version of that assertion listed the README's section TITLE
        among the phrases this page may not contain -- and went red on the
        sentence that points readers at it, which is the behaviour the page is
        supposed to have. A citation names its target; a copy reproduces its
        content. So the title is allowed, and required to sit beside the
        filename, which is what makes it a reference rather than a heading.
        """
        for match in re.finditer(r"Is this a world model", STANCE):
            window = STANCE[max(0, match.start() - 200):match.end() + 200]
            assert "README.md" in window, (
                "STANCE.md uses the README's section title away from any "
                "reference to it, which reads as this page claiming the "
                "subject rather than pointing at it")
        assert not re.search(r"^#+\s*Is this a world model", STANCE,
                             re.MULTILINE), (
            "STANCE.md has taken the README's section as its own heading")

    def test_it_does_not_grow_a_copy_of_the_decline_table(self):
        """`BRIDGES.md` GENERATES its decline index from the enum in the tree
        being staged, precisely so a copy cannot go stale. A hand-typed subset
        here would be the stale copy that derivation exists to prevent."""
        rows = re.findall(r"^\|\s*`[a-z_]+`\s*\|", STANCE, re.MULTILINE)
        assert len(rows) < 3, (
            f"STANCE.md is growing a table of decline reasons ({len(rows)} "
            f"rows); that index is derived in BRIDGES.md and must not be "
            f"transcribed")

    def test_it_says_out_loud_that_it_is_narrow(self):
        """The constraint is load-bearing and the next editor has to meet it.
        A scope stated only in a test is a scope nobody writing prose will see."""
        assert re.search(r"does not restate|deliberately narrow", STANCE), (
            "the page no longer declares its own scope, so nothing in front of "
            "an editor says why the obvious first paragraph is excluded")


class TestTheOtherPagesKeepTheirs:
    """The other direction. Narrowing one page must not empty another."""

    def test_the_readme_still_makes_the_argument_and_points_here(self):
        readme = _readme()
        assert "Is this a world model?" in readme, (
            "the README's section is gone; STANCE.md does not replace it and "
            "deliberately does not contain it")
        assert "STANCE.md" in readme, (
            "the README does not point at the page that answers the question "
            "its own section raises")

    def test_the_bridge_guide_still_documents_the_mechanics(self):
        bridges = _read("BRIDGES.md")
        assert "not_a_producers_submission" in bridges, (
            "the operational half moved out of BRIDGES.md; a bridge author "
            "reading it can no longer act on the decline")

    def test_the_roadmap_no_longer_claims_the_phrase_the_readme_declines(self):
        """The defect this closes: one document headed *A declared world model --
        landed* while the other answered *not in the sense the term now carries*.
        Pinned as the ABSENCE of the retired heading, so it goes red only if the
        claim comes back -- not on every rewrite."""
        roadmap = _read("ROADMAP.md")
        assert "A declared world model" not in roadmap, (
            "the retired heading is back; it points the phrase in the opposite "
            "direction from the README section that declines it")


# THE FRONT-PAGE DOCUMENT TABLE IS CHECKED IN `tests/residual/`, NOT HERE.
#
# The check derives the guide set from the build manifest -- a fact the PACKAGING
# owns -- and the published tree does not carry that file. So in the
# tree this suite actually ships to it could only skip, and it did: two
# assertions went quiet in the 0.2.7 artifact while the suite still read 2780
# passed / 7 skipped. CI caught it by grading the skip SET by name, which is the
# only check that could -- a skip keeps the collected count, so a coverage floor
# cannot see a tier go quiet.
#
# A replacement asserting the OTHER direction here -- every row resolves to a
# file beside the page -- was tried and dropped: in the authoring tree the
# documents are not at the root and two of them do not exist until stage time,
# so it could only have skipped too, one tree over.


class TestThePageAccountsForTheShippedProducer:
    """The page says what a producer is, and the package now ships
    one. A page that described the rule while the shipped example sat outside
    it would be the exact gap this file exists to close, one layer out.
    """

    def _section(self):
        text = STANCE
        start = text.index("## The reference producer")
        return text[start:text.index("\n## ", start + 4)]

    def test_the_page_names_it(self):
        assert "baseline_learner" in self._section()

    def test_the_name_it_gives_is_the_one_that_imports(self):
        """Derived, not transcribed. A page naming a module nobody can import
        is the defect this whole file is about."""
        import importlib

        section = self._section()
        assert "arbiter_engine.producers.baseline_learner" in section
        module = importlib.import_module(
            "arbiter_engine.producers.baseline_learner")
        assert hasattr(module, "forecast_series")

    def test_it_says_the_producer_gets_no_privilege(self):
        """The claim that makes the comparison worth anything."""
        section = self._section().lower()
        assert "privilege" in section or "no special" in section
        assert "reading_history" in section

    def test_it_says_why_a_random_walk_is_not_enough(self):
        section = self._section().lower()
        assert "random walk" in section
        assert "floor" in section
