"""Three envelopes take provisional terms, and every other one keeps the promise.

From the next major release, `simulation`, `plan` and `execution` -- what
`rollout`, `plan` and `file_action` return -- may change in a patch release in
the ways every other envelope keeps for a major one. The terms follow the
ENVELOPE, not the code that fills it. Three things state that, and these tests
hold them to each other:

  - the policy document's section;
  - a marker on each schema definition;
  - the schema's reference structure, which is what keeps the boundary clean.

So a fourth envelope cannot take the terms in one place and not the others. And
no promised envelope can start pointing into a provisional one, which would put
promised content under terms nobody announced for it.
"""

from __future__ import annotations

import json
import pathlib
import re

#: The payload key a verb returns, and the definition that declares it.
PROVISIONAL = {"simulation": "simulation_envelope", "plan": "plan_envelope",
               "execution": "execution_envelope"}

#: Definitions that sit inside the three and nowhere else.
INSIDE = {"simulation_step", "plan_candidate"}

MARKER = "PROVISIONAL TERMS from the next major release"
SECTION = "## Provisional terms: `simulation`, `plan` and `execution`"


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


def _section() -> str:
    text = _published("COMPATIBILITY.md").read_text(encoding="utf-8")
    m = re.search(rf"^{re.escape(SECTION)}$(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert m, "the policy document has no provisional-terms section"
    return m.group(1)


def _refs(node, path, out):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                out.append((path, value.rsplit("/", 1)[-1]))
            _refs(value, f"{path}/{key}", out)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            _refs(value, f"{path}/{i}", out)


class TestTheMarkersAndTheSectionAgree:

    def test_exactly_the_three_definitions_carry_the_marker(self):
        marked = {name for name, d in _schema()["$defs"].items()
                  if MARKER in d.get("$comment", "")}
        assert marked == set(PROVISIONAL.values()), (
            f"marked {sorted(marked)}, while the policy document names "
            f"{sorted(PROVISIONAL.values())}")

    def test_each_marked_definition_is_the_one_its_payload_key_points_at(self):
        schema = _schema()
        for key, name in PROVISIONAL.items():
            refs = []
            _refs(schema["properties"][key], "", refs)
            assert name in {target for _, target in refs}, (key, refs)

    def test_each_marked_definition_says_so_where_a_reader_looks(self):
        schema = _schema()
        for key, name in PROVISIONAL.items():
            definition = schema["$defs"][name]
            assert "provisional" in definition["title"].lower(), name
            assert "PROVISIONAL" in definition["description"], name
            assert "PROVISIONAL" in schema["properties"][key]["description"], key

    def test_the_section_names_each_envelope_and_its_verb(self):
        body = _section()
        for key in PROVISIONAL:
            assert f"`{key}`" in body, key
        for verb in ("rollout", "plan", "file_action"):
            assert f"`{verb}`" in body, verb
        for name in INSIDE:
            assert name in body, name

    def test_the_section_names_what_it_does_not_reach(self):
        """The seam is where a promised envelope carries content one of the
        three produced. Naming it is what keeps the boundary readable."""
        body = _section()
        assert "The terms follow the envelope, not the code that fills it." in body
        for carrier in ("`residuals`", "`case_book`", "`attach_stage`"):
            assert carrier in body, carrier

    def test_the_section_keeps_the_shape_every_reader_relies_on(self):
        body = _section()
        for kept in ("`checked`", "`findings`", "`not_checked`", "`questions`",
                     "`meta.source`", "`imagined_`"):
            assert kept in body, kept


class TestNoPromisedDefinitionPointsIntoAProvisionalOne:

    def test_the_boundary_is_clean(self):
        schema = _schema()
        provisional = set(PROVISIONAL.values()) | INSIDE
        allowed = ({f"/properties/{key}" for key in PROVISIONAL}
                   | {f"/$defs/{name}" for name in provisional})
        refs = []
        _refs(schema, "", refs)
        stray = sorted(path for path, target in refs if target in provisional
                       and not any(path == a or path.startswith(a + "/") for a in allowed))
        assert not stray, (
            f"a promised part of the schema references a provisional definition: "
            f"{stray}. Either that content takes the terms too, and the policy "
            f"document says so, or it gets a promised definition of its own")

    def test_what_sits_inside_the_three_is_reached_only_from_them(self):
        schema = _schema()
        refs = []
        _refs(schema, "", refs)
        for name in INSIDE:
            sources = {path for path, target in refs if target == name}
            assert sources, f"{name} is referenced from nowhere"
            assert all(any(path.startswith(f"/$defs/{d}/") for d in PROVISIONAL.values())
                       for path in sources), (name, sources)
