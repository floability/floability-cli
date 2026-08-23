from __future__ import annotations

import json
import os
import subprocess
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from floability import instance_lock_manager, workers_manager


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
    monkeypatch.setattr(workers_manager.os, "getpgid", lambda _pid: 54321)

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
    assert lock_data["factory_pgid"] == 54321
    assert lock_data["manager_name"] == "worker-lock-test-manager"
    assert worker_data["factory_pid"] == process.pid
    assert worker_data["factory_pgid"] == 54321
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
    monkeypatch.setattr(workers_manager.os, "getpgid", lambda _pid: 54321)
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

    assert signaled_groups == [(54321, workers_manager.signal.SIGTERM)]
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
    assert instance_lock_manager.acquire_workers_lock(tmp_path) is True
    assert instance_lock_manager.promote_workers_lock(
        tmp_path,
        factory_pid=43210,
        factory_pgid=54321,
        manager_name="worker-lock-test-manager",
    )
    monkeypatch.setattr(
        instance_lock_manager,
        "_process_group_alive",
        lambda pgid: pgid == 54321,
    )
    monkeypatch.setattr(instance_lock_manager, "_process_alive", lambda _pid: False)

    assert instance_lock_manager.are_workers_running(tmp_path) is True
