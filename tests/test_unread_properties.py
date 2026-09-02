"""Properties you send that no indicator reads are named, not judged.

The engine takes three input surfaces. Two already reported what they could not
use -- observations no declared indicator reads, threshold overrides nothing
consults -- and entity properties, the surface most callers feed first, reported
nothing at all.

IT EXISTS BECAUSE A REMOVAL MADE THE GAP VISIBLE. A walk used to judge every
property by the words in its name: a key spelled `*_count` was range-checked
whether the model asked or not. That was removed -- it derived an interpretation
fact from a spelling, and its findings sat outside the denominator, so the
envelope reported problems against cells it never claimed to attempt. The rules
are declarable and now declared. But an author cannot declare a property they do
not know they are sending, so the honest other half is this.

THE LINE IS REPORT, NOT FINDING. Naming a key is a statement about the MODEL and
the author can close it. Judging the value would need a rule, and taking the rule
from the name is the thing that was removed.

BOTH DIRECTIONS ARE PINNED. A report that fires for everything is the same defect
as one that fires for nothing: either way nobody can act on a row.
"""
from __future__ import annotations

import tempfile
import textwrap

import pytest

from arbiter_engine.api import EngineSession, gaps, model_describe

MODEL = """
    domain:
      id: d
      name: D
      entity_types: [U]
      relationship_types: [f]
      indicators:
        U:
          - name: level_pct
            type: NUMERIC
            role: percentage
            axioms: [CONSISTENCY]
    """


def _session(props):
    path = tempfile.mktemp(suffix=".yaml")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(textwrap.dedent(MODEL))
    session = EngineSession()
    session.load_model(path)
    session.add_entity("u0", "U", props)
    return session


def _reported(props):
    return {r["property"]
            for r in model_describe(_session(props)).to_dict()["unread_properties"]}


class TestItNamesWhatNothingReads:
    def test_an_undeclared_numeric_property_is_named(self):
        assert _reported({"level_pct": 50.0, "replica_count": 3}) == {"replica_count"}

    def test_the_three_the_removal_left_behind(self):
        """The concrete population that motivated this. Three real properties
        that no pack declares turned up when the removal was sized; under the
        old walk they were judged silently, and after it they were neither
        judged nor mentioned."""
        assert _reported({"level_pct": 1.0, "replicaCount": 3,
                          "cpuPercent": 90.0}) == {"replicaCount", "cpuPercent"}


class TestItStaysSilentWhenItShould:
    """The half that fails if the report fires for everything."""

    def test_a_declared_property_is_not_named(self):
        assert _reported({"level_pct": 50.0}) == set()

    @pytest.mark.parametrize("prop,value", [
        ("name", "u0"),          # a string: a STATE indicator could read it
        ("healthy", True),       # bool subclasses int and would arrive as one
        ("status", {"n": 1}),    # nested: no declaration surface of its own
    ])
    def test_only_numbers_are_named(self, prop, value):
        assert _reported({"level_pct": 1.0, prop: value}) == set()

    def test_no_model_means_no_report(self):
        assert EngineSession().unread_properties() == []


class TestItReportsRatherThanJudges:
    def test_the_row_carries_no_verdict(self):
        rows = model_describe(
            _session({"level_pct": 1.0, "error_count": -3})
        ).to_dict()["unread_properties"]
        assert len(rows) == 1
        assert set(rows[0]) == {"entity_id", "entity_type", "property", "reason"}
        assert rows[0]["reason"] == "undeclared_property"

    def test_an_impossible_value_is_still_only_named(self):
        """`error_count: -3` would have been a finding under the old walk. It is
        a row here and nothing more -- the difference between reporting a gap in
        the model and asserting a rule the model never declared."""
        from arbiter_engine.api import check
        session = _session({"level_pct": 1.0, "error_count": -3})
        assert not [f for f in check(session).to_dict()["findings"]
                    if "error_count" in f["reason"]]
        assert "error_count" in {
            r["property"]
            for r in model_describe(session).to_dict()["unread_properties"]}


class TestBothToolsCarryIt:
    def test_gaps_reports_it_too(self):
        """Its two siblings are in both tools; a report in one is a report a
        caller has to know to go looking for."""
        session = _session({"level_pct": 1.0, "replica_count": 3})
        assert "unread_properties" in gaps(session).to_dict()
