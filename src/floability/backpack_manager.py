"""Backpack manager module.

Utilities for resolving CLI arguments from a Floability backpack
directory structure (software, compute, data, workflow).

This module centralizes logic used by both `ops/run.py` and
`ops/instance.py` to avoid duplication.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Dict

from .instance_metadata import compute_file_hash, record_sync_manifest


SUPPORTED_WORKFLOW_SUFFIXES = {".ipynb", ".py", ".sh"}


def sync_workflow_to_backpack(
    workflow_dir: str,
    backpack_dir: str,
    copied_paths: Iterable[str | Path] | None = None,
    extra_paths: Iterable[str | Path] | None = None,
    metadata_dir: str | None = None,
    verbose: bool = True,
) -> bool:
    """Copy selected instance workflow files back to the backpack.

    ``copied_paths`` contains files originally copied from the backpack. Paths in
    ``extra_paths`` are explicit user requests and may name a file or directory.
    Every path must remain within both workflow directory boundaries. Symlinks
    are skipped so synchronization never follows a link outside either tree.

    Returns True if any files were synced, otherwise False.
    """
    workflow_path = Path(workflow_dir).resolve()
    backpack_path = Path(backpack_dir).resolve()

    if not workflow_path.exists():
        print(
            f"[floability] Warning: Workflow directory does not exist: {workflow_dir}"
        )
        return False

    if not backpack_path.exists():
        print(
            f"[floability] Warning: Backpack directory does not exist: {backpack_dir}"
        )
        return False

    print("[floability] Syncing workflow files from instance to backpack...")
    print(f"[floability]   Source: {workflow_dir}")
    print(f"[floability]   Target: {backpack_dir}")

    selected_files: dict[Path, Path] = {}
    requested_paths = [*(copied_paths or ()), *(extra_paths or ())]

    for requested_path in requested_paths:
        try:
            relative_path = _validate_sync_path(requested_path)
            source = workflow_path / relative_path
            _collect_sync_files(source, workflow_path, selected_files)
        except ValueError as e:
            print(f"[floability]   Skipping sync path '{requested_path}': {e}")

    synced_files_manifest = []
    for relative_path, source in sorted(
        selected_files.items(), key=lambda item: str(item[0])
    ):
        target = backpack_path / relative_path
        try:
            _validate_sync_destination(target, backpack_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            file_info = {
                "path": str(relative_path),
                "type": "workflow",
                "size": source.stat().st_size,
                "hash": compute_file_hash(source),
            }
            synced_files_manifest.append(file_info)
            if verbose:
                print(f"[floability]     ✓ {relative_path}")
        except (OSError, ValueError) as e:
            print(f"[floability]     ✗ Failed to sync {relative_path}: {e}")

    # Record sync manifest
    if metadata_dir and synced_files_manifest:
        try:
            record_sync_manifest(
                Path(metadata_dir),
                synced_files_manifest,
                workflow_path,
                backpack_path,
            )
            if verbose:
                print(
                    f"[floability]   Recorded sync manifest: {metadata_dir}/sync.json"
                )
        except Exception as e:
            print(f"[floability]   Warning: Could not record sync manifest: {e}")

    if synced_files_manifest:
        print(
            "[floability] Successfully synced "
            f"{len(synced_files_manifest)} file(s) to backpack"
        )
        return True
    else:
        print("[floability] No files to sync")
        return False


def _validate_sync_path(path_value: str | Path) -> Path:
    """Return a safe path relative to workflow/, or raise ValueError."""
    path = Path(path_value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("path must remain inside the workflow directory")
    return path


def _is_within(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
        return True
    except ValueError:
        return False


def _collect_sync_files(
    source: Path,
    workflow_path: Path,
    selected_files: dict[Path, Path],
) -> None:
    """Add a requested file or directory without following symlinks."""
    if source.is_symlink():
        raise ValueError("symbolic links are not synchronized")
    if not source.exists():
        raise ValueError("path does not exist in the instance workflow")
    if not _is_within(source.resolve(), workflow_path):
        raise ValueError("resolved path leaves the instance workflow directory")

    if source.is_file():
        selected_files[source.relative_to(workflow_path)] = source
        return
    if not source.is_dir():
        raise ValueError("path is not a regular file or directory")

    for current_root, directory_names, file_names in os.walk(
        source, followlinks=False
    ):
        current_path = Path(current_root)
        directory_names[:] = [
            name
            for name in directory_names
            if not (current_path / name).is_symlink()
        ]
        for file_name in file_names:
            item = current_path / file_name
            if item.is_symlink():
                continue
            if not _is_within(item.resolve(), workflow_path):
                continue
            selected_files[item.relative_to(workflow_path)] = item


def _validate_sync_destination(target: Path, backpack_path: Path) -> None:
    """Ensure copying to target cannot escape the backpack workflow tree."""
    if target.is_symlink():
        raise ValueError("destination is a symbolic link")
    if not _is_within(target.parent.resolve(), backpack_path):
        raise ValueError("destination leaves the backpack workflow directory")


def resolve_backpack_args(args) -> None:
    """Populate missing CLI args from a backpack directory structure.

    Mutates ``args`` in-place. Safe to call even if args.backpack is missing.
    """
    if not getattr(args, "backpack", None):
        return

    backpack_dir = Path(args.backpack).resolve()
    if not backpack_dir.is_dir():
        print(f"[floability] Error: Backpack directory not found: {backpack_dir}")
        return

    print(f"[floability] Processing backpack: {backpack_dir.stem}")

    # Data spec
    if not getattr(args, "data_spec", None):
        candidate = backpack_dir / "data" / "data.yml"
        if candidate.is_file():
            args.data_spec = str(candidate)
            print(f"[floability] Using data spec from backpack: {args.data_spec}")

    # Compute spec
    if not getattr(args, "compute_spec", None):
        candidate = backpack_dir / "compute" / "compute.yml"
        if candidate.is_file():
            args.compute_spec = str(candidate)
            print(f"[floability] Using compute spec from backpack: {args.compute_spec}")

    # Manager environment
    if not getattr(args, "environment", None):
        candidate = backpack_dir / "software" / "environment.yml"
        if candidate.is_file():
            args.environment = str(candidate)
            print(f"[floability] Using environment from backpack: {args.environment}")

    # Worker environment
    if not getattr(args, "worker_environment", None):
        candidate = backpack_dir / "software" / "worker-environment.yml"
        if candidate.is_file():
            args.worker_environment = str(candidate)
            print(
                f"[floability] Using worker environment from backpack: {args.worker_environment}"
            )

    args.backpack_root = str(backpack_dir)


def validate_backpack_structure(
    backpack_dir: str, require_workflow: bool = True
) -> Dict[str, Any]:
    """Validate common Floability backpack structure and report findings.

    Checks for the presence of standard subdirectories/files:
      - workflow/ (at least one .ipynb, .py, or .sh if require_workflow=True)
      - software/environment.yml (optional)
      - software/worker-environment.yml (optional)
      - compute/compute.yml (optional)
      - data/data.yml (optional)

    Returns a dict with keys:
      {
        "exists": bool,
        "problems": [str, ...],
        "workflow_files": [Path, ...],
        "has_environment": bool,
        "has_worker_environment": bool,
        "has_compute_spec": bool,
        "has_data_spec": bool,
      }

    Does not raise; collects problems and prints user-friendly warnings.
    """
    root = Path(backpack_dir)
    result: Dict[str, Any] = {
        "exists": root.is_dir(),
        "problems": [],
        "workflow_files": [],
        "has_environment": False,
        "has_worker_environment": False,
        "has_compute_spec": False,
        "has_data_spec": False,
    }

    if not result["exists"]:
        result["problems"].append(f"Backpack directory not found: {backpack_dir}")
        print(f"[floability] Error: Backpack directory not found: {backpack_dir}")
        return result

    # workflow/
    wf_dir = root / "workflow"
    if not wf_dir.exists():
        msg = "Missing workflow/ directory"
        result["problems"].append(msg)
        print(f"[floability] Warning: {msg}")
    else:
        result["workflow_files"] = sorted(
            (
                path
                for path in wf_dir.rglob("*")
                if path.is_file()
                and path.suffix in SUPPORTED_WORKFLOW_SUFFIXES
                and ".ipynb_checkpoints" not in path.parts
                and "__pycache__" not in path.parts
            ),
            key=lambda path: str(path.relative_to(wf_dir)),
        )
        if require_workflow and not result["workflow_files"]:
            msg = "workflow/ has no .ipynb, .py, or .sh entrypoints"
            result["problems"].append(msg)
            print(f"[floability] Warning: {msg}")

    # software/
    sw_dir = root / "software"
    if sw_dir.exists():
        env_yml = sw_dir / "environment.yml"
        worker_env_yml = sw_dir / "worker-environment.yml"
        result["has_environment"] = env_yml.is_file()
        result["has_worker_environment"] = worker_env_yml.is_file()
    else:
        print("[floability] Info: No software/ directory found (using defaults if any)")

    # compute/
    comp_dir = root / "compute"
    if comp_dir.exists():
        result["has_compute_spec"] = (comp_dir / "compute.yml").is_file()
    else:
        print(
            "[floability] Info: No compute/ directory found (will use CLI overrides or defaults)"
        )

    # data/
    data_dir = root / "data"
    if data_dir.exists():
        result["has_data_spec"] = (data_dir / "data.yml").is_file()
    else:
        print("[floability] Info: No data/ directory found (data ops may be skipped)")

    return result


def require_executable_backpack(
    backpack_dir: str | Path,
    environment_spec: str | Path | None,
) -> Dict[str, Any]:
    """Require the minimum files needed to create an executable instance.

    Validation is intentionally performed before a base directory, instance,
    symlink, lock, or registry entry is created. Data and compute specifications
    remain optional. The environment may come from the canonical backpack path
    or an explicit ``--environment`` override resolved by the caller.
    """
    root = Path(backpack_dir).expanduser().resolve()
    result = validate_backpack_structure(str(root), require_workflow=True)
    problems = list(result["problems"])

    if not environment_spec:
        problems.append(
            "missing environment specification; expected "
            "software/environment.yml or --environment PATH"
        )
    else:
        environment_path = Path(environment_spec).expanduser().resolve()
        if not environment_path.is_file():
            problems.append(
                f"environment specification is not a file: {environment_path}"
            )

    if problems:
        raise ValueError("Invalid Floability backpack: " + "; ".join(problems))
    return result
