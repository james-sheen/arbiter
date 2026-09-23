"""Where this suite's temporary files go, and that they go somewhere.

Seventeen places here build a model with `tempfile.mktemp(suffix=
".yaml")`, write it, load it and walk away. `mktemp` invents a NAME -- it
creates nothing and it removes nothing -- so every one of those calls leaves a
file behind, one per call per run, for as long as the suite has existed.

MEASURED BEFORE THE FIX: 79,031 files, 88.4 MB, oldest 2026-08-17.

THE REASON THIS IS A TEST AND NOT A NOTE. The pile cost nothing where it was
made. It was paid somewhere else entirely: a test in another directory asks
for a domain file to be loaded, the loader reads every YAML sitting beside
that file, and *beside it* was the shared temporary directory this suite had
been filling for weeks. That test hung on one machine and passed in a
container -- a container starts empty -- so it read as a machine-specific
defect for as long as nobody counted the directory.

So the failure mode being guarded is not *files accumulate*. It is *this
suite's mess is invisible from this suite*, and a fixture nobody can see
working is a fixture someone deletes. Remove the redirect in `conftest.py` and
these tests go red, which is the only reason they exist.

WHAT IS NOT CLAIMED HERE. Not that the temporary directory is empty -- other
processes write there and a test that reads a shared directory is the mistake
one layer up. Only that THIS suite's writes are aimed somewhere the runner
prunes, which is the part this suite controls.
"""

from __future__ import annotations

import pathlib
import tempfile

import pytest


def _written_by_the_lane() -> pathlib.Path:
    """A file made exactly the way the seventeen call sites make one."""
    path = pathlib.Path(tempfile.mktemp(suffix=".yaml"))
    path.write_text("domain:\n  id: probe\n", encoding="utf-8")
    return path


class TestTheRedirectIsInPlace:

    def test_the_temp_directory_is_the_runners_and_not_the_systems(self):
        """The fixture is session-scoped and autouse, so by the time any test
        runs this must already be true."""
        assert pathlib.Path(tempfile.gettempdir()).name.startswith(
            "engine_lane"), tempfile.gettempdir()

    def test_a_file_made_the_way_this_suite_makes_them_lands_there(self, tmp_path):
        """`tmp_path` is a directory the runner made for THIS test, so its
        parents name the root the runner prunes. A file this suite writes has
        to be under that same root -- which is the whole claim, stated without
        hardcoding where the runner happens to put its root."""
        base = tmp_path.parents[1]
        path = _written_by_the_lane()
        try:
            assert base in path.parents, f"{path} is not under {base}"
        finally:
            path.unlink(missing_ok=True)

    def test_it_is_not_the_shared_system_directory(self):
        """Stated separately and in the negative, because the assertion above
        would also pass if the runner were ever configured to use the system
        directory as its own root."""
        path = _written_by_the_lane()
        try:
            assert path.parent != pathlib.Path("/tmp")
        finally:
            path.unlink(missing_ok=True)


class TestTheCallSitesStillLookLikeThemselves:
    """If the seventeen ever stop using `tempfile`, the redirect stops
    covering them and the tests above would keep passing while the leak came
    back. This is the half that notices."""

    def test_every_temp_model_in_this_suite_goes_through_tempfile(self):
        here = pathlib.Path(__file__).resolve().parent
        offenders = []
        for path in sorted(here.glob("test_*.py")):
            if path.name == pathlib.Path(__file__).name:
                continue
            text = path.read_text(encoding="utf-8")
            for number, line in enumerate(text.splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                # A literal path into the shared directory would sidestep the
                # redirect entirely, which is the one way back to the pile.
                if '"/tmp/' in stripped or "'/tmp/" in stripped:
                    offenders.append(f"{path.name}:{number}: {stripped[:70]}")
        assert not offenders, "\n".join(offenders)

    def test_the_suite_does_use_the_pattern_this_guards(self):
        """Two-sided: if nothing here writes a temp model any more, the guard
        above is vacuous and should be retired rather than left reassuring."""
        here = pathlib.Path(__file__).resolve().parent
        users = [path.name for path in sorted(here.glob("test_*.py"))
                 if "tempfile.mktemp" in path.read_text(encoding="utf-8")]
        assert users, "nothing writes a temp model; this guard has no subject"
