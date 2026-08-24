"""
Instance metadata management for Floability execution sandboxes.
Captures comprehensive execution context for reproducibility and auditing.
"""

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def _utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp using the existing trailing-Z format."""

    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def get_git_commit(repo_path: Path) -> Optional[str]:
    """
    Get the current git commit hash for a repository.
    Returns None if not a git repo or git is unavailable.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return None


def compute_file_hash(file_path: Path) -> Optional[str]:
    """
    Compute SHA-256 hash of a file.
    Returns None if file doesn't exist or can't be read.
    """
    try:
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
    except (OSError, IOError):
        return None


def create_instance_metadata(
    instance_dir: Path,
    backpack_path: Optional[Path],
    cli_args: Dict[str, Any],
    manager_name: str,
    execution_mode: str,
    environment_spec: Optional[Path] = None,
    worker_environment_spec: Optional[Path] = None,
    data_spec: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Create comprehensive metadata dictionary for an execution instance.

    Args:
        instance_dir: Path to floability instance directory
        backpack_path: Path to source backpack (if any)
        cli_args: Dictionary of command-line arguments
        manager_name: TaskVine manager name
        execution_mode: "run" or "execute"
        environment_spec: Path to environment.yml
        worker_environment_spec: Path to worker-environment.yml
        data_spec: Path to data.yml

    Returns:
        Dictionary containing all metadata
    """
    metadata = {
        "schema_version": "1.0",
        "instance_id": instance_dir.name,
        "instance_path": str(instance_dir.resolve()),
        "created_at": _utc_timestamp(),
        "execution_mode": execution_mode,
        "manager_name": manager_name,
    }

    # Backpack information
    if backpack_path:
        metadata["backpack"] = {
            "path": str(backpack_path.resolve()),
            "name": backpack_path.name,
            "git_commit": get_git_commit(backpack_path),
        }

    # CLI arguments (sanitized)
    metadata["cli_args"] = {
        k: str(v) if v is not None else None
        for k, v in cli_args.items()
        if not k.startswith("_")  # Skip private attributes
    }

    # Environment information
    metadata["environment"] = {}
    if environment_spec:
        metadata["environment"]["manager_spec"] = str(environment_spec)
        metadata["environment"]["manager_spec_hash"] = compute_file_hash(
            environment_spec
        )

    if worker_environment_spec:
        metadata["environment"]["worker_spec"] = str(worker_environment_spec)
        metadata["environment"]["worker_spec_hash"] = compute_file_hash(
            worker_environment_spec
        )

    # Data specification
    if data_spec:
        metadata["data"] = {
            "spec_path": str(data_spec),
            "spec_hash": compute_file_hash(data_spec),
            "profile": cli_args.get("data_profile"),
            "cache_mode": cli_args.get("data_cache_mode", "off"),
            "cache_dirs": [],  # Will be populated during data operations
        }

    # Execution context
    metadata["context"] = {
        "update_backpack": not cli_args.get("no_update_backpack", False),
        "no_worker": cli_args.get("no_worker", False),
        "batch_type": cli_args.get("batch_type", "local"),
        "max_workers": cli_args.get("workers", 0),
    }

    # Execution status (will be updated)
    metadata["status"] = {
        "state": "initializing",
        "started_at": _utc_timestamp(),
        "completed_at": None,
        "success": None,
        "error": None,
    }
    if execution_mode == "instance":
        metadata["preparation"] = {
            "state": "preparing",
            "started_at": _utc_timestamp(),
            "completed_at": None,
            "success": None,
            "error": None,
        }

    return metadata


def update_instance_metadata(
    metadata_path: Path,
    updates: Dict[str, Any],
    merge: bool = True,
) -> None:
    """
    Update instance metadata file with new information.

    Args:
        metadata_path: Path to run.json
        updates: Dictionary of updates to apply
        merge: If True, merge with existing data; if False, overwrite
    """
    existing = {}
    if merge and metadata_path.exists():
        try:
            with open(metadata_path, "r") as f:
                existing = json.load(f)
        except (OSError, json.JSONDecodeError):
            pass

    # Deep merge for nested dictionaries
    def deep_merge(base: dict, update: dict) -> dict:
        result = base.copy()
        for key, value in update.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    merged = deep_merge(existing, updates) if merge else updates

    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    with open(metadata_path, "w") as f:
        json.dump(merged, f, indent=2, default=str)


def record_sync_manifest(
    metadata_dir: Path,
    synced_files: List[Dict[str, str]],
    source_dir: Path,
    target_dir: Path,
) -> None:
    """
    Record what was synced back to the backpack.

    Args:
        metadata_dir: Path to metadata directory
        synced_files: List of dicts with file info (name, hash, size)
        source_dir: Source directory (workflow)
        target_dir: Target directory (backpack)
    """
    sync_manifest = {
        "schema_version": "1.0",
        "synced_at": _utc_timestamp(),
        "source": str(source_dir),
        "target": str(target_dir),
        "files": synced_files,
        "file_count": len(synced_files),
    }

    sync_path = metadata_dir / "sync.json"
    with open(sync_path, "w") as f:
        json.dump(sync_manifest, f, indent=2)


def add_data_cache_dirs(metadata_path: Path, cache_dirs: List[str]) -> None:
    """
    Add data cache directory paths to metadata.

    Args:
        metadata_path: Path to run.json
        cache_dirs: List of cache directory paths used during data fetch
    """
    if not metadata_path.exists():
        return

    try:
        with open(metadata_path, "r") as f:
            metadata = json.load(f)

        if "data" not in metadata:
            metadata["data"] = {}

        existing = metadata["data"].get("cache_dirs") or []
        merged = list(dict.fromkeys(existing + cache_dirs))  # deduplicate, preserve order
        metadata["data"]["cache_dirs"] = merged

        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2, default=str)
    except (OSError, json.JSONDecodeError):
        pass


def finalize_instance_metadata(
    metadata_path: Path,
    success: bool,
    error: Optional[str] = None,
    state: Optional[str] = None,
) -> None:
    """
    Mark instance execution as completed.

    Args:
        metadata_path: Path to run.json
        success: Whether execution succeeded
        error: Error message if failed
        state: Optional explicit terminal state, such as ``interrupted``
    """
    updates = {
        "status": {
            "state": state or ("completed" if success else "failed"),
            "completed_at": _utc_timestamp(),
            "success": success,
            "error": error,
        }
    }
    update_instance_metadata(metadata_path, updates, merge=True)


def finalize_instance_preparation(
    metadata_path: Path,
    success: bool,
    error: Optional[str] = None,
) -> None:
    """Finalize standalone instance preparation as ready or failed."""

    completed_at = _utc_timestamp()
    state = "ready" if success else "failed"
    update_instance_metadata(
        metadata_path,
        {
            "preparation": {
                "state": state,
                "completed_at": completed_at,
                "success": success,
                "error": error,
            },
            "status": {
                "state": state,
                "completed_at": completed_at,
                "success": success,
                "error": error,
            },
        },
        merge=True,
    )


def persist_prepared_environment(
    metadata_path: Path,
    *,
    env_dir: Optional[str],
    worker_environment_pack: Optional[str],
    manager_environment_pack: Optional[str],
    environment_spec: Optional[str],
    worker_environment_spec: Optional[str],
    per_instance_env: bool,
) -> None:
    """Persist the complete, rebuildable environment preparation result.

    The top-level fields remain for compatibility with worker and run code.
    The nested ``environment`` object is the coherent record for newer
    instances and includes both source specifications and resolved artifacts.
    """

    manager_spec = (
        str(Path(environment_spec).expanduser().resolve())
        if environment_spec
        else None
    )
    worker_spec = (
        str(Path(worker_environment_spec).expanduser().resolve())
        if worker_environment_spec
        else None
    )
    resolved_env_dir = str(Path(env_dir).expanduser().resolve()) if env_dir else None
    resolved_worker_pack = (
        str(Path(worker_environment_pack).expanduser().resolve())
        if worker_environment_pack
        else None
    )
    resolved_manager_pack = (
        str(Path(manager_environment_pack).expanduser().resolve())
        if manager_environment_pack
        else None
    )

    update_instance_metadata(
        metadata_path,
        {
            "env_dir": resolved_env_dir,
            "worker_environment_pack": resolved_worker_pack,
            "manager_environment_pack": resolved_manager_pack,
            "environment_spec": manager_spec,
            "worker_environment_spec": worker_spec,
            "per_instance_env": bool(per_instance_env),
            "environment": {
                "strategy": "per-instance" if per_instance_env else "shared",
                "manager_spec": manager_spec,
                "manager_spec_hash": (
                    compute_file_hash(Path(manager_spec)) if manager_spec else None
                ),
                "worker_spec": worker_spec,
                "worker_spec_hash": (
                    compute_file_hash(Path(worker_spec)) if worker_spec else None
                ),
                "env_dir": resolved_env_dir,
                "manager_pack": resolved_manager_pack,
                "worker_pack": resolved_worker_pack,
            },
        },
        merge=True,
    )


def read_prepared_environment(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Read environment preparation fields with legacy-key fallbacks."""

    environment = metadata.get("environment")
    if not isinstance(environment, dict):
        environment = {}

    strategy = environment.get("strategy")
    per_instance_env = metadata.get("per_instance_env")
    if per_instance_env is None:
        per_instance_env = strategy == "per-instance"

    return {
        "environment_spec": metadata.get("environment_spec")
        or environment.get("manager_spec"),
        "worker_environment_spec": metadata.get("worker_environment_spec")
        or environment.get("worker_spec"),
        "per_instance_env": bool(per_instance_env),
        "env_dir": metadata.get("env_dir") or environment.get("env_dir"),
        "manager_environment_pack": metadata.get("manager_environment_pack")
        or environment.get("manager_pack"),
        "worker_environment_pack": metadata.get("worker_environment_pack")
        or environment.get("worker_pack"),
    }
