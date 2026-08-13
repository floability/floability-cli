"""Tests for package version consistency and CLI diagnostics."""

from __future__ import annotations

import importlib.metadata
import subprocess
import sys
import types

from floability import __version__
from floability.version_info import concise_version, verbose_version


def test_import_version_matches_installed_distribution() -> None:
    assert __version__ == importlib.metadata.version("floability")


def test_concise_version() -> None:
    assert concise_version() == f"floability {__version__}"


def test_verbose_version_is_best_effort(monkeypatch) -> None:
    monkeypatch.setattr("floability.version_info.shutil.which", lambda _name: None)

    output = verbose_version()

    assert f"floability {__version__}" in output
    assert "Git commit" in output
    assert "Python executable" in output
    assert "vine_factory" in output
    assert "not found" in output


def test_ndcctools_version_uses_taskvine_module(monkeypatch) -> None:
    taskvine = types.ModuleType("ndcctools.taskvine")
    taskvine.__version__ = "7.17.1"
    ndcctools = types.ModuleType("ndcctools")
    ndcctools.taskvine = taskvine
    monkeypatch.setitem(sys.modules, "ndcctools", ndcctools)
    monkeypatch.setitem(sys.modules, "ndcctools.taskvine", taskvine)

    from floability.version_info import _ndcctools_version

    assert _ndcctools_version() == "7.17.1"


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "floability", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_root_version_option() -> None:
    result = _run_cli("--version")

    assert result.returncode == 0
    assert result.stdout.strip() == f"floability {__version__}"


def test_short_root_version_option() -> None:
    result = _run_cli("-v")

    assert result.returncode == 0
    assert result.stdout.strip() == f"floability {__version__}"


def test_root_verbose_version_option() -> None:
    result = _run_cli("--version", "--verbose")

    assert result.returncode == 0
    assert f"floability {__version__}" in result.stdout
    assert "Git commit" in result.stdout
