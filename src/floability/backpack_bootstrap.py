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
import re
import shutil
import subprocess
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


def load_template_script(variant: str) -> str:
    """
    Load a starter Python script template.

    Args:
        variant: Template variant ('taskvine' or 'taskvine-data')

    Returns:
        Script source as a string

    Raises:
        ValueError: If template not found
    """
    template_dir = get_template_dir()
    script_file = template_dir / f"{variant}.py"

    if not script_file.exists():
        raise ValueError(f"Script template not found: {variant}")

    return script_file.read_text(encoding="utf-8")


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


def extract_conda_package_name(package_spec: str) -> str:
    """Extract package name from a conda spec like `numpy=2.0` or `python>=3.11`."""
    return re.split(r"[<>=!~\s]", package_spec.strip().lower(), maxsplit=1)[0]


def generate_backpack_data_files(data_root: Path, count: int = 10) -> List[Path]:
    """Generate sample text files used by the taskvine-data starter notebook."""
    backpack_data_dir = data_root / "text_data"
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

        local_entries.append(
            {
                "name": f"text_data_{idx:02d}",
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
    backpack_path: Path,
    backpack_name: str,
    template_variant: str,
    use_script: bool = False,
) -> None:
    """
    Initialize a backpack from a template.

    Args:
        backpack_path: Target directory path
        backpack_name: Name of the backpack
        template_variant: 'taskvine' or 'taskvine-data'
        use_script: When True, create a Python script (.py) instead of a
            Jupyter notebook (.ipynb).  The script is executed directly by
            Floability in execute mode; stdout and stderr are tee'd to both
            the terminal and logs/workflow.log inside the instance directory.

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

    # Load and write workflow entrypoint (notebook or script)
    if use_script:
        script_src = load_template_script(template_variant)
        workflow_path = backpack_path / "workflow" / f"{backpack_name}.py"
        workflow_path.write_text(script_src, encoding="utf-8")
    else:
        nb_dict = load_template_notebook(template_variant)
        workflow_path = backpack_path / "workflow" / f"{backpack_name}.ipynb"
        with open(workflow_path, "w") as f:
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

    workflow_type = "script" if use_script else "notebook"
    print(f"[floability] Backpack initialized from template: {template_variant} ({workflow_type})")
    print(f"[floability]   Location: {backpack_path}")
    print(f"[floability]   Workflow: {workflow_path.name}")
    print(f"[floability]   Environment: environment.yml")
    print(f"[floability]   Compute: compute.yml")
    if has_data:
        print(f"[floability]   Data: data.yml + 10 sample files in data/text_data/")


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
    print("  2. Provide conda and/or pip packages")
    print("  3. Skip (barebones: python + ndcctools)")
    print()

    choice = input("Select option (1-3, default 3): ").strip() or "3"

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
        conda_str = input(
            "Conda packages (comma-separated, optional; e.g., ndcctools,numpy=2.6.4): "
        ).strip()
        pip_str = input(
            "Pip packages (comma-separated, optional; e.g., dask==2024.4.2,rich): "
        ).strip()
        raw_conda_packages = [p.strip() for p in conda_str.split(",") if p.strip()]
        conda_packages = list(raw_conda_packages)
        provided_package_names = {
            extract_conda_package_name(spec) for spec in raw_conda_packages
        }
        for required_package in ["python", "ndcctools"]:
            if required_package not in provided_package_names:
                conda_packages.append(required_package)
        pip_packages = [p.strip() for p in pip_str.split(",") if p.strip()]

        if raw_conda_packages or pip_packages:
            conda_deps = conda_packages
            if pip_packages:
                conda_deps.append("pip")
                conda_deps.append({"pip": pip_packages})

            env_dict = {
                "name": backpack_name,
                "channels": ["conda-forge"],
                "dependencies": conda_deps,
            }
            print(
                f"[floability] Generated environment with {len(conda_packages)} conda packages "
                f"and {len(pip_packages)} pip packages"
            )

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
        print(
            "[floability] Note: data.yml is a starter spec. Review and complete it before running."
        )

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
        strict: When True, perform deeper validation such as workflow parsing
            and data.yml spec validation (if present).

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

    # Validate backpack name
    backpack_name = backpack_path.name
    if not backpack_name or not backpack_name.replace("-", "").replace("_", "").isalnum():
        result["valid"] = False
        result["problems"].append(
            f"Invalid backpack name: {backpack_name}. Use alphanumeric characters, hyphens, and underscores."
        )

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

        if strict and result["workflow_file"]:
            workflow_path = workflow_dir / result["workflow_file"]
            try:
                if workflow_path.suffix == ".ipynb":
                    with open(workflow_path) as f:
                        json.load(f)
                else:
                    if workflow_path.stat().st_size == 0:
                        raise ValueError("Workflow file is empty")
            except Exception as e:
                result["valid"] = False
                result["problems"].append(f"Invalid workflow file: {workflow_path.name} ({e})")

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

        try:
            from .data.data_handler import load_and_validate_spec, check_data_from_spec

            load_and_validate_spec(
                data_spec=str(data_file),
                backpack_root=backpack_path,
                requested_profile=None,
                verbose=False,
                op_label="validate",
            )
        except ValueError as e:
            result["valid"] = False
            result["problems"].append(f"[data] {e}")
        except Exception as e:
            result["valid"] = False
            result["problems"].append(f"[data] Failed to validate spec: {e}")

        if strict and result["valid"]:
            try:
                sources_ok = check_data_from_spec(
                    data_spec=str(data_file),
                    backpack_root=backpack_path,
                    show_details=False,
                    verbose=False,
                    data_profile=None,
                    data_cache_mode="off",
                    base_dir=None,
                    cache_base_dir=None,
                    target_root=None,
                )
                if not sources_ok:
                    result["valid"] = False
                    result["problems"].append(
                        "[data] Source validation failed (see data:check output)"
                    )
            except Exception as e:
                result["valid"] = False
                result["problems"].append(
                    f"[data] Failed to validate data sources: {e}"
                )

    return result


# ============================================================================
# ENVIRONMENT UPDATE FROM INSTANCE
# ============================================================================

# Standard conda environment.yml keys — everything else in the backpack's
# environment.yml is floability-specific and must be preserved as-is.
_CONDA_ENV_KEYS = {"name", "channels", "dependencies", "prefix", "variables"}


def _resolve_instance_path(instance_ref: str) -> Path:
    """Resolve an instance reference (path or short name) to an absolute Path."""
    from .instance_registry import resolve_instance

    resolved = resolve_instance(instance_ref)
    if not resolved:
        raise ValueError(
            f"Instance not found: '{instance_ref}'. "
            "Provide a valid directory path or registered instance name."
        )
    path = Path(resolved)
    if not path.is_dir():
        raise ValueError(f"Instance directory does not exist: {path}")
    return path


def _read_env_dir_from_metadata(instance_path: Path) -> str:
    """Read the conda env_dir from instance metadata/run.json."""
    run_json = instance_path / "metadata" / "run.json"
    if not run_json.exists():
        raise ValueError(f"Instance metadata not found: {run_json}")

    with open(run_json, "r") as f:
        metadata = json.load(f)

    env_dir = metadata.get("env_dir")
    if not env_dir:
        raise ValueError(
            f"'env_dir' not found in {run_json}. "
            "The instance may not have completed environment setup."
        )
    return env_dir


def _export_conda_env(env_dir: str) -> Dict[str, Any]:
    """Run `conda env export --no-builds --prefix <env_dir>` and return parsed YAML."""
    print(f"[floability] Exporting conda environment from: {env_dir}")
    result = subprocess.run(
        ["conda", "env", "export", "--no-builds", "--prefix", env_dir],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"conda env export failed (exit {result.returncode}):\n{result.stderr.strip()}"
        )
    exported = yaml.safe_load(result.stdout) or {}
    exported.pop("prefix", None)  # not portable
    return exported


def _has_concrete_version(dep: Any) -> bool:
    """Return True if a conda dependency string has a concrete version pinned."""
    if isinstance(dep, dict):
        return True  # pip section dict — handled separately
    return "=" in str(dep)


def _filter_concrete_deps(dependencies: List[Any]) -> List[Any]:
    """Keep only deps with concrete versions; apply the same filter to pip entries."""
    filtered: List[Any] = []
    for dep in dependencies:
        if isinstance(dep, dict) and "pip" in dep:
            pip_deps = [p for p in dep["pip"] if "==" in str(p)]
            if pip_deps:
                filtered.append({"pip": pip_deps})
        elif _has_concrete_version(dep):
            filtered.append(dep)
    return filtered


def _extra_floability_fields(env: Dict[str, Any]) -> Dict[str, Any]:
    """Return any non-conda keys from the env dict (e.g. post_install_script)."""
    return {k: v for k, v in env.items() if k not in _CONDA_ENV_KEYS}


def _build_full_replacement(
    exported: Dict[str, Any],
    old_env: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a full replacement env dict from the conda export.

    - Name is always taken from the existing backpack environment.yml.
    - Channels come from the export.
    - Dependencies are filtered to concrete versions only.
    - Floability-specific keys (e.g. post_install_script) are preserved from old_env.
    """
    new_env: Dict[str, Any] = {}

    # Always use the user-provided name from the existing backpack env
    new_env["name"] = old_env["name"]

    new_env["channels"] = exported.get("channels", ["conda-forge"])
    new_env["dependencies"] = _filter_concrete_deps(exported.get("dependencies", []))

    # Preserve floability-specific keys
    new_env.update(_extra_floability_fields(old_env))

    return new_env


def _build_versions_only(
    exported: Dict[str, Any],
    old_env: Dict[str, Any],
) -> Dict[str, Any]:
    """Patch versions for packages already listed in the backpack environment.yml.

    All other fields — including name and floability-specific keys — are left
    exactly as the user wrote them. Only the version specs are updated based on
    what is actually installed in the exported environment.
    """
    # Build lookup: lowercase package name -> full exported spec string
    exported_conda: Dict[str, str] = {}
    exported_pip: Dict[str, str] = {}
    for dep in exported.get("dependencies", []):
        if isinstance(dep, dict) and "pip" in dep:
            for pip_dep in dep["pip"]:
                pkg = re.split(r"[<>=!~\s]", str(pip_dep).strip(), maxsplit=1)[0].lower()
                exported_pip[pkg] = str(pip_dep)
        elif isinstance(dep, str):
            pkg = re.split(r"[<>=!~\s]", dep.strip(), maxsplit=1)[0].lower()
            exported_conda[pkg] = dep

    # Start from a copy of the old env so all user fields (name, channels,
    # post_install_script, etc.) are preserved unchanged.
    new_env = {k: v for k, v in old_env.items() if k != "dependencies"}

    updated_deps: List[Any] = []
    for dep in old_env.get("dependencies", []):
        if isinstance(dep, dict) and "pip" in dep:
            updated_pip: List[str] = []
            for pip_dep in dep["pip"]:
                pkg = re.split(r"[<>=!~\s]", str(pip_dep).strip(), maxsplit=1)[0].lower()
                if pkg in exported_pip:
                    new_spec = exported_pip[pkg]
                    if new_spec != str(pip_dep):
                        print(f"[floability]   pip: {pip_dep} -> {new_spec}")
                    updated_pip.append(new_spec)
                else:
                    updated_pip.append(pip_dep)
            updated_deps.append({"pip": updated_pip})
        elif isinstance(dep, str):
            pkg = re.split(r"[<>=!~\s]", dep.strip(), maxsplit=1)[0].lower()
            if pkg in exported_conda:
                new_spec = exported_conda[pkg]
                if new_spec != dep:
                    print(f"[floability]   {dep} -> {new_spec}")
                updated_deps.append(new_spec)
            else:
                updated_deps.append(dep)
        else:
            updated_deps.append(dep)

    new_env["dependencies"] = updated_deps
    return new_env


def update_env_from_instance(
    instance_ref: str,
    backpack_path: Path,
    versions_only: bool = False,
) -> None:
    """Update backpack software/environment.yml from a completed instance's conda env.

    Steps:
      1. Resolve instance_ref to an absolute path (directory or registry name).
      2. Read env_dir from instance metadata/run.json.
      3. Export the conda environment with --no-builds (strips prefix field).
      4. Load the existing backpack environment.yml.
      5. Build the new environment dict (full replacement or versions-only patch).
      6. Save a backup as software/old-environment.yml.
      7. Write the updated software/environment.yml.

    Args:
        instance_ref: Instance directory path or registered short name.
        backpack_path: Path to the backpack directory.
        versions_only: When True, only update versions of packages already listed
                       in the backpack env; leave all other fields unchanged.
    """
    software_dir = backpack_path / "software"
    env_yml_path = software_dir / "environment.yml"

    if not env_yml_path.exists():
        raise ValueError(
            f"Backpack environment.yml not found: {env_yml_path}\n"
            "Make sure you point to a valid backpack directory."
        )

    # Resolve instance and read env_dir
    instance_path = _resolve_instance_path(instance_ref)
    print(f"[floability] Using instance: {instance_path}")
    env_dir = _read_env_dir_from_metadata(instance_path)
    print(f"[floability] Conda environment: {env_dir}")

    exported = _export_conda_env(env_dir)

    with open(env_yml_path, "r") as f:
        old_env = yaml.safe_load(f) or {}

    if "name" not in old_env:
        raise ValueError(
            f"Existing environment.yml has no 'name' field: {env_yml_path}"
        )

    print(f"[floability] Env name (preserved): {old_env['name']}")

    if versions_only:
        print("[floability] Mode: versions-only (patching existing package versions)")
        new_env = _build_versions_only(exported, old_env)
    else:
        print("[floability] Mode: full replacement (using exported dependency list)")
        new_env = _build_full_replacement(exported, old_env)

    # Backup before overwriting
    backup_path = software_dir / "old-environment.yml"
    shutil.copy2(env_yml_path, backup_path)
    print(f"[floability] Saved backup: {backup_path}")

    with open(env_yml_path, "w") as f:
        yaml.safe_dump(new_env, f, default_flow_style=False, sort_keys=False)

    mode_label = "versions patched" if versions_only else "full replacement"
    print(f"[floability] Updated environment.yml ({mode_label}): {env_yml_path}")
