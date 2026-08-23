from __future__ import annotations

import json
import os
import signal
import subprocess
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

from floability import instance_lock_manager, workers_manager
from floability.commands.workers import WorkersCommand
from floability.ops import workers as worker_ops


def _write_instance_metadata(tmp_path: Path, **updates) -> dict:
    metadata_dir = tmp_path / "metadata"
    logs_dir = tmp_path / "logs"
    metadata_dir.mkdir(exist_ok=True)
    logs_dir.mkdir(exist_ok=True)
    metadata = {
        "manager_name": "standalone-manager",
        "manager_ports": "10000,10010",
        "cli_args": {},
    }
    metadata.update(updates)
    (metadata_dir / "run.json").write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )
    return metadata


def _write_running_worker_state(
    tmp_path: Path,
    *,
    factory_pid: int = 43210,
    factory_pgid: int = 54321,
) -> None:
    assert instance_lock_manager.acquire_workers_lock(tmp_path)
    assert instance_lock_manager.promote_workers_lock(
        tmp_path,
        factory_pid=factory_pid,
        factory_pgid=factory_pgid,
        manager_name="standalone-manager",
    )
    assert workers_manager._write_worker_metadata(
        tmp_path,
        {
            "factory_pid": factory_pid,
            "factory_pgid": factory_pgid,
            "manager_name": "standalone-manager",
            "status": "running",
            "started_at": 1.0,
        },
    )


def _zero_cleanup_grace_periods(monkeypatch) -> None:
    monkeypatch.setattr("floability.cleanup.SIGINT_GRACE_SECONDS", 0)
    monkeypatch.setattr("floability.cleanup.SIGTERM_GRACE_SECONDS", 0)
    monkeypatch.setattr("floability.cleanup.SIGKILL_GRACE_SECONDS", 0)


def test_resolve_standalone_runtime_uses_saved_environment(tmp_path, monkeypatch):
    env_dir = tmp_path / "manager-env"
    env_bin = env_dir / "bin"
    env_bin.mkdir(parents=True)
    vine_factory = env_bin / "vine_factory"
    vine_factory.write_text("#!/bin/sh\n", encoding="utf-8")
    vine_factory.chmod(0o755)
    worker_pack = tmp_path / "worker.tar.gz"
    worker_pack.touch()
    _write_instance_metadata(
        tmp_path,
        env_dir=str(env_dir),
        worker_environment_pack=str(worker_pack),
        cli_args={"env_vars": "DEMO_VALUE=saved"},
    )
    monkeypatch.setenv("CONDA_PREFIX", "/unrelated/env")

    resolved_env, instance_env = workers_manager.resolve_instance_worker_runtime(
        tmp_path
    )

    assert resolved_env == str(env_dir)
    assert instance_env["PATH"].split(os.pathsep)[0] == str(env_bin)
    assert instance_env["VINE_MANAGER_NAME"] == "standalone-manager"
    assert instance_env["VINE_MANAGER_PORTS"] == "10000,10010"
    assert instance_env["FLOABILITY_WORKERS_ENABLED"] == "1"
    assert instance_env["DEMO_VALUE"] == "saved"
    assert "CONDA_PREFIX" not in instance_env


def test_resolve_standalone_runtime_rejects_missing_environment(tmp_path):
    _write_instance_metadata(tmp_path, env_dir=str(tmp_path / "missing-env"))

    with pytest.raises(RuntimeError, match="does not exist"):
        workers_manager.resolve_instance_worker_runtime(tmp_path)


def test_standalone_start_requires_active_instance(tmp_path, monkeypatch, capsys):
    _write_instance_metadata(tmp_path)
    monkeypatch.setattr(worker_ops, "resolve_instance", lambda _value: str(tmp_path))
    monkeypatch.setattr(worker_ops, "is_instance_running", lambda _path: False)
    monkeypatch.setattr(
        worker_ops,
        "start_workers_for_instance",
        lambda **_kwargs: pytest.fail("factory startup should not be attempted"),
    )

    assert worker_ops.start_workers(Namespace(instance=str(tmp_path))) == 1
    assert "active instance run" in capsys.readouterr().out


def test_standalone_start_passes_saved_runtime_and_detaches(tmp_path, monkeypatch):
    _write_instance_metadata(tmp_path)
    factory_process = SimpleNamespace(pid=43210)
    captured = {}
    instance_env = {"VINE_MANAGER_NAME": "standalone-manager"}
    monkeypatch.setattr(worker_ops, "resolve_instance", lambda _value: str(tmp_path))
    monkeypatch.setattr(worker_ops, "is_instance_running", lambda _path: True)
    monkeypatch.setattr(
        worker_ops,
        "resolve_instance_worker_runtime",
        lambda _path: ("/prepared/env", instance_env),
    )

    def capture_start(**kwargs):
        captured.update(kwargs)
        return factory_process

    monkeypatch.setattr(worker_ops, "start_workers_for_instance", capture_start)

    args = Namespace(instance=str(tmp_path), workers=3)
    assert worker_ops.start_workers(args) == 0
    assert captured["instance_path"] == tmp_path
    assert captured["cli_args"] is args
    assert captured["env_dir"] == "/prepared/env"
    assert captured["instance_env"] is instance_env
    assert captured["detached"] is True


def test_explicit_worker_values_override_saved_values():
    config = workers_manager._normalize_compute_specs(
        Namespace(
            batch_type="local",
            workers=2,
            cores_per_worker=3,
        ),
        {
            "cli_args": {
                "batch_type": "condor",
                "workers": "9",
                "cores_per_worker": "8",
            }
        },
    )

    assert config["batch_type"] == "local"
    assert config["max_workers"] == 2
    assert config["cores"] == 3


def test_workers_command_applies_site_defaults_only_to_start(monkeypatch):
    applied = []
    monkeypatch.setattr(
        "floability.sites.apply_site_defaults",
        lambda args, explicit_args=None: applied.append((args, explicit_args)),
    )
    monkeypatch.setattr(worker_ops, "run_workers_command", lambda _args: 0)
    command = WorkersCommand()
    start_args = Namespace(
        workers_subcommand="start",
        _explicit_args={"batch_type"},
    )
    status_args = Namespace(workers_subcommand="status", _explicit_args=set())

    assert command.execute(start_args) == 0
    assert command.execute(status_args) == 0
    assert applied == [(start_args, {"batch_type"})]


def test_detached_factory_uses_durable_stderr_log(tmp_path, monkeypatch):
    captured = {}
    process = SimpleNamespace(pid=43210)

    def fake_popen(_cmd, **kwargs):
        captured.update(kwargs)
        captured["stderr_name"] = kwargs["stderr"].name
        return process

    monkeypatch.setattr(workers_manager.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        workers_manager.threading,
        "Thread",
        lambda **_kwargs: pytest.fail("detached startup must not create a reader"),
    )
    cfg = workers_manager._normalize_compute_specs(Namespace(), {})

    assert workers_manager._start_vine_factory(
        manager_name="standalone-manager",
        cfg=cfg,
        run_dir=str(tmp_path),
        scratch_dir=str(tmp_path),
        detached=True,
    ) is process
    assert captured["stderr"] is not subprocess.PIPE
    assert captured["stderr_name"] == str(tmp_path / "vine_factory.stderr")
    assert (tmp_path / "vine_factory.stdout").exists()
    assert (tmp_path / "vine_factory.stderr").exists()


def test_worker_stop_waits_for_group_then_reconciles(tmp_path, monkeypatch):
    _write_instance_metadata(tmp_path)
    _write_running_worker_state(tmp_path)
    _zero_cleanup_grace_periods(monkeypatch)
    group_alive = True
    signals = []

    def fake_killpg(pgid, sig):
        nonlocal group_alive
        assert pgid == 54321
        if sig == 0:
            if not group_alive:
                raise ProcessLookupError
            return
        signals.append(sig)
        if sig == signal.SIGINT:
            group_alive = False

    monkeypatch.setattr("floability.cleanup.os.killpg", fake_killpg)

    assert workers_manager.stop_workers_for_instance(tmp_path) is True
    assert signals == [signal.SIGINT]
    worker_data = json.loads(
        (tmp_path / "metadata" / "workers.json").read_text(encoding="utf-8")
    )
    assert worker_data["status"] == "stopped"
    assert worker_data["stop_reason"] == "workers_stop"
    assert worker_data["stop_requested_at"] > 0
    assert not (tmp_path / "metadata" / "workers.lock").exists()


def test_worker_stop_retains_lock_when_group_survives(tmp_path, monkeypatch):
    _write_instance_metadata(tmp_path)
    _write_running_worker_state(tmp_path)
    _zero_cleanup_grace_periods(monkeypatch)

    monkeypatch.setattr("floability.cleanup.os.killpg", lambda _pgid, _sig: None)

    assert workers_manager.stop_workers_for_instance(tmp_path) is False
    worker_data = json.loads(
        (tmp_path / "metadata" / "workers.json").read_text(encoding="utf-8")
    )
    assert worker_data["status"] == "cleanup_incomplete"
    assert (tmp_path / "metadata" / "workers.lock").exists()


def test_worker_stop_refuses_mismatched_ownership(tmp_path, monkeypatch):
    _write_instance_metadata(tmp_path)
    _write_running_worker_state(tmp_path)
    lock_path = tmp_path / "metadata" / "workers.lock"
    lock_data = json.loads(lock_path.read_text(encoding="utf-8"))
    lock_data["factory_pgid"] = 60000
    lock_path.write_text(json.dumps(lock_data), encoding="utf-8")
    monkeypatch.setattr(
        "floability.cleanup.os.killpg",
        lambda _pgid, _sig: pytest.fail("mismatched ownership must not be signaled"),
    )

    assert workers_manager.stop_workers_for_instance(tmp_path) is False
    worker_data = json.loads(
        (tmp_path / "metadata" / "workers.json").read_text(encoding="utf-8")
    )
    assert worker_data["status"] == "running"
    assert lock_path.exists()


def test_worker_stop_is_idempotent_after_verified_stop(tmp_path):
    _write_instance_metadata(tmp_path)
    assert workers_manager._write_worker_metadata(
        tmp_path,
        {
            "factory_pid": 43210,
            "factory_pgid": 54321,
            "status": "stopped",
            "stopped_at": 2.0,
        },
    )

    assert workers_manager.stop_workers_for_instance(tmp_path) is True
