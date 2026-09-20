"""`model_describe` tells a declared spread of zero from no declared spread.

`transitions.declared[].gain_sigma` reported `0.0` for all three of
these, which are three different claims:

    gain_sigma: 0.002 the author measured it
    gain_sigma: estimate the author asked this engine to propose one
    (absent) nobody said

The spec is explicit that the last two are not the first: *a gain with no
declared spread reports NO interval, rather than an interval of zero width --
a value nobody measured the spread of and a value known to be exact are
different claims, and the second is much the stronger.* The RUNTIME honours
that -- an undeclared spread contributes nothing and no interval appears --
and the report did not. A reader of `model_describe` saw a coupling asserting
perfect certainty about its gain where the model asserts nothing at all.

`estimate` was the worse of the two, because it is the opposite claim: the
author wrote it to say *I do not know this, propose one*, and it came back as
`0.0`. The distinction did survive elsewhere, as `gain_sigma_requested` under
`proposed_transitions.fitted` -- a different block, present only when a fit
succeeded, so on a coupling with too little history to fit, the only thing
the payload said about the request was a zero that means its opposite.
"""
from __future__ import annotations

import pathlib
import tempfile

import pytest

from arbiter_engine import api

MODEL = """
domain:
  id: declared_spread
  name: Three different claims about one gain
  entity_types: [Pump, Tank]
  relationship_types: [feeds]
  indicators:
    Pump:
      - {name: speed_rpm, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 1e9}
    Tank:
      - {name: level_pct, type: NUMERIC, axioms: [BOUNDEDNESS], critical: 1e9}
  relationship_rules:
    - type: feeds
      source_type: Pump
      target_type: Tank
      temporal: {propagation_delay_s: 0, time_constant_s: 1,
                 response_model: step}
      transition: {from: speed_rpm, to: level_pct, gain: 0.02,
                   source: datasheet%(spread)s}
"""


def _declared(spread_clause):
    path = pathlib.Path(tempfile.mkdtemp()) / "model.yaml"
    path.write_text(MODEL % {"spread": spread_clause})
    session = api.EngineSession()
    session.load_model(str(path))
    session.add_entity("pump1", "Pump", {"speed_rpm": 1000.0})
    session.add_entity("tank1", "Tank", {"level_pct": 50.0})
    session.add_relationship("pump1", "feeds", "tank1")
    entries = api.model_describe(session).to_dict()["model"]["transitions"][
        "declared"]
    assert len(entries) == 1, "the premise: one declared coupling"
    return entries[0]


MEASURED = ", gain_sigma: 0.002"
REQUESTED = ", gain_sigma: estimate"
ABSENT = ""


class TestTheThreeClaimsAreThreeReports:

    def test_a_measured_spread_is_the_number(self):
        assert _declared(MEASURED)["gain_sigma"] == pytest.approx(0.002)

    def test_an_undeclared_spread_is_not_a_zero(self):
        entry = _declared(ABSENT)
        assert entry["gain_sigma"] is None, (
            f"nobody declared a spread and the report says "
            f"{entry['gain_sigma']!r}, which is the claim that the gain is "
            f"exact")

    def test_a_requested_spread_is_not_a_zero_either(self):
        entry = _declared(REQUESTED)
        assert entry["gain_sigma"] is None, (
            f"`gain_sigma: estimate` says the author does NOT know this "
            f"number and the report says {entry['gain_sigma']!r}")

    def test_and_the_request_is_visible_on_the_declaration_itself(self):
        """Not only under `proposed_transitions`, which is a different block
        and is empty whenever the fit did not succeed."""
        assert _declared(REQUESTED)["gain_sigma_requested"] is True
        assert _declared(ABSENT)["gain_sigma_requested"] is False
        assert _declared(MEASURED)["gain_sigma_requested"] is False


class TestTheRuntimeIsUnchanged:
    """The report was the only thing wrong. What the engine DOES with each of
    the three is what it always did."""

    def _sigma(self, spread_clause):
        from arbiter_engine.twin.actions import ActionInstance
        path = pathlib.Path(tempfile.mkdtemp()) / "model.yaml"
        path.write_text(MODEL % {"spread": spread_clause} + """
  action_templates:
    - name: throttle_pump
      applies_to: Pump
      parameters_schema:
        speed_rpm: {type: number, entity_property: speed_rpm}
      effect: set
      source: runbook
""")
        session = api.EngineSession()
        session.load_model(str(path))
        session.add_entity("pump1", "Pump", {"speed_rpm": 1000.0})
        session.add_entity("tank1", "Tank", {"level_pct": 50.0})
        session.add_relationship("pump1", "feeds", "tank1")
        simulation = api.rollout(
            session, actions=[ActionInstance(
                "throttle_pump", "pump1", {"speed_rpm": 1500.0}, 0.0)],
            horizon_s=300.0, step_s=60.0).to_dict()["simulation"]
        last = simulation["per_step"][-1]
        return last["sigma"].get("tank1", {}).get("level_pct")

    def test_a_measured_spread_still_reaches_the_value(self):
        assert self._sigma(MEASURED) == pytest.approx(0.002 * 500.0)

    def test_an_undeclared_one_still_reports_no_interval(self):
        assert self._sigma(ABSENT) is None

    def test_a_requested_one_is_still_not_adopted(self):
        """Nothing is adopted until the author writes the number down."""
        assert self._sigma(REQUESTED) is None
