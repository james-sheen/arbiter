"""The figures that make a forecaster an ordinary entity.

THE CLAIM THIS FILE TESTS is that monitoring a forecaster needs no new
mechanism. A miscalibrated model, a model that skips subjects and a model that
delivers late are the same three shapes BOUNDEDNESS, CONSERVATION and
RESPONSIVENESS already judge; what was missing was not an axiom but a way to
get the numbers onto an entity. This assembles them and stops.

THE ENGINE DOES NOT INVENT THE ENTITY, and that is the whole of the
domain-agnostic line here. The type a forecaster is modelled as is a name the
domain author chose in their own YAML; writing that name into this package
would put a domain word in a domain-free core, which is the class three axioms
were rewritten to remove. So this returns figures keyed by model id and the
CALLER decides what type they are and whether to add them at all:

    for model_id, properties in model_figures(session).items():
        session.add_entity(model_id, <your type>, properties)

THE WORD ITSELF IS ABSENT FROM THIS FILE, and a test asserts that. It is not
squeamishness: a name present in a comment is a name a later reader can reach
for, and the removal this rule belongs to was undone once by exactly that.

BOTH HALVES, OR CONSERVATION SAYS NOTHING. The figures go onto the entity AND
into the observation history, because the axioms do not all read the same
surface: BOUNDEDNESS and RESPONSIVENESS judge the current value, and
CONSERVATION reads the series. Measured -- an entity carrying
`forecasts_expected: 3` and `forecasts_issued: 1` as properties alone declines
`insufficient_samples` and reports no imbalance at all, which is the silent
outcome this package keeps closing. `feed_model_figures` writes both, so a
caller cannot do one and get a clean envelope for a model skipping two thirds
of its subjects.

WHAT IS ABSENT IS ABSENT. A figure no graded record supports is left out rather
than defaulted: a `coverage_90` of 0.0 for a model that has never been scored
reads as catastrophically miscalibrated, and an axiom would fire on it. An
indicator whose property is missing declines, which is the true answer.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..clock import now_utc


def model_figures(session: Any) -> Dict[str, Dict[str, float]]:
    """``{model_id: {property: value}}`` -- one subject per forecaster.

    The property names are the ones the modelling guide's example declares, so
    a reader can paste the YAML and have it read what this produces. Anything
    the ledger cannot support is omitted.
    """
    calibration = session.ledger.calibration()
    records = [r for r in session.ledger.records() if r.kind == "distribution"]
    present = now_utc()

    expected = _expected_per_model(session)
    out: Dict[str, Dict[str, float]] = {}

    for model_id in sorted({str(r.model_id) for r in records if r.model_id}):
        mine = [r for r in records if str(r.model_id) == model_id]
        properties: Dict[str, float] = {
            # THE DENOMINATOR TRAVELS WITH THE FIGURE. `graded_n` is what
            # `coverage_90` was computed over, and a coverage of 1.0 from one
            # record and from four thousand are different statements that the
            # rate alone presents identically.
            "forecasts_issued": float(len(mine)),
            "forecast_age_s": float(
                (present - max(r.predicted_at for r in mine)).total_seconds()),
        }
        scored = calibration.get("by_model", {}).get(model_id)
        if scored:
            properties["graded_n"] = float(scored["n"])
            properties["coverage_90"] = float(scored["coverage_90"])
            properties["pinball_loss"] = float(scored["pinball"])
        if model_id in expected:
            properties["forecasts_expected"] = float(expected[model_id])
        out[model_id] = properties
    return out


def feed_model_figures(session: Any, entity_type: str,
                       at: Optional[Any] = None) -> Dict[str, Dict[str, float]]:
    """Put each forecaster in the session as an entity, and file its figures.

    ``entity_type`` is REQUIRED and is the caller's word. The design that
    prompted this names one; nothing here does, because a type name written
    into this package would be a domain word in a domain-free core -- the
    class three axioms were rewritten to remove.

    Returns what it wrote, so a caller can assert on it rather than re-derive.
    """
    figures = model_figures(session)
    stamp = at if at is not None else now_utc()
    for model_id, properties in figures.items():
        existing = session.entities.get(model_id)
        if existing is None:
            session.add_entity(model_id, entity_type, dict(properties))
        else:
            existing.properties.update(properties)
        for name, value in properties.items():
            # ONE READING, at the moment it was computed. A ladder of synthetic
            # samples would let a window-reading axiom answer about a history
            # that never happened -- the fabrication `add_observations` was
            # corrected to stop doing when given bare values.
            session.history.add(model_id, name, value, timestamp=stamp)
    return figures


def _expected_per_model(session: Any) -> Dict[str, int]:
    """How many forecasts each NAMED model was supposed to supply.

    Derived from `forecast: {expected: true, models: [...]}`: a declared pair
    expects one forecast from each model it names. Only from declarations that
    NAME models -- `expected: true` on its own says a forecast is due and says
    nothing about who owes it, so attributing it to whichever model happened to
    send one would invent an obligation and then report it met.
    """
    if session.model is None:
        return {}
    counts: Dict[str, int] = {}
    for entity in session.entities.values():
        for spec in session.model.indicators.get(entity.type, []):
            config = spec.forecast_config or {}
            if not config.get("expected"):
                continue
            for model_id in config.get("models") or ():
                counts[str(model_id)] = counts.get(str(model_id), 0) + 1
    return counts
