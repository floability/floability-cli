"""Ownership-aware lock management for Floability instances and workers."""

from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - Floability targets Linux HPC systems.
    fcntl = None


INSTANCE_LOCK_NAME = "instance.lock"
WORKERS_LOCK_NAME = "workers.lock"
LOCK_SCHEMA_VERSION = 2

IDENTITY_OWNED = "owned"
IDENTITY_GONE = "gone"
IDENTITY_MISMATCHED = "mismatched"
IDENTITY_UNVERIFIABLE = "unverifiable"


def _lock_path(instance_path: Path, lock_name: str) -> Path:
    return instance_path / "metadata" / lock_name


@contextmanager
def _lock_guard(instance_path: Path, lock_name: str):
    """Serialize lock-file replacement and conditional deletion."""
    metadata_dir = instance_path / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    guard_path = metadata_dir / f".{lock_name}.guard"
    with open(guard_path, "a+") as guard_stream:
        if fcntl is not None:
            fcntl.flock(guard_stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(guard_stream.fileno(), fcntl.LOCK_UN)


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


def _read_lock_file(lock_path: Path) -> dict | None:
    if not lock_path.exists():
        return None
    try:
        with open(lock_path) as stream:
            data = json.load(stream)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _read_lock_state(lock_path: Path) -> tuple[str, dict | None]:
    try:
        exists = lock_path.exists()
    except OSError:
        return "unverifiable", None
    if not exists:
        return "missing", None
    data = _read_lock_file(lock_path)
    return ("valid", data) if data is not None else ("corrupt", None)


def _read_boot_id() -> str | None:
    try:
        value = Path("/proc/sys/kernel/random/boot_id").read_text(
            encoding="utf-8"
        )
    except OSError:
        return None
    value = value.strip()
    return value or None


def _read_process_stat(pid: int) -> tuple[str, int, int] | None:
    """Return process state, process group, and Linux start ticks."""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    closing_parenthesis = raw.rfind(")")
    if closing_parenthesis < 0:
        raise ValueError("Malformed /proc process stat record.")
    fields = raw[closing_parenthesis + 2 :].split()
    if len(fields) <= 19:
        raise ValueError("Incomplete /proc process stat record.")
    return fields[0], int(fields[2]), int(fields[19])


def capture_process_identity(pid: int | None = None) -> dict | None:
    """Capture a Linux process identity that remains safe across PID reuse."""
    process_pid = pid if pid is not None else os.getpid()
    try:
        process_stat = _read_process_stat(process_pid)
        boot_id = _read_boot_id()
    except (OSError, ValueError):
        return None
    if process_stat is None or boot_id is None:
        return None
    state, pgid, start_ticks = process_stat
    if state == "Z":
        return None
    return {
        "pid": process_pid,
        "pgid": pgid,
        "start_ticks": start_ticks,
        "boot_id": boot_id,
    }


def _valid_process_identity(identity: object) -> bool:
    return bool(
        isinstance(identity, dict)
        and isinstance(identity.get("pid"), int)
        and identity["pid"] > 0
        and isinstance(identity.get("pgid"), int)
        and identity["pgid"] > 0
        and isinstance(identity.get("start_ticks"), int)
        and identity["start_ticks"] >= 0
        and isinstance(identity.get("boot_id"), str)
        and identity["boot_id"]
    )


def process_identity_status(identity: object) -> str:
    """Return owned, gone, mismatched, or unverifiable for one process."""
    if not _valid_process_identity(identity):
        return IDENTITY_UNVERIFIABLE
    boot_id = _read_boot_id()
    if boot_id is None:
        return IDENTITY_UNVERIFIABLE
    if boot_id != identity["boot_id"]:
        return IDENTITY_MISMATCHED
    try:
        process_stat = _read_process_stat(identity["pid"])
    except (PermissionError, OSError, ValueError):
        return IDENTITY_UNVERIFIABLE
    if process_stat is None:
        return IDENTITY_GONE
    state, pgid, start_ticks = process_stat
    if state == "Z":
        return IDENTITY_GONE
    if pgid != identity["pgid"] or start_ticks != identity["start_ticks"]:
        return IDENTITY_MISMATCHED
    return IDENTITY_OWNED


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


def process_group_identity_status(identity: object) -> str:
    """Validate a process group created by a saved session-leader identity."""
    if not _valid_process_identity(identity):
        return IDENTITY_UNVERIFIABLE
    if identity["pid"] != identity["pgid"]:
        return IDENTITY_UNVERIFIABLE

    leader_status = process_identity_status(identity)
    if leader_status in {
        IDENTITY_OWNED,
        IDENTITY_MISMATCHED,
        IDENTITY_UNVERIFIABLE,
    }:
        return leader_status

    # If the original session leader exited while descendants remain, Linux
    # keeps the original PGID but has no process whose PID equals that PGID.
    return IDENTITY_OWNED if _process_group_alive(identity["pgid"]) else IDENTITY_GONE


def is_process_alive(pid: int) -> bool:
    """Return whether a process exists, including one owned by another user."""
    return _process_alive(pid)


def is_process_group_alive(pgid: int) -> bool:
    """Return whether a process group exists, including an inaccessible one."""
    return _process_group_alive(pgid)


def _instance_lock_status_unlocked(instance_path: Path) -> dict:
    lock_path = _lock_path(instance_path, INSTANCE_LOCK_NAME)
    file_state, data = _read_lock_state(lock_path)
    result = {
        "state": file_state,
        "lock_data": data,
        "owner": data.get("owner") if data else None,
    }
    if file_state != "valid":
        return result

    owner = data.get("owner")
    if owner is not None or data.get("schema_version") == LOCK_SCHEMA_VERSION:
        identity_state = process_identity_status(owner)
        result["identity_state"] = identity_state
        result["state"] = {
            IDENTITY_OWNED: "active",
            IDENTITY_GONE: "stale",
            IDENTITY_MISMATCHED: "mismatched",
            IDENTITY_UNVERIFIABLE: "unverifiable",
        }[identity_state]
        return result

    legacy_pid = data.get("pid")
    if not isinstance(legacy_pid, int) or legacy_pid <= 0:
        result["state"] = "corrupt"
    elif _process_alive(legacy_pid):
        result["state"] = "active_legacy"
    else:
        result["state"] = "stale_legacy"
    return result


def get_instance_lock_status(instance_path: Path) -> dict:
    """Inspect instance ownership without mutating the lock."""
    return _instance_lock_status_unlocked(instance_path)


def read_instance_lock(instance_path: Path) -> dict | None:
    return _read_lock_file(_lock_path(instance_path, INSTANCE_LOCK_NAME))


def acquire_instance_lock(instance_path: Path) -> bool:
    lock_path = _lock_path(instance_path, INSTANCE_LOCK_NAME)
    owner = capture_process_identity()
    if owner is None:
        return False
    with _lock_guard(instance_path, INSTANCE_LOCK_NAME):
        status = _instance_lock_status_unlocked(instance_path)
        if status["state"] not in {"missing", "stale", "mismatched", "stale_legacy"}:
            return False
        if status["state"] != "missing":
            try:
                lock_path.unlink()
            except OSError:
                return False
        return _create_lock_file(
            lock_path,
            {
                "schema_version": LOCK_SCHEMA_VERSION,
                "state": "running",
                "pid": owner["pid"],
                "owner": owner,
                "created_at": time.time(),
            },
        )


def release_instance_lock(
    instance_path: Path,
    *,
    expected_owner: dict | None = None,
) -> bool:
    """Remove only the lock still owned by the expected process identity."""
    expected = expected_owner or capture_process_identity()
    if expected is None:
        return False
    lock_path = _lock_path(instance_path, INSTANCE_LOCK_NAME)
    with _lock_guard(instance_path, INSTANCE_LOCK_NAME):
        file_state, data = _read_lock_state(lock_path)
        if file_state == "missing":
            return True
        if file_state != "valid" or not data:
            return False
        owner = data.get("owner")
        if owner is not None:
            if owner != expected:
                return False
        elif data.get("pid") != expected.get("pid"):
            return False
        try:
            lock_path.unlink()
            return True
        except OSError:
            return False


def mark_instance_cleanup_incomplete(
    instance_path: Path,
    *,
    expected_owner: dict | None = None,
    error: str = "One or more owned processes remained after cleanup.",
    owned_processes_stopped: bool = False,
) -> bool:
    """Retain matching ownership while recording an incomplete cleanup."""
    expected = expected_owner or capture_process_identity()
    if expected is None:
        return False
    lock_path = _lock_path(instance_path, INSTANCE_LOCK_NAME)
    with _lock_guard(instance_path, INSTANCE_LOCK_NAME):
        file_state, data = _read_lock_state(lock_path)
        if file_state != "valid" or not data or data.get("owner") != expected:
            return False
        updated = dict(data)
        updated.update(
            {
                "state": "cleanup_incomplete",
                "cleanup_error": error,
                "cleanup_attempted_at": time.time(),
                "owned_processes_stopped": owned_processes_stopped,
            }
        )
        _replace_lock_file(lock_path, updated)
        return True


def is_instance_running(instance_path: Path) -> bool:
    """Conservatively protect active and unverifiable instance ownership."""
    return get_instance_lock_status(instance_path)["state"] in {
        "active",
        "active_legacy",
        "corrupt",
        "unverifiable",
    }


# High-level workers helpers -------------------------------------------------


def acquire_workers_lock(instance_path: Path) -> bool:
    """Atomically reserve worker startup for the current Floability process."""
    lock_path = _lock_path(instance_path, WORKERS_LOCK_NAME)
    with _lock_guard(instance_path, WORKERS_LOCK_NAME):
        file_state, data = _read_lock_state(lock_path)
        if file_state in {"corrupt", "unverifiable"}:
            return False
        if data and _workers_lock_active(data):
            return False
        if file_state == "valid":
            try:
                lock_path.unlink()
            except OSError:
                return False
        return _create_lock_file(
            lock_path,
            {
                "schema_version": LOCK_SCHEMA_VERSION,
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
    factory_identity: dict | None = None,
) -> bool:
    """Transfer a startup reservation to the launched factory process group."""
    owner = factory_identity or capture_process_identity(factory_pid)
    if (
        not _valid_process_identity(owner)
        or owner["pid"] != factory_pid
        or owner["pgid"] != factory_pgid
        or owner["pid"] != owner["pgid"]
    ):
        return False

    lock_path = _lock_path(instance_path, WORKERS_LOCK_NAME)
    with _lock_guard(instance_path, WORKERS_LOCK_NAME):
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
                "schema_version": LOCK_SCHEMA_VERSION,
                "state": "running",
                "factory_pid": factory_pid,
                "factory_pgid": factory_pgid,
                "factory_owner": owner,
                "manager_name": manager_name,
                "created_at": data.get("created_at", time.time()),
                "updated_at": time.time(),
            },
        )
        return True


def release_workers_lock(
    instance_path: Path,
    *,
    expected_launcher_pid: int | None = None,
    expected_factory_pid: int | None = None,
    expected_factory_pgid: int | None = None,
    expected_factory_owner: dict | None = None,
    expected_legacy_pid: int | None = None,
) -> bool:
    """Release a worker lock only while recorded ownership still matches."""
    lock_path = _lock_path(instance_path, WORKERS_LOCK_NAME)
    with _lock_guard(instance_path, WORKERS_LOCK_NAME):
        file_state, data = _read_lock_state(lock_path)
        if file_state == "missing":
            return True
        if file_state != "valid" or not data:
            return False
        expected_values = (
            ("launcher_pid", expected_launcher_pid),
            ("factory_pid", expected_factory_pid),
            ("factory_pgid", expected_factory_pgid),
            ("factory_owner", expected_factory_owner),
            ("pid", expected_legacy_pid),
        )
        for key, expected in expected_values:
            if expected is not None and data.get(key) != expected:
                return False
        try:
            lock_path.unlink()
            return True
        except OSError:
            return False


def are_workers_running(instance_path: Path) -> bool:
    data = _read_lock_file(_lock_path(instance_path, WORKERS_LOCK_NAME))
    return bool(data and _workers_lock_active(data))


def read_workers_lock(instance_path: Path) -> dict | None:
    """Return worker lock ownership data, or ``None`` when unavailable."""
    return _read_lock_file(_lock_path(instance_path, WORKERS_LOCK_NAME))


def _workers_lock_active(data: dict) -> bool:
    state = data.get("state")
    if state == "starting":
        launcher_pid = data.get("launcher_pid")
        return bool(launcher_pid and _process_alive(launcher_pid))
    if state == "running":
        owner = data.get("factory_owner")
        if owner is not None:
            return process_group_identity_status(owner) in {
                IDENTITY_OWNED,
                IDENTITY_UNVERIFIABLE,
            }
        factory_pgid = data.get("factory_pgid")
        if factory_pgid:
            return _process_group_alive(factory_pgid)
        factory_pid = data.get("factory_pid")
        return bool(factory_pid and _process_alive(factory_pid))

    legacy_pid = data.get("pid")
    return bool(legacy_pid and _process_alive(legacy_pid))
