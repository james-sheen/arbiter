"""An unobserved output side became a finding ABOUT THE SYSTEM.

The balance summed each declared output property and treated an absent one as
zero. Absent is not a measurement of zero, so a conservation block naming a
property the model does not supply produced `conservation_violation` at HIGH
severity with a 100% deficit -- while the fault was a property name.

Worse than a missed detection. Silence costs a finding you should have had;
this costs an investigation you should never have started, and it spends the
credibility of every true finding beside it.

Found by probing which obligations the engine actually guards, after an outside
method document asked the question. The remedy is the MIRROR of the zero-input
exit that already lives in this checker: a deficit ratio has no value against a
zero total, and a deficit has no value against an output side nobody observed.

Deliberately NARROW. Total absence is certain and declines. PARTIAL absence does
not, because it cannot be told from a legitimately sparse channel -- an overflow
that runs rarely has no readings in most windows and is not a modelling error.
That case names the properties in the finding's `reason`, which is the only
free-text field the envelope serialises.
"""
from __future__ import annotations

import pathlib
import tempfile
import textwrap

import pytest

from arbiter_engine.api import EngineSession, check

HEAD = "domain:\n  id: p\n  name: P\n  entity_types: [Unit]\n  indicators:\n"


def _run(output_properties, fed):
    body = f"""
    Unit:
      - name: inflow
        type: NUMERIC
        axioms: [CONSERVATION]
        conservation:
          input_property: inflow
          output_properties: [{', '.join(output_properties)}]
      - name: outflow
        type: NUMERIC
        axioms: []
      - name: overflow
        type: NUMERIC
        axioms: []
    """
    path = pathlib.Path(tempfile.mktemp(suffix=".yaml"))
    path.write_text(HEAD + textwrap.indent(textwrap.dedent(body), "    "))
    session = EngineSession()
    session.load_model(str(path))
    session.add_entity("u", "Unit", fed)
    for prop, value in fed.items():
        session.add_observations("u", prop, [value] * 40, interval_seconds=10)
    return check(session).to_dict()


class TestTheDefect:
    def test_a_typod_output_property_declines_rather_than_finding_a_violation(self):
        p = _run(["outfow"], {"inflow": 50.0, "outflow": 50.0})
        assert not p["findings"], (
            "a property name the model does not supply produced a finding about "
            f"the system: {[f['reason'] for f in p['findings']]}")
        assert [d["reason"] for d in p["not_checked"]] == ["missing_property"]

    def test_the_decline_names_the_property_and_points_at_the_block(self):
        d = _run(["outfow"], {"inflow": 50.0, "outflow": 50.0})["not_checked"][0]
        assert "outfow" in d["detail"]
        assert "property names" in d["detail"]


class TestTheNegativeControls:
    """A fix that suppresses real findings has replaced one defect with a worse one."""

    def test_a_balanced_model_stays_clean(self):
        p = _run(["outflow"], {"inflow": 50.0, "outflow": 50.0})
        assert not p["findings"] and not p["not_checked"]

    def test_a_genuine_imbalance_still_fires(self):
        p = _run(["outflow"], {"inflow": 50.0, "outflow": 10.0})
        assert [f["problem_type"] for f in p["findings"]] == [
            "conservation_violation:inflow"]
        assert not p["not_checked"]

    def test_a_genuine_imbalance_is_still_high_severity(self):
        assert _run(["outflow"], {"inflow": 50.0, "outflow": 10.0}
                    )["findings"][0]["severity"] == "high"


class TestPartialAbsenceIsNotSuppressed:
    """The narrowness is the design, so it is pinned rather than assumed."""

    def test_a_partly_observed_output_side_still_produces_the_finding(self):
        p = _run(["outflow", "overflow"], {"inflow": 50.0, "outflow": 10.0})
        assert [f["problem_type"] for f in p["findings"]] == [
            "conservation_violation:inflow"]

    def test_the_finding_names_what_contributed_nothing(self):
        # In `reason`, because the envelope serialises five keys per finding and
        # `evidence` is not one of them. A signal a consumer cannot read is not
        # a signal -- this pin exists because the first attempt put it there.
        reason = _run(["outflow", "overflow"],
                      {"inflow": 50.0, "outflow": 10.0})["findings"][0]["reason"]
        assert "overflow" in reason and "unmeasured" in reason

    def test_a_fully_observed_output_side_carries_no_such_clause(self):
        reason = _run(["outflow"], {"inflow": 50.0, "outflow": 10.0}
                      )["findings"][0]["reason"]
        assert "unmeasured" not in reason
