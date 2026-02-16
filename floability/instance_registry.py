"""Global instance registry for Floability.

Provides a lightweight persistent mapping from a short instance name to its
absolute path and minimal metadata. Enables commands like:

    floability instance list
    floability run --instance myexp
    floability workers status --instance myexp

Without requiring users to remember full paths or a base directory.

Storage location (Linux/macOS):
  $XDG_DATA_HOME/floability/instances.json if XDG_DATA_HOME is set
  Otherwise: ~/.local/share/floability/instances.json

Schema v1:
{
  "schema_version": 1,
  "instances": {
    "short_name": {
        "path": "/abs/path/to/floability_instance_123",
        "created_at": "2025-11-13T12:34:56Z",
        "last_seen": "2025-11-13T12:34:56Z",
        "manager_name": "floability-uuid",
        "tags": []
    }
  }
}
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

REGISTRY_FILENAME = "instances.json"


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


def _utc_now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def load_registry() -> Dict:
    path = registry_path()
    if not path.exists():
        return {"schema_version": 1, "instances": {}}
    try:
        with open(path, "r") as f:
            data = json.load(f)
        if "instances" not in data:
            data["instances"] = {}
        return data
    except Exception:
        return {"schema_version": 1, "instances": {}}


def save_registry(registry: Dict) -> None:
    path = registry_path()
    # Create temporary file in the same directory as the final registry file
    # to ensure os.replace is atomic and avoids cross-device errors (EXDEV).
    tmp_dir = str(path.parent)
    fd, tmp_path = tempfile.mkstemp(
        prefix="floability-reg-", suffix=".tmp", dir=tmp_dir
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(registry, f, indent=2)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _sanitize(name: str) -> str:
    return name.strip().replace(" ", "_")


def _generate_short_name(
    preferred: Optional[str], instance_path: Path, registry: Dict
) -> str:
    base = preferred or instance_path.name
    base = _sanitize(base)
    # If an entry with same path already exists, reuse its short name.
    for existing, meta in registry["instances"].items():
        if Path(meta.get("path", "")) == instance_path.resolve():
            return existing
    candidate = base
    counter = 2
    while candidate in registry["instances"]:
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate


def register_instance(
    instance_path: Path,
    manager_name: str,
    preferred_name: Optional[str] = None,
    tags: Optional[list] = None,
) -> str:
    registry = load_registry()
    short_name = _generate_short_name(preferred_name, instance_path, registry)
    registry["instances"][short_name] = {
        "path": str(instance_path.resolve()),
        "created_at": _utc_now(),
        "last_seen": _utc_now(),
        "manager_name": manager_name,
        "tags": tags or [],
    }
    save_registry(registry)
    return short_name


def refresh_instance_registry_entry(ref: str) -> None:
    path = resolve_instance(ref)
    if not path:
        return
    registry = load_registry()
    for name, meta in registry["instances"].items():
        if meta.get("path") == path:
            meta["last_seen"] = _utc_now()
            break
    save_registry(registry)


def resolve_instance(ref: str) -> Optional[str]:
    p = Path(ref)
    if p.is_dir():
        return str(p.resolve())
    registry = load_registry()
    meta = registry["instances"].get(ref)
    if meta:
        return meta.get("path")
    return None


def list_instances() -> Dict[str, Dict]:
    return load_registry().get("instances", {})


def instance_status(short_name: str) -> Optional[Dict]:
    registry = load_registry()
    meta = registry["instances"].get(short_name)
    if not meta:
        return None
    path = Path(meta["path"])
    exists = path.is_dir()
    lock_file = path / "metadata" / "instance.lock"
    running = lock_file.exists()
    return {
        "short_name": short_name,
        "path": meta["path"],
        "created_at": meta.get("created_at"),
        "last_seen": meta.get("last_seen"),
        "manager_name": meta.get("manager_name"),
        "exists": exists,
        "running": running,
        "tags": meta.get("tags", []),
    }


def prune_nonexistent_entries() -> int:
    """Remove registry entries whose paths no longer exist. Returns count removed."""
    registry = load_registry()
    instances = registry.get("instances", {})
    to_delete = []
    for name, meta in instances.items():
        p = Path(meta.get("path", ""))
        if not p.is_dir():
            to_delete.append(name)
    if not to_delete:
        return 0
    for name in to_delete:
        instances.pop(name, None)
    registry["instances"] = instances
    save_registry(registry)
    return len(to_delete)


__all__ = [
    "register_instance",
    "resolve_instance",
    "list_instances",
    "instance_status",
    "refresh_instance_registry_entry",
    "prune_nonexistent_entries",
]
