from __future__ import annotations

import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from floability.environment_toolchain import (
    EnvironmentToolResolutionError,
    build_prefix_run_command,
    conda_run_environment,
    discover_conda_executable,
    discover_pixi_executable,
    resolve_environment_plan,
)


def _executable(path: Path, output: str) -> str:
    path.write_text(f"#!/bin/sh\nprintf '%s\\n' '{output}'\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


def test_creator_choice_keeps_conda_runner(tmp_path):
    conda = _executable(tmp_path / "conda", "conda 26.0")
    pixi = _executable(tmp_path / "pixi", "pixi 0.55")
    conda_pack = _executable(tmp_path / "conda-pack", "conda-pack 0.8")

    def all_tools(name: str) -> str | None:
        return {"conda": conda, "pixi": pixi, "conda-pack": conda_pack}.get(name)

    conda_plan = resolve_environment_plan(
        "auto", which=all_tools, environ={}, python_executable=None
    )
    assert conda_plan.environment_type == "python"
    assert conda_plan.spec_format == "conda-yaml"
    assert conda_plan.creator.family == "conda"
    assert conda_plan.artifact_format == "conda-pack"
    assert conda_plan.runner.family == "conda-run"
    assert conda_plan.runner.executable == conda

    pixi_plan = resolve_environment_plan(
        "pixi", which=all_tools, environ={}, python_executable=None
    )
    assert pixi_plan.creator.family == "pixi"
    assert pixi_plan.runner == conda_plan.runner
    assert pixi_plan.artifact_format == "conda-pack"


@pytest.mark.parametrize("creator", ["auto", "pixi"])
def test_plan_requires_conda_even_when_pixi_is_available(tmp_path, creator):
    pixi = _executable(tmp_path / "pixi", "pixi 0.55")
    conda_pack = _executable(tmp_path / "conda-pack", "conda-pack 0.8")

    def which(name: str) -> str | None:
        return {"pixi": pixi, "conda-pack": conda_pack}.get(name)

    with pytest.raises(EnvironmentToolResolutionError, match="Conda is required.*launch"):
        resolve_environment_plan(
            creator, which=which, environ={}, python_executable=None
        )


def test_explicit_pixi_creator_never_falls_back_to_conda(tmp_path):
    conda = _executable(tmp_path / "conda", "conda 26.0")

    with pytest.raises(EnvironmentToolResolutionError, match="Pixi was requested"):
        resolve_environment_plan(
            "pixi",
            which=lambda name: conda if name == "conda" else None,
            environ={},
            home=tmp_path,
            python_executable=None,
        )


def test_pixi_discovery_checks_pixi_home_and_default_home(tmp_path):
    pixi_home = tmp_path / "configured"
    configured = pixi_home / "bin" / "pixi"
    configured.parent.mkdir(parents=True)
    _executable(configured, "pixi")
    assert discover_pixi_executable(
        environ={"PIXI_HOME": str(pixi_home)},
        which=lambda _name: None,
        home=tmp_path / "home",
        python_executable=None,
    ) == str(configured.resolve())

    default = tmp_path / "home" / ".pixi" / "bin" / "pixi"
    default.parent.mkdir(parents=True)
    _executable(default, "pixi")
    assert discover_pixi_executable(
        environ={},
        which=lambda _name: None,
        home=tmp_path / "home",
        python_executable=None,
    ) == str(default.resolve())


def test_prefix_launch_uses_existing_conda(monkeypatch, tmp_path):
    existing_conda = _executable(tmp_path / "existing-conda", "conda 26.0")
    monkeypatch.setenv("CONDA_EXE", existing_conda)
    prefix = tmp_path / "prefix with spaces"

    assert build_prefix_run_command(prefix, ["python", "input file.py"]) == [
        existing_conda,
        "run",
        "--prefix",
        str(prefix.resolve()),
        "--no-capture-output",
        "python",
        "input file.py",
    ]


def test_prefix_launch_reports_missing_conda(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "floability.environment_toolchain.discover_conda_executable", lambda: None
    )
    with pytest.raises(EnvironmentToolResolutionError, match="Conda is required.*launch"):
        build_prefix_run_command(tmp_path, ["python", "workflow.py"])


@pytest.mark.integration
def test_conda_run_preserves_dynamic_and_static_environment(monkeypatch, tmp_path):
    conda = discover_conda_executable()
    if conda is None:
        pytest.skip("Conda is required for the real activation test")

    prefix = tmp_path / "prefix with spaces"
    bin_dir = prefix / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "python").symlink_to(sys.executable)
    state_dir = prefix / "conda-meta"
    state_dir.mkdir()
    (state_dir / "history").touch()
    (state_dir / "state").write_text(
        json.dumps({"env_vars": {"STATIC": "saved value"}})
    )
    activate_dir = prefix / "etc" / "conda" / "activate.d"
    activate_dir.mkdir(parents=True)
    (activate_dir / "example.sh").write_text("export ACTIVATED='yes'\n")

    command = build_prefix_run_command(
        prefix,
        [
            str(bin_dir / "python"),
            "-c",
            (
                "import json, os, sys; "
                "print(json.dumps([os.environ['STATIC'], os.environ['ACTIVATED'], "
                "os.environ['DYNAMIC'], os.environ['CONDA_PREFIX'], sys.argv[1]]))"
            ),
            "argument with spaces",
        ],
        conda_executable=conda,
    )
    # Some launchers inherit a shell level without the corresponding prefix.
    monkeypatch.setenv("CONDA_SHLVL", "1")
    monkeypatch.delenv("CONDA_PREFIX", raising=False)
    command_env = conda_run_environment()
    command_env["DYNAMIC"] = "run value"
    result = subprocess.run(
        command,
        env=command_env,
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )

    assert json.loads(result.stdout) == [
        "saved value",
        "yes",
        "run value",
        str(prefix.resolve()),
        "argument with spaces",
    ]
