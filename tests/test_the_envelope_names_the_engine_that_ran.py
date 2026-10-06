"""An envelope names the installed engine only when that engine is what ran.

`engine_version()` returned the installed `arbiter-engine` version
whatever code was running. Measured with 0.2.7 installed: a source tree's
envelopes said `0.2.7`, and so did a built release tree placed ahead of the
install on the import path, while the installed 0.2.7's own said `0.2.7`
rightly. The version now describes the code only when that code is the
installed distribution's own file, or lies in the directory an editable
install records (https://peps.python.org/pep-0610/) in `direct_url.json`.
"""

from __future__ import annotations

import importlib.metadata
import json
from pathlib import Path

import pytest

from arbiter_engine import envelope

HERE = Path(envelope.__file__).resolve()


class FakeDistribution:
    """What `engine_version` reads of a distribution, and nothing else."""

    version = "9.9.9"

    def __init__(self, located: Path, direct_url: str | None = None) -> None:
        self._located = located
        self._direct_url = direct_url

    def locate_file(self, path):
        return self._located

    def read_text(self, name):
        return self._direct_url if name == "direct_url.json" else None


@pytest.fixture
def installed(monkeypatch):
    """Installs one fake distribution, or none; the cached answer is dropped around each case."""
    def install(dist):
        def distribution(name):
            if dist is None:
                raise importlib.metadata.PackageNotFoundError(name)
            return dist
        monkeypatch.setattr(importlib.metadata, "distribution", distribution)
    envelope.engine_version.cache_clear()
    yield install
    envelope.engine_version.cache_clear()


def _editable(directory: Path) -> str:
    return json.dumps({"url": directory.as_uri(), "dir_info": {"editable": True}})


class TestTheInstalledCopyIsWhatRan:

    def test_its_own_file_names_its_version(self, installed):
        installed(FakeDistribution(HERE))
        assert envelope.engine_version() == "9.9.9"

    def test_an_editable_install_is_named_from_its_source_directory(self, installed, tmp_path):
        installed(FakeDistribution(tmp_path / "envelope.py", _editable(HERE.parent)))
        assert envelope.engine_version() == "9.9.9"


class TestAnotherCopyIsNotNamed:

    def test_a_copy_installed_elsewhere_is_not_named(self, installed, tmp_path):
        installed(FakeDistribution(tmp_path / "arbiter_engine" / "envelope.py"))
        assert envelope.engine_version() is None

    def test_an_editable_install_of_another_tree_is_not_named(self, installed, tmp_path):
        installed(FakeDistribution(tmp_path / "envelope.py", _editable(tmp_path)))
        assert envelope.engine_version() is None

    def test_nothing_installed_names_nothing(self, installed):
        installed(None)
        assert envelope.engine_version() is None

    def test_an_unreadable_install_record_names_nothing(self, installed, tmp_path):
        installed(FakeDistribution(tmp_path / "envelope.py", "{not json"))
        assert envelope.engine_version() is None
