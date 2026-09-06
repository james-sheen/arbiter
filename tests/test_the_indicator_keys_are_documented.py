"""Every key an indicator may carry is either in the guide or exempt with a reason.

THE SHAPE THIS EXISTS FOR, third instance in a week. The envelope's `questions`
leg shipped named only in the schema. The `stability:` block shipped named
nowhere. Both were found from outside the code, by someone trying to use the
thing. The guard written for the second derived its subject from fields ending
`_config` -- so it caught the shape that had just bitten and not the shape of the
problem, and the relationship vocabulary went on being undocumented while that
test was green.

So this one derives from the loader's own `_KNOWN_INDICATOR_KEYS`: the set that
decides what a model may say. A key added there is documented on the day it lands
or this goes red.

**NOT EVERY KEY SHOULD BE DOCUMENTED, and that is the interesting half.** The
exemptions below are keys the guide would be WRONG to teach -- one because a
reader already wrote it expecting the engine to act on it, and two because the
check that reads them cannot be fed from the supported surface.

`normal` and `bad` were exempt here until 2026-09-06 on the strongest possible
ground: nothing in the package read them. That was a reason to give them a
consumer, not a reason to keep quiet about them, and the exemption is gone
because the silence is. An exemption list with a reason each is
the honest shape; a guard demanding every key be documented would force the guide
to teach keys that do nothing.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from arbiter_engine.ontology.domain_loader import _KNOWN_INDICATOR_KEYS

#: Keys deliberately absent from the guide, each with the reason. Reviewed by
#: reading the reason, not by trusting the list: an entry whose reason has gone
#: stale is a documentation gap wearing an exemption.
UNDOCUMENTED_ON_PURPOSE = {
    "plausible_range":
        "read by a component outside this engine, not by any axiom. The guide "
        "taught it once and a reader wrote it expecting the engine to act on "
        "it; withdrawing it from the guide is what closed that. Teaching it "
        "again reopens it.",
    "transient":
        "read, and not reachable. `_check_transient_timeout` needs a STATE "
        "history and the public `add_observations` casts to float, so no caller "
        "on the supported surface can supply one. It declines "
        "`insufficient_samples` rather than passing silently, which is the "
        "honest behaviour -- but a guide entry would describe a check a reader "
        "cannot run.",
    "timeout":
        "the span for the check above, unreachable for the same reason.",
}


def _guide() -> pathlib.Path:
    """The modelling guide, in either tree this file runs in."""
    candidates = [
        pathlib.Path(__file__).resolve().parents[1] / "MODELING.md",
        pathlib.Path(__file__).resolve().parents[2]
        / "docs" / "publication" / "domain-model-spec.md",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise AssertionError(f"no modelling guide found; looked at {candidates}")


def _names(key: str, text: str) -> bool:
    """Backtick-anchored, and the anchor is the whole point.

    The first version of this matcher looked for `` `key:` `` and `` `key` ``
    and UNDERCOUNTED BY THREE, because the guide writes a block as
    `` `consistency: {agrees_with: [...]}` `` -- so every key that opens a block
    matched neither pattern. The count was nearly published. What follows the key
    may be a colon, a closing backtick, or a space.
    """
    return re.search(rf"`{re.escape(key)}(?=[:`\s])", text) is not None


def _expected() -> list[str]:
    return sorted(_KNOWN_INDICATOR_KEYS - set(UNDOCUMENTED_ON_PURPOSE))


class TestTheKeySetIsDerivable:
    def test_there_are_some(self):
        """Non-vacuity. Every assertion below is *each key is named*, true of an
        empty list, so a loader that stopped publishing its key set would turn
        this file green rather than red."""
        assert len(_KNOWN_INDICATOR_KEYS) >= 20
        assert len(_expected()) >= 15

    def test_every_exemption_is_still_a_key(self):
        """An exemption for a key the loader no longer accepts is dead weight
        that hides the next real gap behind a stale reason."""
        stale = set(UNDOCUMENTED_ON_PURPOSE) - _KNOWN_INDICATOR_KEYS
        assert not stale, f"exemptions for keys that no longer exist: {sorted(stale)}"

    def test_the_exemptions_are_a_minority(self):
        """A guard whose exemption list grows to cover the problem has stopped
        being a guard."""
        assert len(UNDOCUMENTED_ON_PURPOSE) * 3 < len(_KNOWN_INDICATOR_KEYS)

    def test_every_exemption_carries_a_reason(self):
        for key, reason in UNDOCUMENTED_ON_PURPOSE.items():
            assert len(reason) > 60, f"{key}'s exemption is asserted, not argued"


class TestTheGuideNamesEveryKeyItShould:
    @pytest.mark.parametrize("key", _expected())
    def test_the_guide_names_it(self, key):
        assert _names(key, _guide().read_text(encoding="utf-8")), (
            f"a model may declare `{key}:` on an indicator and "
            f"{_guide().name} never names it. Either document it, or add it to "
            f"UNDOCUMENTED_ON_PURPOSE with the reason it should not be taught")

    @pytest.mark.parametrize("key", sorted(UNDOCUMENTED_ON_PURPOSE))
    def test_an_exempt_key_is_actually_absent(self, key):
        """The other direction. A key documented AND exempt means one of the two
        is wrong, and the exemption is the half that stops being read."""
        assert not _names(key, _guide().read_text(encoding="utf-8")), (
            f"`{key}` is exempt from documentation and the guide names it "
            f"anyway; remove the exemption or remove the prose")


class TestTheMatcherCanFail:
    def test_a_key_the_guide_omits_is_reported_missing(self):
        assert not _names("perambulation", _guide().read_text(encoding="utf-8"))

    def test_removing_a_key_from_the_guide_breaks_the_check(self):
        text = _guide().read_text(encoding="utf-8")
        for key in _expected():
            elided = re.sub(rf"`{re.escape(key)}(?=[:`\s])", "`xxx", text)
            assert not _names(key, elided), (
                f"eliding `{key}` left the check passing, so it is not reading "
                f"what it claims to read")

    def test_a_key_opening_a_block_is_found(self):
        """The regression for the matcher's own defect, pinned by example."""
        assert _names("consistency", "declare `consistency: {agrees_with: [x]}` on it")
        assert _names("window", "the indicator's `window:` is the lever")
        assert _names("role", "two of them read a declared `role` rather than guessing")
