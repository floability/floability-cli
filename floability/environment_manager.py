# environment.py
import os
import yaml  # pyyaml needed
import json
import shutil
import logging
import subprocess
import tempfile
import hashlib
import textwrap
from pathlib import Path
from typing import Optional, Tuple


def create_conda_pack_from_yml(
    env_yml: str,
    force: bool = False,
    output_file: str = None,
    base_dir: str = "/tmp",
    run_dir: str = "/tmp",
    manager_name: str = None,
    manager_ports: str = "9123,9150",
    is_worker_env: bool = False,
) -> str:
    # Prepare shared directories for env cache
    common_env_dir = os.path.join(base_dir, "flo_common_env")
    extracted_envs_dir = os.path.join(common_env_dir, "extracted_envs")
    tarballs_dir = os.path.join(common_env_dir, "tarballs")
    os.makedirs(extracted_envs_dir, exist_ok=True)
    os.makedirs(tarballs_dir, exist_ok=True)

    # Generate a unique filename based on the hash of the environment file content
    with open(env_yml, "r") as f:
        raw_content = f.read()
    cleaned_content = "".join(raw_content.split())
    file_hash = hashlib.md5(cleaned_content.encode("utf-8")).hexdigest()

    extracted_env_path = os.path.join(extracted_envs_dir, f"env_{file_hash}")
    if output_file is None:
        output_file = os.path.join(tarballs_dir, f"env_{file_hash}.tar.gz")

    print(f"[environment] Output file: {output_file}")

    # If both extracted env and tarball exist and not forced, reuse
    if os.path.exists(extracted_env_path) and os.path.exists(output_file) and not force:
        print(
            f"[environment] Using cached extracted env at '{extracted_env_path}' and tarball '{output_file}'."
        )
        return output_file

    if is_worker_env:
        required_packages = ["python", "cloudpickle"]
        print(
            "[environment] Creating worker environment (no Jupyter or ndcctools required)"
        )
    else:
        required_packages = ["python", "jupyter", "ndcctools", "cloudpickle"]
        print("[environment] Creating manager environment with Jupyter and ndcctools")

    env_path = extracted_env_path
    if os.path.exists(env_path) and force:
        print(f"[environment] [force] Removing shared cached base env: {env_path}")
        shutil.rmtree(env_path, ignore_errors=True)
    os.makedirs(os.path.dirname(env_path), exist_ok=True)

    # Determine whether we need to (re)create and/or (re)pack
    need_create = not os.path.exists(env_path)
    need_pack = force or not os.path.exists(output_file)

    modified_yml = None
    wrapper_script = None

    try:
        # Load and adjust env spec
        with open(env_yml, "r") as f:
            env_data = yaml.safe_load(f)

        if "dependencies" not in env_data:
            env_data["dependencies"] = []

        for pkg in required_packages:
            if pkg not in env_data["dependencies"]:
                env_data["dependencies"].append(pkg)

        # Do not inject manager-specific variables into the base env YAML.
        # These will be applied per-instance (clone/extracted) or via process env.

        # Check for post-installation script in the environment YAML
        post_install_script = env_data.get("post_install_script", None)

        if post_install_script:
            script_dir = os.path.dirname(env_yml)
            if not os.path.isabs(post_install_script):
                post_install_script = os.path.join(script_dir, post_install_script)

        print(
            f"[environment] Creating environment with the following packages: {env_data['dependencies']}"
        )

        if post_install_script:
            print(f"[environment] Post-installation script: {post_install_script}")

        # Remove post_install_script from env_data before writing to modified YAML
        if "post_install_script" in env_data:
            del env_data["post_install_script"]

        # Write modified YAML to a secure temporary file
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".yml", prefix="floability_env_", delete=False
        )
        try:
            yaml.safe_dump(env_data, tmp)
            tmp.flush()
            modified_yml = tmp.name
        finally:
            tmp.close()

        # Create environment if needed
        if need_create:
            print(f"[environment] Creating env from '{env_yml}' into '{env_path}'...")
            cmd_create = [
                "conda",
                "env",
                "create",
                "--file",
                modified_yml,
                "--prefix",
                env_path,
            ]
            subprocess.run(cmd_create, check=True)

            # Run an optional post-installation script inside the newly created environment
            if post_install_script and os.path.exists(post_install_script):
                wrapper_script = os.path.join(env_path, "_exec_post_install.sh")
                script = textwrap.dedent(
                    f"""\
                    #!/bin/bash
                    # Initialize Conda in Bash
                    eval "$(conda shell.bash hook)"

                    # Activate the environment
                    conda activate {env_path}

                    # Set CONDA_PREFIX
                    export CONDA_PREFIX={env_path}

                    echo "[environment] Activated environment at $CONDA_PREFIX"

                    # Execute the user-provided script
                    bash {post_install_script}

                    # Exit with script's status
                    exit $?
                    """
                )
                with open(wrapper_script, "w") as wf:
                    wf.write(script)
                os.chmod(wrapper_script, 0o755)
                print(script)
                result = subprocess.run(["bash", wrapper_script], check=False)
                if result.returncode != 0:
                    print(
                        f"[environment] Post-installation script failed with code {result.returncode}"
                    )
                    raise subprocess.CalledProcessError(
                        result.returncode, wrapper_script
                    )
                else:
                    print(
                        f"[environment] Post-installation script executed successfully."
                    )

        # Pack environment if needed
        if need_pack:
            print(f"[environment] Packing environment into '{output_file}'...")
            cmd_pack = ["conda-pack", "-p", env_path, "-o", output_file, "--force"]
            subprocess.run(cmd_pack, check=True)
            print(f"[environment] Environment successfully packed: {output_file}")

    except subprocess.CalledProcessError as e:
        print(f"[environment] Error creating or packing environment: {e}")
        raise
    finally:
        # Best-effort cleanup of the temporary modified YAML and wrapper
        if modified_yml:
            try:
                if os.path.exists(modified_yml):
                    os.remove(modified_yml)
            except Exception:
                pass
        if wrapper_script:
            try:
                if os.path.exists(wrapper_script):
                    os.remove(wrapper_script)
            except Exception:
                pass

    return output_file


# Higher-level environment management functions


def prepare_conda_environment(
    environment_spec: str,
    base_dir: str,
    run_dir: str,
    manager_name: str,
    is_worker_env: bool = False,
    force: bool = False,
    perf=None,  # PerformanceTracker
) -> str:
    """
    Create or resolve a conda-pack environment file.

    Args:
        environment_spec: Path to environment.yml or .tar.gz file
        base_dir: Base directory for floability files
        run_dir: Run directory
        manager_name: Manager name for the environment
        is_worker_env: Whether this is a worker environment
        force: Force recreation of environment
        perf: Optional performance tracker

    Returns:
        Path to the conda-pack .tar.gz file
    """
    env_file_path = Path(environment_spec)
    ext = env_file_path.suffix

    # If already a packed environment, return it
    if ext in [".tar", ".gz"] or str(environment_spec).endswith(".tar.gz"):
        print(f"[floability] Using conda-pack from '{environment_spec}'")
        return str(env_file_path.resolve())

    # Create conda-pack from YAML
    env_type = "worker" if is_worker_env else "manager"
    print(f"[floability] Creating {env_type} conda-pack from '{environment_spec}'")

    timer_name = f"{env_type}_env_creation"
    if perf:
        perf.start_timer(timer_name)

    environment_pack = create_conda_pack_from_yml(
        env_yml=environment_spec,
        force=force,
        base_dir=base_dir,
        run_dir=run_dir,
        manager_name=manager_name,
        is_worker_env=is_worker_env,
    )

    if perf:
        perf.end_timer(timer_name, f"Time to create {env_type} conda environment")
        perf.measure_file_size(environment_pack, f"{env_type}_environment_pack")

    return environment_pack


def extract_conda_environment(
    environment_pack: str,
    extract_dir: str,
    manager_name: str,
    manager_ports: str = "9123,9150",
    env_vars: Optional[str] = None,
    perf=None,  # PerformanceTracker
) -> str:
    """
    Extract a conda-pack environment and configure it.

    Args:
        environment_pack: Path to the conda-pack .tar.gz file
        extract_dir: Directory where environment should be extracted
        manager_name: Manager name to set in environment
        manager_ports: Manager ports to set in environment
        env_vars: Additional environment variables to set
        perf: Optional performance tracker

    Returns:
        Path to the extracted environment directory
    """
    from .utils import safe_extract_tar, update_env_vars_in_conda

    # Make extract_dir absolute to avoid working directory issues
    env_dir = os.path.abspath(extract_dir)
    print(f"[floability] Conda environment directory: {env_dir}")
    # Fast path: if environment_pack looks like our cached tarball name env_<hash>.tar.gz,
    # try cloning from the shared extracted env to the instance directory.
    pack_name = os.path.basename(environment_pack)
    cloned = False
    prefer_clone = False #Todo: this is temp flag to test performance of cloning vs extraction
    if prefer_clone and pack_name.startswith("env_") and pack_name.endswith(".tar.gz"):
        file_hash = pack_name[len("env_") : -len(".tar.gz")]
        # Derive common extracted path based on the tarball's parent structure
        # Assume layout: .../flo_common_env/tarballs/env_<hash>.tar.gz
        tarballs_dir = os.path.dirname(environment_pack)
        common_env_dir = os.path.dirname(tarballs_dir)
        extracted_envs_dir = os.path.join(common_env_dir, "extracted_envs")
        candidate = os.path.join(extracted_envs_dir, f"env_{file_hash}")
        if os.path.isdir(candidate):
            try:
                if perf:
                    perf.start_timer("clone_environment")
                print(
                    f"[floability] Cloning cached env '{candidate}' -> '{env_dir}' ..."
                )
                subprocess.run(
                    [
                        "conda",
                        "create",
                        "--yes",
                        "--prefix",
                        env_dir,
                        "--clone",
                        candidate,
                    ],
                    check=True,
                )
                if perf:
                    perf.end_timer(
                        "clone_environment", "Time to clone conda environment"
                    )
                cloned = True
            except subprocess.CalledProcessError as e:
                print(
                    f"[floability] Warning: conda clone failed, falling back to extraction: {e}"
                )

    if not cloned:
        # Fallback: extract the tarball into env_dir
        try:
            if perf:
                perf.start_timer("extract_environment")

            # Ensure target directory exists only for extraction path
            os.makedirs(env_dir, exist_ok=True)

            safe_extract_tar(Path(environment_pack), Path(env_dir))

            if perf:
                perf.end_timer(
                    "extract_environment", "Time to extract conda environment"
                )
                perf.measure_file_size(env_dir, "extracted_environment")
        except Exception as e:
            raise RuntimeError(f"Error extracting environment: {e}")
        # Run conda-unpack to fix paths after extraction
        try:
            subprocess.run(
                [
                    "conda",
                    "run",
                    "--prefix",
                    env_dir,
                    "--no-capture-output",
                    "conda-unpack",
                ],
                check=True,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Error running conda-unpack: {e}")

    # Update the manager name and other variables in the (cloned or extracted) environment
    update_env_vars_in_conda(env_dir, manager_name, manager_ports, env_vars)

    return env_dir


def setup_manager_and_worker_envs(
    environment_spec: Optional[str],
    worker_environment_spec: Optional[str],
    base_dir: str,
    instance_root: str,
    manager_name: str,
    manager_ports: str = "9123,9150",
    env_vars: Optional[str] = None,
    force: bool = False,
    perf=None,  # PerformanceTracker
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Set up both manager and worker conda environments.

    Args:
        environment_spec: Path to manager environment.yml or .tar.gz
        worker_environment_spec: Path to worker environment.yml or .tar.gz
        base_dir: Base directory for floability files
        instance_root: Instance root directory
        manager_name: Manager name
        manager_ports: Manager ports
        env_vars: Additional environment variables
        force: Force recreation of environments
        perf: Optional performance tracker

    Returns:
        Tuple of (env_dir, worker_environment_pack, manager_environment_pack)
        - env_dir is None if no manager environment
        - worker_environment_pack is None if no worker environment
        - manager_environment_pack is None if no manager environment
    """
    env_dir = None
    worker_environment_pack = None
    manager_environment_pack = None

    # Setup manager environment
    if environment_spec:
        manager_environment_pack = prepare_conda_environment(
            environment_spec=environment_spec,
            base_dir=base_dir,
            run_dir=instance_root,
            manager_name=manager_name,
            is_worker_env=False,
            force=force,
            perf=perf,
        )

        # Extract to instance root
        extract_dir = os.path.join(instance_root, "current_conda_env")
        env_dir = extract_conda_environment(
            environment_pack=manager_environment_pack,
            extract_dir=extract_dir,
            manager_name=manager_name,
            manager_ports=manager_ports,
            env_vars=env_vars,
            perf=perf,
        )
    else:
        print("[floability] No environment file provided, skipping conda-pack.")

    # Setup worker environment
    if worker_environment_spec:
        worker_environment_pack = prepare_conda_environment(
            environment_spec=worker_environment_spec,
            base_dir=base_dir,
            run_dir=instance_root,
            manager_name=manager_name,
            is_worker_env=True,
            force=force,
            perf=perf,
        )
    else:
        # Use manager environment for workers if no separate worker environment
        if manager_environment_pack:
            # Reuse the manager pack; avoid duplicate creation
            worker_environment_pack = manager_environment_pack

    if (
        manager_environment_pack
        and worker_environment_pack
        and manager_environment_pack != worker_environment_pack
    ):
        print("[floability] Worker environment is different from main environment.")
        print(f"[floability] Worker environment pack: {worker_environment_pack}")

    return env_dir, worker_environment_pack, manager_environment_pack
