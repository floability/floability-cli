# environment.py
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import deque
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml  # pyyaml needed

from .environment_toolchain import (
    EnvironmentPlan,
    build_prefix_run_command,
    print_environment_plan,
    resolve_environment_plan,
)

# -----------------------------------------------------------------------------
# Data Classes
# -----------------------------------------------------------------------------


@dataclass
class EnvCacheInfo:
    """Resolved paths for one cached Python environment."""

    file_hash: str
    shared_env_dir: Path
    tar_path: Path
    cache_entry_root: Path | None = None
    specification_hash: str | None = None

    @property
    def root(self) -> Path:
        return self.cache_entry_root or self.shared_env_dir


@dataclass
class EnvironmentSetupResult:
    """Prepared environment paths plus the plans that produced them."""

    env_dir: str
    worker_tar: str
    manager_tar: str
    manager_plan: EnvironmentPlan
    worker_plan: EnvironmentPlan

    def __iter__(self) -> Iterator[str]:
        # Preserve tuple-unpacking compatibility for existing internal callers.
        yield self.env_dir
        yield self.worker_tar
        yield self.manager_tar


class EnvironmentSetupError(RuntimeError):
    """Raised for an actionable environment preparation command failure."""


class EnvironmentStorageError(EnvironmentSetupError):
    """Raised when environment creation fails because storage is exhausted."""


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------


def setup_manager_and_worker_envs(
    environment_spec: str,
    worker_environment_spec: Optional[str],
    base_dir: str,
    instance_root: str,
    per_instance_env: bool = False,
    environment_creator: str = "auto",
    perf=None,
) -> EnvironmentSetupResult:
    """Set up manager and worker Python environments.

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
    if not environment_spec:
        raise ValueError(
            "environment_spec is required. "
            "Provide a path to an environment.yml via --environment."
        )
    environment_spec = os.path.expanduser(environment_spec)

    # ── Manager environment ──────────────────────────────────────────────────
    manager_plan = resolve_environment_plan(environment_creator)
    print_environment_plan(manager_plan, environment_spec)
    print("[floability] environment setup — warming cache from YAML spec.")
    cache_info = ensure_shared_env(
        environment_spec,
        base_dir,
        is_worker_env=False,
        plan=manager_plan,
        perf=perf,
    )
    manager_tar = str(cache_info.tar_path)

    if per_instance_env:
        # Keep the established on-disk name so existing instances, docs, and
        # cleanup tooling remain compatible. The environment type is Python;
        # its initial portable artifact is still conda-pack.
        instance_env_dir = Path(instance_root) / "current_conda_env"
        if _is_shared_env_valid(instance_env_dir):
            env_dir = str(instance_env_dir)
            print(f"[floability] Reusing per-instance environment: {env_dir}")
        else:
            if instance_env_dir.exists():
                print(
                    "[floability] Removing incomplete per-instance environment: "
                    f"{instance_env_dir}"
                )
                _make_dir_writable(str(instance_env_dir))
                shutil.rmtree(instance_env_dir)
            print("[floability] per-instance-env: extracting dedicated environment.")
            env_dir = extract_env_to_instance(manager_tar, instance_root, perf)
    else:
        env_dir = str(cache_info.shared_env_dir)
        print(f"[floability] Using shared immutable environment: {env_dir}")

    # ── Worker environment ───────────────────────────────────────────────────
    if worker_environment_spec:
        worker_environment_spec = os.path.expanduser(worker_environment_spec)
        worker_plan = manager_plan
        print_environment_plan(worker_plan, worker_environment_spec)
        print("[floability] worker environment — warming cache from YAML spec.")
        worker_cache = ensure_shared_env(
            worker_environment_spec,
            base_dir,
            is_worker_env=True,
            plan=worker_plan,
            perf=perf,
        )
        worker_tar = str(worker_cache.tar_path)
        print(
            "[floability] Worker environment differs from manager. "
            f"Worker pack: {worker_tar}"
        )
    else:
        worker_plan = manager_plan
        worker_tar = manager_tar  # reuse manager pack

    return EnvironmentSetupResult(
        env_dir=env_dir,
        worker_tar=worker_tar,
        manager_tar=manager_tar,
        manager_plan=manager_plan,
        worker_plan=worker_plan,
    )


def ensure_shared_env(
    env_yml: str,
    base_dir: str,
    is_worker_env: bool = False,
    force: bool = False,
    environment_creator: str = "auto",
    plan: EnvironmentPlan | None = None,
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
    plan = plan or resolve_environment_plan(environment_creator)
    cache_info = _resolve_env_cache_paths(
        env_yml,
        base_dir,
        creator=plan.creator.family,
    )

    if plan.creator.family == "pixi" and cache_info.root.exists():
        cached_prefix = _read_cached_environment_prefix(cache_info.root)
        if cached_prefix is not None:
            cache_info.shared_env_dir = cached_prefix

    need_create = force or not _is_shared_env_valid(cache_info.shared_env_dir)
    need_pack = force or not cache_info.tar_path.exists()
    if need_create:
        # A rebuilt prefix must always produce a matching archive, even when a
        # stale archive from an interrupted earlier attempt still exists.
        need_pack = True

    if not need_create and not need_pack:
        print(
            f"[environment] Cache hit — shared env: {cache_info.shared_env_dir}, "
            f"tarball: {cache_info.tar_path}"
        )
        return cache_info

    env_type = "worker" if is_worker_env else "manager"

    if need_create:
        if cache_info.root.exists():
            print(
                f"[environment] Removing stale shared env: {cache_info.root}"
            )
            _make_dir_writable(str(cache_info.root))
            shutil.rmtree(cache_info.root, ignore_errors=True)

        timer = f"{env_type}_env_creation"
        if perf:
            perf.start_timer(timer)
        try:
            if plan.creator.family == "conda":
                _create_conda_env(
                    env_yml,
                    str(cache_info.shared_env_dir),
                    is_worker_env,
                    conda_executable=plan.creator.executable,
                )
            elif plan.creator.family == "pixi":
                cache_info.shared_env_dir = _create_pixi_env(
                    env_yml,
                    cache_info.root,
                    is_worker_env,
                    pixi_executable=plan.creator.executable,
                    base_dir=base_dir,
                )
            else:
                raise EnvironmentSetupError(
                    f"Unsupported environment creator: {plan.creator.family}"
                )
        except BaseException:
            if cache_info.root.exists():
                _make_dir_writable(str(cache_info.root))
                shutil.rmtree(cache_info.root, ignore_errors=True)
            raise
        if perf:
            perf.end_timer(timer, f"Time to create {env_type} Python environment")

        _write_environment_cache_manifest(cache_info, plan)

    if need_pack:
        if perf:
            perf.start_timer("pack_environment")
        _pack_conda_env(
            str(cache_info.shared_env_dir),
            str(cache_info.tar_path),
            packer_executable=plan.packer.executable,
        )
        if perf:
            perf.end_timer("pack_environment", "Time to pack Python environment")
            perf.measure_file_size(
                str(cache_info.tar_path), f"{env_type}_environment_pack"
            )

    print(f"[environment] Locking cache entry as read-only: {cache_info.root}")
    _make_dir_readonly(str(cache_info.root))

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
        raise RuntimeError(f"Error extracting environment: {e}") from e

    try:
        conda_unpack_path = os.path.join(env_dir, "bin", "conda-unpack")
        subprocess.run([conda_unpack_path], check=True)
    except (OSError, subprocess.CalledProcessError) as e:
        raise RuntimeError(f"Error running conda-unpack: {e}") from e

    return env_dir


# -----------------------------------------------------------------------------
# Private Helpers — Level 1
# (called directly by the public methods above)
# -----------------------------------------------------------------------------


def _resolve_env_cache_paths(
    env_yml: str,
    base_dir: str,
    creator: str = "conda",
) -> EnvCacheInfo:
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

    specification_hash = _compute_env_hash(env_yml)
    if creator == "conda":
        # Preserve existing Conda cache keys exactly.
        file_hash = specification_hash
        cache_name = f"env_{file_hash}"
    else:
        identity = ":".join(
            (creator, sys.platform, platform.machine(), specification_hash)
        )
        file_hash = hashlib.md5(identity.encode("utf-8")).hexdigest()
        cache_name = f"env_{creator}_{file_hash}"
    cache_root = Path(extracted_envs_dir) / cache_name
    prefix = cache_root if creator == "conda" else cache_root / ".pixi/envs/default"
    return EnvCacheInfo(
        file_hash=file_hash,
        shared_env_dir=prefix,
        tar_path=Path(tarballs_dir) / f"{cache_name}.tar.gz",
        cache_entry_root=cache_root,
        specification_hash=specification_hash,
    )


def _is_shared_env_valid(shared_env_dir: Path) -> bool:
    """Return whether an extracted environment contains ``bin/python``."""
    python_exe = shared_env_dir / "bin" / "python"
    return shared_env_dir.is_dir() and python_exe.exists()


def _conda_package_name(package_spec: str) -> str:
    """Return the normalized package name from a Conda dependency spec."""
    unqualified_spec = package_spec.strip().lower().rsplit("::", maxsplit=1)[-1]
    return re.split(r"[<>=!~\s]", unqualified_spec, maxsplit=1)[0]


def _ensure_runtime_dependencies(dependencies: list, is_worker_env: bool) -> list[str]:
    """Add missing runtime dependencies and return user-facing warnings.

    Existing Conda package specifications always take precedence, including
    versioned and channel-qualified specifications. Pip dependency mappings
    are not Conda package specifications and are ignored here.
    """
    provided_package_names = {
        _conda_package_name(dependency)
        for dependency in dependencies
        if isinstance(dependency, str)
    }
    warnings = []

    if "ndcctools" not in provided_package_names:
        warnings.append(
            "'ndcctools' is not in environment.yml. Add "
            "'ndcctools=7.17.1' if this workflow uses TaskVine."
        )

    required_packages = [
        ("python", "python=3.12"),
        ("cloudpickle", "cloudpickle"),
    ]
    if not is_worker_env:
        required_packages.insert(1, ("jupyter", "jupyter"))

    for package_name, default_spec in required_packages:
        if package_name in provided_package_names:
            continue
        dependencies.append(default_spec)
        provided_package_names.add(package_name)
        warnings.append(
            f"'{package_name}' is not in environment.yml. "
            f"Floability added '{default_spec}'."
        )

    return warnings


def _prepare_environment_spec(
    env_yml: str,
    *,
    is_worker_env: bool,
) -> tuple[dict, str | None]:
    """Load and normalize an environment YAML without changing its source."""
    try:
        with open(env_yml) as stream:
            env_data = yaml.safe_load(stream) or {}
    except (OSError, yaml.YAMLError) as error:
        raise EnvironmentSetupError(
            f"Could not read environment specification {env_yml}: {error}"
        ) from error
    if not isinstance(env_data, dict):
        raise EnvironmentSetupError(
            f"Environment specification must contain a YAML mapping: {env_yml}"
        )

    dependencies = env_data.setdefault("dependencies", [])
    if not isinstance(dependencies, list):
        raise EnvironmentSetupError(
            "The environment.yml 'dependencies' value must be a list."
        )
    warnings = _ensure_runtime_dependencies(
        dependencies,
        is_worker_env=is_worker_env,
    )
    if warnings:
        print("=" * 50)
        print("[environment] Environment warnings:")
        for warning in warnings:
            print(f"- {warning}")
        print("=" * 50)

    post_install_script = env_data.pop("post_install_script", None)
    if post_install_script:
        script_path = Path(str(post_install_script)).expanduser()
        if not script_path.is_absolute():
            script_path = Path(env_yml).resolve().parent / script_path
        post_install_script = str(script_path.resolve())
        print(f"[environment] Post-installation script: {post_install_script}")

    return env_data, post_install_script


def _validate_pixi_compatible_spec(env_data: Mapping, env_yml: str) -> None:
    """Reject Conda-YAML features the initial Pixi adapter cannot preserve."""
    if env_data.get("variables"):
        raise EnvironmentSetupError(
            f"Pixi creation does not yet support top-level 'variables:' in {env_yml}. "
            "Use '--environment-creator conda'. Floability's per-run manager, "
            "port, and --env-vars values are unaffected by this restriction."
        )

    unsupported: list[str] = []
    for dependency in env_data.get("dependencies", []):
        if not isinstance(dependency, dict):
            continue
        pip_dependencies = dependency.get("pip", [])
        if not isinstance(pip_dependencies, list):
            unsupported.append(repr(pip_dependencies))
            continue
        for item in pip_dependencies:
            value = str(item).strip()
            lowered = value.lower()
            if (
                lowered.startswith("-")
                or lowered.startswith("git+")
                or lowered.startswith("hg+")
                or lowered.startswith("svn+")
                or lowered.startswith("bzr+")
            ):
                unsupported.append(value)

    if unsupported:
        rendered = ", ".join(repr(item) for item in unsupported)
        raise EnvironmentSetupError(
            "Pixi cannot import these environment.yml pip entries: "
            f"{rendered}. Requirements-file options, index options, editable "
            "installs, and bare VCS URLs are not supported by this adapter. "
            "Use '--environment-creator conda'."
        )


def _run_streaming_command(
    command: list[str],
    *,
    env: Mapping[str, str] | None = None,
) -> None:
    """Run a command visibly while retaining its output tail for diagnostics."""
    output_tail: deque[str] = deque(maxlen=2000)
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            bufsize=1,
            env=None if env is None else dict(env),
        )
    except FileNotFoundError as error:
        raise EnvironmentSetupError(
            f"Required environment command was not found: {command[0]}. "
            "Activate floability-env and verify the installation with "
            "'floability --version --verbose'."
        ) from error
    if process.stdout is not None:
        for line in process.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            output_tail.append(line)
    returncode = process.wait()
    if returncode != 0:
        raise subprocess.CalledProcessError(
            returncode,
            command,
            output="".join(output_tail),
        )


def _is_storage_exhaustion(output: str) -> bool:
    """Recognize specific disk-full and filesystem-quota failure signatures."""
    normalized = output.lower()
    signatures = (
        "no space left on device",
        "errno 28",
        "disk quota exceeded",
        "quota exceeded",
        "errno 122",
        "enospc",
        "edquot",
    )
    return any(signature in normalized for signature in signatures)


def _environment_base_dir(env_path: str) -> Path:
    """Return the Floability base containing a standard shared environment."""
    resolved = Path(env_path).expanduser().resolve()
    for parent in resolved.parents:
        if parent.name == "flo_common_env":
            return parent.parent
    return resolved.parent


def _storage_error_message(
    env_path: str,
    *,
    operation: str = "create the workflow environment",
    output_path: str | None = None,
    tool_name: str = "Conda",
    tool_cache_path: str | None = None,
) -> str:
    base_dir = _environment_base_dir(env_path)
    output_detail = (
        f"\n[floability] Output target: {output_path}" if output_path else ""
    )
    cache_detail = (
        f"\n[floability] {tool_name} package cache: {tool_cache_path}"
        if tool_cache_path
        else ""
    )
    cache_guidance = (
        "\n[floability] If the Pixi package cache is on a small home filesystem, "
        "set PIXI_CACHE_DIR to a directory on the same filesystem as --base-dir."
        if tool_name == "Pixi"
        else ""
    )
    return (
        f"{tool_name} could not {operation} because the target "
        "filesystem has no available space or the account quota was exceeded.\n"
        f"[floability] Environment target: {env_path}\n"
        f"[floability] Floability base: {base_dir}"
        f"{output_detail}{cache_detail}{cache_guidance}\n"
        "[floability] Choose a base with more available space using "
        "--base-dir PATH, or preview removable unreferenced caches with:\n"
        f"[floability]   floability tools clean --base-dir {base_dir} "
        "--mode data-and-env --dry-run\n"
        "[floability] Review the plan, then repeat without --dry-run to clean. "
        f"The original {tool_name} output appears above."
    )


def _create_conda_env(
    env_yml: str,
    env_path: str,
    is_worker_env: bool,
    *,
    conda_executable: str | None = None,
) -> None:
    """Create a conda environment unconditionally from a YAML spec.

    Adds python=3.12 and the mode-specific runtime packages only when the
    backpack does not provide its own specifications. Warns when optional
    ndcctools is absent. Runs an optional post-install script defined via the
    ``post_install_script`` key in the YAML.

    Raises subprocess.CalledProcessError on failure.
    """

    if is_worker_env:
        print("[environment] Creating worker environment (python + cloudpickle)")
    else:
        print("[environment] Creating manager environment (jupyter + cloudpickle)")

    env_data, post_install_script = _prepare_environment_spec(
        env_yml,
        is_worker_env=is_worker_env,
    )

    print(f"[environment] Packages: {env_data['dependencies']}")
    print(f"[environment] Creating env at: {env_path}")

    modified_yml: str | None = None
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

        conda_command = [
            conda_executable or "conda",
            "env",
            "create",
            "--file",
            modified_yml,
            "--prefix",
            env_path,
        ]
        try:
            _run_streaming_command(conda_command)
        except subprocess.CalledProcessError as error:
            if _is_storage_exhaustion(error.output or ""):
                raise EnvironmentStorageError(
                    _storage_error_message(env_path, tool_name="Conda")
                ) from error
            raise EnvironmentSetupError(
                "Conda environment creation failed with exit status "
                f"{error.returncode}. Review software/environment.yml and the "
                "original Conda output above."
            ) from error

        # Optional post-install script
        if post_install_script and os.path.exists(post_install_script):
            print(f"[environment] Running post-install script: {post_install_script}")
            result = subprocess.run(
                build_prefix_run_command(
                    env_path,
                    ["bash", post_install_script],
                ),
                check=False,
            )
            if result.returncode != 0:
                print(
                    "[environment] Post-install script failed "
                    f"(code {result.returncode})"
                )
                raise EnvironmentSetupError(
                    "Environment post-install script failed with exit status "
                    f"{result.returncode}: {post_install_script}"
                )
            print("[environment] Post-install script executed successfully.")

    except subprocess.CalledProcessError:
        raise
    finally:
        if modified_yml and os.path.exists(modified_yml):
            try:
                os.remove(modified_yml)
            except Exception:
                pass


def _pixi_command_environment(base_dir: str) -> tuple[dict[str, str], Path]:
    """Return a stable Pixi command environment and its package cache path."""
    command_env = os.environ.copy()
    configured_cache = command_env.get("PIXI_CACHE_DIR")
    if configured_cache:
        package_cache = Path(configured_cache).expanduser().resolve()
    else:
        package_cache = (
            Path(base_dir).expanduser().resolve()
            / "flo_common_env"
            / "tool_cache"
            / "pixi"
        )
        command_env["PIXI_CACHE_DIR"] = str(package_cache)
    package_cache.mkdir(parents=True, exist_ok=True)
    print(f"[environment] Pixi package cache: {package_cache}")

    base_path = Path(base_dir).expanduser().resolve()
    base_path.mkdir(parents=True, exist_ok=True)
    try:
        if package_cache.stat().st_dev != base_path.stat().st_dev:
            print(
                "[environment] Warning: PIXI_CACHE_DIR is on a different "
                "filesystem from --base-dir; Pixi may copy packages instead "
                "of hardlinking them and use more storage."
            )
    except OSError:
        pass
    return command_env, package_cache


def _select_pixi_prefix(info: Mapping, cache_root: Path) -> Path:
    """Select and validate Pixi's default prefix from ``pixi info --json``."""
    environments = info.get("environments_info")
    if not isinstance(environments, list):
        raise EnvironmentSetupError(
            "Pixi did not report an environments_info list for the cached workspace."
        )
    selected = next(
        (
            item
            for item in environments
            if isinstance(item, dict) and item.get("name") == "default"
        ),
        None,
    )
    if selected is None:
        raise EnvironmentSetupError(
            "Pixi did not report a 'default' environment for the cached workspace."
        )
    raw_prefix = selected.get("prefix")
    if not raw_prefix:
        raise EnvironmentSetupError(
            "Pixi reported no prefix for its default environment."
        )
    root = cache_root.expanduser().resolve()
    prefix = Path(str(raw_prefix)).expanduser().resolve()
    if prefix == root or root not in prefix.parents:
        raise EnvironmentSetupError(
            f"Refusing Pixi prefix outside its Floability cache entry: {prefix} "
            f"(expected below {root})."
        )
    if not (prefix / "bin" / "python").is_file():
        raise EnvironmentSetupError(
            f"Pixi's default environment is incomplete (missing bin/python): {prefix}"
        )
    return prefix


def _resolve_pixi_prefix(
    cache_root: Path,
    pixi_executable: str,
    command_env: Mapping[str, str],
) -> Path:
    """Ask Pixi for its real prefix rather than assuming an install location."""
    command = [
        pixi_executable,
        "info",
        "--json",
        "--manifest-path",
        str(cache_root / "pixi.toml"),
    ]
    try:
        result = subprocess.run(
            command,
            env=dict(command_env),
            capture_output=True,
            text=True,
            check=True,
        )
        info = json.loads(result.stdout)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        detail = getattr(error, "stderr", None) or str(error)
        raise EnvironmentSetupError(
            f"Could not resolve the Pixi environment prefix: {detail}"
        ) from error
    return _select_pixi_prefix(info, cache_root)


def _sanitize_pixi_workspace(cache_root: Path) -> None:
    """Remove user identity and repository helper files generated by Pixi."""
    manifest = cache_root / "pixi.toml"
    try:
        lines = manifest.read_text().splitlines()
        filtered = [line for line in lines if not line.lstrip().startswith("authors =")]
        manifest.write_text("\n".join(filtered) + "\n")
    except OSError as error:
        raise EnvironmentSetupError(
            f"Could not sanitize generated Pixi manifest {manifest}: {error}"
        ) from error
    for generated_name in (".gitignore", ".gitattributes"):
        generated = cache_root / generated_name
        try:
            generated.unlink(missing_ok=True)
        except OSError as error:
            raise EnvironmentSetupError(
                f"Could not remove generated Pixi file {generated}: {error}"
            ) from error


def _create_pixi_env(
    env_yml: str,
    cache_root: Path,
    is_worker_env: bool,
    *,
    pixi_executable: str | None,
    base_dir: str,
) -> Path:
    """Create a Conda-compatible prefix through Pixi's YAML importer."""
    if not pixi_executable:
        raise EnvironmentSetupError("Pixi was selected but no executable was resolved.")
    env_data, post_install_script = _prepare_environment_spec(
        env_yml,
        is_worker_env=is_worker_env,
    )
    _validate_pixi_compatible_spec(env_data, env_yml)
    command_env, package_cache = _pixi_command_environment(base_dir)
    modified_yml: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".yml",
            prefix="floability_pixi_env_",
            delete=False,
        ) as temporary_spec:
            yaml.safe_dump(env_data, temporary_spec)
            modified_yml = temporary_spec.name

        cache_root.parent.mkdir(parents=True, exist_ok=True)
        print(f"[environment] Creating Pixi workspace at: {cache_root}")
        try:
            _run_streaming_command(
                [
                    pixi_executable,
                    "init",
                    str(cache_root),
                    "--import",
                    modified_yml,
                ],
                env=command_env,
            )
        except subprocess.CalledProcessError as error:
            if _is_storage_exhaustion(error.output or ""):
                raise EnvironmentStorageError(
                    _storage_error_message(
                        str(cache_root),
                        tool_name="Pixi",
                        tool_cache_path=str(package_cache),
                    )
                ) from error
            raise EnvironmentSetupError(
                "Pixi could not import software/environment.yml. Review the "
                "original Pixi output above, or use "
                "'--environment-creator conda'."
            ) from error

        config_dir = cache_root / ".pixi"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.toml").write_text("detached-environments = false\n")
        _sanitize_pixi_workspace(cache_root)

        try:
            _run_streaming_command(
                [
                    pixi_executable,
                    "install",
                    "--manifest-path",
                    str(cache_root / "pixi.toml"),
                ],
                env=command_env,
            )
        except subprocess.CalledProcessError as error:
            if _is_storage_exhaustion(error.output or ""):
                raise EnvironmentStorageError(
                    _storage_error_message(
                        str(cache_root),
                        tool_name="Pixi",
                        tool_cache_path=str(package_cache),
                    )
                ) from error
            raise EnvironmentSetupError(
                "Pixi environment creation failed with exit status "
                f"{error.returncode}. Review software/environment.yml and the "
                "original Pixi output above. You can retry with "
                "'--environment-creator conda'."
            ) from error

        prefix = _resolve_pixi_prefix(cache_root, pixi_executable, command_env)
        if post_install_script:
            if not Path(post_install_script).is_file():
                raise EnvironmentSetupError(
                    "Environment post-install script was not found: "
                    f"{post_install_script}"
                )
            command = [
                pixi_executable,
                "run",
                "--as-is",
                "--manifest-path",
                str(cache_root / "pixi.toml"),
                "bash",
                post_install_script,
            ]
            try:
                _run_streaming_command(command, env=command_env)
            except subprocess.CalledProcessError as error:
                raise EnvironmentSetupError(
                    "Environment post-install script failed through Pixi with "
                    f"exit status {error.returncode}: {post_install_script}"
                ) from error
        return prefix
    finally:
        if modified_yml:
            Path(modified_yml).unlink(missing_ok=True)


def _write_environment_cache_manifest(
    cache_info: EnvCacheInfo,
    plan: EnvironmentPlan,
) -> None:
    root = cache_info.root.resolve()
    prefix = cache_info.shared_env_dir.resolve()
    try:
        relative_prefix = str(prefix.relative_to(root)) if prefix != root else "."
    except ValueError as error:
        raise EnvironmentSetupError(
            f"Environment prefix escaped its cache entry: {prefix}"
        ) from error
    manifest = {
        "schema_version": 1,
        "cache_key": cache_info.file_hash,
        "specification_hash": cache_info.specification_hash,
        "platform": sys.platform,
        "architecture": platform.machine(),
        "prefix": relative_prefix,
        "plan": plan.as_metadata(),
    }
    (root / ".floability-environment.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )


def _read_cached_environment_prefix(cache_root: Path) -> Path | None:
    manifest_path = cache_root / ".floability-environment.json"
    try:
        manifest = json.loads(manifest_path.read_text())
        raw_prefix = manifest["prefix"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return None
    root = cache_root.resolve()
    prefix = (root / str(raw_prefix)).resolve()
    if prefix == root or root not in prefix.parents:
        return None
    return prefix


def _pack_conda_env(
    env_path: str,
    tar_path: str,
    *,
    packer_executable: str | None = None,
) -> None:
    """Pack an existing conda environment into a tarball unconditionally.

    Ensures conda-pack can derive a valid archive timestamp from Conda history.
    Raises subprocess.CalledProcessError on failure.
    """
    _ensure_conda_history_file(env_path)
    print(f"[environment] Packing '{env_path}' → '{tar_path}'")
    pack_command = [
        packer_executable or "conda-pack",
        "-p",
        env_path,
        "-o",
        tar_path,
        "--force",
    ]
    try:
        _run_streaming_command(pack_command)
    except subprocess.CalledProcessError as error:
        if _is_storage_exhaustion(error.output or ""):
            raise EnvironmentStorageError(
                _storage_error_message(
                    env_path,
                    operation="pack the workflow environment",
                    output_path=tar_path,
                )
            ) from error
        raise EnvironmentSetupError(
            "Environment packing failed with exit status "
            f"{error.returncode}. Review the original conda-pack output above."
        ) from error
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
    
    # for hashing purpose, we will set a common name for the environment,
    # since the name does not affect the actual environment content 
    # but can cause cache misses if different names are used for the same spec.
    # This allows users to have different environment names in their 
    # YAML files without causing unnecessary cache misses. 
    env_data["name"] = "floability_env_for_hashing"
    
    hash_content = yaml.safe_dump(env_data, sort_keys=True)  # sort keys for consistent hashing

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


def _make_dir_readonly(path: str) -> None:
    """Recursively remove write permission from all files and directories.

    After this call any attempt to write into the directory (e.g. an accidental
    ``pip install`` against the shared base env) will raise PermissionError.
    Call _make_dir_writable before rmtree to allow deletion.
    """
    for root, dirs, files in os.walk(path):
        for name in dirs:
            try:
                p = os.path.join(root, name)
                os.chmod(p, os.stat(p).st_mode & ~0o222)
            except OSError:
                pass
        for name in files:
            try:
                p = os.path.join(root, name)
                os.chmod(p, os.stat(p).st_mode & ~0o222)
            except OSError:
                pass
    # Also lock the root directory itself
    try:
        os.chmod(path, os.stat(path).st_mode & ~0o222)
    except OSError:
        pass


def _make_dir_writable(path: str) -> None:
    """Recursively restore user write permission on all files and directories.

    Required before rmtree on a read-only shared env dir.
    """
    for root, dirs, files in os.walk(path):
        for name in dirs:
            try:
                p = os.path.join(root, name)
                os.chmod(p, os.stat(p).st_mode | 0o200)
            except OSError:
                pass
        for name in files:
            try:
                p = os.path.join(root, name)
                os.chmod(p, os.stat(p).st_mode | 0o200)
            except OSError:
                pass
    try:
        os.chmod(path, os.stat(path).st_mode | 0o200)
    except OSError:
        pass


def _ensure_conda_history_file(env_path: str) -> None:
    """Ensure conda-meta/history exists with a valid mtime before packing.

    conda-pack uses the history file mtime when it stamps the generated
    conda-unpack script. If the file is missing or has a zero timestamp, the
    archive can fail with a tarfile ValueError on Python 3.13+.
    """
    history_file = Path(env_path) / "conda-meta" / "history"
    history_file.parent.mkdir(parents=True, exist_ok=True)

    if not history_file.exists():
        history_file.touch()

    current_time = time.time()
    os.utime(history_file, (current_time, current_time))
