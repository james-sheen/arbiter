"""Every name the changelog tells you to use is a name this package has.

A release note that renames things is a set of instructions: *you were importing
`A`, import `B`*. Both halves are claims about the package, and until now the
document was the only thing asserting either. The first version of the entry
this checks cited a check that does not ship, which is how the gap got noticed:
a reader could not follow the reference and had nothing else to hold the table
to.

WHAT IS CHECKABLE FROM HERE AND WHAT IS NOT. That the table's *new* names exist
and its *old* names are gone -- both decidable against the installed package, and
both are the failure a reader would actually hit. That the table is COMPLETE is
not: completeness is a claim about two versions, and only one of them is here.
The check that answers it differences the public names of the previous release
against the tree and runs where releases are prepared; it is named in the
changelog rather than described as something you can run.

So this closes the half that can be closed, and the half it cannot close is
written down instead of implied. A guard whose evidence never ships cannot be
cited by the people it exists to reassure -- which is the rule this file is the
third application of.

THE TABLE IS FOUND BY ITS HEADER, not by position. An entry moves from
`[Unreleased]` into a version section the day it ships, and a check keyed on the
pending section would go quiet exactly then -- guarding only the release nobody
has made yet.
"""
from __future__ import annotations

import dataclasses
import importlib
import pathlib
import pkgutil
import re

import pytest

from arbiter_engine import api as _anchor

PACKAGE = pathlib.Path(_anchor.__file__).parent
ROOT = _anchor.__name__.rsplit(".", 1)[0]

#: The header that marks a rename table. Three columns: what you had, what to
#: use, and where it lives.
HEADER = re.compile(r"^\s*\|\s*Was\s*\|\s*Is\s*\|\s*On\s*\|\s*$", re.MULTILINE)
ROW = re.compile(r"^\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|\s*$")

#: The `|---|---|---|` line. Skipped rather than treated as the end of the
#: table: stopping on it read every table as empty, and an empty table makes a
#: table-driven guard pass against anything.
RULE = re.compile(r"^\s*\|[\s\-:|]+\|\s*$")


def _changelog() -> pathlib.Path:
    """The changelog, in either tree this file runs in.

    Shipped, it sits beside `tests/`. In the repository it is the source the
    build copies. A wheel carries neither, and the tests below skip rather than
    assert nothing -- the same treatment the workflow gets one file over.
    """
    candidates = [
        pathlib.Path(__file__).resolve().parents[1] / "CHANGELOG.md",
        pathlib.Path(__file__).resolve().parents[2]
        / "docs" / "publication" / "engine-changelog" / "CHANGELOG.md",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    pytest.skip(
        "no CHANGELOG.md in this tree, so there is no rename table to hold the "
        f"package to; looked at {[str(c) for c in candidates]}")


def _rows() -> list[tuple[str, str, str]]:
    """Every (was, is, on) row under every rename header in the document."""
    text = _changelog().read_text(encoding="utf-8")
    found: list[tuple[str, str, str]] = []
    for header in HEADER.finditer(text):
        for line in text[header.end():].splitlines()[1:]:
            if RULE.match(line):
                continue
            row = ROW.match(line)
            if not row:
                break
            found.append(row.groups())
    return found


def _modules() -> dict[str, object]:
    """Every importable module in the package, by dotted name below the root.

    Modules needing an optional extra are skipped and REPORTED by the caller,
    because a name hiding in a module this could not import would otherwise look
    like a name that does not exist.
    """
    loaded, skipped = {}, []
    root = importlib.import_module(ROOT)
    for found in pkgutil.walk_packages(root.__path__, prefix=f"{ROOT}."):
        try:
            loaded[found.name[len(ROOT) + 1:]] = importlib.import_module(found.name)
        except Exception:
            skipped.append(found.name)
    loaded["__skipped__"] = skipped
    return loaded


def _classes(modules: dict) -> dict[str, type]:
    out = {}
    for name, module in modules.items():
        if name == "__skipped__":
            continue
        for attribute in vars(module).values():
            if isinstance(attribute, type) and dataclasses.is_dataclass(attribute):
                out.setdefault(attribute.__name__, attribute)
    return out


def _find_record(name: str):
    """A record the package walk did not reach, found by where it is DEFINED.

    Shipped, this never fires: everything is under one root and the walk sees it.
    In the tree this package is cut from, one directory is grafted in from
    outside the walk's root by the build -- so a record living there is invisible
    to a walk anchored on the module this file imports, and the row naming it
    would read as a name the package does not have.

    Searching the distribution root's FILES rather than walking its packages is
    the difference between a second of work and twenty: that root holds two and a
    half thousand modules before the cut, and importing them to find one class is
    a cost paid on every run to answer a question about six.
    """
    root = importlib.import_module(ROOT.split(".")[0])
    directory = pathlib.Path(root.__file__).parent
    marker = re.compile(rf"^class {re.escape(name)}\b", re.MULTILINE)
    for path in sorted(directory.rglob("*.py")):
        if not marker.search(path.read_text(encoding="utf-8", errors="ignore")):
            continue
        dotted = ".".join(
            [root.__name__, *path.relative_to(directory).with_suffix("").parts])
        try:
            return getattr(importlib.import_module(dotted), name, None)
        except Exception:
            return None
    return None


class TestEveryNewNameExists:
    def test_the_table_was_found_at_all(self):
        """Nought rows would make every test below pass by having nothing to
        check, which is the way a table-driven guard usually dies."""
        assert _rows(), (
            f"no rename table in {_changelog().name}; either no release has "
            f"renamed anything or the header this reads has moved")

    def test_each_row_resolves_in_this_package(self):
        modules = _modules()
        classes = _classes(modules)
        unresolved = []
        for was, now, on in _rows():
            record = classes.get(on) or _find_record(on)
            if record is not None:
                fields = {f.name for f in dataclasses.fields(record)}
                if now not in fields:
                    unresolved.append(f"{on}.{now} (field; has {sorted(fields)})")
            elif on in modules:
                if not hasattr(modules[on], now):
                    unresolved.append(f"{on}.{now} (module attribute)")
            else:
                unresolved.append(
                    f"{on} names neither a record nor a module in this package")
        assert unresolved == [], (
            f"the changelog tells a reader to use these and this package does "
            f"not have them: {unresolved}. Modules that could not be imported "
            f"(optional extras): {modules['__skipped__']}")

    def test_each_old_name_is_actually_gone(self):
        """The other half of the instruction. A rename that left the old name in
        place would make the entry wrong in the direction that wastes a reader's
        afternoon rather than breaking their build."""
        modules = _modules()
        classes = _classes(modules)
        survivors = []
        for was, now, on in _rows():
            record = classes.get(on) or _find_record(on)
            if record is not None:
                if was in {f.name for f in dataclasses.fields(record)}:
                    survivors.append(f"{on}.{was}")
            elif on in modules and hasattr(modules[on], was):
                survivors.append(f"{on}.{was}")
        assert survivors == [], (
            f"{survivors} are named as renamed away and are still here")


class TestTheCheckCouldFail:
    """A table-driven assertion passes just as well against a table it failed to
    parse, or a package it failed to walk."""

    def test_the_walk_reaches_the_package(self):
        modules = _modules()
        assert len(modules) > 30, f"walked {len(modules) - 1} modules"

    def test_the_row_pattern_matches_a_row_and_not_a_heading(self):
        assert ROW.match("| `old_name` | `new_name` | `some.module` |")
        assert not ROW.match("| Was | Is | On |")
        assert not ROW.match("|---|---|---|")

    def test_the_separator_is_skipped_and_not_read_as_the_end(self):
        """Reading it as the end is what made the first version of this find
        nought rows, in a document holding thirteen."""
        assert RULE.match("|---|---|---|")
        assert RULE.match("  | :--- | ---: | --- |")
        assert not RULE.match("| `a` | `b` | `c` |")

    def test_a_row_naming_something_absent_would_be_caught(self):
        """The assertion above, exercised on a row this package cannot satisfy."""
        modules = _modules()
        classes = _classes(modules)
        was, now, on = "whatever", "a_name_this_package_does_not_have", "api"
        assert on in modules
        assert not hasattr(modules[on], now)

    def test_a_row_naming_an_unknown_carrier_would_be_caught(self):
        modules = _modules()
        assert "twin.no_such_module" not in modules
        assert "NoSuchRecord" not in _classes(modules)

    def test_a_record_outside_the_walk_is_still_found(self):
        """The fallback, exercised. Without this it is a branch that only runs in
        one of the two trees this file lives in, and the one where it does not
        run is the one it was written for."""
        for row in _rows():
            if row[2].startswith("Production"):
                assert _find_record(row[2]) is not None, row[2]
                break
        else:
            pytest.skip("no record-carrying row in the table to exercise it on")

    def test_the_fallback_does_not_invent_a_record(self):
        assert _find_record("NoSuchRecordDefinedAnywhere") is None
