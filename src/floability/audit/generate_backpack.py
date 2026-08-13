"""
Generate a complete floability backpack structure from audit outputs.

Creates:
  <backpack_name>/
  ├── workflow/           notebook + local helper .py files
  ├── software/
  │   └── environment.yml (from manager_environment.yml produced by audit)
  ├── compute/
  │   └── compute.yml     (from bootstrap template)
  └── data/               (when data deps are provided)
      ├── data.yml
      └── <data files copied from audit machine>
"""

import hashlib
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Union

import yaml


def _load_template_compute() -> dict:
    """Load compute.yml from bootstrap templates."""
    template_dir = Path(__file__).parent.parent / "bootstrap_templates"
    compute_file = template_dir / "compute.yml"
    with open(compute_file) as f:
        return yaml.safe_load(f) or {}


def _sha256(file_path: Path) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_name(rel_path: str) -> str:
    """Derive a data entry name from a relative path."""
    return rel_path.replace("/", "_").replace(".", "_").strip("_")


def generate_data_yml(
    backpack_path: Path,
    consolidated_data_deps: Dict[str, Union[int, str]],
    notebook_dir: Path,
) -> None:
    """
    Build data/data.yml and copy data files into the backpack.

    Each detected data file is copied from its audit-time absolute path into
    backpack/data/<rel_path>, where rel_path is the path relative to notebook_dir.
    The data.yml entry uses source_type: backpack with matching source and
    target_location fields.

    Args:
        backpack_path: Root of the backpack being created.
        consolidated_data_deps: {abs_path: size} from audit (union of manager + worker).
        notebook_dir: Absolute path to the directory containing the notebook.
                      Used to compute rel_path for each file.
    """
    data_dir = backpack_path / "data"
    data_dir.mkdir(exist_ok=True)

    entries = []
    for abs_path, size in consolidated_data_deps.items():
        src = Path(abs_path)
        if not src.is_file():
            print(f"[floability]   Warning: data file not found, skipping: {abs_path}")
            continue

        try:
            rel_path = src.relative_to(notebook_dir)
        except ValueError:
            # file not under notebook_dir — use basename only as rel_path
            rel_path = Path(src.name)
            print(f"[floability]   Warning: {src.name} outside notebook dir, placing under data/")

        rel_str = rel_path.as_posix()

        # Always store files under backpack/data/ for cleanliness.
        # If rel_path already starts with data/, copy directly (avoids data/data/).
        # Otherwise prepend data/ to the backpack-side source path.
        if rel_str.startswith("data/"):
            source_str = rel_str
            dest = backpack_path / rel_path
        else:
            source_str = "data/" + rel_str
            dest = backpack_path / "data" / rel_path

        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)

        checksum = _sha256(dest)

        entry = {
            "name": _safe_name(rel_str),
            "source_type": "backpack",
            "source": source_str,
            "target_location": rel_str,
        }
        if isinstance(size, int):
            entry["expected_size"] = size
        entry["checksum"] = f"sha256:{checksum}"

        entries.append(entry)
        print(f"[floability]   Added data file: {rel_str} ({size} bytes)")

    data_yml = {
        "schema_version": 1.0,
        "default_profile": "local_data",
        "profiles": {
            "local_data": {
                "policy": {
                    "retry_attempts": 0,
                    "timeout": 30,
                    "size_tolerance_bytes": 10,
                },
                "data": entries,
            }
        },
    }

    data_yml_path = data_dir / "data.yml"
    with open(data_yml_path, "w") as f:
        yaml.safe_dump(data_yml, f, default_flow_style=False, sort_keys=False)

    print(f"[floability]   Generated data/data.yml with {len(entries)} file(s)")


def generate_backpack(
    backpack_name: str,
    notebook_path: str,
    manager_env_yml: str,
    local_helper_files: List[Path],
    output_dir: Optional[str] = None,
    force: bool = False,
    consolidated_data_deps: Optional[Dict[str, Union[int, str]]] = None,
    notebook_dir: Optional[Path] = None,
) -> Path:
    """
    Build a backpack directory from audit outputs.

    Args:
        backpack_name: Name for the backpack (also the directory name).
        notebook_path: Absolute path to the source notebook.
        manager_env_yml: Path to manager_environment.yml produced by audit.
        local_helper_files: Local .py files detected from strace (go into workflow/).
        output_dir: Where to create the backpack directory. Defaults to CWD.
        force: Overwrite existing backpack directory.
        consolidated_data_deps: {abs_path: size} union of manager+worker data files.
                                 When provided, generates data/data.yml.
        notebook_dir: Absolute path to notebook directory. Required when
                      consolidated_data_deps is provided.

    Returns:
        Path to the created backpack directory.
    """
    base = Path(output_dir).resolve() if output_dir else Path.cwd()
    backpack_path = base / backpack_name

    if backpack_path.exists():
        if force:
            print(f"[floability] Removing existing backpack at {backpack_path}")
            shutil.rmtree(backpack_path)
        else:
            raise ValueError(
                f"Backpack directory already exists: {backpack_path}\n"
                "Use --force to overwrite."
            )

    # Create structure
    (backpack_path / "workflow").mkdir(parents=True)
    (backpack_path / "software").mkdir()
    (backpack_path / "compute").mkdir()

    # --- workflow/ ---
    nb = Path(notebook_path).resolve()
    shutil.copy2(nb, backpack_path / "workflow" / nb.name)

    for helper in local_helper_files:
        dest = backpack_path / "workflow" / helper.name
        shutil.copy2(helper, dest)
        print(f"[floability]   Copied helper: {helper.name}")

    # --- software/environment.yml ---
    env_src = Path(manager_env_yml)
    if env_src.is_file():
        shutil.copy2(env_src, backpack_path / "software" / "environment.yml")
    else:
        print(f"[floability] Warning: manager_environment.yml not found at {env_src}")

    # --- compute/compute.yml ---
    compute_dict = _load_template_compute()
    with open(backpack_path / "compute" / "compute.yml", "w") as f:
        yaml.safe_dump(compute_dict, f, default_flow_style=False, sort_keys=False)

    # --- data/ ---
    if consolidated_data_deps and notebook_dir:
        generate_data_yml(backpack_path, consolidated_data_deps, notebook_dir)

    return backpack_path
