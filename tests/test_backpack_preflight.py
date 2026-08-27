from __future__ import annotations

import os
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest

from floability.instance_lock_manager import release_instance_lock
from floability.ops import instance as instance_ops
from floability.ops import run as run_ops


def _execution_args(backpack: Path, base_dir: Path, *, entrypoint=None) -> Namespace:
    return Namespace(
        backpack=str(backpack),
        backpack_root=".",
        environment=None,
        worker_environment=None,
        data_spec=None,
        compute_spec=None,
        entrypoint=entrypoint,
        base_dir=str(base_dir),
        data_cache_dir=None,
        manager_name="preflight-manager",
    )


def _write_environment(backpack: Path) -> None:
    software = backpack / "software"
    software.mkdir(parents=True)
    (software / "environment.yml").write_text(
        "name: preflight\ndependencies:\n  - python=3.12\n",
        encoding="utf-8",
    )


def test_public_run_rejects_non_backpack_without_creating_base(
    tmp_path,
    monkeypatch,
):
    backpack = tmp_path / "not-a-backpack"
    backpack.mkdir()
    base_dir = tmp_path / "base"
    xdg_data_home = tmp_path / "xdg"
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg_data_home))
    executable = Path(sys.executable).parent / "floability"
    environment = dict(os.environ)
    environment["XDG_DATA_HOME"] = str(xdg_data_home)

    result = subprocess.run(
        [
            str(executable),
            "run",
            "--backpack",
            str(backpack),
            "--base-dir",
            str(base_dir),
            "--no-worker",
        ],
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 1
    assert "Invalid Floability backpack" in result.stdout
    assert "Missing workflow/ directory" in result.stdout
    assert "missing environment specification" in result.stdout
    assert not base_dir.exists()
    assert "Created instance structure" not in result.stdout


def test_run_rejects_missing_environment_before_creating_base(tmp_path):
    backpack = tmp_path / "backpack"
    workflow = backpack / "workflow"
    workflow.mkdir(parents=True)
    (workflow / "backpack.ipynb").touch()
    base_dir = tmp_path / "base"

    with pytest.raises(ValueError, match="missing environment specification"):
        run_ops._prepare_new_instance(
            _execution_args(backpack, base_dir),
            "run",
        )

    assert not base_dir.exists()


def test_run_rejects_python_entrypoint_before_creating_base(tmp_path):
    backpack = tmp_path / "python-backpack"
    workflow = backpack / "workflow"
    workflow.mkdir(parents=True)
    (workflow / "python-backpack.py").touch()
    _write_environment(backpack)
    base_dir = tmp_path / "base"

    with pytest.raises(RuntimeError, match="floability execute"):
        run_ops._prepare_new_instance(
            _execution_args(backpack, base_dir),
            "run",
        )

    assert not base_dir.exists()


def test_execute_rejects_missing_explicit_entrypoint_before_creating_base(
    tmp_path,
):
    backpack = tmp_path / "backpack"
    workflow = backpack / "workflow"
    workflow.mkdir(parents=True)
    (workflow / "available.py").touch()
    _write_environment(backpack)
    base_dir = tmp_path / "base"

    with pytest.raises(RuntimeError, match="was not found"):
        run_ops._prepare_new_instance(
            _execution_args(
                backpack,
                base_dir,
                entrypoint="missing.py",
            ),
            "execute",
        )

    assert not base_dir.exists()


def test_instance_create_rejects_invalid_backpack_before_creating_base(tmp_path):
    backpack = tmp_path / "not-a-backpack"
    backpack.mkdir()
    base_dir = tmp_path / "base"
    args = _execution_args(backpack, base_dir)

    assert instance_ops.create_instance(args) == 1
    assert not base_dir.exists()


def test_new_instance_saves_preflight_entrypoint_without_rescanning(
    tmp_path,
    capsys,
):
    backpack = tmp_path / "backpack"
    workflow = backpack / "workflow"
    workflow.mkdir(parents=True)
    (workflow / "backpack.ipynb").touch()
    _write_environment(backpack)
    base_dir = tmp_path / "base"

    ctx = run_ops._prepare_new_instance(
        _execution_args(backpack, base_dir),
        "run",
    )
    try:
        assert ctx.entrypoint_path == ctx.workflow_dir / "backpack.ipynb"
        assert ctx.entrypoint_path.is_file()
        assert "Auto-detected entrypoint" not in capsys.readouterr().out

        # A later file must not make the already selected entrypoint ambiguous.
        (ctx.workflow_dir / "later-generated.ipynb").touch()
        assert run_ops._prepared_entrypoint(ctx) == str(ctx.entrypoint_path)
        output = capsys.readouterr().out
        assert output.count("Auto-detected entrypoint") == 1
    finally:
        assert release_instance_lock(ctx.root)
