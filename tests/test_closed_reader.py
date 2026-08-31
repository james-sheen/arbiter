"""A reader that stops reading must not become a verdict about the benchmark.

`| head` is an ordinary thing to do to a table, and there are TWO ways a writer
dies of it. Output long enough to fill the pipe buffer raises out of `print`,
where an `except` around the call can see it. Output short enough to sit in the
buffer raises nowhere: the run returns cleanly and the interpreter flushes on
the way out, printing `Exception ignored` and exiting `120`.

The guard was written for the first mode and shipped claiming both. This table
is short, so the mode it actually hits was the untested one — and the docstring
asserting the fix was in the built package, installed and running, while the
failure it described still reproduced in one command.

So this file spawns the script and closes the reader, because that is the only
thing that can tell the two modes apart. Reading the source cannot: both
versions have the same `except` clause and the same redirect, and the working
one differs by where a flush sits.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from arbiter_engine.scripts import benchmark_check

#: Derived, so the rewrite that renames the package on the way out carries it.
#: Writing the dotted path as a literal would pin the name of one side.
MODULE = benchmark_check.__name__

#: Small enough to keep this fast; the point is the pipe, not the measurement.
FAST = ["--sizes", "10", "--model-sizes", "5"]

BROKEN_PIPE = 128 + 13
FLUSH_FAILED_AT_EXIT = 120


def _spawn(**kwargs) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-B", "-m", MODULE, *FAST],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            **kwargs)


@pytest.fixture(scope="module")
def full_output() -> bytes:
    process = _spawn()
    out, err = process.communicate(timeout=300)
    assert process.returncode == 0, err.decode()
    return out


class TestTheFixtureReachesTheRightFailureMode:
    """Without this, the test below could pass for the wrong reason."""

    def test_the_report_fits_in_a_pipe_buffer(self, full_output):
        """Which is what makes the deferred flush the mode under test.

        A report larger than the buffer would fail during the run instead, and
        this file would then be exercising the mode that already worked while
        reporting on the one that did not.
        """
        assert 0 < len(full_output) < 65536, len(full_output)

    def test_it_prints_a_table_at_all(self, full_output):
        assert full_output.count(b"\n") > 5


class TestTheReaderLeaving:
    def test_the_exit_status_is_the_broken_pipe_one(self):
        process = _spawn()
        process.stdout.close()          # the reader is gone, as `head` becomes
        error = process.stderr.read()
        assert process.wait(timeout=300) == BROKEN_PIPE, error.decode()

    def test_nothing_is_printed_about_it(self):
        """The benchmark completed. Saying so in a traceback would replace a
        measurement that exists with a report about the terminal."""
        process = _spawn()
        process.stdout.close()
        error = process.stderr.read().decode()
        process.wait(timeout=300)
        assert "Traceback" not in error
        assert "Exception ignored" not in error
        assert error == "", error

    def test_it_is_not_the_status_that_means_the_flush_failed(self):
        """Pinned by name because it is the number the earlier guard returned,
        and it is not in this project's exit vocabulary at all."""
        process = _spawn()
        process.stdout.close()
        process.stderr.read()
        assert process.wait(timeout=300) != FLUSH_FAILED_AT_EXIT


class TestTheOrdinaryRunIsUnchanged:
    def test_a_reader_that_stays_gets_zero(self, full_output):
        assert b"| entities |" in full_output
