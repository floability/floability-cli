"""State/lock manager for Floability instances and workers.

Provides simple file-based locking to prevent duplicate runs or worker
factories for the same instance. Each lock file is created atomically
and contains JSON metadata (pid, timestamp).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

INSTANCE_LOCK_NAME = "instance.lock"
WORKERS_LOCK_NAME = "workers.lock"


def _lock_path(instance_path: Path, lock_name: str) -> Path:
    return instance_path / "metadata" / lock_name


def _write_lock_file(lock_path: Path) -> None:
    data = {
        "pid": os.getpid(),
        "timestamp": time.time(),
    }
    with open(lock_path, "w") as f:
        json.dump(data, f)


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
    except OSError:
        return False


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
    # Atomic create
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        _write_lock_file(lock_path)
        return True
    except FileExistsError:
        return False


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
    return acquire_lock(instance_path, WORKERS_LOCK_NAME)


def release_workers_lock(instance_path: Path) -> None:
    release_lock(instance_path, WORKERS_LOCK_NAME)


def are_workers_running(instance_path: Path) -> bool:
    return is_lock_active(instance_path, WORKERS_LOCK_NAME)
