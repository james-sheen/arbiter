"""`loss_margin: 0` is a legal declaration, and it was the only silent one.

THE STRICTER THE AUTHOR, THE QUIETER THE ENGINE. A balance of COUNTS -- how
many forecasts were expected against how many arrived, how many units went in
against how many came out -- has no rounding error to allow, so `loss_margin: 0`
is the declaration that says what the author means. Every deficit then cleared
the finding condition and divided by zero computing its confidence, the checker
raised, and a real imbalance surfaced as `checker_error`. A zero allowance could
report nothing at all.

FOUND BY WRITING AN EXAMPLE, not by reading the checker. `margin_book.yaml`
declares the forecaster's expected-against-issued balance at zero because that
is what the balance means, and the first run of it printed a division error
where the finding belonged.

THE CONTROL IS HALF THIS FILE. Asserting that a zero allowance now reports
proves nothing on its own -- an instrument that fires on everything is not a
check -- so the balanced pair has to stay silent, and a non-zero allowance has
to keep producing a confidence that still varies with the size of the deficit.
Flattening every confidence to 1.0 would pass the first test and destroy the
signal the field carries.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from arbiter_engine.api import EngineSession, check
from arbiter_engine.clock import as_of
from arbiter_engine.ontology.axioms.conservation import (
    ConservationChecker,
)

NOW = datetime(2026, 9, 17, 12, 0, 0)


def _model(loss_margin: str) -> str:
    return f"""
domain:
  id: allowance
  name: Zero Allowance
  entity_types: [Batch]
  relationship_types: []
  indicators:
    Batch:
      - name: units_in
        type: NUMERIC
        axioms: [CONSERVATION]
        window: 24h
        flow: in
        conservation:
          input_property: units_in
          output_properties: [units_out]
          loss_margin: {loss_margin}
      - name: units_out
        type: NUMERIC
        axioms: []
        flow: out
"""


def _session(loss_margin: str, out_values):
    session = EngineSession()
    session.load_model(_model(loss_margin))
    session.add_entity("batch1", "Batch",
                       {"units_in": 100.0, "units_out": out_values[-1]})
    session.add_observations("batch1", "units_in", [100.0] * len(out_values))
    session.add_observations("batch1", "units_out", list(out_values))
    return session


def _run(loss_margin: str, out_values):
    with as_of(NOW):
        return check(_session(loss_margin, out_values)).to_dict()


def _problems(loss_margin: str, out_values):
    """The checker's own output.

    THE ENVELOPE SERIALISES FIVE KEYS PER FINDING and neither `confidence` nor
    `evidence` is one of them, so the expression this file exists to pin is not
    reachable from `check`. Asserting into a key the envelope drops is how a
    test quietly becomes `assert True`, which this project has paid for; so the
    published surface is asserted above and the checker is called here.
    """
    with as_of(NOW):
        session = _session(loss_margin, out_values)
        spec, = [i for i in session.model.indicators["Batch"]
                 if i.name == "units_in"]
        checker = ConservationChecker()
        return checker.check(session.entities["batch1"], spec,
                             session.graph, session.history,
                             entities=session.entities)


def _payload(envelope):
    return envelope.get("payload", envelope)


def _conservation(envelope):
    return [f for f in _payload(envelope).get("findings", [])
            if f.get("problem_type", "").startswith("conservation_violation")]


def _errors(envelope):
    blob = str(_payload(envelope))
    return "checker_error" in blob or "division by zero" in blob


class TestAZeroAllowanceReportsTheDeficit:
    def test_the_imbalance_is_a_finding_and_not_an_error(self):
        """The regression itself: 100 in, 90 out, no allowance."""
        envelope = _run("0", [90.0] * 6)
        assert not _errors(envelope), "the checker raised where a finding belonged"
        assert _conservation(envelope), "a zero allowance reported nothing"

    def test_the_confidence_is_full_rather_than_uncomputable(self):
        """Ratio-to-allowance is undefined against zero; the answer it stands
        in for is not -- any deficit is over the whole of it."""
        problem, = _problems("0", [90.0] * 6)
        assert problem.confidence == pytest.approx(1.0)

    def test_the_deficit_it_reports_is_the_real_one(self):
        """Full confidence is not a licence to round the measurement."""
        problem, = _problems("0", [90.0] * 6)
        assert problem.evidence["deficit_ratio"] == pytest.approx(0.10)
        assert problem.evidence["margin"] == 0

    def test_the_published_reason_carries_the_deficit(self):
        """What a consumer actually receives, since evidence does not survive
        serialisation."""
        finding, = _conservation(_run("0", [90.0] * 6))
        assert "10.0% deficit" in finding["reason"]


class TestTheControl:
    """Without these, the file proves only that something fires."""

    def test_a_balanced_pair_stays_silent_at_zero(self):
        envelope = _run("0", [100.0] * 6)
        assert not _conservation(envelope), (
            "a zero allowance fired on a balance with no deficit, so the "
            "assertions above are about an instrument that fires on anything")
        assert not _errors(envelope)

    def test_the_allowance_still_governs_whether_a_finding_appears(self):
        """The allowance is not decoration. It decides the verdict; what it
        never decided was the confidence."""
        assert not _conservation(_run("0.2", [85.0] * 6)), (
            "a 15% deficit fired against a 20% allowance")
        assert _conservation(_run("0.2", [75.0] * 6)), (
            "a 25% deficit stayed silent against a 20% allowance")

    def test_every_finding_carries_full_confidence_by_construction(self):
        """Pinned so the division does not grow back.

        A finding exists only where `deficit_ratio > margin`, so the quotient
        the old expression computed was greater than one on every path that
        could reach it and the clamp returned 1.0 every time. Writing it as a
        constant is not a behaviour change -- it is the removal of arithmetic
        whose only reachable effect was to raise on a zero allowance.
        """
        for margin, out in (("0", 90.0), ("0.01", 90.0), ("0.2", 75.0)):
            problem, = _problems(margin, [out] * 6)
            assert problem.confidence == pytest.approx(1.0), (
                f"loss_margin={margin} produced confidence "
                f"{problem.confidence}, so the constant is wrong and the "
                f"expression carried signal after all")

    def test_an_allowance_that_covers_the_deficit_reports_nothing(self):
        assert not _conservation(_run("0.2", [90.0] * 6))
