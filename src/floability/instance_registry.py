"""Persistent registries for Floability instances and recently used bases."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - Floability targets Linux HPC systems.
    fcntl = None


REGISTRY_FILENAME = "instances.json"
BASE_DIRECTORIES_FILENAME = "base-directories.json"
REGISTRY_LOCK_FILENAME = ".registries.lock"

# Keep a small history for diagnostics and future selection without allowing
# paths accumulated over years of runs to grow this user-level file forever.
MAX_RECENT_BASE_DIRECTORIES = 10


class RegistryError(RuntimeError):
    """Raised when registry state cannot be read or safely interpreted."""


def _user_data_dir() -> Path:
    if os.name == "nt":  # Windows
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) / "Floability" if appdata else Path.home() / "Floability"
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        if xdg:
            base = Path(xdg) / "floability"
        else:
            base = Path.home() / ".local" / "share" / "floability"
    base.mkdir(parents=True, exist_ok=True)
    return base


def registry_path() -> Path:
    return _user_data_dir() / REGISTRY_FILENAME


def base_directories_registry_path() -> Path:
    return _user_data_dir() / BASE_DIRECTORIES_FILENAME


@contextmanager
def _registry_lock():
    """Serialize registry read-modify-write transactions for this user."""
    lock_path = _user_data_dir() / REGISTRY_LOCK_FILENAME
    with open(lock_path, "a+") as lock_stream:
        if fcntl is not None:
            fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _timestamp_value(value) -> float:
    if not isinstance(value, str) or not value.strip():
        return float("-inf")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return float("-inf")


def _normalized_path(value) -> str:
    if not isinstance(value, (str, os.PathLike)) or not str(value).strip():
        raise RegistryError("Registry path must be a non-empty string.")
    return str(Path(value).expanduser().resolve())


def _atomic_write_json(path: Path, data: dict) -> None:
    fd, temporary_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass


def _read_json_object(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    try:
        with open(path) as stream:
            data = json.load(stream)
    except (OSError, json.JSONDecodeError) as error:
        raise RegistryError(f"Could not read registry {path}: {error}") from error
    if not isinstance(data, dict):
        raise RegistryError(f"Registry {path} must contain a JSON object.")
    return data


def _load_instance_registry_unlocked() -> dict:
    data = _read_json_object(
        registry_path(),
        {"schema_version": 1, "instances": {}},
    )
    instances = data.get("instances")
    if not isinstance(instances, dict):
        raise RegistryError("instances.json field 'instances' must be an object.")
    return data


def _load_base_registry_unlocked() -> dict:
    data = _read_json_object(
        base_directories_registry_path(),
        {"schema_version": 1, "base_directories": []},
    )
    entries = data.get("base_directories")
    if not isinstance(entries, list):
        raise RegistryError(
            "base-directories.json field 'base_directories' must be a list."
        )
    return data


def load_registry() -> dict:
    with _registry_lock():
        return _load_instance_registry_unlocked()


def save_registry(registry: dict) -> None:
    """Atomically replace instances.json while holding the shared registry lock."""
    with _registry_lock():
        if not isinstance(registry.get("instances"), dict):
            raise RegistryError("instances.json field 'instances' must be an object.")
        _atomic_write_json(registry_path(), registry)


def _sanitize(name: str) -> str:
    return name.strip().replace(" ", "_")


def _generate_short_name(
    preferred: str | None,
    instance_path: Path,
    registry: dict,
) -> str:
    resolved_path = instance_path.resolve()
    for existing, metadata in registry["instances"].items():
        if isinstance(metadata, dict) and metadata.get("path"):
            if Path(metadata["path"]).expanduser().resolve() == resolved_path:
                return existing

    base = _sanitize(preferred or instance_path.name)
    candidate = base
    counter = 2
    while candidate in registry["instances"]:
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate


def _metadata_created_at(instance_path: Path) -> str | None:
    metadata_file = instance_path / "metadata" / "run.json"
    try:
        with open(metadata_file) as stream:
            metadata = json.load(stream)
        value = metadata.get("created_at")
        return value if isinstance(value, str) else None
    except (OSError, json.JSONDecodeError, AttributeError):
        return None


def _infer_legacy_last_run_at(instance_path: Path, metadata: dict) -> str | None:
    """Conservatively identify a completed or currently active legacy run."""
    metadata_file = instance_path / "metadata" / "run.json"
    try:
        with open(metadata_file) as stream:
            run_metadata = json.load(stream)
        completed_at = (run_metadata.get("status") or {}).get("completed_at")
        if isinstance(completed_at, str) and completed_at:
            return completed_at
    except (OSError, json.JSONDecodeError, AttributeError):
        pass

    try:
        from .instance_lock_manager import is_instance_running

        if is_instance_running(instance_path):
            last_seen = metadata.get("last_seen")
            return last_seen if isinstance(last_seen, str) else None
    except (OSError, ValueError):
        pass
    return None


def _migrate_instance_record(name: str, metadata: dict) -> tuple[dict, bool]:
    if not isinstance(metadata, dict):
        raise RegistryError(f"Instance registry entry {name!r} must be an object.")
    migrated = dict(metadata)
    instance_path = Path(_normalized_path(migrated.get("path")))
    changed = migrated.get("path") != str(instance_path)
    migrated["path"] = str(instance_path)

    if not migrated.get("base_dir"):
        migrated["base_dir"] = str(instance_path.parent)
        changed = True
    else:
        normalized_base = _normalized_path(migrated["base_dir"])
        if migrated["base_dir"] != normalized_base:
            migrated["base_dir"] = normalized_base
            changed = True

    if "last_run_at" not in migrated:
        migrated["last_run_at"] = _infer_legacy_last_run_at(
            instance_path,
            migrated,
        )
        changed = True
    return migrated, changed


def _path_state(path: Path) -> str:
    """Return present, missing, or unknown without deleting on access errors."""
    try:
        return "present" if stat.S_ISDIR(path.stat().st_mode) else "missing"
    except (FileNotFoundError, NotADirectoryError):
        return "missing"
    except OSError:
        return "unknown"


def _maintain_instance_registry_unlocked(registry: dict) -> tuple[dict, int, bool]:
    maintained = {}
    removed = 0
    changed = False
    for name, metadata in registry["instances"].items():
        migrated, was_migrated = _migrate_instance_record(name, metadata)
        state = _path_state(Path(migrated["path"]))
        if state == "missing":
            removed += 1
            changed = True
            continue
        maintained[name] = migrated
        changed = changed or was_migrated
    registry["instances"] = maintained
    return registry, removed, changed


def register_instance(
    instance_path: Path,
    manager_name: str,
    preferred_name: str | None = None,
    tags: list | None = None,
    base_dir: Path | None = None,
) -> str:
    resolved_path = instance_path.resolve()
    resolved_base = (base_dir or resolved_path.parent).expanduser().resolve()
    with _registry_lock():
        registry = _load_instance_registry_unlocked()
        short_name = _generate_short_name(preferred_name, resolved_path, registry)
        existing = registry["instances"].get(short_name, {})
        created_at = existing.get("created_at") or _metadata_created_at(resolved_path)
        registry["instances"][short_name] = {
            "path": str(resolved_path),
            "base_dir": str(resolved_base),
            "created_at": created_at or _utc_now(),
            "last_run_at": existing.get("last_run_at"),
            "last_seen": _utc_now(),
            "manager_name": manager_name,
            "tags": tags if tags is not None else existing.get("tags", []),
        }
        _atomic_write_json(registry_path(), registry)
    return short_name


def _sorted_base_entries(entries: list[dict]) -> list[dict]:
    normalized = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise RegistryError("Each base-directory registry entry must be an object.")
        path = _normalized_path(entry.get("path"))
        used_at = entry.get("last_used_at")
        if _timestamp_value(used_at) == float("-inf"):
            raise RegistryError(f"Base directory {path} has an invalid last_used_at.")
        previous = normalized.get(path)
        if previous is None or _timestamp_value(used_at) > _timestamp_value(
            previous["last_used_at"]
        ):
            normalized[path] = {"path": path, "last_used_at": used_at}
    return sorted(
        normalized.values(),
        key=lambda entry: (-_timestamp_value(entry["last_used_at"]), entry["path"]),
    )


def _record_base_directory_unlocked(
    registry: dict,
    base_dir: Path,
    used_at: str,
) -> dict:
    entries = list(registry["base_directories"])
    entries.append(
        {
            "path": str(base_dir.expanduser().resolve()),
            "last_used_at": used_at,
        }
    )
    registry["base_directories"] = _sorted_base_entries(entries)[
        :MAX_RECENT_BASE_DIRECTORIES
    ]
    return registry


def record_instance_run(
    instance_path: Path,
    base_dir: Path,
    manager_name: str | None = None,
    ran_at: str | None = None,
) -> str:
    """Record one accepted run and update the recent-base registry."""
    resolved_path = instance_path.expanduser().resolve()
    resolved_base = base_dir.expanduser().resolve()
    timestamp = ran_at or _utc_now()
    if _timestamp_value(timestamp) == float("-inf"):
        raise ValueError("ran_at must be an ISO-8601 timestamp.")

    with _registry_lock():
        instance_registry = _load_instance_registry_unlocked()
        short_name = _generate_short_name(None, resolved_path, instance_registry)
        existing = instance_registry["instances"].get(short_name, {})
        instance_registry["instances"][short_name] = {
            "path": str(resolved_path),
            "base_dir": str(resolved_base),
            "created_at": existing.get("created_at")
            or _metadata_created_at(resolved_path)
            or timestamp,
            "last_run_at": timestamp,
            "last_seen": timestamp,
            "manager_name": manager_name or existing.get("manager_name"),
            "tags": existing.get("tags", []),
        }

        base_registry = _load_base_registry_unlocked()
        _record_base_directory_unlocked(base_registry, resolved_base, timestamp)

        _atomic_write_json(registry_path(), instance_registry)
        _atomic_write_json(base_directories_registry_path(), base_registry)
    return short_name


def refresh_instance_registry_entry(ref: str) -> None:
    path = resolve_instance(ref)
    if not path:
        return
    resolved_path = str(Path(path).resolve())
    with _registry_lock():
        registry = _load_instance_registry_unlocked()
        for metadata in registry["instances"].values():
            if isinstance(metadata, dict) and metadata.get("path") == resolved_path:
                metadata["last_seen"] = _utc_now()
                _atomic_write_json(registry_path(), registry)
                return


def resolve_instance(ref: str) -> str | None:
    path = Path(ref)
    if path.is_dir():
        return str(path.resolve())
    with _registry_lock():
        registry = _load_instance_registry_unlocked()
        metadata = registry["instances"].get(ref)
        if isinstance(metadata, dict):
            value = metadata.get("path")
            return str(value) if value else None
    return None


def list_instances() -> dict[str, dict]:
    with _registry_lock():
        return dict(_load_instance_registry_unlocked()["instances"])


def instance_status(short_name: str) -> dict | None:
    statuses = get_registered_instances_status()
    return statuses.get(short_name)


def _sorted_instance_statuses(instances: dict[str, dict]) -> dict[str, dict]:
    items = list(instances.items())
    items.sort(key=lambda item: item[0])
    items.sort(
        key=lambda item: (
            item[1].get("last_run_at") is not None,
            _timestamp_value(item[1].get("last_run_at")),
            _timestamp_value(item[1].get("created_at")),
        ),
        reverse=True,
    )
    return dict(items)


def get_registered_instances_status() -> dict[str, dict]:
    """Return one maintained, globally sorted snapshot of registered instances."""
    with _registry_lock():
        registry = _load_instance_registry_unlocked()
        registry, _removed, changed = _maintain_instance_registry_unlocked(registry)
        if changed:
            _atomic_write_json(registry_path(), registry)
        snapshot = dict(registry["instances"])

    from .instance_lock_manager import is_instance_running

    statuses = {}
    for name, metadata in snapshot.items():
        path = Path(metadata["path"])
        path_state = _path_state(path)
        statuses[name] = {
            "short_name": name,
            **metadata,
            "path_state": path_state,
            "exists": path_state == "present",
            "running": path_state == "present" and is_instance_running(path),
        }
    return _sorted_instance_statuses(statuses)


def prune_nonexistent_entries() -> int:
    with _registry_lock():
        registry = _load_instance_registry_unlocked()
        registry, removed, changed = _maintain_instance_registry_unlocked(registry)
        if changed:
            _atomic_write_json(registry_path(), registry)
        return removed


def get_recent_base_directories(
    valid_bases: set[str] | None = None,
) -> list[dict]:
    """Return timestamp-sorted recent bases, safely pruning unusable entries."""
    normalized_valid = (
        {_normalized_path(path) for path in valid_bases}
        if valid_bases is not None
        else None
    )
    with _registry_lock():
        registry = _load_base_registry_unlocked()
        original = registry["base_directories"]
        entries = _sorted_base_entries(original)
        maintained = []
        for entry in entries:
            if normalized_valid is not None and entry["path"] not in normalized_valid:
                continue
            if _path_state(Path(entry["path"])) == "missing":
                continue
            maintained.append(entry)
        maintained = maintained[:MAX_RECENT_BASE_DIRECTORIES]
        registry["base_directories"] = maintained
        if maintained != original:
            _atomic_write_json(base_directories_registry_path(), registry)
        return maintained


def seed_base_directories_from_instances(instances: dict[str, dict]) -> list[dict]:
    """Reconcile recent-base history from authoritative instance run records."""
    candidates = {}
    for metadata in instances.values():
        base_dir = metadata.get("base_dir")
        last_run_at = metadata.get("last_run_at")
        if not base_dir or _timestamp_value(last_run_at) == float("-inf"):
            continue
        normalized_base = _normalized_path(base_dir)
        if _path_state(Path(normalized_base)) == "missing":
            continue
        current = candidates.get(normalized_base)
        if current is None or _timestamp_value(last_run_at) > _timestamp_value(current):
            candidates[normalized_base] = last_run_at

    with _registry_lock():
        registry = _load_base_registry_unlocked()
        original = list(registry["base_directories"])
        for path, used_at in candidates.items():
            _record_base_directory_unlocked(registry, Path(path), used_at)
        if registry["base_directories"] != original:
            _atomic_write_json(base_directories_registry_path(), registry)
        return _sorted_base_entries(registry["base_directories"])[
            :MAX_RECENT_BASE_DIRECTORIES
        ]


__all__ = [
    "BASE_DIRECTORIES_FILENAME",
    "MAX_RECENT_BASE_DIRECTORIES",
    "REGISTRY_FILENAME",
    "RegistryError",
    "base_directories_registry_path",
    "get_recent_base_directories",
    "get_registered_instances_status",
    "instance_status",
    "list_instances",
    "load_registry",
    "prune_nonexistent_entries",
    "record_instance_run",
    "refresh_instance_registry_entry",
    "register_instance",
    "registry_path",
    "resolve_instance",
    "save_registry",
    "seed_base_directories_from_instances",
]
