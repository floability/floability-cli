"""Tests for package version consistency and CLI diagnostics."""

from __future__ import annotations

import importlib.metadata
import subprocess
import sys
import types
from pathlib import Path

from floability import __version__
from floability.version_info import _jupyter_version, concise_version, verbose_version


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


def test_jupyter_version_uses_metadata_without_starting_cli(monkeypatch) -> None:
    versions = {
        "jupyter": "1.1.1",
        "jupyterlab": "4.5.0",
        "jupyter-core": "5.9.1",
    }
    monkeypatch.setattr(
        "floability.version_info.importlib.metadata.version",
        lambda name: versions[name],
    )
    monkeypatch.setattr(
        "floability.version_info.shutil.which",
        lambda name: "/test/env/bin/jupyter" if name == "jupyter" else None,
    )

    assert _jupyter_version() == (
        "jupyter 1.1.1; jupyterlab 4.5.0; jupyter-core 5.9.1; "
        "executable /test/env/bin/jupyter"
    )


def test_jupyter_version_reports_missing_installation(monkeypatch) -> None:
    def missing(_name):
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(
        "floability.version_info.importlib.metadata.version",
        missing,
    )
    monkeypatch.setattr("floability.version_info.shutil.which", lambda _name: None)

    assert _jupyter_version() == "not installed"


def test_git_details_finds_repository_above_src_layout(monkeypatch, tmp_path) -> None:
    repository = tmp_path / "repository"
    package_dir = repository / "src" / "floability"
    package_dir.mkdir(parents=True)
    (repository / ".git").mkdir()
    monkeypatch.setattr("floability.version_info.shutil.which", lambda _name: "git")

    def fake_run(command, **_kwargs):
        stdout = "abc123\n" if command[1:3] == ["rev-parse", "HEAD"] else ""
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr("floability.version_info.subprocess.run", fake_run)

    from floability.version_info import _git_details

    assert _git_details(Path(package_dir)) == ("abc123", "no")


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
