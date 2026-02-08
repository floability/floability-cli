"""Instance manager module.

Provides reusable functions for creating and preparing Floability instance
directories plus metadata recording and backpack argument resolution.

This consolidates logic previously duplicated across `ops/instance.py` and
`ops/run.py`.
"""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path
from typing import Dict, Optional

from .utils import create_unique_directory
from .instance_metadata import create_instance_metadata, update_instance_metadata


"""
Instance manager module.

Provides reusable functions for creating and preparing Floability instance
directories plus metadata recording.
"""


def create_instance_structure(
    base_dir: str, prefix: str = "floability_instance"
) -> Dict[str, Path]:
    """Create a unique instance directory with standard sub-directories."""
    base_dir = os.path.expanduser(base_dir)
    root = create_unique_directory(base_dir=base_dir, prefix=prefix)
    paths = {
        "root": Path(root),
        "workflow": Path(root) / "workflow",
        "logs": Path(root) / "logs",
        "metrics": Path(root) / "metrics",
        "metadata": Path(root) / "metadata",
    }
    for key in ["workflow", "logs", "metrics", "metadata"]:
        paths[key].mkdir(parents=True, exist_ok=True)

    print(f"[floability] Created instance structure at: {os.path.abspath(root)}")
    print("[floability]   workflow/ - execution sandbox")
    print("[floability]   logs/     - execution logs")
    print("[floability]   metrics/  - performance data")
    print("[floability]   metadata/ - run metadata")
    return paths


def create_latest_symlink(base_dir: str, target_dir: str) -> None:
    base_dir = os.path.expanduser(base_dir)
    target_dir = os.path.expanduser(target_dir)
    latest = Path(base_dir) / "latest_floability_instance"
    if latest.is_symlink() or latest.exists():
        latest.unlink()
    latest.symlink_to(target_dir)
    print(f"[floability] Created symlink to latest instance: {os.path.abspath(latest)}")


def copy_workflow_directory(
    source_workflow_dir: Path,
    dest_workflow_dir: Path,
    skip_patterns: Optional[list] = None,
) -> int:
    """Copy entire workflow directory contents from backpack to instance.
    
    Args:
        source_workflow_dir: Source workflow directory (typically backpack/workflow)
        dest_workflow_dir: Destination workflow directory (typically instance/workflow)
        skip_patterns: Directory/file patterns to skip (default: .ipynb_checkpoints, __pycache__, vine-run-info)
    
    Returns:
        Number of files copied
    """
    if skip_patterns is None:
        skip_patterns = [".ipynb_checkpoints", "__pycache__", "vine-run-info", ".git"]
    
    if not source_workflow_dir.exists():
        print(f"[floability] Warning: Source workflow directory not found: {source_workflow_dir}")
        return 0
    
    dest_workflow_dir.mkdir(parents=True, exist_ok=True)
    files_copied = 0
    
    print(f"[floability] Copying workflow directory contents...")
    print(f"[floability]   From: {source_workflow_dir}")
    print(f"[floability]   To:   {dest_workflow_dir}")
    
    for item in source_workflow_dir.rglob("*"):
        # Skip patterns
        if any(pattern in item.parts for pattern in skip_patterns):
            continue
        
        rel_path = item.relative_to(source_workflow_dir)
        dest_path = dest_workflow_dir / rel_path
        
        if item.is_file():
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest_path)
            files_copied += 1
        elif item.is_dir():
            dest_path.mkdir(parents=True, exist_ok=True)
    
    print(f"[floability] Copied {files_copied} file(s) from workflow directory")
    return files_copied


def record_initial_metadata(args, instance_paths: Dict[str, Path], mode: str) -> Path:
    """Create and persist initial instance metadata; returns path to metadata file."""
    metadata_file = instance_paths["metadata"] / "run.json"
    backpack_path = Path(args.backpack) if getattr(args, "backpack", None) else None
    initial = create_instance_metadata(
        instance_dir=instance_paths["root"],
        backpack_path=backpack_path,
        cli_args=vars(args),
        manager_name=args.manager_name,
        execution_mode=mode,
        environment_spec=(
            Path(args.environment) if getattr(args, "environment", None) else None
        ),
        worker_environment_spec=(
            Path(args.worker_environment)
            if getattr(args, "worker_environment", None)
            else None
        ),
        data_spec=Path(args.data_spec) if getattr(args, "data_spec", None) else None,
    )
    update_instance_metadata(metadata_file, initial, merge=False)
    print(f"[floability] Recorded instance metadata: {metadata_file}")
    return metadata_file


def prepare_instance(args, mode: str = "instance") -> Dict[str, Path]:
    """High-level helper to fully prepare an instance directory structure.

    Returns the instance_paths dict.
    """
    # Ensure manager name
    if getattr(args, "manager_name", None) is None:
        args.manager_name = f"floability-{uuid.uuid4()}"

    # Build instance prefix
    instance_prefix = "floability_instance"
    if getattr(args, "instance_prefix", None):
        instance_prefix = f"floability_instance_{args.instance_prefix}"
    
    instance_paths = create_instance_structure(args.base_dir, prefix=instance_prefix)
    create_latest_symlink(args.base_dir, str(instance_paths["root"]))

    # Record metadata early (before data/environment operations)
    try:
        record_initial_metadata(args, instance_paths, mode=mode)
    except Exception as e:
        print(f"[floability] Warning: Could not create metadata: {e}")

    # Copy entire workflow directory contents (always into sandbox for instance create)
    if getattr(args, "backpack_root", None):
        source_workflow = Path(args.backpack_root) / "workflow"
        copy_workflow_directory(
            source_workflow_dir=source_workflow,
            dest_workflow_dir=instance_paths["workflow"],
        )
    return instance_paths


def get_registered_instances_status() -> Dict[str, Dict]:
    """Return a mapping of short_name -> status dict for all registered instances.

    Each status dict contains keys: path, running, created_at, last_seen,
    manager_name, tags. Instances with missing status (e.g., record corrupted)
    are skipped.
    """
    try:
        from .instance_registry import (
            list_instances,
            instance_status,
            prune_nonexistent_entries,
        )
    except Exception:
        return {}
    # Prune stale entries first (paths that no longer exist)
    try:
        prune_nonexistent_entries()
    except Exception:
        pass
    entries = list_instances()
    results: Dict[str, Dict] = {}
    for name in entries.keys():
        try:
            st = instance_status(name)
            if st:
                results[name] = st
        except Exception:
            # Skip problematic entries silently; could log later
            continue
    return results
