"""The legal files ship together, and their copyright lines do not drift apart.

Both halves read the INSTALLED DISTRIBUTION rather than the working tree, which
is the whole point. The NOTICE's closing paragraph said TRADEMARK.md sat
"alongside this file". That was true in a checkout and false in every wheel:
the file was not among `license-files`, so `pip install` delivered a NOTICE
pointing at nothing, and Apache Section 4(d) then obliged redistributors to
carry the dangling pointer onward. Every check in this repository read the
checkout and passed.

So the predicate here is the artifact. Asking `license-files` whether it
declares the file would be cheaper than the claim and would answer a different
question -- the same shape as the defect.

CI installs the package before running the suite, so the skip never fires
there. It fires for a bare `pytest` in a checkout, where there is no artifact
to ask, and it names the command that closes the window.
"""

from __future__ import annotations

import re
from importlib import metadata

import pytest

DISTRIBUTION = "arbiter-engine"

# A URL is not a path into this distribution. Stripped first, because
# `apache.org` matches a filename as readily as `TRADEMARK.md` does.
_URL = re.compile(r"\w+://\S+")
_FILENAME = re.compile(r"\b[A-Za-z0-9_-]+\.[a-z]{2,4}\b")
_COPYRIGHT = re.compile(r"Copyright\s+(?:\(c\)\s+)?(\d{4}(?:-\d{4})?)\s+([^.\n]+)")


def _files_named_in(text: str) -> set:
    """Filenames the prose claims are present. Derived, so the next file the
    NOTICE points at is covered on the day it is named, not the day someone
    remembers this test exists."""
    return set(_FILENAME.findall(_URL.sub(" ", text)))


def _shipped_legal_files() -> dict:
    """Every file `license-files` put into the installed distribution, by name.

    These land under `.dist-info/licenses/`, which is what "alongside this
    file" means once the distribution is installed rather than cloned.
    """
    try:
        entries = metadata.files(DISTRIBUTION)
    except metadata.PackageNotFoundError:
        pytest.skip(
            f"{DISTRIBUTION} is not installed, so there is no artifact to read. "
            f"`python -m pip install .` and re-run.")
    if entries is None:
        pytest.skip(f"{DISTRIBUTION} records no file list, so nothing can be read")
    return {entry.name: entry for entry in entries
            if ".dist-info/licenses/" in entry.as_posix()}


def test_the_distribution_ships_legal_files_at_all():
    """Non-vacuity. Everything below quantifies over this mapping, and both
    assertions would hold of an empty one."""
    shipped = _shipped_legal_files()
    assert shipped, "the installed distribution carries no license files"
    assert "NOTICE" in shipped, (
        f"NOTICE is not among {sorted(shipped)}; the file the checks below "
        f"read is the one that is missing")


def test_the_notice_names_only_files_that_ship_beside_it():
    """A NOTICE that points at a file is making a claim about what a user
    received, and the NOTICE is the one file Apache 4(d) obliges downstream to
    reproduce. A pointer it cannot resolve travels with it."""
    shipped = _shipped_legal_files()
    named = _files_named_in(shipped["NOTICE"].read_text())
    assert named, (
        "the NOTICE names no file at all. That is a legitimate edit, but it "
        "makes the assertion below vacuous -- delete this test with the "
        "sentence, or it will wear a green it did not earn")
    missing = sorted(name for name in named if name not in shipped)
    assert missing == [], (
        f"the NOTICE names {missing}, which a `pip install` does not deliver. "
        f"Add them to `license-files` in pyproject.toml, or stop naming them")


def test_the_extractor_can_see_a_file_that_is_absent():
    """Before believing the negative above, prove the probe can produce a
    positive. The passing case is one filename that happens to ship, which is
    also what a broken extractor returning nothing looks like."""
    named = _files_named_in("see GOVERNANCE.md, at http://example.org/x")
    assert named == {"GOVERNANCE.md"}, (
        f"the extractor read {named}; it can neither see a named file nor "
        f"ignore a URL, and the check above is decorative")


def test_the_copyright_lines_do_not_disagree():
    """Two records of one fact drift. The holder and the year range are
    asserted against each OTHER rather than against a literal here -- a literal
    would be a third record, and would need editing every January by whoever is
    least likely to be reading this file."""
    shipped = _shipped_legal_files()
    claims = {}
    for name, entry in sorted(shipped.items()):
        for years, holder in _COPYRIGHT.findall(entry.read_text()):
            claims.setdefault((years, holder.strip()), []).append(name)
    assert claims, "no file states a copyright holder"
    assert len(claims) == 1, (
        "the shipped legal files disagree about who holds copyright, or over "
        "what years: " + "; ".join(f"{k!r} in {sorted(v)}" for k, v in claims.items()))
