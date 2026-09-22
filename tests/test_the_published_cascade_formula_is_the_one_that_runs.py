"""The derivation a reader implements must be the derivation that runs.

Two published copies of the exact two-stage cascade response -- the
modelling guide and the `cascade_fraction` docstring -- carried a sign error
from the closure that derived the form. Read with the `phi` defined beside it,
the printed expression returns 1.1116 at `tau1 = tau2 = 600` and `t = 900`,
where the response is 0.442174599629. A step response above one.

THE CODE WAS NEVER WRONG, which is why this survived. Every NUMBER in the
surrounding paragraph was measured from the engine and is correct -- the 2e-14
at one second of separation, the 0.625 against the true value at 1e-13, the
divide-by-zero at equality. Only the symbolic form was wrong, and a number
beside a formula reads as evidence for it. Two rounds of outside review read
past it; the third copied it verbatim into a third-party comparison, which is
how it was found.

SO THIS EVALUATES THE PUBLISHED TEXT rather than restating it. A test that
hard-codes the corrected expression and compares it to the engine would pass on
the broken document, because the document is not what it read. The translator
below is small and REFUSES what it does not recognise: a reworded formula fails
here rather than slipping through as a vacuous pass.
"""
from __future__ import annotations

import ast
import math
import pathlib
import re

import pytest

from arbiter_engine.twin.topology import TwinEdge

#: `tau1`, `tau2`, `t`. Includes the equal-tau branch, a separation of one
#: second either side of it, and a ratio of twenty, because the published
#: paragraph makes its accuracy claim across exactly this kind of sweep.
SWEEP = [(t1, t2, t) for t1 in (120.0, 300.0, 600.0, 1800.0)
         for t2 in (60.0, 299.0, 300.0, 301.0, 600.0, 2400.0)
         for t in (30.0, 300.0, 900.0, 7200.0)]


def _guide() -> str:
    """The modelling guide, from whichever copy this tree has.

    The same two candidates the rest of the suite uses, and the same refusal to
    fall through: a guide check that SKIPS when it cannot find the guide is a
    green that means nothing, and the published tree is the one where this pin
    matters most.
    """
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[1] / "MODELING.md",
                      here.parents[2] / "docs" / "publication"
                      / "domain-model-spec.md"):
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    raise AssertionError("no modelling guide found to check against")


def _docstring() -> str:
    """The other published copy. Two copies of one formula is how a sign
    survives a correction to one of them, so both are held to the code."""
    return TwinEdge.cascade_fraction.__doc__ or ""


#: Ordered rewrites from the published notation to Python. Every one of them is
#: a shape that actually appears in the two documents; nothing here is
#: defensive breadth.
_REWRITES = (
    (r"e\^\{-at\}", "exp(-a*t)"),        # the leading decay
    (r"e\^x", "exp(x)"),                 # inside the phi definition
    (r"\bphi\b", "PHI"),                 # protect the name from the * pass
    (r"-\(b-a\)\s*t", "-(b-a)*t"),       # the guide's spelling of the argument
    (r"-d\*t", "-(b-a)*t"),              # the docstring's, via d = b - a
    # Implicit multiplication, which both documents use and Python does not:
    # `a t phi(...)` and `e^{-at} (1 + ...)`. Applied last so the named
    # rewrites above have already run.
    (r"(?<=[0-9a-zA-Z)])\s+(?=[0-9a-zA-Z(])", "*"),
)

_ALLOWED = re.compile(r"^[0-9a-zA-Z_+\-*/(). ]+$")


def _to_python(expr: str) -> str:
    """Translate one published expression, refusing anything unrecognised."""
    out = expr.strip()
    for pattern, replacement in _REWRITES:
        out = re.sub(pattern, replacement, out)
    out = out.replace("PHI", "phi")
    out = re.sub(r"\s*\*\s*", "*", out)
    assert _ALLOWED.match(out), (
        f"the published formula uses notation this test cannot read: {out!r}. "
        "Extend the translator deliberately -- do not relax the guard, which "
        "is the only thing keeping a reworded formula from passing vacuously.")
    try:
        ast.parse(out, mode="eval")
    except SyntaxError as exc:                      # pragma: no cover - guard
        raise AssertionError(
            f"the published formula does not read as an expression this test "
            f"cannot read: {out!r} ({exc})") from exc
    return out


def _extract(text: str):
    """The `h(t)` body and the `phi(x)` body, as Python source."""
    line = None
    for candidate in text.splitlines():
        if "h(t)" in candidate and "phi(" in candidate:
            line = candidate
            break
    assert line is not None, "no published cascade formula found"
    h_src, _, phi_src = line.partition("phi(x) =")
    assert phi_src, f"the formula does not define phi beside it: {line!r}"
    h_body = h_src.split("h(t) =", 1)[1].strip().rstrip(",").strip()
    return _to_python(h_body), _to_python(phi_src.strip().rstrip(","))


def _evaluate(h_src: str, phi_src: str, tau1: float, tau2: float, t: float):
    a, b = 1.0 / tau1, 1.0 / tau2
    def phi(x: float) -> float:
        if x == 0.0:
            return 1.0          # the removable singularity of (e^x - 1)/x
        return eval(phi_src, {"exp": math.exp, "x": x})   # noqa: S307
    return eval(h_src, {"exp": math.exp, "phi": phi,      # noqa: S307
                        "a": a, "b": b, "t": t})


@pytest.fixture(scope="module", params=["guide", "docstring"])
def published(request):
    text = _guide() if request.param == "guide" else _docstring()
    return _extract(text)


class TestTheDocumentAgreesWithTheCode:
    def test_it_reproduces_cascade_fraction_across_the_sweep(self, published):
        h_src, phi_src = published
        worst = 0.0
        for tau1, tau2, t in SWEEP:
            engine = TwinEdge.cascade_fraction([(tau1, 0.0), (tau2, 0.0)], t)
            printed = _evaluate(h_src, phi_src, tau1, tau2, t)
            worst = max(worst, abs(engine - printed))
            assert abs(engine - printed) < 1e-12, (
                f"the published formula and the engine disagree at "
                f"tau1={tau1}, tau2={tau2}, t={t}: engine {engine!r}, "
                f"document {printed!r}. The document is what a reader "
                f"implements.")
        assert worst < 1e-12

    def test_no_printed_response_exceeds_one(self, published):
        """The failure this guard was written for had a signature anyone can
        recognise without knowing the closed form: a step response above 1."""
        h_src, phi_src = published
        for tau1, tau2, t in SWEEP:
            value = _evaluate(h_src, phi_src, tau1, tau2, t)
            assert 0.0 <= value <= 1.0, (
                f"the published formula gives {value!r} at tau1={tau1}, "
                f"tau2={tau2}, t={t} -- a step response outside [0, 1]")


class TestTheGuardCouldFail:
    """A guard that cannot fail is a comment. These pin the detector on the
    text that was actually published, so the test is known to catch it."""

    BROKEN = "1 - e^{-at} (1 - a t phi(-(b-a) t)),   phi(x) = (e^x - 1)/x"
    FIXED = "1 - e^{-at} (1 + a t phi(-(b-a) t)),   phi(x) = (e^x - 1)/x"

    def _read(self, body: str):
        return _extract(f"    h(t) = {body}\n")

    def test_it_rejects_the_form_that_was_published(self):
        h_src, phi_src = self._read(self.BROKEN)
        engine = TwinEdge.cascade_fraction([(600.0, 0.0), (600.0, 0.0)], 900.0)
        printed = _evaluate(h_src, phi_src, 600.0, 600.0, 900.0)
        assert abs(engine - printed) > 0.6
        assert printed > 1.0, "the broken form's signature is a value above 1"

    def test_it_accepts_the_form_that_replaced_it(self):
        h_src, phi_src = self._read(self.FIXED)
        for tau1, tau2, t in SWEEP:
            engine = TwinEdge.cascade_fraction([(tau1, 0.0), (tau2, 0.0)], t)
            assert abs(engine - _evaluate(h_src, phi_src, tau1, tau2, t)) < 1e-12

    def test_it_refuses_notation_it_cannot_read(self):
        with pytest.raises(AssertionError, match="cannot read"):
            _to_python("1 - e^{-at} (1 + a t psi_unknown[-(b-a) t])")
