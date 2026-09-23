"""The two documents a consumer pins against, held to each other.

`COMPATIBILITY.md` is the document a version pin points at. Two things
in it had gone stale in the same way -- corrected once, in the changelog, and
left standing here:

  - It named one reserved version number and PREDICTED the next breaking
    release from it. That was an inference from measured numbers, the release
    that needed the number found it false at the upload, and the changelog
    dropped the prediction while this file kept it. The version it named has
    never existed and never can.
  - It told a reader that a `<0.2` ceiling does what they intend. Six
    consumers of this engine hold that ceiling; it stops at 0.1.18 and does
    not resolve the 0.2 series at all, so every one of them sees no release
    made since. The changelog says so in as many words. This file said the
    opposite.

Both are the same defect the project already names -- a second copy of a
vocabulary drifting from the first -- and this file is what a second copy needs
if it is going to exist. The fix removed the copy and left a pointer; these
tests stop a new one arriving.

The sub-envelope half is the same shape with a happier ending. The schema has
declared `simulation` and `plan` for two releases while the prose enumerated
six disciplines and stopped, so `rollout` and `plan` -- two supported verbs --
returned payloads a reader could find no policy for. An outside review read
that gap exactly as it reads and asked for the whole twin package to be marked
experimental. The schema was right; only the sentence was short.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

#: The envelope's own four legs plus its meta. Everything else at the top
#: level of the schema is a discipline mounting its report.
ENVELOPE_KEYS = frozenset({"checked", "findings", "not_checked", "questions", "meta"})


def _published(name: str) -> pathlib.Path:
    """A file that ships at the tree root, from either tree."""
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / name,
                      here.parents[2] / "docs" / "publication" / "engine-changelog" / name):
        if candidate.is_file():
            return candidate
    raise AssertionError(f"{name} not found in this tree")


def _schema() -> dict:
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / "schema" / "envelope.schema.json",
                      here.parents[2] / "detection" / "schema" / "envelope.schema.json"):
        if candidate.is_file():
            return json.loads(candidate.read_text(encoding="utf-8"))
    raise AssertionError("no envelope schema found in this tree")


def _compatibility() -> str:
    return _published("COMPATIBILITY.md").read_text(encoding="utf-8")


def _changelog() -> str:
    return _published("CHANGELOG.md").read_text(encoding="utf-8")


def _released_versions() -> set:
    """Every version the changelog carries a dated section for."""
    return set(re.findall(r"^## \[(\d+\.\d+\.\d+)\]", _changelog(), re.MULTILINE))


def _versions_named(text: str) -> set:
    return set(re.findall(r"(?<![\w.])(\d+\.\d+\.\d+)(?![\w.])", text))


class TestThePolicyNamesNoVersionThatDoesNotExist:

    def test_the_changelog_parse_found_releases(self):
        """Guards the guard. An empty set would make every version legal."""
        assert len(_released_versions()) >= 10, sorted(_released_versions())

    def test_the_policy_names_some_versions_to_check(self):
        assert len(_versions_named(_compatibility())) >= 2

    def test_every_version_it_names_has_a_changelog_section(self):
        """The prediction that was wrong named a version with no section, and
        could not have had one: the number is permanently unavailable on the
        index. Anything this document names must be something a reader can
        actually go and read about."""
        unknown = _versions_named(_compatibility()) - _released_versions()
        assert unknown == set(), (
            f"the policy document names versions the changelog has no section "
            f"for: {sorted(unknown)}")


class TestTheCeilingAdviceMatchesTheChangelogs:

    def test_the_changelog_states_a_ceiling_to_compare_against(self):
        assert "<0.3" in _changelog()

    def test_the_policy_recommends_the_same_ceiling(self):
        assert "<0.3" in _compatibility(), (
            "the policy document names no current ceiling, so a consumer "
            "reading it has nothing to move their pin to")

    def test_it_does_not_leave_the_old_ceiling_unqualified(self):
        """Two-sided against the fix, not against the wording. `<0.2` may be
        mentioned -- it has to be, six consumers hold it -- but not in a
        paragraph that never names the one that works."""
        for block in _compatibility().split("\n\n"):
            if "<0.2" in block:
                assert "<0.3" in block or "not" in block.lower(), block


class TestEveryDisciplineTheSchemaDeclaresIsNamedInThePolicy:

    def test_the_schema_declares_disciplines_to_look_for(self):
        payload = set(_schema()["properties"]) - ENVELOPE_KEYS
        assert len(payload) >= 6, sorted(payload)

    def test_the_policy_names_each_of_them(self):
        """The two that were missing are the two a consumer reaches through a
        supported verb. Deriving the list from the schema rather than pinning
        it means a NINTH discipline cannot ship undocumented either."""
        payload = set(_schema()["properties"]) - ENVELOPE_KEYS
        prose = _compatibility()
        missing = sorted(key for key in payload if f"`{key}`" not in prose)
        assert missing == [], (
            f"the schema declares these payload keys and the policy document "
            f"names none of them: {missing}")
