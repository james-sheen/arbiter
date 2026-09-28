"""The evidence README lists every path its documents cite that this repository
does not hold, and this file is where that list comes from.

The documents in `evidence/` are preserved records of a larger platform, and
their README says so: a component you cannot find here is part of that
platform. An outside review read `tech_brief.md` directly, met the path
domains/trading.yaml as though it shipped, and asked for the specific
references. Eight backticked paths in two documents name files this
repository does not hold. None of them is false: each names a file or an
endpoint of the unpublished platform. The README lists them.

THE LIST IS DERIVED, NOT TRANSCRIBED. A hand-written list is a second copy of
what the documents say, and the copy nobody edits is the one that goes wrong.
So this reads the documents, keeps every backticked path with a file extension
that the tree does not hold, and requires the README's list to be the same
set, both ways. Each of these fails here:

  - a document gaining a citation;
  - the tree gaining a file one of them names;
  - a list edited by hand.

The documents themselves are not touched: they are the record, and the README
is the label on it.

IT SHIPS, BECAUSE THE README SAYS A CHECK EXISTS. The same review found the
sentence and no check in the published tree. The derivation ran only in the
maintainers' own lane, so from here the sentence read as a claim.

It runs where `evidence/` sits beside `tests/`, which is the published layout.
In the repository these files are maintained in, `evidence/` does not exist
until publication assembles it, and "this repository" would mean a different
tree with every one of the eight in it. There the published-tree class skips,
and says why.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence"
#: A backticked token that names a file: a path ending in an extension.
PATH_TOKEN = re.compile(r"`([A-Za-z0-9_./-]+\.(?:ya?ml|py|md|json|sh|toml))`")
#: Where the README's list starts and ends.
HEADING = "They name paths this repository does not hold"
TAIL = "The list is derived"


def unresolved(root: Path, documents) -> dict[str, set[str]]:
    """Per document, every path it cites that `root` does not hold.

    A path resolves when it exists from the root, or when a file of that name
    exists anywhere in the tree: a document citing `water_tank.yaml` bare means
    the example this repository ships, not a missing one.
    """
    names = {p.name for p in root.rglob("*") if ".git" not in p.parts}
    out: dict[str, set[str]] = {}
    for document in documents:
        for path in PATH_TOKEN.findall(document.read_text(encoding="utf-8")):
            if (root / path.lstrip("/")).exists() or Path(path).name in names:
                continue
            out.setdefault(document.name, set()).add(path)
    return out


def listed(readme: str) -> dict[str, set[str]]:
    """The README's list, as `{document: {path, ...}}`."""
    assert HEADING in readme and TAIL in readme, "the README carries no list"
    section = readme.split(HEADING, 1)[1].split(TAIL, 1)[0]
    out: dict[str, set[str]] = {}
    for item in re.split(r"\n\s*-\s+", section)[1:]:
        tokens = re.findall(r"`([^`]+)`", item)
        if tokens:
            out[tokens[0]] = set(tokens[1:])
    return out


def _ticked(path: str) -> str:
    """A citation built at run time. Written out in this source, a backticked
    file name reads as a claim that the file ships, and the check that holds
    every published citation to the tree would be right to refuse it."""
    return f"`{path}`"


def test_the_derivation_finds_what_it_is_for(tmp_path):
    """Before believing an equality, show the derivation can see a gap."""
    (tmp_path / "examples").mkdir()
    (tmp_path / "examples" / "shipped.yaml").write_text("x: 1\n")
    document = tmp_path / "record.md"
    document.write_text(f"See {_ticked('examples/shipped.yaml')}, "
                        f"{_ticked('shipped.yaml')} and "
                        f"{_ticked('platform/missing.yaml')}, and "
                        f"{_ticked('not a path')}.\n")
    assert unresolved(tmp_path, [document]) == {"record.md": {"platform/missing.yaml"}}


def test_the_list_parser_reads_a_wrapped_item():
    readme = (f"- **{HEADING}.** Each is part of the platform:\n"
              f"  - {_ticked('a.md')}: {_ticked('x/one.yaml')},\n"
              f"    {_ticked('two.py')} and {_ticked('/three.json')};\n"
              f"  - {_ticked('b.md')}: {_ticked('four.sh')}.\n\n"
              f"  {TAIL} from the documents.\n")
    assert listed(readme) == {"a.md": {"x/one.yaml", "two.py", "/three.json"},
                              "b.md": {"four.sh"}}


@pytest.mark.skipif(
    not EVIDENCE.is_dir(),
    reason="no evidence/ beside tests/: this is the maintainers' tree, where "
           "evidence/ is assembled at publication and every cited path exists; "
           "the published tree runs this")
class TestThePublishedReadme:

    def _documents(self):
        return sorted(p for p in EVIDENCE.glob("*.md") if p.name != "README.md")

    def test_it_lists_exactly_what_the_documents_cite_and_the_tree_lacks(self):
        derived = unresolved(ROOT, self._documents())
        assert derived, "no document cites a path the tree lacks; nothing is checked"
        assert listed((EVIDENCE / "README.md").read_text(encoding="utf-8")) == derived

    def test_every_listed_document_is_one_of_them(self):
        names = {p.name for p in self._documents()}
        assert set(listed((EVIDENCE / "README.md").read_text(encoding="utf-8"))) <= names

    def test_the_readme_names_this_file(self):
        """The sentence that used to assert a check nobody could find names it."""
        here = Path(__file__).relative_to(ROOT).as_posix()
        assert f"`{here}`" in (EVIDENCE / "README.md").read_text(encoding="utf-8")
