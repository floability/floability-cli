from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from floability.backpack_manager import resolve_backpack_args
from floability.ops.run import InstanceContext, _resolve_entrypoint


def _context(workflow_dir: Path) -> InstanceContext:
    return InstanceContext(
        root=workflow_dir.parent,
        paths={},
        metadata_file=workflow_dir.parent / "metadata" / "run.json",
        workflow_dir=workflow_dir,
    )


def _args(entrypoint: str | None = None) -> Namespace:
    return Namespace(
        backpack="test-backpack",
        entrypoint=entrypoint,
    )


@pytest.mark.parametrize("explicit", [False, True])
def test_run_accepts_notebook(tmp_path, explicit):
    workflow = tmp_path / "workflow"
    workflow.mkdir()
    entrypoint = workflow / "workflow.ipynb"
    entrypoint.touch()

    selected = _resolve_entrypoint(
        _args(entrypoint.name if explicit else None),
        _context(workflow),
        "run",
    )

    assert selected == str(entrypoint)


@pytest.mark.parametrize("suffix", [".py", ".sh"])
@pytest.mark.parametrize("explicit", [False, True])
def test_run_rejects_scripts_with_execute_guidance(tmp_path, suffix, explicit):
    workflow = tmp_path / "workflow"
    workflow.mkdir()
    entrypoint = workflow / f"workflow{suffix}"
    entrypoint.touch()

    with pytest.raises(RuntimeError) as exc_info:
        _resolve_entrypoint(
            _args(entrypoint.name if explicit else None),
            _context(workflow),
            "run",
        )

    message = str(exc_info.value)
    assert "requires a .ipynb entrypoint" in message
    assert "floability execute --backpack test-backpack" in message


@pytest.mark.parametrize("suffix", [".ipynb", ".py", ".sh"])
@pytest.mark.parametrize("explicit", [False, True])
def test_execute_accepts_supported_entrypoints(tmp_path, suffix, explicit):
    workflow = tmp_path / "workflow"
    workflow.mkdir()
    entrypoint = workflow / f"workflow{suffix}"
    entrypoint.touch()

    selected = _resolve_entrypoint(
        _args(entrypoint.name if explicit else None),
        _context(workflow),
        "execute",
    )

    assert selected == str(entrypoint)


@pytest.mark.parametrize("mode", ["run", "execute"])
def test_auto_discovery_rejects_ambiguous_entrypoints(tmp_path, mode):
    workflow = tmp_path / "workflow"
    workflow.mkdir()
    (workflow / "one.ipynb").touch()
    (workflow / "two.ipynb").touch()

    with pytest.raises(RuntimeError, match="Select one with --entrypoint"):
        _resolve_entrypoint(_args(), _context(workflow), mode)


@pytest.mark.parametrize("mode", ["run", "execute"])
def test_auto_discovery_prefers_unique_backpack_named_entrypoint(tmp_path, mode):
    backpack = tmp_path / "matrix-multiplication"
    workflow = backpack / "workflow"
    workflow.mkdir(parents=True)
    preferred = workflow / "matrix-multiplication.ipynb"
    preferred.touch()
    (workflow / "matrix-multiplication-2.ipynb").touch()
    args = _args()
    args.backpack = str(backpack)

    assert _resolve_entrypoint(args, _context(workflow), mode) == str(preferred)


def test_run_ignores_same_named_python_file_when_selecting_notebook(tmp_path):
    backpack = tmp_path / "analysis"
    workflow = backpack / "workflow"
    workflow.mkdir(parents=True)
    notebook = workflow / "analysis.ipynb"
    notebook.touch()
    (workflow / "analysis.py").touch()
    args = _args()
    args.backpack = str(backpack)

    assert _resolve_entrypoint(args, _context(workflow), "run") == str(notebook)


def test_execute_rejects_same_named_notebook_and_python_file(tmp_path):
    backpack = tmp_path / "analysis"
    workflow = backpack / "workflow"
    workflow.mkdir(parents=True)
    (workflow / "analysis.ipynb").touch()
    (workflow / "analysis.py").touch()
    args = _args()
    args.backpack = str(backpack)

    with pytest.raises(RuntimeError, match="Select one with --entrypoint"):
        _resolve_entrypoint(args, _context(workflow), "execute")


@pytest.mark.parametrize("mode", ["run", "execute"])
def test_missing_explicit_entrypoint_does_not_fall_back(tmp_path, mode):
    workflow = tmp_path / "workflow"
    workflow.mkdir()
    (workflow / "available.ipynb").touch()

    with pytest.raises(RuntimeError, match="was not found"):
        _resolve_entrypoint(_args("missing.ipynb"), _context(workflow), mode)


def test_backpack_resolution_does_not_preselect_an_entrypoint(tmp_path):
    workflow = tmp_path / "workflow"
    workflow.mkdir()
    (workflow / "one.ipynb").touch()
    (workflow / "two.ipynb").touch()
    args = _args()
    args.backpack = str(tmp_path)
    args.data_spec = None
    args.compute_spec = None
    args.environment = None
    args.worker_environment = None

    resolve_backpack_args(args)

    assert args.entrypoint is None
