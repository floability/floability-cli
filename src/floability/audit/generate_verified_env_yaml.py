import sys
import os
import subprocess
import json
import re
import yaml
import pathlib
import argparse
import platform
from collections import defaultdict


def get_filtered_dependencies(dependencies):
    """
    Filter out dependencies that are not relevant for the environment irrelevant of the version of dependencies.
    """
    exceptions = {"floability"}
    output = []

    for dep in dependencies:
        # Remove version information if present
        dep_name = dep.split("==")[0]
        dep_name = dep_name.split(" ")[0]  # Remove any trailing spaces or version
        if dep_name in exceptions:
            continue
        output.append(dep)
        # Further filtering logic can be added here
    return output


def get_environment_type():
    """
    Determines the type of Python environment (venv or conda) based on sys.prefix and environment variables.
    Returns a Tuple:
        - ('venv', python_prefix) if it's a virtual environment
        - ('conda', python_prefix) if it's a conda environment
        - ('unknown', python_prefix) if it cannot be determined
    """

    python_executable = sys.executable
    python_prefix = sys.prefix

    virtual_env_path = os.environ.get("VIRTUAL_ENV")
    conda_prefix_path = os.environ.get("CONDA_PREFIX")

    # Prefer venv if sys.prefix matches VIRTUAL_ENV (covers nested case)
    if virtual_env_path and python_prefix.startswith(virtual_env_path):
        print(f"Info: Detected venv environment based on VIRTUAL_ENV.")
        return "venv", python_prefix

    # Else, check if it's Conda
    elif conda_prefix_path and python_prefix.startswith(conda_prefix_path):
        # Double check with conda-meta for robustness
        conda_meta_path = pathlib.Path(python_prefix) / "conda-meta"
        if conda_meta_path.is_dir():
            print(
                f"Info: Detected Conda environment based on CONDA_PREFIX and conda-meta."
            )
            return "conda", python_prefix
        else:
            # sys.prefix matches CONDA_PREFIX but no conda-meta? Unusual.
            # Still treat as conda based on CONDA_PREFIX match for now.
            print(
                f"Warning: sys.prefix matches CONDA_PREFIX '{conda_prefix_path}' but no conda-meta found."
            )
            return "conda", python_prefix

    # Fallback: If conda thinks an env is active, check if python looks like it came from it
    elif conda_prefix_path and os.environ.get("CONDA_DEFAULT_ENV"):
        conda_meta_path = pathlib.Path(python_prefix) / "conda-meta"
        if conda_meta_path.is_dir():
            print(
                f"Info: Detected Conda environment based on CONDA_DEFAULT_ENV and conda-meta."
            )
            return "conda", python_prefix

    # Fallback: Check if VIRTUAL_ENV is set but didn't match prefix (less likely)
    elif virtual_env_path:
        print(
            f"Warning: VIRTUAL_ENV is set ('{virtual_env_path}') but doesn't match sys.prefix ('{python_prefix}')."
        )
        # Treat as venv if VIRTUAL_ENV is the only indicator? Risky. Default to unknown.
        return (
            "unknown",
            python_prefix,
        )  # Or potentially 'venv' depending on desired strictness

    # If none match, assume system or other environment type
    return "unknown", python_prefix


def get_installed_packages_pip():
    """Gets installed packages using pip list."""
    installed = {}
    try:
        # Use json format for reliable parsing
        result = subprocess.run(
            [sys.executable, "-m", "pip", "list", "--format=json", "--not-required"],
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
        )
        packages = json.loads(result.stdout)
        for pkg in packages:
            # Normalize name for matching (lowercase)
            norm_name = pkg["name"].lower().replace("-", "_")
            # norm_name = pkg['name']
            installed[norm_name] = {
                "name": pkg["name"],  # Keep original name for output
                "version": pkg["version"],
                "channel": "pypi",  # Assume pip means PyPI origin
            }
    except (
        subprocess.CalledProcessError,
        json.JSONDecodeError,
        FileNotFoundError,
    ) as e:
        print(f"Error running pip list: {e}")
    return installed


def get_installed_packages_conda(prefix=None):
    """Gets installed packages using conda list.

    Args:
        prefix: Path to conda environment prefix to query. When None, queries
                the currently active environment.
    """
    installed = {}
    cmd = ["conda", "list", "--json"]
    if prefix:
        cmd += ["--prefix", prefix]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
        )
        packages = json.loads(result.stdout)
        for pkg in packages:
            # Normalize name for matching (lowercase, replace hyphens)
            norm_name = pkg["name"].lower().replace("-", "_")
            channel = pkg.get("channel", "unknown")
            # Conda often shows '<pip>' for pip installed packages
            if channel == "<pip>":
                channel = "pypi"

            installed[norm_name] = {
                "name": pkg["name"],  # Keep original name for output
                "version": pkg["version"],
                "channel": channel,
            }
    except (
        subprocess.CalledProcessError,
        json.JSONDecodeError,
        FileNotFoundError,
    ) as e:
        print(f"Error running conda list: {e}")
        print("Falling back to pip list to get package versions...")
        # Fallback gracefully if conda command fails but we know it's a conda env type
        installed = get_installed_packages_pip()
        # Mark channels as unknown if we fell back
        for data in installed.values():
            data["channel"] = "unknown_conda_fallback"

    return installed


def normalize_req_line(line):
    """
    Extracts a normalized package name from a requirements line.
    Handles name==version, name>=version, name-version.dist-info, name-version.egg-info etc.
    Returns None if it's a comment, empty, or looks like a path/invalid line.
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    # Ignore lines that look like paths
    if "/" in line or "\\" in line or line == "__pycache__":
        return None

    # Match common patterns first (e.g., name==version, name>=version)
    # Simple split approach first, then regex if needed
    match = re.match(r"^([a-zA-Z0-9_.-]+)", line)
    if not match:
        return None  # Doesn't start like a package name

    name_part = match.group(1)

    # Attempt to refine name by removing potential version suffixes like .dist-info/.egg-info
    # Regex to find common package name patterns before version/suffixes
    # This tries to capture 'package-name' from 'package-name-1.2.3.dist-info'
    # or 'package_name' from 'package_name==1.0'
    # It's not perfect but covers many common cases.
    refined_match = re.match(
        r"^([a-zA-Z0-9_.-]+?)(?:[=<>!~]=?|[-_](?:[0-9]+[.!-]?)|\.(?:dist|egg)-info)",
        line,
        re.IGNORECASE,
    )

    if refined_match:
        potential_name = refined_match.group(1)
    else:
        # If no version/suffix found, assume the whole initial part is the name
        potential_name = name_part

    # Basic sanity check - avoid overly short names if they resulted from suffix removal
    if len(potential_name) < 2 and len(name_part) > len(potential_name):
        potential_name = name_part  # Revert if suffix removal made it too short

    # Normalize: lowercase and replace dashes with underscores for consistent dict keys
    # Keep original dashes/underscores in the name itself for output later if needed?
    # Let's normalize for the key, but we retrieve the original name from installed list
    return potential_name.lower().replace("-", "_")


# --- Main Logic ---


def main(requirements_file, output="environment.yaml", env_name="reconstructed-env", conda_prefix=None):

    req_file_path = pathlib.Path(requirements_file)
    output_file_path = pathlib.Path(output)

    if not req_file_path.is_file():
        print(f"Error: Input requirements file not found: {req_file_path}")
        sys.exit(1)

    print(f"Step 1: Determining active environment type...")
    if conda_prefix:
        # Target env is always conda when explicitly specified
        env_type = "conda"
        print(f"--> Using specified conda env: {conda_prefix}")
    else:
        env_type, active_prefix = get_environment_type()
        print(f"--> Active environment type: {env_type}")
        print(f"--> Active Python prefix: {active_prefix}")

    if env_type == "unknown":
        print(
            "Warning: Could not reliably determine environment type. Assuming 'pip'-based workflow."
        )
        env_type = "venv"

    print(f"\nStep 2: Getting installed packages from {conda_prefix or 'active'} environment...")
    if env_type == "conda":
        installed_packages = get_installed_packages_conda(prefix=conda_prefix)
    else:
        installed_packages = get_installed_packages_pip()

    if not installed_packages:
        print("Error: Could not retrieve installed packages. Exiting.")
        sys.exit(1)
    print(f"--> Found {len(installed_packages)} installed packages.")
    # print("Installed packages:", json.dumps(installed_packages, indent=2)) # Debug print

    print(f"\nStep 3: Parsing requirements file '{req_file_path}'...")
    required_packages_norm = set()
    try:
        with open(req_file_path, "r", encoding="utf-8") as f:
            for line in f:
                norm_name = normalize_req_line(line)
                if norm_name:
                    required_packages_norm.add(norm_name)
    except Exception as e:
        print(f"Error reading requirements file: {e}")
        sys.exit(1)
    print(f"--> Found {len(required_packages_norm)} potential requirements entries.")
    # print("Normalized required names:", required_packages_norm) # Debug print

    print(
        "\nStep 4: Matching requirements to installed packages and building dependencies..."
    )
    conda_deps = []
    pip_deps = []
    conda_channels = set(["defaults"])  # Start with defaults
    processed_norm_names = set()

    # Use sorted list for deterministic output order
    for norm_req_name in sorted(list(required_packages_norm)):
        if norm_req_name in installed_packages:
            package_data = installed_packages[norm_req_name]
            original_name = package_data["name"]
            version = package_data["version"]
            channel = package_data.get("channel", "unknown")  # Ensure channel exists

            dep_string = f"{original_name}=={version}"

            # Add to processed set to avoid duplicates if normalization collided
            processed_norm_names.add(norm_req_name)

            if env_type == "conda":
                # Decide if it's a Conda dep or Pip dep within Conda env
                if (
                    channel != "pypi"
                    and channel != "unknown"
                    and channel != "unknown_conda_fallback"
                ):
                    # Add channel if it's not a default one (heuristic)
                    # if channel not in ['defaults', 'conda-forge', 'anaconda']: # Add more known 'default-like' channels if needed
                    if channel not in [
                        "defaults",
                        "anaconda",
                    ]:  # Add more known 'default-like' channels if needed
                        dep_string = f"{channel}::{dep_string}"

                    if channel not in conda_channels:
                        conda_channels.add(channel)

                    # Add to conda dependencies and channels
                    conda_deps.append(dep_string)
                    print(
                        f"  [Conda Dep]: {dep_string} (Found in installed Conda list, channel: {channel})"
                    )

                else:
                    # Treat PyPI/Unknown channel packages as pip dependencies within conda env
                    pip_deps.append(dep_string)
                    print(
                        f"  [Pip Dep]:   {dep_string} (Found via Conda list as channel '{channel}' or via pip fallback)"
                    )
            else:  # env_type is 'venv' or 'unknown'
                pip_deps.append(dep_string)
                print(f"  [Pip Dep]:   {dep_string} (Found in installed pip list)")

        else:
            print(
                f"  \n**[Not Found]:** {norm_req_name} (Not found in the list of currently installed packages)\n"
            )

    # Get Python version from the queried package list so it matches the target env
    python_pkg = installed_packages.get("python")
    python_version = python_pkg["version"] if python_pkg else platform.python_version()
    conda_deps.insert(0, f"python=={python_version}")
    print(f"\nAdded Python dependency: python=={python_version}")

    # Ensure pip is included if there are pip dependencies
    if (
        pip_deps
        and not any(p.startswith("pip==") for p in conda_deps)
        and not any(p.startswith("pip==") for p in pip_deps)
    ):
        if "pip" in installed_packages:
            pip_version = installed_packages["pip"]["version"]
            # Add to conda deps list usually
            conda_deps.append(f"pip=={pip_version}")
            print(f"Added Pip dependency: pip=={pip_version}")
        else:
            conda_deps.append("pip")  # Add pip without version if not found
            print("Added Pip dependency (no specific version found)")

    print("\nStep 5: Generating environment.yaml structure...")
    # Sensible default channels - add any specific ones found earlier
    if "conda-forge" in conda_channels:  # Prioritize conda-forge if used
        ordered_channels = ["conda-forge"] + sorted(
            list(conda_channels - {"conda-forge"})
        )
    else:
        ordered_channels = sorted(list(conda_channels))

    conda_deps = get_filtered_dependencies(conda_deps)
    pip_deps = get_filtered_dependencies(pip_deps)

    yaml_data = {
        "name": env_name,
        "channels": ordered_channels,
        "dependencies": sorted(conda_deps),  # Sort conda deps alphabetically
    }

    if pip_deps:
        # Add the pip section only if there are pip dependencies
        yaml_data["dependencies"].append(
            {"pip": sorted(pip_deps)}
        )  # Sort pip deps alphabetically

    print(f"\nStep 6: Writing YAML to '{output_file_path}'...")
    print("YAML structure:\n")
    print(yaml.dump(yaml_data, default_flow_style=False, sort_keys=False))
    # Write to the output file
    try:
        with open(output_file_path, "w", encoding="utf-8") as f:
            yaml.dump(yaml_data, f, default_flow_style=False, sort_keys=False)
        print("Done.")
    except Exception as e:
        print(f"Error writing YAML file: {e}")
        sys.exit(1)
