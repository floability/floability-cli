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
import time
from pathlib import Path
from typing import Optional, Tuple
from dataclasses import dataclass


# -----------------------------------------------------------------------------
# Data Classes
# -----------------------------------------------------------------------------


@dataclass
class EnvCacheInfo:
    """Resolved paths for a cached conda environment."""

    file_hash: str
    shared_env_dir: Path  # .../flo_common_env/extracted_envs/env_<hash>/
    tar_path: Path  # .../flo_common_env/tarballs/env_<hash>.tar.gz


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------


def setup_manager_and_worker_envs(
    environment_spec: str,
    worker_environment_spec: Optional[str],
    base_dir: str,
    instance_root: str,
    per_instance_env: bool = False,
    perf=None,
) -> Tuple[str, str, str]:
    """Set up manager and worker conda environments.

    Manager environment:
      Warms the shared env cache from the YAML spec (no-op if already valid).
      per_instance_env=True  → extract tar into <instance_root>/current_conda_env.
      per_instance_env=False → point env_dir at the shared extracted base.

    Worker environment:
      - worker_environment_spec provided → build a separate worker env.
      - None → reuse the manager tarball.

    Args:
        environment_spec:        Path to manager environment.yml (required).
        worker_environment_spec: Path to worker environment.yml, or None.
        base_dir:                Base directory for floability cache files.
        instance_root:           Instance root directory.
        per_instance_env:        Extract a dedicated conda env per instance.
        perf:                    Optional PerformanceTracker.

    Returns:
        (env_dir, worker_tar, manager_tar)
          env_dir     — active manager conda env path (shared or per-instance).
          worker_tar  — worker conda-pack tarball path.
          manager_tar — manager conda-pack tarball path.
    """

    base_dir = os.path.expanduser(base_dir)
    instance_root = os.path.expanduser(instance_root)
    environment_spec = os.path.expanduser(environment_spec)

    # ── Manager environment ──────────────────────────────────────────────────
    print("[floability] environment setup — warming cache from YAML spec.")
    cache_info = ensure_shared_env(
        environment_spec, base_dir, is_worker_env=False, perf=perf
    )
    manager_tar = str(cache_info.tar_path)

    if per_instance_env:
        print("[floability] per-instance-env: extracting dedicated environment.")
        env_dir = extract_env_to_instance(manager_tar, instance_root, perf)
    else:
        env_dir = str(cache_info.shared_env_dir)
        print(f"[floability] Using shared immutable environment: {env_dir}")

    # ── Worker environment ───────────────────────────────────────────────────
    if worker_environment_spec:
        worker_environment_spec = os.path.expanduser(worker_environment_spec)
        print("[floability] worker environment — warming cache from YAML spec.")
        worker_cache = ensure_shared_env(
            worker_environment_spec, base_dir, is_worker_env=True, perf=perf
        )
        worker_tar = str(worker_cache.tar_path)
        print(
            f"[floability] Worker environment differs from manager. Worker pack: {worker_tar}"
        )
    else:
        worker_tar = manager_tar  # reuse manager pack

    return env_dir, worker_tar, manager_tar


def ensure_shared_env(
    env_yml: str,
    base_dir: str,
    is_worker_env: bool = False,
    force: bool = False,
    perf=None,
) -> EnvCacheInfo:
    """Ensure the shared cached environment exists for a given YAML spec.

    Decision logic (both checks are independent):
      - need_create: force OR shared_env_dir is missing / has no bin/python
      - need_pack:   force OR tar_path does not exist

    If need_create, removes any stale shared_env_dir first, then calls
    _create_conda_env.  If need_pack, calls _pack_conda_env.
    Returns an EnvCacheInfo whose shared_env_dir and tar_path are guaranteed
    to exist and be valid after this call.
    """
    env_yml = os.path.expanduser(env_yml)
    cache_info = _resolve_env_cache_paths(env_yml, base_dir)

    need_create = force or not _is_shared_env_valid(cache_info.shared_env_dir)
    need_pack = force or not cache_info.tar_path.exists()

    if not need_create and not need_pack:
        print(
            f"[environment] Cache hit — shared env: {cache_info.shared_env_dir}, "
            f"tarball: {cache_info.tar_path}"
        )
        return cache_info

    env_type = "worker" if is_worker_env else "manager"

    if need_create:
        if cache_info.shared_env_dir.exists():
            print(
                f"[environment] Removing stale shared env: {cache_info.shared_env_dir}"
            )
            shutil.rmtree(cache_info.shared_env_dir, ignore_errors=True)

        timer = f"{env_type}_env_creation"
        if perf:
            perf.start_timer(timer)
        _create_conda_env(env_yml, str(cache_info.shared_env_dir), is_worker_env)
        if perf:
            perf.end_timer(timer, f"Time to create {env_type} conda environment")

    if need_pack:
        if perf:
            perf.start_timer("pack_environment")
        _pack_conda_env(str(cache_info.shared_env_dir), str(cache_info.tar_path))
        if perf:
            perf.end_timer("pack_environment", "Time to pack conda environment")
            perf.measure_file_size(
                str(cache_info.tar_path), f"{env_type}_environment_pack"
            )

    return cache_info


def extract_env_to_instance(
    tar_path: str,
    instance_root: str,
    perf=None,
) -> str:
    """Extract a conda-pack tarball into <instance_root>/current_conda_env.

    Runs conda-unpack to fix baked-in absolute paths after extraction.
    Does NOT write any env vars into activation scripts — those are
    injected at the process level via _build_instance_env in ops/run.py.

    Returns the path to the extracted env directory.
    Raises RuntimeError on failure.
    """
    from .utils import safe_extract_tar

    env_dir = os.path.abspath(
        os.path.join(os.path.expanduser(instance_root), "current_conda_env")
    )
    print(f"[floability] Extracting environment to: {env_dir}")

    try:
        if perf:
            perf.start_timer("extract_environment")
        os.makedirs(env_dir, exist_ok=True)
        safe_extract_tar(Path(tar_path), Path(env_dir))
        if perf:
            perf.end_timer("extract_environment", "Time to extract conda environment")
            perf.measure_file_size(env_dir, "extracted_environment")
    except Exception as e:
        raise RuntimeError(f"Error extracting environment: {e}")

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

    return env_dir


# -----------------------------------------------------------------------------
# Private Helpers — Level 1
# (called directly by the public methods above)
# -----------------------------------------------------------------------------


def _resolve_env_cache_paths(env_yml: str, base_dir: str) -> EnvCacheInfo:
    """Compute hash and resolve all standard cache directory paths for a YAML spec.

    Creates the cache directory structure if it does not yet exist.
    Does NOT create or validate the environment itself.
    """
    base_dir = os.path.expanduser(base_dir)
    common_env_dir = os.path.join(base_dir, "flo_common_env")
    extracted_envs_dir = os.path.join(common_env_dir, "extracted_envs")
    tarballs_dir = os.path.join(common_env_dir, "tarballs")
    os.makedirs(extracted_envs_dir, exist_ok=True)
    os.makedirs(tarballs_dir, exist_ok=True)

    file_hash = _compute_env_hash(env_yml)
    return EnvCacheInfo(
        file_hash=file_hash,
        shared_env_dir=Path(extracted_envs_dir) / f"env_{file_hash}",
        tar_path=Path(tarballs_dir) / f"env_{file_hash}.tar.gz",
    )


def _is_shared_env_valid(shared_env_dir: Path) -> bool:
    """Return True if the shared extracted env directory looks healthy (has bin/python)."""
    python_exe = shared_env_dir / "bin" / "python"
    return shared_env_dir.is_dir() and python_exe.exists()


def _create_conda_env(env_yml: str, env_path: str, is_worker_env: bool) -> None:
    """Create a conda environment unconditionally from a YAML spec.

    Injects required packages (jupyter+cloudpickle for manager,
    python+cloudpickle for worker) and runs an optional post-install
    script defined via the ``post_install_script`` key in the YAML.

    Raises subprocess.CalledProcessError on failure.
    """

    if is_worker_env:
        required_packages = ["python", "cloudpickle"]
        print("[environment] Creating worker environment (python + cloudpickle)")
    else:
        required_packages = ["python", "jupyter", "cloudpickle"]
        print("[environment] Creating manager environment (jupyter + cloudpickle)")

    with open(env_yml, "r") as f:
        env_data = yaml.safe_load(f)

    if "dependencies" not in env_data:
        env_data["dependencies"] = []
    for pkg in required_packages:
        if pkg not in env_data["dependencies"]:
            env_data["dependencies"].append(pkg)

    if "ndcctools" not in env_data["dependencies"]:
        # Note: we are not makiing it required, becasue sometimes we need custom instalation steps for ndcctools (e.g., from source)
        # but we warn the user if it's not included, since it's required for TaskVine workflows and easy to forget.
        print(
            "=" * 50,
            "[environment] Warning: 'ndcctools' not found in dependencies. ",
            "If your workflow uses TaskVine, you should include 'ndcctools' in your environment.yml",
            "=" * 50,
        )

    # Resolve post-install script before stripping the key from env_data
    post_install_script = env_data.pop("post_install_script", None)
    if post_install_script:
        script_dir = os.path.dirname(env_yml)
        post_install_script = (
            post_install_script
            if os.path.isabs(post_install_script)
            else os.path.join(script_dir, post_install_script)
        )
        print(f"[environment] Post-installation script: {post_install_script}")

    print(f"[environment] Packages: {env_data['dependencies']}")
    print(f"[environment] Creating env at: {env_path}")

    modified_yml: Optional[str] = None
    wrapper_script: Optional[str] = None
    try:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".yml", prefix="floability_env_", delete=False
        )
        try:
            yaml.safe_dump(env_data, tmp)
            tmp.flush()
            modified_yml = tmp.name
        finally:
            tmp.close()

        subprocess.run(
            [
                "conda",
                "env",
                "create",
                "--file",
                modified_yml,
                "--prefix",
                env_path,
            ],
            check=True,
        )

        # Optional post-install script
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
                    f"[environment] Post-install script failed (code {result.returncode})"
                )
                raise subprocess.CalledProcessError(result.returncode, wrapper_script)
            print("[environment] Post-install script executed successfully.")

    except subprocess.CalledProcessError:
        raise
    finally:
        if modified_yml and os.path.exists(modified_yml):
            try:
                os.remove(modified_yml)
            except Exception:
                pass
        if wrapper_script and os.path.exists(wrapper_script):
            try:
                os.remove(wrapper_script)
            except Exception:
                pass


def _pack_conda_env(env_path: str, tar_path: str) -> None:
    """Pack an existing conda environment into a tarball unconditionally.

    Fixes file timestamps first (conda-pack fails on files with mtime=0/None).
    Raises subprocess.CalledProcessError on failure.
    """
    _fix_file_timestamps(env_path)
    print(f"[environment] Packing '{env_path}' → '{tar_path}'")
    subprocess.run(
        ["conda-pack", "-p", env_path, "-o", tar_path, "--force"],
        check=True,
    )
    print(f"[environment] Packed: {tar_path}")


# -----------------------------------------------------------------------------
# Private Helpers — Level 2
# (called by level-1 helpers above)
# -----------------------------------------------------------------------------


def _compute_env_hash(env_yml: str) -> str:
    """Compute a content-based MD5 hash for an environment YAML file.

    Includes the content of any referenced post_install_script so that
    changes to the script also invalidate the cache.
    """
    with open(env_yml, "r") as f:
        raw_content = f.read()

    env_data = yaml.safe_load(raw_content)
    hash_content = raw_content

    post_install_script = env_data.get("post_install_script", None)
    if post_install_script:
        script_dir = os.path.dirname(env_yml)
        script_path = (
            post_install_script
            if os.path.isabs(post_install_script)
            else os.path.join(script_dir, post_install_script)
        )
        if os.path.exists(script_path):
            with open(script_path, "r") as f:
                hash_content += f.read()
        else:
            print(
                f"[environment] Warning: Post-install script not found at {script_path}"
            )

    cleaned = "".join(hash_content.split())
    return hashlib.md5(cleaned.encode("utf-8")).hexdigest()


def _fix_file_timestamps(env_path: str) -> None:
    """Fix files with invalid timestamps that cause conda-pack to fail.

    conda-pack fails on files whose mtime is None or 0. This scans the
    environment directory and resets any such timestamps to the current time.
    """
    current_time = time.time()
    fixed_count = 0
    for root, dirs, files in os.walk(env_path):
        for file in files:
            filepath = os.path.join(root, file)
            try:
                stat_info = os.stat(filepath)
                if stat_info.st_mtime is None or stat_info.st_mtime == 0:
                    os.utime(filepath, (current_time, current_time))
                    fixed_count += 1
            except (OSError, IOError) as e:
                try:
                    os.utime(filepath, (current_time, current_time))
                    fixed_count += 1
                except (OSError, IOError):
                    print(
                        f"[environment] Warning: Could not fix timestamp for {filepath}: {e}"
                    )
    if fixed_count > 0:
        print(f"[environment] Fixed timestamps for {fixed_count} files")
