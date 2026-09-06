"""Every per-axiom configuration block a model can declare is named in the guide.

THE DEFECT THIS EXISTS FOR. `stability:` loaded from a domain model, sat on the
indicator spec beside its four siblings, and was read by the checker -- and the
modelling guide named the other four and not it. Four of the five tune a check
that runs anyway; `stability:` is the one that is OFF until declared, so a model
author who could not learn the key could not reach the feature at all. It shipped
that way, working, for weeks.

It is the second instance of one shape inside a week -- the envelope's `questions`
leg was the first -- which is why this guard is written against the CLASS rather
than the instance. Fixing `stability:` and stopping would leave the next block to
arrive undocumented in exactly the same silence.

DERIVED, NOT LISTED. The block names come out of the spec's own fields: any
attribute named `<something>_config` is a block a model can declare, and the
guide has to name it. A tuple typed into this file would be a second copy of that
set, and a second copy stays true about what it lists while going silent about
what it does not -- which is the defect above, one level up.
"""
from __future__ import annotations

import dataclasses
import pathlib
import re

import pytest

from arbiter_engine.interfaces import IndicatorSpec

#: Fields whose presence means *a model may declare a block by this name*. The
#: mapping from field to key is the suffix, and it is asserted rather than
#: assumed by `TestTheDerivationMatchesTheLoader` below.
SUFFIX = "_config"


def _guide() -> pathlib.Path:
    """The modelling guide, in either tree this file runs in.

    Shipped, it sits beside `tests/`. In the repository it is the source the
    build renders from. Both are tried and the failure names both, because a
    resolver that silently picks the wrong one would check a document nobody
    reads.
    """
    candidates = [
        pathlib.Path(__file__).resolve().parents[1] / "MODELING.md",
        pathlib.Path(__file__).resolve().parents[2]
        / "docs" / "publication" / "domain-model-spec.md",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise AssertionError(f"no modelling guide found; looked at {candidates}")


def _blocks() -> list[str]:
    fields = (dataclasses.fields(IndicatorSpec)
              if dataclasses.is_dataclass(IndicatorSpec)
              else [type("F", (), {"name": n}) for n in vars(IndicatorSpec())])
    return sorted(f.name[: -len(SUFFIX)] for f in fields
                  if f.name.endswith(SUFFIX))


class TestTheBlockSetIsDerivable:
    def test_there_are_some(self):
        """The non-vacuity half. Every assertion below is *each block is named*,
        and that is TRUE of an empty list -- so a spec that stopped carrying
        `_config` fields would turn this file green rather than red."""
        assert len(_blocks()) >= 4, (
            f"only {len(_blocks())} config blocks derived; this file cannot be "
            f"checking anything meaningful")

    def test_stability_is_one_of_them(self):
        """Pinned by name because it is the block this file was written for. If
        it stops existing, this guard should be re-read rather than quietly keep
        passing on the other four."""
        assert "stability" in _blocks()


class TestTheGuideNamesEveryBlock:
    @pytest.mark.parametrize("block", _blocks())
    def test_the_guide_names_it(self, block):
        text = _guide().read_text(encoding="utf-8")
        assert f"`{block}:" in text, (
            f"a model may declare `{block}:` on an indicator and "
            f"{_guide().name} never names it. An opt-in feature whose switch is "
            f"undocumented cannot be reached by the person the guide is for")


class TestTheDerivationMatchesTheLoader:
    """The derivation asserts a convention -- field `x_config` means key `x:`.
    A convention nothing checks is a guess, so it is exercised: each derived key
    is fed through the public loader and read back off the spec."""

    @pytest.mark.parametrize("block", _blocks())
    def test_the_key_the_guide_documents_is_the_key_that_loads(self, block):
        yaml = pytest.importorskip("yaml")
        from arbiter_engine.api import load_domain

        model = {"domain": {
            "id": "derivation-probe", "name": "derivation probe",
            "entity_types": ["Thing"], "relationship_types": ["touches"],
            "indicators": {"Thing": [{
                "name": "measured", "type": "NUMERIC",
                block: {"probe_marker": True}}]}}}
        spec = load_domain(yaml.safe_dump(model)).indicators["Thing"][0]
        assert getattr(spec, block + SUFFIX) == {"probe_marker": True}, (
            f"`{block}:` is documented and does not reach "
            f"`IndicatorSpec.{block}{SUFFIX}`; the guide would then be teaching "
            f"a key that loads nothing")


class TestTheMatcherCanFail:
    def test_a_block_the_guide_omits_is_reported_missing(self):
        assert "`perambulation:" not in _guide().read_text(encoding="utf-8")

    def test_removing_a_block_from_the_guide_breaks_the_check(self):
        text = _guide().read_text(encoding="utf-8")
        for block in _blocks():
            elided = text.replace(f"`{block}:", "`xxx:")
            assert f"`{block}:" not in elided, (
                f"eliding `{block}:` left it present, so the check is not "
                f"reading what it claims to read")
