from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from argparse import Namespace

import pytest

from floability import instance_lock_manager
from floability.cleanup import CleanupManager
from floability.ops import instance as instance_ops


def _owner(pid: int = 43210, *, start_ticks: int = 12345) -> dict:
    return {
        "pid": pid,
        "pgid": pid,
        "start_ticks": start_ticks,
        "boot_id": "test-boot-id",
    }


def _prepare_instance(tmp_path, *, metadata_state: str = "running"):
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    (metadata_dir / "run.json").write_text(
        json.dumps({"status": {"state": metadata_state}}),
        encoding="utf-8",
    )
    return metadata_dir


def _write_instance_lock(metadata_dir, owner, *, state: str = "running"):
    lock_path = metadata_dir / "instance.lock"
    lock_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "state": state,
                "pid": owner["pid"],
                "owner": owner,
            }
        ),
        encoding="utf-8",
    )
    return lock_path


def test_current_process_identity_is_owned_and_start_ticks_detect_pid_reuse():
    owner = instance_lock_manager.capture_process_identity()

    assert owner is not None
    assert instance_lock_manager.process_identity_status(owner) == "owned"

    changed_owner = dict(owner, start_ticks=owner["start_ticks"] + 1)
    assert instance_lock_manager.process_identity_status(changed_owner) == "mismatched"


def test_process_identity_permission_failure_is_unverifiable(monkeypatch):
    def deny_process_stat(_pid):
        raise PermissionError

    monkeypatch.setattr(
        instance_lock_manager,
        "_read_boot_id",
        lambda: "test-boot-id",
    )
    monkeypatch.setattr(
        instance_lock_manager,
        "_read_process_stat",
        deny_process_stat,
    )

    assert (
        instance_lock_manager.process_identity_status(_owner())
        == instance_lock_manager.IDENTITY_UNVERIFIABLE
    )


def test_instance_lock_release_is_compare_and_delete(tmp_path):
    metadata_dir = _prepare_instance(tmp_path)
    owner = _owner()
    lock_path = _write_instance_lock(metadata_dir, owner)

    assert instance_lock_manager.release_instance_lock(
        tmp_path,
        expected_owner=_owner(start_ticks=99999),
    ) is False
    assert lock_path.exists()
    assert instance_lock_manager.release_instance_lock(
        tmp_path,
        expected_owner=owner,
    ) is True
    assert not lock_path.exists()


def test_corrupt_instance_lock_is_preserved_and_blocks_acquisition(
    tmp_path,
    monkeypatch,
):
    metadata_dir = _prepare_instance(tmp_path)
    lock_path = metadata_dir / "instance.lock"
    lock_path.write_text("{not-json", encoding="utf-8")
    monkeypatch.setattr(
        instance_lock_manager,
        "capture_process_identity",
        lambda _pid=None: _owner(os.getpid()),
    )

    status = instance_lock_manager.get_instance_lock_status(tmp_path)
    assert status["state"] == "corrupt"
    assert instance_lock_manager.acquire_instance_lock(tmp_path) is False
    assert lock_path.read_text(encoding="utf-8") == "{not-json"


def test_verified_cleanup_stops_signaling_when_identity_changes(monkeypatch):
    states = iter(["owned", "owned", "mismatched"])
    signals = []
    cleanup = CleanupManager(process_sigint_grace_seconds=0)
    cleanup.register_verified_process(43210, lambda: next(states, "mismatched"))
    monkeypatch.setattr(
        "floability.cleanup.os.kill",
        lambda pid, signal_number: signals.append((pid, signal_number)),
    )

    assert cleanup.cleanup() is False
    assert [signal_number for _pid, signal_number in signals] == [signal.SIGINT]


def test_stop_refuses_live_legacy_lock(tmp_path, monkeypatch):
    metadata_dir = _prepare_instance(tmp_path)
    lock_path = metadata_dir / "instance.lock"
    lock_path.write_text(json.dumps({"pid": 43210}), encoding="utf-8")
    monkeypatch.setattr(instance_lock_manager, "_process_alive", lambda _pid: True)
    monkeypatch.setattr(instance_ops, "resolve_instance", lambda _ref: str(tmp_path))

    assert instance_ops.stop_instance(Namespace(instance=str(tmp_path))) == 1
    assert lock_path.exists()


def test_stop_does_not_signal_mismatched_owner_and_releases_terminal_lock(
    tmp_path,
    monkeypatch,
):
    metadata_dir = _prepare_instance(tmp_path, metadata_state="completed")
    lock_path = _write_instance_lock(metadata_dir, _owner())
    monkeypatch.setattr(
        instance_lock_manager,
        "process_identity_status",
        lambda _owner: instance_lock_manager.IDENTITY_MISMATCHED,
    )
    monkeypatch.setattr(instance_ops, "resolve_instance", lambda _ref: str(tmp_path))
    monkeypatch.setattr(
        instance_ops,
        "CleanupManager",
        lambda **_kwargs: pytest.fail("mismatched ownership must not be signaled"),
    )

    assert instance_ops.stop_instance(Namespace(instance=str(tmp_path))) == 0
    assert not lock_path.exists()


def test_stop_returns_success_only_after_verified_owner_is_gone(
    tmp_path,
    monkeypatch,
):
    metadata_dir = _prepare_instance(tmp_path)
    owner = _owner()
    lock_path = _write_instance_lock(metadata_dir, owner)
    owner_alive = True

    def identity_status(_owner):
        return (
            instance_lock_manager.IDENTITY_OWNED
            if owner_alive
            else instance_lock_manager.IDENTITY_GONE
        )

    class SuccessfulCleanup:
        def __init__(self, **_kwargs):
            self.ownership_check = None

        def register_verified_process(self, _pid, ownership_check):
            self.ownership_check = ownership_check

        def cleanup(self):
            nonlocal owner_alive
            assert self.ownership_check() == instance_lock_manager.IDENTITY_OWNED
            owner_alive = False
            (metadata_dir / "run.json").write_text(
                json.dumps({"status": {"state": "interrupted"}}),
                encoding="utf-8",
            )
            return True

    monkeypatch.setattr(
        instance_lock_manager,
        "process_identity_status",
        identity_status,
    )
    monkeypatch.setattr(instance_ops, "process_identity_status", identity_status)
    monkeypatch.setattr(instance_ops, "CleanupManager", SuccessfulCleanup)
    monkeypatch.setattr(instance_ops, "resolve_instance", lambda _ref: str(tmp_path))

    assert instance_ops.stop_instance(Namespace(instance=str(tmp_path))) == 0
    assert not lock_path.exists()


def test_stop_retains_lock_when_verified_owner_survives(tmp_path, monkeypatch):
    metadata_dir = _prepare_instance(tmp_path)
    owner = _owner()
    lock_path = _write_instance_lock(metadata_dir, owner)

    class IncompleteCleanup:
        def __init__(self, **_kwargs):
            pass

        def register_verified_process(self, _pid, _ownership_check):
            pass

        def cleanup(self):
            return False

    monkeypatch.setattr(
        instance_lock_manager,
        "process_identity_status",
        lambda _owner: instance_lock_manager.IDENTITY_OWNED,
    )
    monkeypatch.setattr(
        instance_ops,
        "process_identity_status",
        lambda _owner: instance_lock_manager.IDENTITY_OWNED,
    )
    monkeypatch.setattr(instance_ops, "CleanupManager", IncompleteCleanup)
    monkeypatch.setattr(instance_ops, "resolve_instance", lambda _ref: str(tmp_path))

    assert instance_ops.stop_instance(Namespace(instance=str(tmp_path))) == 1
    assert lock_path.exists()


def test_stop_without_process_or_worker_state_is_idempotent(tmp_path, monkeypatch):
    _prepare_instance(tmp_path, metadata_state="completed")
    monkeypatch.setattr(instance_ops, "resolve_instance", lambda _ref: str(tmp_path))

    assert instance_ops.stop_instance(Namespace(instance=str(tmp_path))) == 0


def test_stop_never_signals_live_process_with_reused_identity(tmp_path, monkeypatch):
    metadata_dir = _prepare_instance(tmp_path, metadata_state="completed")
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
    )
    try:
        actual_owner = instance_lock_manager.capture_process_identity(process.pid)
        assert actual_owner is not None
        reused_owner = dict(
            actual_owner,
            start_ticks=actual_owner["start_ticks"] + 1,
        )
        lock_path = _write_instance_lock(metadata_dir, reused_owner)
        monkeypatch.setattr(
            instance_ops,
            "resolve_instance",
            lambda _ref: str(tmp_path),
        )

        assert instance_ops.stop_instance(Namespace(instance=str(tmp_path))) == 0
        assert process.poll() is None
        assert not lock_path.exists()
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_forced_stop_retains_nonterminal_lock(tmp_path, monkeypatch):
    metadata_dir = _prepare_instance(tmp_path)
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import signal,time; "
                "signal.signal(signal.SIGINT, signal.SIG_IGN); "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "print('ready', flush=True); "
                "time.sleep(60)"
            ),
        ],
        start_new_session=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout.readline().strip() == "ready"
        owner = instance_lock_manager.capture_process_identity(process.pid)
        assert owner is not None
        lock_path = _write_instance_lock(metadata_dir, owner)
        monkeypatch.setattr(
            instance_ops,
            "resolve_instance",
            lambda _ref: str(tmp_path),
        )
        monkeypatch.setattr(instance_ops, "INSTANCE_STOP_SIGINT_GRACE_SECONDS", 0)
        monkeypatch.setattr("floability.cleanup.SIGTERM_GRACE_SECONDS", 0)
        monkeypatch.setattr("floability.cleanup.SIGKILL_GRACE_SECONDS", 0)

        assert instance_ops.stop_instance(Namespace(instance=str(tmp_path))) == 1
        assert lock_path.exists()
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
