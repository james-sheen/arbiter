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
