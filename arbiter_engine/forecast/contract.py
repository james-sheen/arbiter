"""Parse one forecast record, or say precisely why it cannot be used.

THE ENGINE NEVER GUESSES A DISTRIBUTION, and that rule is what shapes this
module. Three input shapes are accepted because three are what producers
actually emit, and two of them have to become quantiles before anything can be
scored:

* ``quantiles`` — taken as given. The producer stated its own resolution.
* ``samples`` — reduced to empirical quantiles. Arithmetic on what was sent;
  no distribution is assumed, and the count is carried so a reader can see how
  thin the tails are.
* ``mean`` + ``sigma`` — expanded under a NORMAL assumption, which is the
  engine choosing a shape the producer did not state. That is allowed and it is
  never silent: `gaussian_from_mean_sigma` is stamped into the record's
  assumptions, beside whatever the producer declared. A score traceable to an
  assumption nobody recorded is the thing this project refuses everywhere else.

REJECTIONS ARE RETURNED, NOT RAISED. A batch of four hundred forecasts with one
malformed record must file three hundred and ninety-nine and report the one --
the same ruling that keeps `add_observations` accepting any property name. An
exception here would make one producer's bug cost another producer's data.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..clock import as_naive_utc, now_utc

#: The two levels a distributional record cannot be scored without. Stated here
#: as the contract's requirement and enforced again by the ledger, which is not
#: duplication: this one rejects a record with a reason a producer can act on,
#: and the ledger's raises because by then it is a programming error.
REQUIRED_QUANTILES: Tuple[str, str] = ("q05", "q95")

#: Stamped onto a record the engine expanded from a mean and a sigma. Named as
#: a fact about how the numbers were MADE, not about the producer's method,
#: because the producer did not make them -- this module did.
GAUSSIAN_STAMP = "gaussian_from_mean_sigma"

#: Levels produced when expanding a mean and sigma, or reducing samples. The
#: two required ones plus the median, which is what the shadow check reads and
#: what a point-estimate consumer expects.
DERIVED_LEVELS: Tuple[Tuple[str, float], ...] = (
    ("q05", 0.05), ("q50", 0.50), ("q95", 0.95))

#: The standard normal quantiles for the levels above. Written out rather than
#: computed, because the inverse error function is not in the standard library
#: and pulling one in for three constants would add a dependency to a package
#: whose stated boundary is numpy and pyyaml.
_Z = {0.05: -1.6448536269514722, 0.50: 0.0, 0.95: 1.6448536269514722}


@dataclass(frozen=True)
class ForecastRejected:
    """Why one record could not be used, in the vocabulary the envelope uses."""

    reason: str
    detail: str
    entity_id: Optional[str] = None
    property_name: Optional[str] = None
    model_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        out = {"reason": self.reason, "detail": self.detail}
        for key, value in (("entity_id", self.entity_id),
                           ("indicator", self.property_name),
                           ("model_id", self.model_id)):
            if value is not None:
                out[key] = value
        return out


@dataclass(frozen=True)
class Forecast:
    """One producer's statement about one property of one entity at one horizon."""

    model_id: str
    entity_id: str
    property_name: str
    issued_at: datetime
    horizon_s: float
    quantiles: Dict[str, float]
    assumptions: List[str] = field(default_factory=list)
    features_hash: Optional[str] = None
    #: How many samples the quantiles were reduced from, when they were. None
    #: for a producer that stated its own quantiles. Carried because a q05 from
    #: twenty samples and one from twenty thousand are different claims and the
    #: record would otherwise present them identically.
    sample_count: Optional[int] = None


def _number(raw: Any) -> Optional[float]:
    """A finite float, or None. Bools are not numbers here: `True` would read
    as 1.0 and a forecast of 1.0 is a real forecast."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    value = float(raw)
    return value if math.isfinite(value) else None


def _instant(raw: Any) -> Optional[datetime]:
    """A datetime, an ISO-8601 string or a POSIX timestamp, as naive UTC."""
    if isinstance(raw, datetime):
        return as_naive_utc(raw)
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        # AWARE FIRST, THEN FLATTENED. The obvious call for this reads a
        # POSIX timestamp straight into a naive UTC datetime, and it is
        # deprecated from Python 3.12 and scheduled for removal; this
        # suite turns a DeprecationWarning into an error, so it shipped
        # green on 3.10 and red on every interpreter most users run.
        # `as_naive_utc` converts an aware value to UTC before
        # flattening it, so the instant is identical and only the route
        # to it changed.
        return as_naive_utc(
            datetime.fromtimestamp(float(raw), timezone.utc))
    if isinstance(raw, str):
        text = raw.strip()
        # `Z` is valid ISO-8601 and `fromisoformat` did not accept it before
        # 3.11. A producer writing UTC the obvious way must not be refused by
        # an interpreter version.
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        try:
            return as_naive_utc(datetime.fromisoformat(text))
        except ValueError:
            return None
    return None


def _empirical_quantiles(samples: Sequence[float]) -> Dict[str, float]:
    """Linear-interpolated quantiles of the sample set, at DERIVED_LEVELS.

    The same rule numpy's default uses, written out to keep this module free of
    an import it would need for three lines.
    """
    ordered = sorted(samples)
    last = len(ordered) - 1
    out: Dict[str, float] = {}
    for key, level in DERIVED_LEVELS:
        position = level * last
        low = math.floor(position)
        high = math.ceil(position)
        if low == high:
            out[key] = float(ordered[int(position)])
        else:
            weight = position - low
            out[key] = float(ordered[low] * (1 - weight) + ordered[high] * weight)
    return out


def parse_forecast(raw: Any, *,
                   at: Optional[datetime] = None
                   ) -> Tuple[Optional[Forecast], Optional[ForecastRejected]]:
    """``(forecast, None)`` or ``(None, rejection)``. Never both, never raises.

    ``at`` is the moment the record is being read, defaulting to the session
    clock -- so a replay judges a forecast against the replayed present rather
    than against wall-clock now.
    """
    if not isinstance(raw, Mapping):
        return None, ForecastRejected(
            "malformed_forecast",
            f"a forecast record must be a mapping; got {type(raw).__name__}")

    model_id = raw.get("model_id")
    entity_id = raw.get("entity_id")
    prop = raw.get("property") or raw.get("property_name")
    identity = {"entity_id": str(entity_id) if entity_id else None,
                "property_name": str(prop) if prop else None,
                "model_id": str(model_id) if model_id else None}

    for name, value in (("model_id", model_id), ("entity_id", entity_id),
                        ("property", prop)):
        if not isinstance(value, str) or not value.strip():
            return None, ForecastRejected(
                "malformed_forecast",
                f"`{name}` is required and must be a non-empty string; got "
                f"{value!r}", **identity)

    horizon = _number(raw.get("horizon_s"))
    if horizon is None or horizon <= 0:
        return None, ForecastRejected(
            "malformed_forecast",
            f"`horizon_s` must be a positive finite number of seconds; got "
            f"{raw.get('horizon_s')!r}. A forecast with no horizon names no "
            f"moment to be graded at", **identity)

    issued = _instant(raw.get("issued_at"))
    if issued is None:
        return None, ForecastRejected(
            "malformed_forecast",
            f"`issued_at` is required and must be a datetime, an ISO-8601 "
            f"string or a POSIX timestamp; got {raw.get('issued_at')!r}",
            **identity)

    present = at if at is not None else now_utc()
    if issued > as_naive_utc(present):
        return None, ForecastRejected(
            "malformed_forecast",
            f"`issued_at` is {issued.isoformat()}, which is after the present "
            f"moment {as_naive_utc(present).isoformat()}; a record issued in "
            f"the future is not a forecast", **identity)

    assumptions = list(raw.get("assumptions") or [])
    sample_count: Optional[int] = None

    shapes = [name for name in ("quantiles", "samples", "mean")
              if raw.get(name) is not None]
    if not shapes:
        return None, ForecastRejected(
            "malformed_forecast",
            "a forecast must carry `quantiles`, `samples`, or `mean` with "
            "`sigma`; this record carries none of them", **identity)
    if len(shapes) > 1:
        # NOT a merge and not a precedence rule. Two shapes are two statements
        # about one distribution, and picking one silently would score the
        # producer against a claim they may not have meant to make.
        return None, ForecastRejected(
            "malformed_forecast",
            f"a forecast states its distribution ONE way; this record carries "
            f"{', '.join(sorted(shapes))}. Two shapes are two claims and the "
            f"engine will not choose between them", **identity)

    shape = shapes[0]
    if shape == "quantiles":
        block = raw.get("quantiles")
        if not isinstance(block, Mapping) or not block:
            return None, ForecastRejected(
                "malformed_forecast",
                f"`quantiles` must be a non-empty mapping of level to value; "
                f"got {block!r}", **identity)
        quantiles: Dict[str, float] = {}
        for key, value in block.items():
            number = _number(value)
            if number is None:
                return None, ForecastRejected(
                    "malformed_forecast",
                    f"quantile {key!r} is {value!r}, which is not a finite "
                    f"number", **identity)
            quantiles[str(key)] = number
        missing = [k for k in REQUIRED_QUANTILES if k not in quantiles]
        if missing:
            return None, ForecastRejected(
                "malformed_forecast",
                f"a distributional forecast requires {list(REQUIRED_QUANTILES)}; "
                f"missing {missing}. A forecast with no stated interval cannot "
                f"be scored for coverage, and an unscoreable record counted in "
                f"a calibration figure is worse than no figure", **identity)
    elif shape == "samples":
        block = raw.get("samples")
        if not isinstance(block, Sequence) or isinstance(block, (str, bytes)):
            return None, ForecastRejected(
                "malformed_forecast",
                f"`samples` must be a sequence of numbers; got {block!r}",
                **identity)
        numbers = [_number(v) for v in block]
        if not numbers or any(n is None for n in numbers):
            return None, ForecastRejected(
                "malformed_forecast",
                f"`samples` must be a non-empty sequence of finite numbers; "
                f"{sum(1 for n in numbers if n is None)} of {len(numbers)} are "
                f"not", **identity)
        if len(numbers) < 2:
            # ONE sample is a point estimate wearing a distribution's clothes:
            # every level collapses to the same number, coverage is vacuously
            # 1.0, and the record would flatter the producer forever.
            return None, ForecastRejected(
                "malformed_forecast",
                "`samples` carries one value, which gives every quantile the "
                "same number and a coverage of 1.0 by construction; send a "
                "point estimate as `mean` with a `sigma`, or send more samples",
                **identity)
        quantiles = _empirical_quantiles([n for n in numbers if n is not None])
        sample_count = len(numbers)
    else:
        mean = _number(raw.get("mean"))
        sigma = _number(raw.get("sigma"))
        if mean is None:
            return None, ForecastRejected(
                "malformed_forecast",
                f"`mean` must be a finite number; got {raw.get('mean')!r}",
                **identity)
        if sigma is None or sigma < 0:
            return None, ForecastRejected(
                "malformed_forecast",
                f"`mean` needs a `sigma` that is a finite number at or above "
                f"zero; got {raw.get('sigma')!r}. A mean on its own states no "
                f"interval, and the engine does not invent one", **identity)
        quantiles = {key: mean + _Z[level] * sigma for key, level in DERIVED_LEVELS}
        # THE ENGINE CHOSE THE SHAPE, so the engine says so. The producer sent
        # two numbers; normality is this module's reading of them, and a score
        # that turns on it must carry it.
        if GAUSSIAN_STAMP not in assumptions:
            assumptions.append(GAUSSIAN_STAMP)

    ordered = sorted(quantiles.items(), key=lambda kv: _level_of(kv[0]))
    for (lo_key, lo), (hi_key, hi) in zip(ordered, ordered[1:]):
        if hi < lo:
            return None, ForecastRejected(
                "malformed_forecast",
                f"quantiles are not monotone: {hi_key}={hi:g} < {lo_key}={lo:g}. "
                f"A producer whose 95th percentile sits below its 5th has "
                f"mislabelled its own output", **identity)

    return Forecast(
        model_id=str(model_id).strip(),
        entity_id=str(entity_id).strip(),
        property_name=str(prop).strip(),
        issued_at=issued,
        horizon_s=horizon,
        quantiles=quantiles,
        assumptions=assumptions,
        features_hash=(str(raw["features_hash"])
                       if raw.get("features_hash") is not None else None),
        sample_count=sample_count,
    ), None


def _level_of(key: str) -> float:
    """The fractional level a quantile key names, or 0.5 when it is unreadable.

    Deliberately forgiving, because this is used only to ORDER the keys for the
    monotonicity check; the ledger owns the strict reading and rejects a
    malformed key there. Two readers of one spelling rule would be two rules.
    """
    text = str(key).strip().lower()
    if text.startswith("q"):
        digits = text[1:]
        if digits.isdigit():
            return float(f"0.{digits}")
    try:
        return float(text)
    except ValueError:
        return 0.5
