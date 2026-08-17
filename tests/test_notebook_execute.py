from __future__ import annotations

import signal
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

from floability import jupyter_runner
from floability.cleanup import CleanupManager
from floability.ops import run as run_ops


class _Cleanup:
    def __init__(self):
        self.calls = 0

    def cleanup(self):
        self.calls += 1


class _Perf:
    enabled = False


class _Process:
    pid = 1234
    returncode = 0

    def wait(self):
        return self.returncode


class _Thread:
    instances = []

    def __init__(self, **_kwargs):
        self.options = _kwargs
        self.instances.append(self)

    def start(self):
        pass


def _context(tmp_path: Path) -> run_ops.InstanceContext:
    workflow = tmp_path / "workflow"
    logs = tmp_path / "logs"
    metadata = tmp_path / "metadata"
    workflow.mkdir()
    logs.mkdir()
    metadata.mkdir()
    return run_ops.InstanceContext(
        root=tmp_path,
        paths={"workflow": workflow, "logs": logs, "metadata": metadata},
        metadata_file=metadata / "run.json",
        workflow_dir=workflow,
        lock_acquired=False,
        is_new=False,
    )


@pytest.mark.parametrize("notebook_success", [True, False])
def test_execute_batch_returns_and_finalizes_notebook_result(
    monkeypatch, tmp_path, notebook_success
):
    ctx = _context(tmp_path)
    notebook = ctx.workflow_dir / "workflow.ipynb"
    notebook.touch()
    cleanup = _Cleanup()
    finalized = []
    monkeypatch.setattr(run_ops, "execute_notebook", lambda **_kwargs: notebook_success)
    monkeypatch.setattr(
        run_ops,
        "_finalize_run",
        lambda *args, **kwargs: finalized.append(kwargs),
    )

    result = run_ops._execute_batch(
        Namespace(backpack=None),
        ctx,
        SimpleNamespace(env_dir=None, instance_env={}),
        cleanup,
        _Perf(),
        str(notebook),
    )

    assert result is notebook_success
    assert cleanup.calls == 1
    assert finalized == [
        {
            "sync_outputs": False,
            "success": notebook_success,
            "error": None
            if notebook_success
            else "Workflow entrypoint execution failed",
        }
    ]


def test_execute_notebook_uses_selected_environment(monkeypatch, tmp_path):
    commands = []
    monkeypatch.setattr(
        jupyter_runner.subprocess,
        "Popen",
        lambda command, **_kwargs: commands.append(command) or _Process(),
    )

    result = jupyter_runner.execute_notebook(
        notebook_path="workflow.ipynb",
        run_dir=str(tmp_path),
        conda_env_dir="/backpack/env",
        working_dir=str(tmp_path),
        extra_env={},
    )

    assert result is True
    assert commands == [
        [
            "conda",
            "run",
            "--prefix",
            "/backpack/env",
            "--no-capture-output",
            "/backpack/env/bin/jupyter-nbconvert",
            "--to",
            "notebook",
            "--execute",
            "--inplace",
            "workflow.ipynb",
        ]
    ]
    assert (tmp_path / "notebook-execution.log").is_file()


def test_start_jupyterlab_uses_dedicated_binary_without_lab_argument(
    monkeypatch, tmp_path
):
    launches = []
    _Thread.instances.clear()
    monkeypatch.setattr(
        jupyter_runner.subprocess,
        "Popen",
        lambda command, **kwargs: launches.append((command, kwargs)) or _Process(),
    )
    monkeypatch.setattr(jupyter_runner.threading, "Thread", _Thread)
    monkeypatch.setattr(jupyter_runner.os, "getpgid", lambda pid: pid)

    process = jupyter_runner.start_jupyterlab(
        notebook_path="workflow.ipynb",
        port=8899,
        run_dir=str(tmp_path),
        conda_env_dir="/backpack/env",
        working_dir=str(tmp_path),
        extra_env={"VINE_MANAGER_NAME": "test-manager"},
    )

    assert process.pid == 1234
    command, popen_kwargs = launches[0]
    assert command == [
        "conda",
        "run",
        "--prefix",
        "/backpack/env",
        "--no-capture-output",
        "/backpack/env/bin/jupyter-lab",
        "--no-browser",
        "--port",
        "8899",
        "--ip",
        "0.0.0.0",
        "--allow-root",
        "workflow.ipynb",
    ]
    assert popen_kwargs["env"] == {"VINE_MANAGER_NAME": "test-manager"}
    assert popen_kwargs["start_new_session"] is True
    assert _Thread.instances[0].options["daemon"] is True


def test_instance_environment_puts_backpack_tools_first(monkeypatch, tmp_path):
    ctx = _context(tmp_path)
    monkeypatch.setenv("PATH", "/outer/env/bin:/usr/bin")
    monkeypatch.setenv("CONDA_PREFIX", "/outer/env")
    monkeypatch.setenv("CONDA_DEFAULT_ENV", "outer")
    monkeypatch.setenv("CONDA_SHLVL", "1")
    monkeypatch.setenv("CONDA_EXE", "/opt/conda/bin/conda")
    monkeypatch.setattr(run_ops, "_get_env_python_version", lambda _prefix: "3.12")

    env = run_ops._build_instance_env(
        Namespace(
            env_vars="WORKFLOW_SETTING=enabled",
            manager_name="test-manager",
            manager_ports="9123,9150",
        ),
        ctx,
        "/backpack/env",
    )

    path_entries = env["PATH"].split(":")
    assert path_entries[1:] == [
        "/backpack/env/bin",
        "/outer/env/bin",
        "/usr/bin",
    ]
    assert "CONDA_PREFIX" not in env
    assert "CONDA_DEFAULT_ENV" not in env
    assert "CONDA_SHLVL" not in env
    assert env["CONDA_EXE"] == "/opt/conda/bin/conda"
    assert env["VINE_MANAGER_NAME"] == "test-manager"
    assert env["VINE_MANAGER_PORTS"] == "9123,9150"
    assert env["WORKFLOW_SETTING"] == "enabled"


def test_cleanup_terminates_process_group_after_wrapper_exits(monkeypatch):
    class ExitedWrapper:
        pid = 1234

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

    group_exists = True
    signals = []

    def fake_killpg(pgid, sig):
        nonlocal group_exists
        if sig == 0:
            if not group_exists:
                raise ProcessLookupError
            return
        signals.append((pgid, sig))
        if sig == signal.SIGTERM:
            group_exists = False

    monkeypatch.setattr("floability.cleanup.os.getpgid", lambda _pid: 4321)
    monkeypatch.setattr("floability.cleanup.os.killpg", fake_killpg)
    monkeypatch.setattr("floability.cleanup.time.sleep", lambda _seconds: None)

    cleanup = CleanupManager()
    cleanup.register_subprocess(ExitedWrapper())
    cleanup.cleanup()

    assert signals == [
        (4321, signal.SIGINT),
        (4321, signal.SIGTERM),
    ]
