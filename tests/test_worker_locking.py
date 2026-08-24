from __future__ import annotations

import json
import os
import subprocess
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import pytest

from floability import instance_lock_manager, workers_manager
from floability.cleanup import CleanupManager
from floability.ops import run as run_ops


class _FactoryProcess:
    def __init__(self, pid=43210, returncode=None):
        self.pid = pid
        self.returncode = returncode
        self.terminated = False

    def wait(self, timeout):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("vine_factory", timeout)
        return self.returncode

    def terminate(self):
        self.terminated = True


def _factory_identity(pid=43210, pgid=43210):
    return {
        "pid": pid,
        "pgid": pgid,
        "start_ticks": pid + 1000,
        "boot_id": "test-boot-id",
    }


def _prepare_instance(tmp_path):
    metadata_dir = tmp_path / "metadata"
    logs_dir = tmp_path / "logs"
    metadata_dir.mkdir()
    logs_dir.mkdir()
    (metadata_dir / "run.json").write_text(
        json.dumps(
            {
                "manager_name": "worker-lock-test-manager",
                "worker_environment_pack": "/tmp/worker-environment.tar.gz",
                "cli_args": {},
            }
        ),
        encoding="utf-8",
    )


def _record_running_workers(tmp_path, factory_pid=43210, factory_pgid=43210):
    factory_owner = _factory_identity(factory_pid, factory_pgid)
    assert instance_lock_manager.acquire_workers_lock(tmp_path) is True
    assert instance_lock_manager.promote_workers_lock(
        tmp_path,
        factory_pid=factory_pid,
        factory_pgid=factory_pgid,
        manager_name="worker-lock-test-manager",
        factory_identity=factory_owner,
    )
    assert workers_manager._write_worker_metadata(
        tmp_path,
        {
            "factory_pid": factory_pid,
            "factory_pgid": factory_pgid,
            "factory_owner": factory_owner,
            "manager_name": "worker-lock-test-manager",
            "status": "running",
            "started_at": 1.0,
        },
    )


def test_worker_reservation_is_atomic(tmp_path):
    barrier = Barrier(2)

    def reserve_at_the_same_time():
        barrier.wait()
        return instance_lock_manager.acquire_workers_lock(tmp_path)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: reserve_at_the_same_time(), range(2)))

    assert sorted(results) == [False, True]
    lock_data = json.loads(
        (tmp_path / "metadata" / "workers.lock").read_text(encoding="utf-8")
    )
    assert lock_data["state"] == "starting"
    assert lock_data["launcher_pid"] == os.getpid()


def test_worker_start_reserves_before_launch_and_records_factory_group(
    tmp_path,
    monkeypatch,
):
    _prepare_instance(tmp_path)
    process = _FactoryProcess()

    def verify_reservation_before_launch(**_kwargs):
        lock_data = json.loads(
            (tmp_path / "metadata" / "workers.lock").read_text(encoding="utf-8")
        )
        assert lock_data["state"] == "starting"
        assert lock_data["launcher_pid"] == os.getpid()
        return process

    monkeypatch.setattr(
        workers_manager,
        "_start_vine_factory",
        verify_reservation_before_launch,
    )
    factory_owner = _factory_identity(process.pid, process.pid)
    monkeypatch.setattr(workers_manager.os, "getpgid", lambda _pid: process.pid)
    monkeypatch.setattr(
        workers_manager,
        "capture_process_identity",
        lambda _pid: factory_owner,
    )

    result = workers_manager.start_workers_for_instance(
        tmp_path,
        cli_args=Namespace(),
    )

    assert result is process
    lock_data = json.loads(
        (tmp_path / "metadata" / "workers.lock").read_text(encoding="utf-8")
    )
    worker_data = json.loads(
        (tmp_path / "metadata" / "workers.json").read_text(encoding="utf-8")
    )
    assert lock_data["state"] == "running"
    assert lock_data["factory_pid"] == process.pid
    assert lock_data["factory_pgid"] == process.pid
    assert lock_data["factory_owner"] == factory_owner
    assert lock_data["manager_name"] == "worker-lock-test-manager"
    assert worker_data["factory_pid"] == process.pid
    assert worker_data["factory_pgid"] == process.pid
    assert worker_data["factory_owner"] == factory_owner
    assert worker_data["status"] == "running"


def test_duplicate_worker_start_does_not_launch_factory(tmp_path, monkeypatch):
    _prepare_instance(tmp_path)
    assert instance_lock_manager.acquire_workers_lock(tmp_path) is True

    def unexpected_launch(**_kwargs):
        pytest.fail("vine_factory was launched despite an active reservation")

    monkeypatch.setattr(workers_manager, "_start_vine_factory", unexpected_launch)

    with pytest.raises(RuntimeError, match="already starting or running"):
        workers_manager.start_workers_for_instance(
            tmp_path,
            cli_args=Namespace(),
        )


def test_factory_launch_failure_releases_worker_reservation(tmp_path, monkeypatch):
    _prepare_instance(tmp_path)

    def fail_launch(**_kwargs):
        raise RuntimeError("factory launch failed")

    monkeypatch.setattr(workers_manager, "_start_vine_factory", fail_launch)

    with pytest.raises(RuntimeError, match="factory launch failed"):
        workers_manager.start_workers_for_instance(
            tmp_path,
            cli_args=Namespace(),
        )

    assert not (tmp_path / "metadata" / "workers.lock").exists()


def test_factory_immediate_exit_releases_worker_reservation(tmp_path, monkeypatch):
    _prepare_instance(tmp_path)
    process = _FactoryProcess(returncode=2)

    monkeypatch.setattr(
        workers_manager,
        "_start_vine_factory",
        lambda **_kwargs: process,
    )

    with pytest.raises(RuntimeError, match="exited immediately with status 2"):
        workers_manager.start_workers_for_instance(
            tmp_path,
            cli_args=Namespace(),
        )

    assert process.terminated is True
    assert not (tmp_path / "metadata" / "workers.lock").exists()


def test_metadata_failure_stops_factory_group_and_releases_lock(
    tmp_path,
    monkeypatch,
):
    _prepare_instance(tmp_path)
    process = _FactoryProcess()
    signaled_groups = []

    monkeypatch.setattr(
        workers_manager,
        "_start_vine_factory",
        lambda **_kwargs: process,
    )
    factory_owner = _factory_identity(process.pid, process.pid)
    monkeypatch.setattr(workers_manager.os, "getpgid", lambda _pid: process.pid)
    monkeypatch.setattr(
        workers_manager,
        "capture_process_identity",
        lambda _pid: factory_owner,
    )
    monkeypatch.setattr(
        workers_manager.os,
        "killpg",
        lambda pgid, signal_number: signaled_groups.append((pgid, signal_number)),
    )
    monkeypatch.setattr(
        workers_manager,
        "_write_worker_metadata",
        lambda *_args, **_kwargs: False,
    )

    with pytest.raises(RuntimeError, match="Could not record vine_factory metadata"):
        workers_manager.start_workers_for_instance(
            tmp_path,
            cli_args=Namespace(),
        )

    assert signaled_groups == [(process.pid, workers_manager.signal.SIGTERM)]
    assert not (tmp_path / "metadata" / "workers.lock").exists()


def test_stale_worker_reservation_can_be_recovered(tmp_path, monkeypatch):
    lock_path = tmp_path / "metadata" / "workers.lock"
    lock_path.parent.mkdir()
    lock_path.write_text(
        json.dumps(
            {
                "state": "starting",
                "launcher_pid": 999999,
                "created_at": 1.0,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(instance_lock_manager, "_process_alive", lambda _pid: False)

    assert instance_lock_manager.acquire_workers_lock(tmp_path) is True

    lock_data = json.loads(lock_path.read_text(encoding="utf-8"))
    assert lock_data["state"] == "starting"
    assert lock_data["launcher_pid"] == os.getpid()


def test_running_worker_lock_uses_factory_process_group(tmp_path, monkeypatch):
    factory_owner = _factory_identity()
    assert instance_lock_manager.acquire_workers_lock(tmp_path) is True
    assert instance_lock_manager.promote_workers_lock(
        tmp_path,
        factory_pid=43210,
        factory_pgid=43210,
        manager_name="worker-lock-test-manager",
        factory_identity=factory_owner,
    )
    monkeypatch.setattr(
        instance_lock_manager,
        "process_group_identity_status",
        lambda owner: (
            instance_lock_manager.IDENTITY_OWNED
            if owner == factory_owner
            else instance_lock_manager.IDENTITY_MISMATCHED
        ),
    )
    monkeypatch.setattr(instance_lock_manager, "_process_alive", lambda _pid: False)

    assert instance_lock_manager.are_workers_running(tmp_path) is True


def test_successful_cleanup_stops_worker_state_and_releases_matching_lock(tmp_path):
    _prepare_instance(tmp_path)
    _record_running_workers(tmp_path)

    assert workers_manager.reconcile_workers_after_cleanup(
        tmp_path,
        cleanup_succeeded=True,
        expected_factory_pid=43210,
    )

    worker_data = json.loads(
        (tmp_path / "metadata" / "workers.json").read_text(encoding="utf-8")
    )
    assert worker_data["status"] == "stopped"
    assert worker_data["stop_reason"] == "run_cleanup"
    assert worker_data["stopped_at"] > 0
    assert not (tmp_path / "metadata" / "workers.lock").exists()


def test_incomplete_cleanup_retains_lock_and_retry_reconciles_state(tmp_path):
    _prepare_instance(tmp_path)
    _record_running_workers(tmp_path)

    assert workers_manager.reconcile_workers_after_cleanup(
        tmp_path,
        cleanup_succeeded=False,
        expected_factory_pid=43210,
    )

    worker_data = json.loads(
        (tmp_path / "metadata" / "workers.json").read_text(encoding="utf-8")
    )
    assert worker_data["status"] == "cleanup_incomplete"
    assert worker_data["cleanup_attempted_at"] > 0
    assert "remained alive" in worker_data["cleanup_error"]
    assert (tmp_path / "metadata" / "workers.lock").exists()

    assert workers_manager.reconcile_workers_after_cleanup(
        tmp_path,
        cleanup_succeeded=True,
        expected_factory_pid=43210,
    )

    worker_data = json.loads(
        (tmp_path / "metadata" / "workers.json").read_text(encoding="utf-8")
    )
    assert worker_data["status"] == "stopped"
    assert "cleanup_attempted_at" not in worker_data
    assert "cleanup_error" not in worker_data
    assert not (tmp_path / "metadata" / "workers.lock").exists()


def test_cleanup_does_not_change_state_owned_by_another_factory(tmp_path):
    _prepare_instance(tmp_path)
    _record_running_workers(tmp_path, factory_pid=90001, factory_pgid=90001)
    metadata_path = tmp_path / "metadata" / "workers.json"
    original_worker_data = json.loads(metadata_path.read_text(encoding="utf-8"))

    assert workers_manager.reconcile_workers_after_cleanup(
        tmp_path,
        cleanup_succeeded=True,
        expected_factory_pid=43210,
    )

    assert json.loads(metadata_path.read_text(encoding="utf-8")) == original_worker_data
    assert (tmp_path / "metadata" / "workers.lock").exists()


def test_cleanup_callback_failure_keeps_cleanup_retryable():
    outcomes = iter([False, True])
    cleanup = CleanupManager()
    cleanup.register_cleanup_callback(lambda _succeeded: next(outcomes))

    assert cleanup.cleanup() is False
    assert cleanup.cleanup_complete is False
    assert cleanup.cleanup() is True
    assert cleanup.cleanup_complete is True


def test_run_registers_worker_state_reconciliation(tmp_path, monkeypatch):
    class CleanupRegistration:
        def __init__(self):
            self.processes = []
            self.callbacks = []

        def register_subprocess(self, process):
            self.processes.append(process)

        def register_cleanup_callback(self, callback):
            self.callbacks.append(callback)

    factory_process = SimpleNamespace(pid=43210)
    cleanup = CleanupRegistration()
    reconcile_calls = []
    context = SimpleNamespace(root=tmp_path)
    environment = SimpleNamespace(env_dir="/tmp/env", instance_env={})

    monkeypatch.setattr(
        run_ops,
        "start_workers_for_instance",
        lambda **_kwargs: factory_process,
    )
    monkeypatch.setattr(
        run_ops,
        "reconcile_workers_after_cleanup",
        lambda *args, **kwargs: reconcile_calls.append((args, kwargs)) or True,
    )

    assert run_ops._start_workers(
        Namespace(no_worker=False),
        context,
        environment,
        cleanup,
    ) is factory_process
    assert cleanup.processes == [factory_process]
    assert len(cleanup.callbacks) == 1

    assert cleanup.callbacks[0](False) is True
    assert reconcile_calls == [
        (
            (tmp_path,),
            {
                "cleanup_succeeded": False,
                "expected_factory_pid": 43210,
                "expected_factory_owner": None,
            },
        )
    ]
