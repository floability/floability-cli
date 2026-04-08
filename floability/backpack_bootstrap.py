"""
Backpack bootstrap helper module.

Provides utilities for:
- Resolving backpack names and paths
- Loading starter templates
- Initializing backpacks from templates or custom workflows
- Validating backpack structure

Templates are loaded from floability/bootstrap_templates/
"""

import json
import hashlib
import random
import shutil
import sys
from pathlib import Path
from typing import Tuple, Dict, List, Any, Optional

import yaml


# ============================================================================
# PATH & NAME RESOLUTION
# ============================================================================


def resolve_backpack_target(name_or_path: str) -> Tuple[Path, str]:
    """
    Resolve a backpack name or path argument to (target_path, backpack_name).

    Args:
        name_or_path: Either a simple name like 'my-backpack' or a path like
                     '/home/user/backpacks/my-backpack'

    Returns:
        (backpack_path, backpack_name) tuple

    Raises:
        ValueError: If the argument is invalid
    """
    path = Path(name_or_path).resolve()

    # If it looks like a path (contains /), use it as-is and extract leaf as name
    if "/" in name_or_path or "\\" in name_or_path:
        backpack_name = path.name
        backpack_path = path
    else:
        # It's a simple name, create in current directory
        backpack_name = name_or_path
        backpack_path = Path.cwd() / name_or_path

    if not backpack_name or not backpack_name.replace("-", "").replace("_", "").isalnum():
        raise ValueError(
            f"Invalid backpack name: {backpack_name}. Use alphanumeric characters, hyphens, and underscores."
        )

    return backpack_path, backpack_name


# ============================================================================
# TEMPLATE LOADING
# ============================================================================


def get_template_dir() -> Path:
    """Get the bootstrap templates directory."""
    # Templates are in floability/bootstrap_templates/
    module_dir = Path(__file__).parent
    template_dir = module_dir / "bootstrap_templates"
    if not template_dir.exists():
        raise RuntimeError(f"Bootstrap templates directory not found: {template_dir}")
    return template_dir


def load_template_notebook(variant: str) -> Dict[str, Any]:
    """
    Load a starter notebook template.

    Args:
        variant: Template variant ('taskvine' or 'taskvine-data')

    Returns:
        Notebook dict (parsed JSON)

    Raises:
        ValueError: If template not found
    """
    template_dir = get_template_dir()
    notebook_file = template_dir / f"{variant}.ipynb"

    if not notebook_file.exists():
        raise ValueError(f"Notebook template not found: {variant}")

    with open(notebook_file) as f:
        return json.load(f)


def load_template_yaml(filename: str) -> Dict[str, Any]:
    """
    Load a starter YAML template (environment, compute, data).

    Args:
        filename: Template filename ('environment.yml', 'compute.yml', 'data.yml')

    Returns:
        Parsed YAML dict

    Raises:
        ValueError: If template not found
    """
    template_dir = get_template_dir()
    yaml_file = template_dir / filename

    if not yaml_file.exists():
        raise ValueError(f"YAML template not found: {filename}")

    with open(yaml_file) as f:
        return yaml.safe_load(f) or {}


# ============================================================================
# PERSONALIZATION
# ============================================================================


def personalize_environment_yml(env_dict: Dict[str, Any], backpack_name: str) -> Dict[str, Any]:
    """
    Personalize environment.yml with backpack name.

    Args:
        env_dict: Loaded environment template
        backpack_name: Name of the backpack

    Returns:
        Updated environment dict
    """
    env_dict["name"] = backpack_name
    return env_dict


def generate_backpack_data_files(data_root: Path, count: int = 10) -> List[Path]:
    """Generate sample text files used by the taskvine-data starter notebook."""
    backpack_data_dir = data_root / "backpack_data"
    backpack_data_dir.mkdir(parents=True, exist_ok=True)

    generated_paths: List[Path] = []
    for idx in range(1, count + 1):
        file_path = backpack_data_dir / f"sample_{idx:02d}.txt"
        random_value = random.randint(1, 100000000)
        file_path.write_text(
            (
                f"sample_file={idx}\n"
                f"description=generated backpack sample input\n"
                f"value={random_value}\n"
            ),
            encoding="utf-8",
        )
        generated_paths.append(file_path)

    return generated_paths


def build_taskvine_data_yml(generated_files: List[Path], backpack_path: Path) -> Dict[str, Any]:
    """Build data.yml content for taskvine-data with local backpack samples."""
    local_entries: List[Dict[str, Any]] = []

    for idx, file_path in enumerate(generated_files, start=1):
        rel_path = file_path.relative_to(backpack_path).as_posix()
        file_bytes = file_path.read_bytes()
        checksum = hashlib.sha256(file_bytes).hexdigest()
        expected_size = file_path.stat().st_size

        local_entries.append(
            {
                "name": f"backpack_data_{idx:02d}",
                "source_type": "backpack",
                "source": rel_path,
                "checksum": f"sha256:{checksum}",
                "target_location": rel_path,
            }
        )

    return {
        "schema_version": 1.0,
        "default_profile": "local_data",
        "profiles": {
            "local_data": {
                "policy": {
                    "retry_attempts": 0,
                    "timeout": 30,
                    "size_tolerance_bytes": 10,
                },
                "data": local_entries,
            },
        },
    }


# ============================================================================
# BACKPACK INITIALIZATION
# ============================================================================


def init_from_template(
    backpack_path: Path, backpack_name: str, template_variant: str
) -> None:
    """
    Initialize a backpack from a template.

    Args:
        backpack_path: Target directory path
        backpack_name: Name of the backpack
        template_variant: 'taskvine' or 'taskvine-data'

    Raises:
        ValueError: If template_variant is invalid
    """
    if template_variant not in ["taskvine", "taskvine-data"]:
        raise ValueError(
            f"Invalid template variant: {template_variant}. Must be 'taskvine' or 'taskvine-data'."
        )

    # Create directories
    backpack_path.mkdir(parents=True, exist_ok=True)
    (backpack_path / "workflow").mkdir(exist_ok=True)
    (backpack_path / "software").mkdir(exist_ok=True)
    (backpack_path / "compute").mkdir(exist_ok=True)

    # Load and write notebook
    nb_dict = load_template_notebook(template_variant)
    nb_path = backpack_path / "workflow" / f"{backpack_name}.ipynb"
    with open(nb_path, "w") as f:
        json.dump(nb_dict, f, indent=2)

    # Load, personalize, and write environment.yml
    env_dict = load_template_yaml("environment.yml")
    env_dict = personalize_environment_yml(env_dict, backpack_name)
    env_path = backpack_path / "software" / "environment.yml"
    with open(env_path, "w") as f:
        yaml.safe_dump(env_dict, f, default_flow_style=False, sort_keys=False)

    # Load and write compute.yml
    compute_dict = load_template_yaml("compute.yml")
    compute_path = backpack_path / "compute" / "compute.yml"
    with open(compute_path, "w") as f:
        yaml.safe_dump(compute_dict, f, default_flow_style=False, sort_keys=False)

    # Create data directory and data.yml if with-data variant
    has_data = template_variant == "taskvine-data"
    if has_data:
        (backpack_path / "data").mkdir(exist_ok=True)
        generated_files = generate_backpack_data_files(backpack_path / "data", count=10)
        data_dict = build_taskvine_data_yml(generated_files, backpack_path)
        data_path = backpack_path / "data" / "data.yml"
        with open(data_path, "w") as f:
            yaml.safe_dump(data_dict, f, default_flow_style=False, sort_keys=False)

    print(f"[floability] Backpack initialized from template: {template_variant}")
    print(f"[floability]   Location: {backpack_path}")
    print(f"[floability]   Workflow: {nb_path.name}")
    print(f"[floability]   Environment: environment.yml")
    print(f"[floability]   Compute: compute.yml")
    if has_data:
        print(f"[floability]   Data: data.yml + 10 sample files in data/backpack_data/")


def init_from_workflow(
    backpack_path: Path, backpack_name: str, workflow_source: Path
) -> None:
    """
    Initialize a backpack from an existing workflow file (custom mode).

    Prompts user for environment input, generates compute and optional data.yml.

    Args:
        backpack_path: Target directory path
        backpack_name: Name of the backpack
        workflow_source: Path to notebook or script file

    Raises:
        ValueError: If workflow_source is invalid or doesn't exist
        IOError: If file operations fail
    """
    # Validate workflow source
    if not workflow_source.exists():
        raise ValueError(f"Workflow source file not found: {workflow_source}")

    if workflow_source.suffix not in [".ipynb", ".py", ".sh"]:
        raise ValueError(
            f"Invalid workflow file type. Must be .ipynb, .py, or .sh, got {workflow_source.suffix}"
        )

    # Create directories
    backpack_path.mkdir(parents=True, exist_ok=True)
    (backpack_path / "workflow").mkdir(exist_ok=True)
    (backpack_path / "software").mkdir(exist_ok=True)
    (backpack_path / "compute").mkdir(exist_ok=True)

    # Copy workflow file
    workflow_dest = backpack_path / "workflow" / workflow_source.name
    shutil.copy2(workflow_source, workflow_dest)

    # Prompt for environment strategy
    print("\n[floability] Environment Configuration")
    print("-" * 50)
    print("Options:")
    print("  1. Path to existing environment.yml")
    print("  2. Comma-separated conda packages (e.g., numpy,pandas)")
    print("  3. Comma-separated pip packages (e.g., requests,pyyaml)")
    print("  4. Skip (barebones: python + ndcctools)")
    print()

    choice = input("Select option (1-4, default 4): ").strip() or "4"

    env_dict = None

    if choice == "1":
        env_file = input("Path to environment.yml: ").strip()
        if env_file and Path(env_file).exists():
            with open(env_file) as f:
                env_dict = yaml.safe_load(f) or {}
            print(f"[floability] Using environment from: {env_file}")
        else:
            print(f"[floability] File not found, using barebones")

    elif choice == "2":
        packages_str = input("Conda packages (comma-separated): ").strip()
        if packages_str:
            packages = [p.strip() for p in packages_str.split(",")]
            env_dict = {
                "name": backpack_name,
                "channels": ["conda-forge"],
                "dependencies": ["python"] + packages + ["ndcctools"],
            }
            print(f"[floability] Generated environment with {len(packages)} packages")

    elif choice == "3":
        packages_str = input("Pip packages (comma-separated): ").strip()
        if packages_str:
            pip_packages = [p.strip() for p in packages_str.split(",")]
            # Build conda environment with pip subsection
            conda_deps = ["python", "ndcctools", "pip"]
            env_dict = {
                "name": backpack_name,
                "channels": ["conda-forge"],
                "dependencies": conda_deps + [{"pip": pip_packages}],
            }
            print(f"[floability] Generated environment with {len(pip_packages)} pip packages")

    # Default to barebones if no env_dict yet
    if not env_dict:
        env_dict = load_template_yaml("environment.yml")
        env_dict = personalize_environment_yml(env_dict, backpack_name)
        print("[floability] Using barebones environment (python + ndcctools)")

    # Write environment.yml
    env_path = backpack_path / "software" / "environment.yml"
    with open(env_path, "w") as f:
        yaml.safe_dump(env_dict, f, default_flow_style=False, sort_keys=False)

    # Load and write compute.yml
    compute_dict = load_template_yaml("compute.yml")
    compute_path = backpack_path / "compute" / "compute.yml"
    with open(compute_path, "w") as f:
        yaml.safe_dump(compute_dict, f, default_flow_style=False, sort_keys=False)

    # Ask about data.yml
    print("\n[floability] Data Configuration")
    answer = input("Create data.yml? (y/n, default n): ").strip().lower()
    if answer in ["y", "yes"]:
        (backpack_path / "data").mkdir(exist_ok=True)
        data_dict = load_template_yaml("data.yml")
        data_path = backpack_path / "data" / "data.yml"
        with open(data_path, "w") as f:
            yaml.safe_dump(data_dict, f, default_flow_style=False, sort_keys=False)
        print("[floability] Created data.yml (empty, ready for user input)")

    print(f"\n[floability] Backpack initialized from workflow file")
    print(f"[floability]   Location: {backpack_path}")
    print(f"[floability]   Workflow: {workflow_dest.name}")
    print(f"[floability]   Environment: environment.yml")
    print(f"[floability]   Compute: compute.yml")


# ============================================================================
# VALIDATION
# ============================================================================


def validate_backpack(backpack_path: Path, strict: bool = False) -> Dict[str, Any]:
    """
    Validate a backpack structure.

    Args:
        backpack_path: Path to backpack directory
        strict: Reserved for future use. Currently has no effect. When implemented,
                will perform stricter checks such as environment buildability,
                TaskVine notebook validation, and compute spec reasonableness.

    Returns:
        Validation result dict with keys: valid, path, problems, workflow_file, has_data
    """
    result: Dict[str, Any] = {
        "valid": True,
        "path": str(backpack_path),
        "problems": [],
        "workflow_file": None,
        "has_data": False,
    }

    # Check backpack directory exists
    if not backpack_path.is_dir():
        result["valid"] = False
        result["problems"].append(f"Backpack directory not found: {backpack_path}")
        return result

    # Check workflow/ directory
    workflow_dir = backpack_path / "workflow"
    if not workflow_dir.exists():
        result["valid"] = False
        result["problems"].append("Missing workflow/ directory")
    else:
        # Check for workflow entrypoint
        notebooks = list(workflow_dir.glob("*.ipynb"))
        scripts = list(workflow_dir.glob("*.py")) + list(workflow_dir.glob("*.sh"))

        if notebooks:
            result["workflow_file"] = notebooks[0].name
        elif scripts:
            result["workflow_file"] = scripts[0].name
        else:
            result["valid"] = False
            result["problems"].append("No workflow entrypoint (.ipynb, .py, or .sh) found in workflow/")

    # Check software/environment.yml
    env_file = backpack_path / "software" / "environment.yml"
    if not env_file.exists():
        result["valid"] = False
        result["problems"].append("Missing software/environment.yml")
    else:
        try:
            with open(env_file) as f:
                yaml.safe_load(f)
        except Exception as e:
            result["valid"] = False
            result["problems"].append(f"Invalid YAML in environment.yml: {e}")

    # Check compute/compute.yml
    compute_file = backpack_path / "compute" / "compute.yml"
    if not compute_file.exists():
        result["valid"] = False
        result["problems"].append("Missing compute/compute.yml")
    else:
        try:
            with open(compute_file) as f:
                yaml.safe_load(f)
        except Exception as e:
            result["valid"] = False
            result["problems"].append(f"Invalid YAML in compute.yml: {e}")

    # Check data/data.yml (optional)
    data_file = backpack_path / "data" / "data.yml"
    if data_file.exists():
        result["has_data"] = True
        try:
            with open(data_file) as f:
                yaml.safe_load(f)
        except Exception as e:
            result["valid"] = False
            result["problems"].append(f"Invalid YAML in data.yml: {e}")

    return result
