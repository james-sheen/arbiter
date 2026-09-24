"""Turning the ingest-caller gate on must answer *who ingested*, not *I did*.

`observation_production` can attribute each ingest to the frame that
asked for it, behind `DT_INGEST_CALLER_TAG_ENABLED`, which is off by default.
The walk climbs outward while a frame's module is one of the funnel's own, and
reports the first frame that is not.

THE FUNNEL SET WAS WRITTEN OUT BY HAND, and the paths it held named the tree
the file was authored in rather than the one it runs in. A module path written
without the published root's prefix is not rewritten on the way out, so the
strings arrived naming modules that exist nowhere here, nothing ever matched,
the walk stopped at the first frame it saw -- its own -- and every ingest was
attributed to the funnel.

Measured on the published package before the fix, ingesting from a function
named `a_reader_ingesting_something`:

    {'<pkg>.history.observation_production:_bump_ingest_heartbeat': 1}

The gate being off by default is why this survived: nothing observable happens
until a reader turns it on to find out who is ingesting, which is the moment
the answer is wrong. THE FEATURE HAD NO TEST AND NO OTHER READER -- six rounds
of outside review passed over the paragraphs above it and none of them ran it.

So this file runs it, in a subprocess, because the gate is read at import time
and a flag already read cannot be un-read.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import textwrap

# Derived, never written down -- the defect above is a written-down module path.
from arbiter_engine import types as _anchor

PACKAGE = _anchor.__package__
FUNNEL = f"{PACKAGE}.history.observation_production"
GATE = "DT_INGEST_CALLER_TAG_ENABLED"


def _tree_root() -> pathlib.Path:
    top = PACKAGE.split(".")[0]
    for parent in pathlib.Path(__file__).resolve().parents:
        if (parent / top).is_dir():
            return parent
    raise AssertionError(f"no directory above this file contains {top}/")


def _run(code: str, gate: str | None, **extra_env: str):
    env = {**os.environ, "PYTHONPATH": str(_tree_root()),
           "PYTHONDONTWRITEBYTECODE": "1"}
    if gate is None:
        env.pop(GATE, None)
    else:
        env[GATE] = gate
    env.update(extra_env)
    return subprocess.run([sys.executable, "-B", "-c", textwrap.dedent(code)],
                          capture_output=True, text=True, env=env)


class TestTheTagNamesTheCaller:

    def test_the_tag_is_the_function_that_ingested(self):
        """The whole claim. The name below is deliberately unmistakable: if the
        answer is anything else, the report is about the reporter."""
        r = _run(f"""
            from {FUNNEL} import (
                _bump_ingest_heartbeat, get_ingest_caller_tags)

            def a_reader_ingesting_something():
                _bump_ingest_heartbeat()

            a_reader_ingesting_something()
            tags = get_ingest_caller_tags()
            assert len(tags) == 1, tags
            (name, count), = tags.items()
            assert count == 1, tags
            assert name.endswith(":a_reader_ingesting_something"), name
            assert "observation_production" not in name, (
                "the funnel named itself: " + name)
            print("ok")
        """, gate="1")
        assert r.returncode == 0, r.stderr[-1500:]

    def test_the_public_entry_point_is_attributed_the_same_way(self):
        """Through `record_observation`, which is the path a caller actually
        takes -- so the walk has real funnel frames to climb, not one.

        It sits behind a SECOND gate of its own, and that is worth saying: the
        first version of this test set only the tagging gate, collected nothing
        and read as a defect in the walk. Two default-off gates in series is
        how a feature ends up with no test.
        """
        r = _run(f"""
            from {FUNNEL} import record_observation, get_ingest_caller_tags

            def some_bridge_feeding_the_engine():
                record_observation("obs-1", "src-1", 1.0)

            some_bridge_feeding_the_engine()
            tags = get_ingest_caller_tags()
            assert tags, "no ingest was tagged at all"
            assert any(k.endswith(":some_bridge_feeding_the_engine")
                       for k in tags), tags
            assert not any("observation_production" in k for k in tags), tags
            print("ok")
        """, gate="1", DT_OBSERVATION_PRODUCTION_ENABLED="1")
        assert r.returncode == 0, r.stderr[-1500:]


class TestTheGateStillDefaultsOff:
    """Two-sided. Deriving the funnel set correctly must not turn a
    frame-inspecting feature on for everyone who never asked for it."""

    def test_nothing_is_collected_when_the_gate_is_unset(self):
        r = _run(f"""
            from {FUNNEL} import (
                _bump_ingest_heartbeat, get_ingest_caller_tags)
            _bump_ingest_heartbeat()
            assert get_ingest_caller_tags() == {{}}, get_ingest_caller_tags()
            print("ok")
        """, gate=None)
        assert r.returncode == 0, r.stderr[-1500:]


class TestTheFunnelSetIsDerived:
    """The mechanism, not the outcome -- this half runs without touching the
    gate and would have caught the defect on the day it shipped."""

    def test_every_funnel_module_is_a_module_that_exists_here(self):
        r = _run(f"""
            import importlib
            import {FUNNEL} as f
            assert f._FUNNEL_MODULES, "the funnel set is empty"
            for name in f._FUNNEL_MODULES:
                importlib.import_module(name)
            print("ok")
        """, gate=None)
        assert r.returncode == 0, (
            "a funnel module does not exist in this tree, so the walk can "
            f"never match it:\n{r.stderr[-1500:]}")

    def test_the_funnel_names_this_package_and_not_another_tree(self):
        r = _run(f"""
            import {FUNNEL} as f
            root = "{PACKAGE}".split(".")[0]
            bad = [m for m in f._FUNNEL_MODULES if not m.startswith(root)]
            assert not bad, bad
            assert f.__name__ in f._FUNNEL_MODULES, (
                "the funnel does not name itself, so its own frames are not "
                "skipped")
            print("ok")
        """, gate=None)
        assert r.returncode == 0, r.stderr[-1500:]
