"""The README's supported-name count, checked where a reader can check it.

THE README SAID THIS TEST EXISTED AND IT DID NOT. After the count went stale
once -- `11` published for a release that exported fourteen names -- the fix
paragraph was written: *it is now derived from `arbiter_engine.__all__` by a
test rather than typed, which is the only version of this fix that stays
fixed.* No such test was written. `grep -rn '__all__' tests/` returned nothing,
and the number was correct only because someone had just retyped it.

That is the exact shape the same section warns about, one level up: a
checkable claim with no check behind it. A reader who believed the sentence
had less reason to recount than one who had never read it, which makes the
unbacked claim worse than no claim.

DERIVED FROM `__all__`, NOT FROM A LIST HERE. A second list would be the same
defect wearing a test's clothes -- it would agree with the README and both
could drift from the package together.
"""
from __future__ import annotations

import importlib
import json
import pathlib
import re

import pytest

from arbiter_engine import api as _anchor


def _declared_names() -> list:
    """The SUPPORTED names, from whichever authority this tree carries.

    Two trees, two authorities, and they are not interchangeable. Shipped, the
    root package's `__all__` IS the contract. In the repository the root
    package exports forty-eight names -- everything a detection layer needs
    internally -- and the published fourteen are chosen in the build manifest,
    which is where adding a name is a decision somebody can diff. Reading
    `__all__` here would compare the README against the wrong list and fail a
    lane for being the lane it is.
    """
    manifest = (pathlib.Path(__file__).resolve().parents[2]
                / "docs" / "publication" / "engine-manifest.json")
    if manifest.is_file():
        declared = json.loads(manifest.read_text(encoding="utf-8"))
        return [e["name"] for e in declared["public_api"]["exports"]]
    root = importlib.import_module(_anchor.__package__)
    names = list(getattr(root, "__all__", []))
    if not names:
        pytest.skip(f"no manifest at {manifest} and the root package "
                    f"{_anchor.__package__!r} declares no __all__")
    return names


def _declared_with_modules() -> list:
    """`(name, module_suffix_or_None)` for every supported name.

    The manifest says which module each name is lifted from; the shipped
    package has already done the lifting, so there the suffix is `None`.
    """
    manifest = (pathlib.Path(__file__).resolve().parents[2]
                / "docs" / "publication" / "engine-manifest.json")
    if manifest.is_file():
        declared = json.loads(manifest.read_text(encoding="utf-8"))
        # `from` is EMPTY for a name that is already a submodule of the root
        # (`api`), and absent means the same thing. Both are "look on the
        # root", and treating empty as a path produced a trailing dot.
        return [(e["name"], e.get("from") or None)
                for e in declared["public_api"]["exports"]]
    return [(name, None) for name in _declared_names()]


def _readme() -> pathlib.Path:
    """The README, in either tree this file runs in. See the sibling test."""
    candidates = [
        pathlib.Path(__file__).resolve().parents[1] / "README.md",
        pathlib.Path(__file__).resolve().parents[2]
        / "docs" / "publication" / "README-merged.md",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise AssertionError(f"no README found; looked at {candidates}")


#: Every way the README states the number. Both are bold headings a reader
#: lands on, and the stale one was the copy nobody was looking at.
CLAIMS = (
    r"\*\*(\d+) names\.\*\*",
    r"heading \*\*(\d+) names\*\*",
    r"(\d+) supported\b",
)


class TestTheCountMatchesTheExportedNames:

    def test_the_package_exports_what_the_readme_says(self):
        text = _readme().read_text(encoding="utf-8")
        names = _declared_names()
        exported = len(names)
        found = []
        for pattern in CLAIMS:
            found.extend(int(m) for m in re.findall(pattern, text))
        assert found, (
            "the README states no supported-name count in any form this test "
            f"recognises; patterns tried: {CLAIMS}")
        wrong = sorted({n for n in found if n != exported})
        assert not wrong, (
            f"the README states {wrong} where `arbiter_engine.__all__` exports "
            f"{exported}. Correct the README, or the export list if a name was "
            f"added without being meant as public: {sorted(names)}")

    def test_every_declared_name_actually_resolves(self):
        """A count is not the promise; the names are.

        The list is hand-maintained either way, so a rename can leave it naming
        something that no longer exists -- and the count would still agree with
        the README while the import failed for a reader.

        WHERE a name lives differs by tree, and the check follows it rather
        than asserting one shape. Shipped, all of them sit on the root package
        because the build put them there. In the repository they sit at the
        module paths the manifest names, and the root is a different, larger
        surface -- so resolving them there is what says the manifest could be
        built at all. Both prefixes come from the anchor, never written as a
        literal, because the packaging step rewrites them.
        """
        root_name = _anchor.__package__
        missing = []
        for name, module in _declared_with_modules():
            target = root_name if module is None else f"{root_name}.{module}"
            try:
                holder = importlib.import_module(target)
            except ImportError as exc:                    # pragma: no cover
                missing.append(f"{name} ({target}: {exc})")
                continue
            if not hasattr(holder, name):
                missing.append(f"{name} (not in {target})")
        assert missing == [], (
            "the supported-name list promises names that do not resolve: "
            + ", ".join(missing))


class TestTheCountIsStatedMoreThanOnce:
    """Two copies of one number is the condition that produced the drift, and
    it is deliberate here -- the headings serve different readers. This asserts
    they agree with each other, so the second copy stays a convenience rather
    than becoming a second source of truth."""

    def test_the_copies_agree(self):
        text = _readme().read_text(encoding="utf-8")
        stated = set()
        for pattern in CLAIMS:
            stated.update(int(m) for m in re.findall(pattern, text))
        assert len(stated) <= 1, (
            f"the README states the supported-name count as {sorted(stated)} "
            f"in different places")


# --- the numbers the same paragraph states in WORDS --------------------------

#: Written out because the README writes them out. Only as far as the counts
#: this package can actually reach; a bigger map would be a vocabulary nobody
#: uses.
_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20,
}
_ORDINALS = {
    "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12,
    "thirteenth": 13, "fourteenth": 14, "fifteenth": 15, "sixteenth": 16,
}


def _mcp_server():
    """The MCP shim, in whichever tree this runs in.

    The two trees differ in SHAPE and not only in prefix -- the shim sits beside
    the engine package in one and is folded into it in the other -- so the path
    cannot be built from the anchor the rest of this file uses.

    IT USED TO TRY A TUPLE OF TWO PATHS, and the derivation
    substituted one into the other, so the published copy read

        for path in ("<root>.mcp.server", "<root>.mcp.server"):

    and tried a single module twice while this docstring said it tried both. A
    plain import is correct in both trees for the same reason the tuple was
    not: the substitution reaches an import statement and gets it right. The
    guard that would have caught this had been failing on an unrelated file,
    and a check that is already red cannot report the next thing.
    """
    try:
        from arbiter_engine.mcp import server
    except ImportError:
        return None
    return server


class TestTheProseFormsAreCheckedToo:
    """The three patterns above match DIGITS. The same paragraph states the
    split in words -- *thirteen of those are types and the kernel; the
    fourteenth is a module* -- and a spelled number is exactly as able to drift
    as a written one, with nothing watching it. It was already the last
    uncovered copy of this count when the count test was written.
    """

    def test_the_spelled_split_adds_up_to_the_exported_count(self):
        text = _readme().read_text(encoding="utf-8")
        exported = len(_declared_names())
        match = re.search(
            r"\*\*(\w+) of those are types and the kernel; "
            r"the (\w+) is a module", text, re.IGNORECASE)
        assert match, (
            "the README no longer states the name split in the form this test "
            "recognises; if the sentence was rewritten, update the pattern or "
            "drop this test rather than leaving it matching nothing")
        types_and_kernel = _WORDS[match.group(1).lower()]
        total = _ORDINALS[match.group(2).lower()]
        assert total == exported, (
            f"the README calls the last name the {match.group(2)!r} of "
            f"{exported} exported names")
        assert types_and_kernel + 1 == exported, (
            f"the README says {match.group(1)!r} of the names are types and "
            f"the kernel and one more is a module, which totals "
            f"{types_and_kernel + 1}, against {exported} exported")


class TestTheToolAndVerbCountsAreDerivedToo:
    """`TOOL_SPECS` is the one place that knows how many tools there are, and
    the README's figure was a second copy of it -- the copy that said *five*
    through every release that had more, up to twelve. The shim's own docstring
    said five as well. Three statements of one number, one of which could be
    checked and was not.
    """

    def test_the_readme_tool_count_matches_the_registry(self):
        server = _mcp_server()
        if server is None:                               # pragma: no cover
            pytest.skip("the MCP shim is not importable in this tree")
        text = _readme().read_text(encoding="utf-8")
        # Anchored on the shim's own name. A bare `(\w+) tools?`
        # matched the words "invoking tools" thirty lines earlier and
        # skipped itself with `tool count written as 'the'` -- a test
        # that reported NOT APPLICABLE about a number it was built to
        # check, which reads green.
        match = re.search(r"mcp\.server`?\s*[^\n]*?(\w+) tools\b",
                          text, re.IGNORECASE)
        assert match, "the README states no tool count beside the shim"
        stated = _WORDS.get(match.group(1).lower())
        if stated is None:                               # pragma: no cover
            pytest.skip(f"tool count written as {match.group(1)!r}")
        assert stated == len(server.TOOL_SPECS), (
            f"the README says {match.group(1)!r} tools; TOOL_SPECS registers "
            f"{len(server.TOOL_SPECS)}")

    def test_the_readme_verb_count_matches_the_api_surface(self):
        """A VERB is a tool that is a function on `api`. The other three are
        feeders and are session methods, which is the distinction the sentence
        itself draws -- so it is derived here rather than listed."""
        server = _mcp_server()
        if server is None:                               # pragma: no cover
            pytest.skip("the MCP shim is not importable in this tree")
        verbs = [spec["name"] for spec in server.TOOL_SPECS
                 if callable(getattr(_anchor, spec["name"], None))]
        text = _readme().read_text(encoding="utf-8")
        match = re.search(r"(\w+) verbs\b", text, re.IGNORECASE)
        assert match, "the README states no verb count"
        stated = _WORDS.get(match.group(1).lower())
        if stated is None:                               # pragma: no cover
            pytest.skip(f"verb count written as {match.group(1)!r}")
        assert stated == len(verbs), (
            f"the README says {match.group(1)!r} verbs; `api` carries "
            f"{len(verbs)} of the {len(server.TOOL_SPECS)} registered tools: "
            f"{sorted(verbs)}")
