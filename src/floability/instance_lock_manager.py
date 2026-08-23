"""State/lock manager for Floability instances and workers.

Provides simple file-based locking to prevent duplicate runs or worker
factories for the same instance. Each lock file is created atomically
and contains JSON metadata (pid, timestamp).
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Optional

INSTANCE_LOCK_NAME = "instance.lock"
WORKERS_LOCK_NAME = "workers.lock"


def _lock_path(instance_path: Path, lock_name: str) -> Path:
    return instance_path / "metadata" / lock_name


def _create_lock_file(lock_path: Path, data: dict) -> bool:
    """Publish a complete lock file without exposing partially written JSON."""
    fd, temporary_path = tempfile.mkstemp(
        prefix=f".{lock_path.name}.",
        suffix=".tmp",
        dir=lock_path.parent,
    )
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary_path, lock_path)
            return True
        except FileExistsError:
            return False
    finally:
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass


def _replace_lock_file(lock_path: Path, data: dict) -> None:
    """Atomically replace an existing lock with updated ownership data."""
    fd, temporary_path = tempfile.mkstemp(
        prefix=f".{lock_path.name}.",
        suffix=".tmp",
        dir=lock_path.parent,
    )
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, lock_path)
    finally:
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass


def _read_lock_file(lock_path: Path) -> Optional[dict]:
    if not lock_path.exists():
        return None
    try:
        with open(lock_path, "r") as f:
            return json.load(f)
    except Exception:
        return None


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _process_group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def is_process_alive(pid: int) -> bool:
    """Return whether a process exists, including one owned by another user."""
    return _process_alive(pid)


def is_process_group_alive(pgid: int) -> bool:
    """Return whether a process group exists, including an inaccessible one."""
    return _process_group_alive(pgid)


def acquire_lock(instance_path: Path, lock_name: str) -> bool:
    lock_path = _lock_path(instance_path, lock_name)
    metadata_dir = lock_path.parent
    metadata_dir.mkdir(parents=True, exist_ok=True)

    if lock_path.exists():
        data = _read_lock_file(lock_path) or {}
        pid = data.get("pid")
        if pid and _process_alive(pid):
            return False  # Active lock
        else:
            try:
                lock_path.unlink()
            except OSError:
                return False
    return _create_lock_file(
        lock_path,
        {
            "pid": os.getpid(),
            "timestamp": time.time(),
        },
    )


def release_lock(instance_path: Path, lock_name: str) -> None:
    lock_path = _lock_path(instance_path, lock_name)
    if lock_path.exists():
        try:
            lock_path.unlink()
        except OSError:
            pass


def is_lock_active(instance_path: Path, lock_name: str) -> bool:
    lock_path = _lock_path(instance_path, lock_name)
    data = _read_lock_file(lock_path)
    if not data:
        return False
    pid = data.get("pid")
    return bool(pid and _process_alive(pid))


# High-level instance helpers -------------------------------------------------


def acquire_instance_lock(instance_path: Path) -> bool:
    return acquire_lock(instance_path, INSTANCE_LOCK_NAME)


def release_instance_lock(instance_path: Path) -> None:
    release_lock(instance_path, INSTANCE_LOCK_NAME)


def is_instance_running(instance_path: Path) -> bool:
    return is_lock_active(instance_path, INSTANCE_LOCK_NAME)


# High-level workers helpers --------------------------------------------------


def acquire_workers_lock(instance_path: Path) -> bool:
    """Atomically reserve worker startup for the current Floability process."""
    lock_path = _lock_path(instance_path, WORKERS_LOCK_NAME)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    if lock_path.exists():
        data = _read_lock_file(lock_path)
        if data and _workers_lock_active(data):
            return False
        try:
            lock_path.unlink()
        except OSError:
            return False

    return _create_lock_file(
        lock_path,
        {
            "state": "starting",
            "launcher_pid": os.getpid(),
            "created_at": time.time(),
        },
    )


def promote_workers_lock(
    instance_path: Path,
    factory_pid: int,
    factory_pgid: int,
    manager_name: str,
) -> bool:
    """Transfer a startup reservation to the launched factory process group."""
    lock_path = _lock_path(instance_path, WORKERS_LOCK_NAME)
    data = _read_lock_file(lock_path)
    if not data:
        return False
    if data.get("state") != "starting":
        return False
    if data.get("launcher_pid") != os.getpid():
        return False

    _replace_lock_file(
        lock_path,
        {
            "state": "running",
            "factory_pid": factory_pid,
            "factory_pgid": factory_pgid,
            "manager_name": manager_name,
            "created_at": data.get("created_at", time.time()),
            "updated_at": time.time(),
        },
    )
    return True


def release_workers_lock(
    instance_path: Path,
    *,
    expected_launcher_pid: Optional[int] = None,
    expected_factory_pid: Optional[int] = None,
    expected_factory_pgid: Optional[int] = None,
    expected_legacy_pid: Optional[int] = None,
) -> bool:
    """Release a worker lock, optionally only when ownership still matches."""
    lock_path = _lock_path(instance_path, WORKERS_LOCK_NAME)
    if not lock_path.exists():
        return True

    if any(
        expected is not None
        for expected in (
            expected_launcher_pid,
            expected_factory_pid,
            expected_factory_pgid,
            expected_legacy_pid,
        )
    ):
        data = _read_lock_file(lock_path)
        if not data:
            return False
        if (
            expected_launcher_pid is not None
            and data.get("launcher_pid") != expected_launcher_pid
        ):
            return False
        if (
            expected_factory_pid is not None
            and data.get("factory_pid") != expected_factory_pid
        ):
            return False
        if (
            expected_factory_pgid is not None
            and data.get("factory_pgid") != expected_factory_pgid
        ):
            return False
        if (
            expected_legacy_pid is not None
            and data.get("pid") != expected_legacy_pid
        ):
            return False

    try:
        lock_path.unlink()
        return True
    except OSError:
        return False


def are_workers_running(instance_path: Path) -> bool:
    data = _read_lock_file(_lock_path(instance_path, WORKERS_LOCK_NAME))
    return bool(data and _workers_lock_active(data))


def read_workers_lock(instance_path: Path) -> Optional[dict]:
    """Return worker lock ownership data, or ``None`` when unavailable."""
    return _read_lock_file(_lock_path(instance_path, WORKERS_LOCK_NAME))


def _workers_lock_active(data: dict) -> bool:
    state = data.get("state")
    if state == "starting":
        launcher_pid = data.get("launcher_pid")
        return bool(launcher_pid and _process_alive(launcher_pid))
    if state == "running":
        factory_pgid = data.get("factory_pgid")
        if factory_pgid:
            return _process_group_alive(factory_pgid)
        factory_pid = data.get("factory_pid")
        return bool(factory_pid and _process_alive(factory_pid))

    # Backward compatibility with the original generic worker-lock format.
    legacy_pid = data.get("pid")
    return bool(legacy_pid and _process_alive(legacy_pid))
