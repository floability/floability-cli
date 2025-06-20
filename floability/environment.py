# environment.py
import os
import yaml  # pyyaml needed
import json
import shutil
import logging
import tempfile
import subprocess
import hashlib
import textwrap


def create_conda_pack_from_yml(
    env_yml: str,
    solver: str = "libmamba",
    force: bool = False,
    output_file: str = None,
    base_dir: str = "/tmp",
    run_dir: str = "/tmp",
    manager_name: str = None,
    is_worker_env: bool = False,
) -> str:
    common_env_dir = os.path.join(base_dir, "flo_common_env")
    os.makedirs(common_env_dir, exist_ok=True)

    if output_file is None:
        # Generate a unique filename based on the hash of the environment file conent
        with open(env_yml, "r") as f:
            raw_content = f.read()
        cleaned_content = "".join(raw_content.split())
        file_hash = hashlib.md5(cleaned_content.encode("utf-8")).hexdigest()

        output_file = os.path.join(common_env_dir, f"env_{file_hash}.tar.gz")

    print(f"[environment] Output file: {output_file}")

    if os.path.exists(output_file) and not force:
        print(
            f"[environment] '{output_file}' already exists. Skipping environment creation."
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

    temp_dir = tempfile.mkdtemp(prefix="conda_env_")
    env_path = os.path.join(temp_dir, "env")

    try:
        with open(env_yml, "r") as f:
            env_data = yaml.safe_load(f)

        if "dependencies" not in env_data:
            env_data["dependencies"] = []

        for pkg in required_packages:
            if pkg not in env_data["dependencies"]:
                env_data["dependencies"].append(pkg)

        if "variables" not in env_data:
            env_data["variables"] = {}

        if manager_name is None:
            env_data["variables"]["VINE_MANAGER_NAME"] = manager_name

        # Check for post-installation script in the environment YAML
        post_install_script = env_data.get("post_install_script", None)

        if post_install_script:
            script_dir = os.path.dirname(env_yml)
            if not os.path.isabs(post_install_script):
                post_install_script = os.path.join(script_dir, post_install_script)

        print(
            f"[environment] Creating environment with the following packages: {env_data['dependencies']} and variables: {env_data['variables']}"
        )

        if post_install_script:
            print(f"[environment] Post-installation script: {post_install_script}")

        # Remove post_install_script from env_data before writing to modified YAML
        if "post_install_script" in env_data:
            del env_data["post_install_script"]

        modified_yml = os.path.join(temp_dir, "modifed_env.yml")

        with open(modified_yml, "w") as f:
            yaml.safe_dump(env_data, f)

        print(f"[environment] Creating env from '{env_yml}' with solver={solver}...")
        cmd_create = [
            "conda",
            "env",
            "create",
            "--file",
            modified_yml,
            "--prefix",
            env_path,
            "--solver",
            solver,
        ]
        subprocess.run(cmd_create, check=True)

        if post_install_script and os.path.exists(post_install_script):
            wrapper_script = os.path.join(temp_dir, "exec_script.sh")

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
            
            sleep 5

            # Execute the user-provided script
            bash {post_install_script}

            # Exit with script's status
            exit $?
            """
            )

            with open(wrapper_script, "w") as f:
                f.write(script)

            # Make the wrapper script executable
            os.chmod(wrapper_script, 0o755)

            print(script)

            result = subprocess.run(["bash", wrapper_script], check=False)

            if result.returncode != 0:
                print(
                    f"[environment] Post-installation script failed with code {result.returncode}"
                )
                raise subprocess.CalledProcessError(result.returncode, wrapper_script)
            else:
                print(f"[environment] Post-installation script executed successfully.")

        print(f"[environment] Packing environment into '{output_file}'...")
        cmd_pack = ["conda-pack", "-p", env_path, "-o", output_file, "--force"]
        subprocess.run(cmd_pack, check=True)

        print(f"[environment] Environment successfully packed: {output_file}")

    except subprocess.CalledProcessError as e:
        print(f"[environment] Error creating or packing environment: {e}")
        raise
    finally:
        print(f"[environment] Cleaning up temporary directory: {temp_dir}")
        shutil.rmtree(temp_dir, ignore_errors=True)

    return output_file
