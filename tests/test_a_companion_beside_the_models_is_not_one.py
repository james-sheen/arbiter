"""`is_domain_model` is a filter, and for a long time it filtered nothing.

The loader publishes it so a directory scan does not need exceptions for control
flow, and its docstring says which files it exists to skip: the companions that
ship beside the models. It answered TRUE for any mapping at all -- for
`{"anything": 1}`, for a JSON config, for a shopping list.

WHY THAT SURVIVED. With no `domain:` key the loader falls back to the document
itself, and every field it reads goes through `.get(...)` with a default. So a
document sharing nothing with the model vocabulary parsed into a model with an
empty id, no entity types and no indicators, and nothing raised. The only
companions in front of it were the `*_constraints.yaml` files, whose `domain:`
key IS present and is a string -- refused one line earlier, by a check that
looks like this one and is not.

HOW IT SURFACED. The first companion of a different shape to be shipped beside
the examples -- a surprise corpus, a file whose subject is a model rather than
being one -- was accepted as a model. Two censuses walk that directory. One
subscripted `["domain"]` and raised `KeyError`, which is how it was found. The
other called `load_model` on it, got a model declaring nothing, iterated its
zero entity types and contributed zero offenders: it passed, and it passed
because it was reading a file it should never have opened. A census blind to a
member it should have skipped is one edit from a census blind to a member it
should have read.

WHAT THIS FILE PINS. That the filter refuses a document declaring nothing the
loader reads; that it still accepts every model the engine ships, including a
degenerate one; and -- the part that does not go stale -- that the key set the
refusal turns on is the set `load_domain` actually reads, derived from its
source rather than transcribed beside it.
"""

from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

from arbiter_engine.ontology import domain_loader
from arbiter_engine.ontology.domain_loader import (
    NotADomainModelError, is_domain_model, load_domain)


def _examples_dir() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / "examples",
                      here.parents[2] / "examples",
                      here.parents[2] / "docs" / "publication" / "engine-example"):
        if (candidate / "water_tank.yaml").is_file():
            return candidate
    raise AssertionError("no examples directory found in this tree")


class TestTheFilterRefusesWhatItWasWrittenFor:

    @pytest.mark.parametrize("source", [
        {"anything": 1},
        {"surprises": {"domain": "x", "entries": []}},
        {"family": "electrical", "entity_mappings": {}},
        {},
    ])
    def test_a_document_declaring_nothing_the_loader_reads_is_refused(self, source):
        assert is_domain_model(source) is False
        with pytest.raises(NotADomainModelError):
            load_domain(source)

    def test_the_refusal_names_what_it_looked_at(self):
        """A refusal that does not say what it wanted sends the author to guess.
        The constraints-companion message one line up names its own cause; this
        one has to as well or the two are not the same quality of answer."""
        with pytest.raises(NotADomainModelError) as raised:
            load_domain({"surprises": {"entries": []}})
        message = str(raised.value)
        assert "surprises" in message, "the message does not name what was there"
        assert "entity_types" in message, "nor what it wanted instead"
        assert "is_domain_model" in message, "nor the filter that avoids it"

    def test_the_constraints_companion_is_still_refused_by_its_own_check(self):
        """The older refusal, unchanged. Two companion shapes, two messages:
        one names a `domain:` that is a string, the other names an absent
        vocabulary, and collapsing them would lose which repair applies."""
        with pytest.raises(NotADomainModelError) as raised:
            load_domain({"domain": "some-other-model", "family": "x"})
        assert "constraints companion" in str(raised.value)


class TestTheFilterStillAcceptsEveryModel:

    def test_every_shipped_example_that_is_a_model_still_loads(self):
        models = [p for p in sorted(_examples_dir().glob("*.yaml"))
                  if "surprises" not in p.name]
        assert len(models) >= 5, f"only {len(models)} examples; near vacuous"
        for path in models:
            assert is_domain_model(str(path)) is True, f"{path.name} refused"

    def test_a_degenerate_model_is_still_a_model(self):
        """Declaring indicators and no entity types checks nothing, and is a
        model whose author made a mistake -- not a companion. The refusal must
        not become a validator: `domain:` has never checked its own top level,
        and making it do so here would refuse models that load today."""
        assert is_domain_model({"indicators": {}}) is True
        assert is_domain_model({"domain": {}}) is True

    def test_an_explicit_domain_key_is_taken_at_its_word(self):
        """`domain:` present and a mapping is an author saying what this file
        is. The vocabulary test is for documents that did not say."""
        assert is_domain_model({"domain": {"unknown_field": 1}}) is True


class TestTheKeySetIsDerivedFromTheLoader:
    """The half that does not go stale.

    A filter narrower than the loader turns a real model into a companion, and
    the transcription that causes it looks correct on the day it is written.
    """

    @staticmethod
    def _keys_load_domain_reads() -> set:
        """Every literal `X.get("...")` inside `load_domain`, from its source.

        `domain` itself is excluded: it is the WRAPPER the fallback turns on,
        not a field, and the check this backs only runs when it is absent.
        """
        tree = ast.parse(inspect.getsource(load_domain))
        keys = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in ("domain", "data")
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                keys.add(node.args[0].value)
        keys.discard("domain")
        return keys

    def test_the_declared_set_is_what_the_loader_reads(self):
        read = self._keys_load_domain_reads()
        assert read, "the derivation found nothing; it is broken, not clean"
        declared = set(domain_loader._MODEL_KEYS)
        missing = sorted(read - declared)
        stray = sorted(declared - read)
        assert not missing, (
            f"{missing} are read by load_domain and not in the set the "
            f"companion check turns on, so a model declaring only one of them "
            f"would be refused as a companion")
        assert not stray, (
            f"{stray} are in the set and read by nothing, so a document "
            f"carrying only one of them is accepted as a model and parses to "
            f"an empty one -- the defect this check exists to remove")

    def test_the_derivation_can_fail(self):
        """The guard on the guard. An AST walk that silently matches nothing
        would make the test above pass against any set at all."""
        assert len(self._keys_load_domain_reads()) >= 10
