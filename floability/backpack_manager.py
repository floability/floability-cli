"""Backpack manager module.

Utilities for resolving CLI arguments from a Floability backpack
directory structure (software, compute, data, workflow).

This module centralizes logic used by both `ops/run.py` and
`ops/instance.py` to avoid duplication.
"""

from __future__ import annotations

from pathlib import Path
import shutil
from typing import Optional, Dict, Any, List

from .instance_metadata import record_sync_manifest, compute_file_hash


def sync_outputs_to_backpack(
    workflow_dir: str,
    backpack_dir: str,
    metadata_dir: Optional[str] = None,
    verbose: bool = True,
) -> bool:
    """Sync executed notebooks and outputs/ back to the backpack.

    - Copies executed notebooks (*.ipynb) from the instance workflow dir to the backpack workflow dir
    - Recursively copies the workflow/outputs/ directory if present
    - Records a sync manifest into metadata/sync.json when metadata_dir is provided

    Returns True if any files were synced, otherwise False.
    """
    workflow_path = Path(workflow_dir)
    backpack_path = Path(backpack_dir)

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

    print(f"[floability] Syncing outputs from instance to backpack...")
    print(f"[floability]   Source: {workflow_dir}")
    print(f"[floability]   Target: {backpack_dir}")

    synced_files_manifest = []

    # 1. Sync executed notebooks
    print(f"[floability]   Syncing notebooks...")
    for notebook in workflow_path.glob("*.ipynb"):
        target = backpack_path / notebook.name
        try:
            shutil.copy2(notebook, target)
            file_info = {
                "path": notebook.name,
                "type": "notebook",
                "size": notebook.stat().st_size,
                "hash": compute_file_hash(notebook),
            }
            synced_files_manifest.append(file_info)
            if verbose:
                print(f"[floability]     ✓ {notebook.name}")
        except Exception as e:
            print(f"[floability]     ✗ Failed to sync {notebook.name}: {e}")

    # 2. Sync workflow/outputs/
    outputs_dir = workflow_path / "outputs"
    if outputs_dir.exists() and outputs_dir.is_dir():
        print(f"[floability]   Syncing outputs/ directory...")
        target_outputs = backpack_path / "outputs"
        target_outputs.mkdir(parents=True, exist_ok=True)

        for item in outputs_dir.rglob("*"):
            if item.is_file():
                rel_path = item.relative_to(outputs_dir)
                target = target_outputs / rel_path
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, target)
                    file_info = {
                        "path": f"outputs/{rel_path}",
                        "type": "output",
                        "size": item.stat().st_size,
                        "hash": compute_file_hash(item),
                    }
                    synced_files_manifest.append(file_info)
                    if verbose:
                        print(f"[floability]     ✓ outputs/{rel_path}")
                except Exception as e:
                    print(f"[floability]     ✗ Failed to sync outputs/{rel_path}: {e}")

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
            f"[floability] Successfully synced {len(synced_files_manifest)} file(s) to backpack"
        )
        return True
    else:
        print(f"[floability] No files to sync")
        return False


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

    # Notebook / Python script selection
    if not getattr(args, "notebook", None) and not getattr(args, "python_script", None):
        workflow_dir = backpack_dir / "workflow"
        notebooks = list(workflow_dir.glob("*.ipynb"))
        scripts = list(workflow_dir.glob("*.py"))

        prefer_python = getattr(args, "prefer_python", False)

        def _pick_by_name(files: List[Path], stem: str) -> Path:
            if len(files) == 1:
                return files[0]
            for f in files:
                if f.stem == stem:
                    return f
            return files[0]

        # Default: prefer notebook. With --prefer-python: prefer script.
        if notebooks and not prefer_python:
            args.notebook = str(_pick_by_name(notebooks, backpack_dir.stem))
            print(f"[floability] Using notebook from backpack: {args.notebook}")
        elif scripts:
            args.python_script = str(_pick_by_name(scripts, backpack_dir.stem))
            print(f"[floability] Using Python script from backpack: {args.python_script}")
        elif notebooks:
            # --prefer-python set but no scripts found; fall back to notebook
            args.notebook = str(_pick_by_name(notebooks, backpack_dir.stem))
            print(f"[floability] Using notebook from backpack: {args.notebook}")

    args.backpack_root = str(backpack_dir)


def validate_backpack_structure(
    backpack_dir: str, require_workflow: bool = True
) -> Dict[str, Any]:
    """Validate common Floability backpack structure and report findings.

    Checks for the presence of standard subdirectories/files:
      - workflow/ (at least one .ipynb or .py if require_workflow=True)
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
        notebooks = list(wf_dir.glob("*.ipynb"))
        scripts = list(wf_dir.glob("*.py"))
        result["workflow_files"] = notebooks + scripts
        if require_workflow and not (notebooks or scripts):
            msg = "workflow/ has no .ipynb or .py entrypoints"
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
