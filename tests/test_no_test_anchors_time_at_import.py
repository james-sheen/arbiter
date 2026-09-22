"""A test that reads the wall clock at IMPORT time has an expiry date.

Two files in this directory bound a module-level constant to
`datetime.now(...)` and then anchored their observations to it, while the engine
evaluated each declared `window` against the real clock. pytest imports a module
during COLLECTION and runs it later, so the gap between those two moments is
baked into every timestamp the module produces.

WHY IT SURVIVED SO LONG. In the engine lane, collection and execution are
seconds apart and the anchor is effectively current, so both files were green
every time anyone looked. The gap only opens in a long run -- and a full
regression is the one lane this project deliberately does not run often. The
defect was therefore invisible to every check that was cheap enough to repeat.

WHAT IT LOOKED LIKE WHEN IT FINALLY FIRED. A 22-minute full regression reported
four failures in `test_a_freeze_is_found_inside_its_window.py`, and they pointed
in OPPOSITE directions: the 10m and 15m windows stopped finding a freeze that
was there, and the 30m window began reporting one that was not. That is the
signature of a window sliding along the series rather than of a detector being
wrong, and it is worth recognising -- a failure set that contradicts itself is
usually the fixture moving, not the subject.

The sibling `test_the_rate_arm_declines_what_it_used_to_guess.py` carried the
same construction and had never failed; it tolerates fifteen minutes of drift
and loses fourteen tests at sixty. Fixing only the file that failed would have
left it waiting for a slower day.

SO THIS GUARDS THE SHAPE, not the two instances. A module-level binding to a
wall-clock call is the thing to refuse; taking the reading inside the function
that builds the series costs nothing and cannot go stale.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

HERE = pathlib.Path(__file__).resolve().parent

#: Calls that read the real clock. `time.time` and `time.monotonic` are in the
#: list for the same reason the datetime forms are: bound once at module level,
#: they are a measurement of when the file was imported.
CLOCK_CALLS = {"now", "utcnow", "today", "now_utc", "time", "monotonic"}


def _clock_call(node: ast.AST) -> str | None:
    """The clock function this expression calls, if it calls one.

    Matches `X.now(...)`, `now_utc()` and `time.time()` by the NAME being
    called, because the import spelling varies across these files -- `_dt`,
    `datetime`, and a direct `from ..clock import now_utc` all appear.
    """
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr in CLOCK_CALLS:
        return func.attr
    if isinstance(func, ast.Name) and func.id in CLOCK_CALLS:
        return func.id
    return None


def _module_level_clock_bindings(path: pathlib.Path) -> list[tuple[str, int]]:
    """Every module-level assignment whose value reads the clock.

    Module level only. The same call inside a function is correct and is the
    fix this guard exists to encourage, so walking the whole tree would refuse
    the remedy along with the defect.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if value is None:
            continue
        for inner in ast.walk(value):
            call = _clock_call(inner)
            if call:
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                name = ", ".join(ast.unparse(t) for t in targets)
                found.append((f"{name} = ...{call}(...)", node.lineno))
                break
    return found


@pytest.mark.parametrize(
    "path", sorted(HERE.glob("test_*.py")), ids=lambda p: p.name)
def test_no_module_level_clock_reading(path: pathlib.Path):
    offenders = _module_level_clock_bindings(path)
    assert not offenders, (
        f"{path.name} reads the wall clock at import time: "
        + "; ".join(f"line {line}: {what}" for what, line in offenders)
        + ". pytest imports a module during collection and runs it later, so "
        "this value is stale by the length of the run. Take the reading inside "
        "the function that needs it.")


class TestTheGuardCouldFail:
    """A guard that cannot fail is a comment. These pin the detector itself."""

    def test_it_catches_the_construction_that_was_removed(self, tmp_path):
        probe = tmp_path / "test_probe.py"
        probe.write_text(
            "import datetime as _dt\n"
            "NOW = _dt.datetime.now(_dt.timezone.utc)\n")
        assert _module_level_clock_bindings(probe)

    def test_it_catches_the_bare_helper_form(self, tmp_path):
        probe = tmp_path / "test_probe.py"
        probe.write_text("from x import now_utc\nSTAMP = now_utc()\n")
        assert _module_level_clock_bindings(probe)

    def test_it_allows_the_remedy(self, tmp_path):
        """The fix must not trip the guard, or the guard forbids the cure."""
        probe = tmp_path / "test_probe.py"
        probe.write_text(
            "import datetime as _dt\n"
            "def _now():\n"
            "    return _dt.datetime.now(_dt.timezone.utc)\n")
        assert not _module_level_clock_bindings(probe)

    def test_it_allows_a_fixed_instant(self, tmp_path):
        """A literal anchor is deterministic and has no expiry -- it is the
        other correct answer, and several files here use it."""
        probe = tmp_path / "test_probe.py"
        probe.write_text(
            "import datetime as _dt\n"
            "NOW = _dt.datetime(2026, 9, 22, tzinfo=_dt.timezone.utc)\n")
        assert not _module_level_clock_bindings(probe)
