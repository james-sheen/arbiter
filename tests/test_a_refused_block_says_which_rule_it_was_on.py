"""A refused `transition:` block names the rule it was declared on.

`model_describe` has reported refused blocks since, under
`model.transitions.refused_blocks`, and that report is the reason this file is
narrow: the fact is already on the wire, and only its address was missing.

Every entry is indexed WITHIN its own rule, so a model with two rules that each
refuse a block reports:

    transition[0] is missing source; a transition without all of.
    transition[0] is missing gain; a transition without all of.

Both say `transition[0]`, because both blocks are the first on their own rule.
Nothing in either entry says which rule that is. On the two-rule model below an
author can still guess from the missing key; on a model with a dozen edges,
several of which forget the same key, the report names a defect and withholds
its location.

WHY THIS IS THE WHOLE FIX. The sibling defect was a refusal that
reached no consumer at all on the `gaps` surface. This one reaches the consumer
and arrives unaddressed. Adding a SECOND report of the same refusal -- under
`dropped_declarations`, which was the first shape considered -- would have put
one fact on two surfaces, and this project has twice watched two records of one
fact disagree. The entry gets an address instead.
"""
from __future__ import annotations

import pathlib
import tempfile

from arbiter_engine import api

TWO_RULES = """
domain:
  id: two_refusals
  name: Two rules, each refusing its own block
  entity_types: [Pump, Header, Tank]
  relationship_types: [feeds, drains]
  indicators:
    Pump:
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 1e9}
    Header:
      - {name: pressure_bar, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 9.5}
    Tank:
      - {name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 99.0}
  relationship_rules:
    - type: feeds
      source_type: Pump
      target_type: Header
      temporal: {propagation_delay_s: 0, time_constant_s: 1,
                 response_model: step}
      transition: {from: speed_rpm, to: pressure_bar, gain: 0.0012}
    - type: drains
      source_type: Header
      target_type: Tank
      temporal: {propagation_delay_s: 0, time_constant_s: 1,
                 response_model: step}
      transition: {from: pressure_bar, to: level_pct, source: datasheet}
"""


def _refused(text):
    path = pathlib.Path(tempfile.mkdtemp()) / "model.yaml"
    path.write_text(text)
    session = api.EngineSession()
    session.load_model(str(path))
    return api.model_describe(session).to_dict()[
        "model"]["transitions"]["refused_blocks"]


class TestThePremise:

    def test_both_blocks_are_refused(self):
        assert len(_refused(TWO_RULES)) == 2

    def test_and_each_still_names_the_key_it_wants(self):
        """The content put there. An address is being added to it,
        not substituted for it."""
        joined = " | ".join(_refused(TWO_RULES))
        assert "source" in joined and "gain" in joined


class TestEachRefusalCarriesItsAddress:

    def test_a_refusal_names_its_rule(self):
        entries = _refused(TWO_RULES)
        assert all("feeds" in e or "drains" in e for e in entries), (
            f"the report is {entries}, and an author with a dozen edges "
            f"cannot tell which one each line is about: every entry is "
            f"indexed within its own rule, so they all read transition[0]")

    def test_and_the_two_refusals_are_told_apart(self):
        entries = _refused(TWO_RULES)
        feeds = [e for e in entries if "feeds" in e]
        drains = [e for e in entries if "drains" in e]
        assert len(feeds) == 1 and len(drains) == 1
        assert "source" in feeds[0], (
            f"the Pump-feeds->Header block omitted `source`; its entry reads "
            f"{feeds[0]!r}")
        assert "gain" in drains[0], (
            f"the Header-drains->Tank block omitted `gain`; its entry reads "
            f"{drains[0]!r}")


class TestAModelThatRefusesNothingReportsNothing:
    """The negative case, so an address cannot be added by making every rule
    report one."""

    def test_a_complete_model_has_an_empty_report(self):
        complete = TWO_RULES.replace(
            "{from: speed_rpm, to: pressure_bar, gain: 0.0012}",
            "{from: speed_rpm, to: pressure_bar, gain: 0.0012, "
            "source: datasheet}",
        ).replace(
            "{from: pressure_bar, to: level_pct, source: datasheet}",
            "{from: pressure_bar, to: level_pct, gain: 0.5, "
            "source: datasheet}",
        )
        assert _refused(complete) == []
