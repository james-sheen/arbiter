"""Every input form the README says `load_model()` takes, it takes.

The README said **`load_model()` takes a mapping, not a file**, and
both halves were false. Measured: it accepts a parsed mapping, YAML text AND a
filesystem path, and a bad path raises `FileNotFoundError` rather than being
parsed as YAML -- so paths are genuinely handled, not tolerated. The measurement
the sentence carried alongside, that the parse in front of the load costs about
thirty times the load at a hundred and eighty indicators, was right, and is the
reason anybody wrote the sentence. The contract stated beside it was not.

IT LEFT THE REPOSITORY BEFORE ANYONE HERE CAUGHT IT. An outside comparison of
this engine copied the sentence into its own *before you depend on it* list,
where it contradicted that same document's quick start two sections earlier --
which loads a model from `read_text()`, a string, and works, twice. A false
sentence of ours reached a reader as a false sentence of theirs, and this is the
third time that has happened with a published sentence nobody was checking.

THE FORMS ARE READ OUT OF THE PROSE rather than listed in here, which is the
whole point. An edit naming a fourth form gets it exercised on the day it is
written. An edit naming a form nothing can build FAILS, rather than skipping:
a check that shrugs at a word it does not recognise is how a derived claim stops
being derived while still looking green.
"""
from __future__ import annotations

import pathlib
import re

import pytest
import yaml

from arbiter_engine.api import EngineSession, model_describe

#: The sentence, found by its subject rather than its position.
SENTENCE = re.compile(
    r"\*\*`load_model\(\)`\s+accepts\s+([^*]+?)\*\*", re.IGNORECASE)

#: Every form the sentence is allowed to name, and how to build one. A form
#: appearing in the prose with no entry here is a failure below, not a skip.
BUILDERS = {
    "a parsed mapping": lambda path: yaml.safe_load(path.read_text(encoding="utf-8")),
    "YAML text": lambda path: path.read_text(encoding="utf-8"),
    "a path": lambda path: str(path),
}


def _readme() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / "README.md",
                      here.parents[2] / "docs" / "publication" / "README-merged.md"):
        if candidate.is_file():
            return candidate
    pytest.skip("no README in this tree, so there is no sentence to hold the code to")


def _example() -> pathlib.Path:
    """Whichever copy this tree has; never an absolute path, because this file
    ships and an absolute one names a directory only the author has."""
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / "examples",
                      here.parents[2] / "docs" / "publication" / "engine-example"):
        if candidate.is_dir() and list(candidate.glob("*.yaml")):
            return candidate / "pump_tank_dynamics.yaml"
    raise AssertionError("no examples directory found in this tree")


def _named_forms() -> list:
    """The forms the README's sentence lists, in the order it lists them."""
    match = SENTENCE.search(_readme().read_text(encoding="utf-8"))
    assert match, (
        "the README states no accepted-input list for `load_model()`; the "
        "sentence this check derives from has been reworded or removed")
    listed = re.sub(r"\s+", " ", match.group(1)).strip().rstrip(":")
    return [part.strip() for part in re.split(r",| or ", listed) if part.strip()]


def _loaded(source):
    session = EngineSession()
    session.load_model(source)
    return session


class TestTheReadmeNamesTheFormsLoadModelTakes:

    def test_every_form_the_sentence_names_can_be_built(self):
        """The prose and this table stay in step, and neither one leads."""
        unknown = [form for form in _named_forms() if form not in BUILDERS]
        assert not unknown, (
            f"the README says `load_model()` accepts {unknown}, and this check "
            f"has no way to build one; add a builder rather than narrowing the "
            f"sentence to what the check already covers")

    def test_the_sentence_names_more_than_one_form(self):
        """Non-vacuity. The assertions here quantify over the parsed list, and a
        sentence narrowed to nothing would satisfy all of them."""
        assert len(_named_forms()) >= 2, (
            "the sentence names fewer than two input forms; it was written "
            "because the engine takes several")

    @pytest.mark.parametrize("form", sorted(BUILDERS))
    def test_each_named_form_loads_the_same_model(self, form):
        if form not in _named_forms():
            pytest.skip(f"the README does not name {form!r}")
        example = _example()
        described = model_describe(_loaded(BUILDERS[form](example))).to_dict()
        reference = model_describe(_loaded(BUILDERS["a parsed mapping"](example))).to_dict()
        assert described["checked"] == reference["checked"], (
            f"loading from {form!r} gave a different model from the mapping form")

    def test_a_path_that_does_not_exist_is_not_parsed_as_yaml(self):
        """The half of the old sentence that was closest to true. A path IS
        handled, and the evidence is that a missing one is reported as a missing
        file rather than as a model with no entity types."""
        with pytest.raises(FileNotFoundError):
            _loaded("/no/such/model.yaml")
