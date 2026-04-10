"""
Instance metadata management for Floability execution sandboxes.
Captures comprehensive execution context for reproducibility and auditing.
"""

import json
import subprocess
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List


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
        "created_at": datetime.utcnow().isoformat() + "Z",
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
            "cache_keys": [],  # Will be populated during data operations
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
        "started_at": datetime.utcnow().isoformat() + "Z",
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
        "synced_at": datetime.utcnow().isoformat() + "Z",
        "source": str(source_dir),
        "target": str(target_dir),
        "files": synced_files,
        "file_count": len(synced_files),
    }

    sync_path = metadata_dir / "sync.json"
    with open(sync_path, "w") as f:
        json.dump(sync_manifest, f, indent=2)


def add_data_cache_keys(metadata_path: Path, cache_keys: List[str]) -> None:
    """
    Add data cache keys to metadata.

    Args:
        metadata_path: Path to run.json
        cache_keys: List of cache keys used for data
    """
    if not metadata_path.exists():
        return

    try:
        with open(metadata_path, "r") as f:
            metadata = json.load(f)

        if "data" not in metadata:
            metadata["data"] = {}

        metadata["data"]["cache_keys"] = cache_keys

        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2, default=str)
    except (OSError, json.JSONDecodeError):
        pass


def finalize_instance_metadata(
    metadata_path: Path,
    success: bool,
    error: Optional[str] = None,
) -> None:
    """
    Mark instance execution as completed.

    Args:
        metadata_path: Path to run.json
        success: Whether execution succeeded
        error: Error message if failed
    """
    updates = {
        "status": {
            "state": "completed" if success else "failed",
            "completed_at": datetime.utcnow().isoformat() + "Z",
            "success": success,
            "error": error,
        }
    }
    update_instance_metadata(metadata_path, updates, merge=True)
