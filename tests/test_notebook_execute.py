from __future__ import annotations

import json
import signal
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

from floability import instance_lock_manager, jupyter_runner
from floability.cleanup import CleanupManager
from floability.ops import run as run_ops


class _Cleanup:
    def __init__(self):
        self.calls = 0
        self.subprocesses = []
        self.owned_processes_stopped = True

    def register_subprocess(self, process):
        self.subprocesses.append(process)

    def cleanup(self):
        self.calls += 1
        return True


class _Perf:
    enabled = False

    def start_timer(self, *_args):
        pass


class _Process:
    pid = 1234
    returncode = 0

    def wait(self):
        return self.returncode

    def poll(self):
        return None


class _ExitedProcess(_Process):
    def __init__(self, returncode):
        self.returncode = returncode

    def poll(self):
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
    metrics = tmp_path / "metrics"
    metadata = tmp_path / "metadata"
    workflow.mkdir()
    logs.mkdir()
    metrics.mkdir()
    metadata.mkdir()
    return run_ops.InstanceContext(
        root=tmp_path,
        paths={
            "workflow": workflow,
            "logs": logs,
            "metrics": metrics,
            "metadata": metadata,
        },
        metadata_file=metadata / "run.json",
        workflow_dir=workflow,
        lock_acquired=False,
        is_new=False,
    )


def test_incomplete_cleanup_retains_instance_ownership(tmp_path, capsys):
    ctx = _context(tmp_path)
    ctx.metadata_file.write_text(
        json.dumps({"status": {"state": "running"}}),
        encoding="utf-8",
    )
    assert instance_lock_manager.acquire_instance_lock(ctx.root)
    ctx.lock_acquired = True

    run_ops._finalize_run(
        Namespace(backpack=None),
        ctx,
        _Perf(),
        cleanup_succeeded=False,
        owned_processes_stopped=False,
    )

    status = json.loads(ctx.metadata_file.read_text(encoding="utf-8"))["status"]
    lock_data = instance_lock_manager.read_instance_lock(ctx.root)
    assert status["state"] == "cleanup_incomplete"
    assert status["success"] is False
    assert lock_data["state"] == "cleanup_incomplete"
    assert lock_data["owned_processes_stopped"] is False
    output = capsys.readouterr().out
    assert f"floability instance status {ctx.root}" in output
    assert f"floability instance stop {ctx.root}" in output
    assert "incomplete-only" in output


@pytest.mark.parametrize("failure_type", [ValueError, RuntimeError])
def test_setup_failure_finalizes_metadata_and_returns_one(
    monkeypatch, tmp_path, failure_type
):
    ctx = _context(tmp_path)
    ctx.lock_acquired = True
    ctx.is_new = True
    ctx.metadata_file.write_text(
        json.dumps({"status": {"state": "initializing"}}),
        encoding="utf-8",
    )
    cleanup = _Cleanup()
    released = []
    args = Namespace(base_dir=str(tmp_path), manager_name="test-manager")

    def fail_during_setup(*_args):
        raise failure_type("setup failed")

    monkeypatch.setattr(run_ops, "_is_new_instance_required", lambda _args: True)
    monkeypatch.setattr(
        run_ops,
        "_prepare_new_instance",
        lambda _args, _mode: ctx,
    )
    monkeypatch.setattr(run_ops, "PerformanceTracker", lambda **_kwargs: _Perf())
    monkeypatch.setattr(run_ops, "_register_new_instance", lambda *_args: None)
    monkeypatch.setattr(run_ops, "_materialize_data", fail_during_setup)
    monkeypatch.setattr(
        run_ops,
        "release_instance_lock",
        lambda root: released.append(root),
    )

    assert run_ops.run_workflow(args, cleanup, mode="execute") == 1

    status = json.loads(ctx.metadata_file.read_text(encoding="utf-8"))["status"]
    assert status["state"] == "failed"
    assert status["success"] is False
    assert status["error"] == "setup failed"
    assert status["completed_at"]
    assert cleanup.calls == 1
    assert released == [ctx.root]


def test_unexpected_setup_failure_finalizes_metadata_before_reraising(
    monkeypatch, tmp_path
):
    ctx = _context(tmp_path)
    ctx.metadata_file.write_text(
        json.dumps({"status": {"state": "initializing"}}),
        encoding="utf-8",
    )
    cleanup = _Cleanup()
    args = Namespace(base_dir=str(tmp_path), manager_name="test-manager")

    def fail_during_setup(*_args):
        raise FileNotFoundError("tool missing")

    monkeypatch.setattr(run_ops, "_is_new_instance_required", lambda _args: True)
    monkeypatch.setattr(
        run_ops,
        "_prepare_new_instance",
        lambda _args, _mode: ctx,
    )
    monkeypatch.setattr(run_ops, "PerformanceTracker", lambda **_kwargs: _Perf())
    monkeypatch.setattr(run_ops, "_register_new_instance", lambda *_args: None)
    monkeypatch.setattr(run_ops, "_materialize_data", fail_during_setup)

    with pytest.raises(FileNotFoundError, match="tool missing"):
        run_ops.run_workflow(args, cleanup, mode="execute")

    status = json.loads(ctx.metadata_file.read_text(encoding="utf-8"))["status"]
    assert status["state"] == "failed"
    assert status["success"] is False
    assert status["error"] == "tool missing"
    assert cleanup.calls == 1


def test_unverified_worker_startup_cleanup_retains_instance_ownership(
    monkeypatch,
    tmp_path,
):
    ctx = _context(tmp_path)
    ctx.is_new = True
    ctx.lock_acquired = True
    ctx.metadata_file.write_text(
        json.dumps({"status": {"state": "initializing"}}),
        encoding="utf-8",
    )
    assert instance_lock_manager.acquire_instance_lock(ctx.root)
    cleanup = _Cleanup()
    args = Namespace(base_dir=str(tmp_path), manager_name="test-manager")

    def fail_during_setup(*_args):
        raise run_ops.WorkerStartupCleanupError("factory cleanup failed")

    monkeypatch.setattr(run_ops, "_is_new_instance_required", lambda _args: True)
    monkeypatch.setattr(
        run_ops,
        "_prepare_new_instance",
        lambda _args, _mode: ctx,
    )
    monkeypatch.setattr(run_ops, "PerformanceTracker", lambda **_kwargs: _Perf())
    monkeypatch.setattr(run_ops, "_register_new_instance", lambda *_args: None)
    monkeypatch.setattr(run_ops, "_materialize_data", fail_during_setup)

    assert run_ops.run_workflow(args, cleanup, mode="execute") == 1

    status = json.loads(ctx.metadata_file.read_text(encoding="utf-8"))["status"]
    lock_data = instance_lock_manager.read_instance_lock(ctx.root)
    assert status["state"] == "cleanup_incomplete"
    assert status["success"] is False
    assert lock_data["state"] == "cleanup_incomplete"


@pytest.mark.parametrize(
    ("interruption", "expected_status", "expected_error"),
    [
        (KeyboardInterrupt(), 130, "Interrupted by user"),
        (run_ops.TerminationRequested(signal.SIGTERM), 143, "Terminated by signal 15"),
    ],
)
def test_run_workflow_finalizes_interruption_after_instance_acceptance(
    monkeypatch,
    tmp_path,
    interruption,
    expected_status,
    expected_error,
):
    ctx = _context(tmp_path)
    ctx.is_new = True
    ctx.lock_acquired = True
    ctx.metadata_file.write_text(
        json.dumps({"status": {"state": "initializing"}}),
        encoding="utf-8",
    )
    assert instance_lock_manager.acquire_instance_lock(ctx.root)
    cleanup = _Cleanup()
    args = Namespace(
        base_dir=str(tmp_path),
        manager_name="test-manager",
        no_update_backpack=False,
        backpack=None,
    )

    monkeypatch.setattr(run_ops, "_is_new_instance_required", lambda _args: True)
    monkeypatch.setattr(
        run_ops,
        "_prepare_new_instance",
        lambda _args, _mode: ctx,
    )
    monkeypatch.setattr(run_ops, "PerformanceTracker", lambda **_kwargs: _Perf())
    monkeypatch.setattr(run_ops, "_register_new_instance", lambda *_args: None)
    monkeypatch.setattr(run_ops, "record_instance_run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(run_ops, "_materialize_data", lambda *_args: None)
    monkeypatch.setattr(
        run_ops,
        "_setup_environment",
        lambda *_args: SimpleNamespace(env_dir=None, instance_env={}),
    )
    monkeypatch.setattr(
        run_ops,
        "_prepared_entrypoint",
        lambda _ctx: str(ctx.workflow_dir / "workflow.ipynb"),
    )
    monkeypatch.setattr(run_ops, "_send_catalog_event", lambda *_args: None)
    monkeypatch.setattr(run_ops, "_start_workers", lambda *_args: None)

    def interrupt(*_args):
        raise interruption

    monkeypatch.setattr(run_ops, "_run_interactive", interrupt)

    assert run_ops.run_workflow(args, cleanup, mode="run") == expected_status

    status = json.loads(ctx.metadata_file.read_text(encoding="utf-8"))["status"]
    assert status["state"] == "interrupted"
    assert status["success"] is False
    assert status["error"] == expected_error
    assert cleanup.calls == 1
    assert instance_lock_manager.read_instance_lock(ctx.root) is None


@pytest.mark.parametrize(
    ("interruption", "expected_state", "expected_error"),
    [
        (KeyboardInterrupt(), "interrupted", "Interrupted by user"),
        (
            run_ops.TerminationRequested(signal.SIGTERM),
            "interrupted",
            "Terminated by signal 15",
        ),
        (RuntimeError("copy failed"), "failed", "copy failed"),
    ],
)
def test_preparation_exception_finalizes_and_releases_instance_lock(
    tmp_path,
    interruption,
    expected_state,
    expected_error,
):
    ctx = _context(tmp_path)
    ctx.metadata_file.write_text(
        json.dumps({"status": {"state": "initializing"}}),
        encoding="utf-8",
    )
    assert instance_lock_manager.acquire_instance_lock(ctx.root)

    run_ops._finalize_preparation_exception(
        ctx.root,
        ctx.metadata_file,
        interruption,
    )

    status = json.loads(ctx.metadata_file.read_text(encoding="utf-8"))["status"]
    assert status["state"] == expected_state
    assert status["success"] is False
    assert status["error"] == expected_error
    assert instance_lock_manager.read_instance_lock(ctx.root) is None


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
            "cleanup_succeeded": True,
            "owned_processes_stopped": True,
            "sync_workflow": False,
            "success": notebook_success,
            "error": None
            if notebook_success
            else "Workflow entrypoint execution failed",
        }
    ]


def test_execute_success_returns_false_when_cleanup_is_incomplete(
    monkeypatch,
    tmp_path,
):
    ctx = _context(tmp_path)
    notebook = ctx.workflow_dir / "workflow.ipynb"
    notebook.touch()
    cleanup = _Cleanup()
    cleanup.owned_processes_stopped = False
    cleanup.cleanup = lambda: False
    finalized = []
    monkeypatch.setattr(run_ops, "execute_notebook", lambda **_kwargs: True)
    monkeypatch.setattr(run_ops, "_sync_workflow_if_needed", lambda *_args: None)
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

    assert result is False
    assert finalized[0]["cleanup_succeeded"] is False
    assert finalized[0]["success"] is True


def test_interactive_interrupt_cleans_up_and_syncs_saved_workflow(
    monkeypatch, tmp_path
):
    ctx = _context(tmp_path)
    ctx.is_new = True
    cleanup = _Cleanup()
    process = _Process()
    finalized = []

    monkeypatch.setattr(run_ops, "start_jupyterlab", lambda **_kwargs: process)
    monkeypatch.setattr(
        run_ops.time,
        "sleep",
        lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt),
    )
    monkeypatch.setattr(
        run_ops,
        "_finalize_run",
        lambda *args, **kwargs: finalized.append(kwargs),
    )

    with pytest.raises(KeyboardInterrupt):
        run_ops._run_interactive(
            Namespace(jupyter_port=8888),
            ctx,
            SimpleNamespace(env_dir=None, instance_env={}),
            cleanup,
            None,
            _Perf(),
            str(ctx.workflow_dir / "workflow.ipynb"),
        )

    assert cleanup.subprocesses == [process]
    assert cleanup.calls == 0
    assert finalized == []


@pytest.mark.parametrize(
    (
        "jupyter_status",
        "factory_status",
        "expected_success",
        "expected_error",
    ),
    [
        (0, None, True, None),
        (1, None, False, "JupyterLab exited with status 1."),
        (None, 0, False, "Worker factory exited before JupyterLab with status 0."),
        (0, 2, True, None),
    ],
)
def test_interactive_child_order_determines_session_outcome(
    monkeypatch,
    tmp_path,
    jupyter_status,
    factory_status,
    expected_success,
    expected_error,
):
    ctx = _context(tmp_path)
    cleanup = _Cleanup()
    jupyter = (
        _Process() if jupyter_status is None else _ExitedProcess(jupyter_status)
    )
    factory = (
        None
        if factory_status is None
        else _ExitedProcess(factory_status)
    )
    finalized = []
    monkeypatch.setattr(run_ops, "start_jupyterlab", lambda **_kwargs: jupyter)
    monkeypatch.setattr(run_ops.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        run_ops,
        "_finalize_run",
        lambda *args, **kwargs: finalized.append(kwargs),
    )

    result = run_ops._run_interactive(
        Namespace(jupyter_port=8888),
        ctx,
        SimpleNamespace(env_dir=None, instance_env={}),
        cleanup,
        factory,
        _Perf(),
        str(ctx.workflow_dir / "workflow.ipynb"),
    )

    assert result is expected_success
    assert finalized == [
        {
            "cleanup_succeeded": True,
            "owned_processes_stopped": True,
            "sync_workflow": True,
            "success": expected_success,
            "error": expected_error,
        }
    ]


def test_interactive_cleanup_failure_overrides_success(monkeypatch, tmp_path):
    ctx = _context(tmp_path)
    cleanup = _Cleanup()
    cleanup.owned_processes_stopped = False
    cleanup.cleanup = lambda: False
    finalized = []
    monkeypatch.setattr(
        run_ops,
        "start_jupyterlab",
        lambda **_kwargs: _ExitedProcess(0),
    )
    monkeypatch.setattr(run_ops.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        run_ops,
        "_finalize_run",
        lambda *args, **kwargs: finalized.append(kwargs),
    )

    result = run_ops._run_interactive(
        Namespace(jupyter_port=8888),
        ctx,
        SimpleNamespace(env_dir=None, instance_env={}),
        cleanup,
        None,
        _Perf(),
        str(ctx.workflow_dir / "workflow.ipynb"),
    )

    assert result is False
    assert finalized[0]["cleanup_succeeded"] is False
    assert finalized[0]["success"] is True


def test_interactive_rejects_missing_jupyter_process(monkeypatch, tmp_path):
    ctx = _context(tmp_path)
    monkeypatch.setattr(run_ops, "start_jupyterlab", lambda **_kwargs: None)

    with pytest.raises(RuntimeError, match="did not return a process"):
        run_ops._run_interactive(
            Namespace(jupyter_port=8888),
            ctx,
            SimpleNamespace(env_dir=None, instance_env={}),
            _Cleanup(),
            None,
            _Perf(),
            str(ctx.workflow_dir / "workflow.ipynb"),
        )


def test_jupyter_launch_failure_is_runtime_error(monkeypatch, tmp_path):
    monkeypatch.setattr(
        jupyter_runner.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError()),
    )

    with pytest.raises(RuntimeError, match="JupyterLab could not be started"):
        jupyter_runner.start_jupyterlab(
            notebook_path="workflow.ipynb",
            run_dir=str(tmp_path),
            working_dir=str(tmp_path),
        )


def test_execute_batch_dispatches_shell_entrypoint(monkeypatch, tmp_path):
    ctx = _context(tmp_path)
    script = ctx.workflow_dir / "workflow.sh"
    script.touch()
    cleanup = _Cleanup()
    calls = []
    monkeypatch.setattr(
        run_ops,
        "execute_shell_script",
        lambda **kwargs: calls.append(kwargs) or True,
    )
    monkeypatch.setattr(run_ops, "_finalize_run", lambda *_args, **_kwargs: None)

    result = run_ops._execute_batch(
        Namespace(backpack=None),
        ctx,
        SimpleNamespace(env_dir="/backpack/env", instance_env={"SETTING": "yes"}),
        cleanup,
        _Perf(),
        str(script),
    )

    assert result is True
    assert cleanup.calls == 1
    assert calls == [
        {
            "script_path": str(script),
            "run_dir": str(ctx.paths["logs"]),
            "conda_env_dir": "/backpack/env",
            "working_dir": str(ctx.workflow_dir),
            "extra_env": {"SETTING": "yes"},
            "cleanup_manager": cleanup,
        }
    ]


def test_worker_startup_requires_factory_process(monkeypatch, tmp_path):
    ctx = _context(tmp_path)
    monkeypatch.setattr(
        run_ops,
        "start_workers_for_instance",
        lambda **_kwargs: None,
    )

    with pytest.raises(RuntimeError, match="did not return a vine_factory process"):
        run_ops._start_workers(
            Namespace(no_worker=False),
            ctx,
            SimpleNamespace(env_dir=None, instance_env={}),
            _Cleanup(),
        )


def test_execute_notebook_uses_selected_environment(monkeypatch, tmp_path):
    commands = []
    cleanup = _Cleanup()
    monkeypatch.setenv("CONDA_EXE", "/opt/conda/bin/conda")
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
        cleanup_manager=cleanup,
    )

    assert result is True
    assert commands == [
        [
            "/opt/conda/bin/conda",
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
    assert len(cleanup.subprocesses) == 1
    assert cleanup.subprocesses[0].pid == 1234
    assert (tmp_path / "notebook-execution.log").is_file()


def test_start_jupyterlab_uses_dedicated_binary_without_lab_argument(
    monkeypatch, tmp_path
):
    launches = []
    monkeypatch.setenv("CONDA_EXE", "/opt/conda/bin/conda")
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
        "/opt/conda/bin/conda",
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
            manager_ports="9123:9150",
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
    assert env["FLOABILITY_WORKERS_ENABLED"] == "1"
    assert env["WORKFLOW_SETTING"] == "enabled"


def test_instance_environment_records_disabled_workers(monkeypatch, tmp_path):
    ctx = _context(tmp_path)
    monkeypatch.setattr(run_ops, "_get_env_python_version", lambda _prefix: "3.12")

    env = run_ops._build_instance_env(
        Namespace(
            env_vars=None,
            manager_name="test-manager",
            manager_ports="9123:9150",
            no_worker=True,
        ),
        ctx,
        "/backpack/env",
    )

    assert env["FLOABILITY_WORKERS_ENABLED"] == "0"


@pytest.mark.parametrize("exit_code, expected", [(0, True), (7, False)])
def test_execute_shell_script_propagates_exit_status(tmp_path, exit_code, expected):
    workflow = tmp_path / "workflow"
    logs = tmp_path / "logs"
    workflow.mkdir()
    logs.mkdir()
    script = workflow / "entrypoint.sh"
    script.write_text(f"printf 'shell output\\n'\nexit {exit_code}\n")

    result = run_ops.execute_shell_script(
        script_path=str(script),
        run_dir=str(logs),
        working_dir=str(workflow),
        extra_env={},
    )

    assert result is expected
    log = (logs / "workflow.log").read_text()
    assert "command: /bin/bash entrypoint.sh" in log
    assert "shell output" in log


def test_cleanup_kills_process_group_after_wrapper_exits(monkeypatch, capsys):
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
        # Model a worker that ignores the graceful signals after its wrapper
        # has exited. Only SIGKILL removes the process group.
        if sig == signal.SIGKILL:
            group_exists = False

    monkeypatch.setattr("floability.cleanup.os.getpgid", lambda _pid: 4321)
    monkeypatch.setattr("floability.cleanup.os.killpg", fake_killpg)
    monkeypatch.setattr("floability.cleanup.SIGINT_GRACE_SECONDS", 0)
    monkeypatch.setattr("floability.cleanup.SIGTERM_GRACE_SECONDS", 0)
    monkeypatch.setattr("floability.cleanup.SIGKILL_GRACE_SECONDS", 0)

    cleanup = CleanupManager()
    cleanup.register_subprocess(ExitedWrapper())
    assert cleanup.cleanup() is True

    assert signals == [
        (4321, signal.SIGINT),
        (4321, signal.SIGTERM),
        (4321, signal.SIGKILL),
    ]
    assert cleanup.cleanup_complete is True
    assert "All subprocesses cleaned up" in capsys.readouterr().out


def test_cleanup_does_not_report_success_while_process_group_survives(
    monkeypatch, capsys
):
    class ExitedWrapper:
        pid = 1234

        def poll(self):
            return 0

    signals = []

    def fake_killpg(pgid, sig):
        if sig != 0:
            signals.append((pgid, sig))

    monkeypatch.setattr("floability.cleanup.os.getpgid", lambda _pid: 4321)
    monkeypatch.setattr("floability.cleanup.os.killpg", fake_killpg)
    monkeypatch.setattr("floability.cleanup.SIGINT_GRACE_SECONDS", 0)
    monkeypatch.setattr("floability.cleanup.SIGTERM_GRACE_SECONDS", 0)
    monkeypatch.setattr("floability.cleanup.SIGKILL_GRACE_SECONDS", 0)

    cleanup = CleanupManager()
    cleanup.register_subprocess(ExitedWrapper())

    assert cleanup.cleanup() is False
    assert cleanup.cleanup_complete is False
    assert signals == [
        (4321, signal.SIGINT),
        (4321, signal.SIGTERM),
        (4321, signal.SIGKILL),
    ]

    output = capsys.readouterr().out
    assert "cleanup incomplete" in output
    assert "All subprocesses cleaned up" not in output

    # Since the first cleanup did not finish, another caller can retry it.
    assert cleanup.cleanup() is False
    assert len(signals) == 6
