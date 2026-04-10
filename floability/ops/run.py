"""
Run and execute operations for Floability CLI.
"""

import argparse
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any
from ..cleanup import CleanupManager
from ..performance_tracker import PerformanceTracker
from ..environment_manager import setup_manager_and_worker_envs, ensure_shared_env
from ..workers_manager import start_workers_for_instance
from ..backpack_manager import (
    resolve_backpack_args,
    validate_backpack_structure,
    sync_outputs_to_backpack,
)
from ..instance_manager import (
    create_instance_structure,
    create_latest_symlink,
    record_initial_metadata,
)
from ..utils import normalize_cli_base_dir
from ..jupyter_runner import start_jupyterlab, execute_notebook
from ..instance_lock_manager import (
    acquire_instance_lock,
    release_instance_lock,
    is_instance_running,
)
from ..instance_registry import (
    refresh_instance_registry_entry,
    resolve_instance,
    register_instance,
)
from ..catalog import send_catalog_update
from ..instance_metadata import finalize_instance_metadata, update_instance_metadata, add_data_cache_dirs
from ..data.data_handler import execute_default_data_operation

# -----------------------------------------------------------------------------
# Data Classes
# -----------------------------------------------------------------------------


@dataclass
class InstanceContext:
    """Holds instance-related paths and state during workflow execution."""

    root: Path
    paths: dict
    metadata_file: Path
    workflow_dir: Path
    lock_acquired: bool = False
    is_new: bool = True


@dataclass
class EnvironmentContext:
    """Holds environment setup results."""

    env_dir: Optional[str] = None
    worker_pack: Optional[str] = None
    manager_pack: Optional[str] = None
    instance_env: dict = field(default_factory=dict)


# -----------------------------------------------------------------------------
# Primary Operation
# -----------------------------------------------------------------------------


def run_workflow(
    args: argparse.Namespace, cleanup_manager: CleanupManager, mode="run"
) -> None:
    """Run or execute a workflow either by creating a new instance from a backpack
    or by reusing an existing instance (via --instance).
    """
    try:
        # Step 1: Determine instance source (new from backpack vs existing)
        new_instance_required = _is_new_instance_required(args)

        # Step 2: Prepare instance (new or existing)
        if new_instance_required:
            ctx = _prepare_new_instance(args, mode)
        else:
            ctx = _prepare_existing_instance(args)

        # Initialize performance tracking
        perf = PerformanceTracker(
            output_dir=str(ctx.paths["metrics"]),
            enabled=getattr(args, "measure_performance", False),
        )
        perf.start_timer("total_run_time")

        # Register new instance in global registry
        if ctx.is_new:
            _register_new_instance(ctx.root, args.manager_name)

        # Step 3: Materialize data
        _materialize_data(args, ctx, perf)

        # Step 4: Setup environment
        env_ctx = _setup_environment(args, ctx, perf)

        # Step 5: Send catalog event
        _send_catalog_event(args, ctx, mode)

        # Step 6: Start workers
        factory_proc = _start_workers(args, ctx, env_ctx, cleanup_manager)

        # Step 7: Find notebook
        notebook_path = _find_notebook(args, ctx, mode)

        # Step 8: Run or execute
        if mode == "run":
            _run_interactive(
                args, ctx, env_ctx, cleanup_manager, factory_proc, perf, notebook_path
            )
        else:
            _execute_batch(args, ctx, env_ctx, cleanup_manager, perf, notebook_path)

        print("[floability] Exiting run.")

    except ValueError as e:
        print(f"[floability] Error: {e}")
        return
    except RuntimeError as e:
        print(f"[floability] Error: {e}")
        if "ctx" in locals():
            _cleanup_and_abort(cleanup_manager, ctx)
        return
    except Exception as e:
        print(f"[floability] Unexpected error: {e}")
        if "ctx" in locals():
            _cleanup_and_abort(cleanup_manager, ctx)
        raise


# todo: revist and make unified execution for any scripts
def execute_python_script(
    script_path, run_dir, conda_env_dir=None, working_dir=None, extra_env: dict = None
):
    script_abs_path = os.path.abspath(script_path)
    script_name = os.path.basename(script_abs_path)

    # Use provided working_dir or fall back to script's directory
    exec_dir = working_dir if working_dir else os.path.dirname(script_abs_path)

    print(f"[floability] Changing directory to: {exec_dir}")
    print(f"[floability] Executing Python script: {script_name}")
    log_file = os.path.join(run_dir, "python_execution.log")
    print(f"[floability] Logging to: {log_file}")
    with open(log_file, "w") as log:
        original_dir = os.getcwd()
        try:
            os.chdir(exec_dir)
            log.write(f"[floability] Changed working directory to: {exec_dir}\n")
            cmd = []
            if conda_env_dir:
                cmd = [
                    "conda",
                    "run",
                    "--prefix",
                    conda_env_dir,
                    "--no-capture-output",
                    "python",
                    script_name,
                ]
            else:
                cmd = ["python", script_name]
            cmd_str = " ".join(cmd)
            print(f"[floability] Running command: {cmd_str}")
            log.write(f"[floability] Running command: {cmd_str}\n")
            log.flush()
            result = subprocess.run(
                cmd,
                env=extra_env,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
                text=True,
            )
            print(
                f"[floability] Python script execution completed with exit code {result.returncode}"
            )
            print(f"[floability] Logs saved to {log_file}")
        except subprocess.CalledProcessError as e:
            print(f"[floability] Error executing Python script: {e}")
            print(f"[floability] Check logs at {log_file}")
        finally:
            os.chdir(original_dir)


# -----------------------------------------------------------------------------
# Private Helper Functions
# -----------------------------------------------------------------------------


def _is_new_instance_required(args: argparse.Namespace) -> bool:
    """Check if a new instance needs to be created or an existing one should be reused.

    Returns:
        True if new instance required (default), False if reusing existing instance.

    Raises:
        ValueError: If arguments are invalid (e.g., both --backpack and --instance specified).
    """
    if getattr(args, "backpack", None) and getattr(args, "instance", None):
        raise ValueError("--backpack and --instance cannot be used together.")

    if getattr(args, "instance", None):
        resolved = resolve_instance(args.instance)
        if not resolved:
            raise ValueError(f"Instance reference not found: {args.instance}")
        args.instance = resolved
        refresh_instance_registry_entry(args.instance)
        return False
    return True


def _prepare_new_instance(args: argparse.Namespace, mode: str) -> InstanceContext:
    """Create a new instance from a backpack.

    Returns:
        InstanceContext if successful.

    Raises:
        RuntimeError: If instance creation fails.
    """

    print("[floability] Preparing new instance from backpack")

    if getattr(args, "manager_name", None) is None:
        args.manager_name = f"floability-{uuid.uuid4()}"

    resolve_backpack_args(args)

    if getattr(args, "backpack", None):
        validate_backpack_structure(args.backpack, require_workflow=False)

    _normalize_base_and_cache_directories(args)

    _backpack_arg = getattr(args, "backpack", None)
    if _backpack_arg == ".":
        backpack_name = Path.cwd().name
    elif _backpack_arg:
        backpack_name = Path(_backpack_arg).resolve().name
    else:
        backpack_name = None
    if getattr(args, "instance_prefix", None):
        raw_prefix = args.instance_prefix
        instance_prefix = raw_prefix if raw_prefix.startswith("fi_") else f"fi_{raw_prefix}"
    elif backpack_name:
        instance_prefix = f"fi_{backpack_name}"
    else:
        instance_prefix = "fi"

    instance_paths = create_instance_structure(args.base_dir, prefix=instance_prefix)
    instance_root = Path(instance_paths["root"])
    create_latest_symlink(args.base_dir, str(instance_root))

    if not acquire_instance_lock(instance_root):
        raise RuntimeError("Failed to acquire instance run lock for new instance.")

    metadata_file = instance_paths["metadata"] / "run.json"
    try:
        record_initial_metadata(args, instance_paths, mode=mode)
    except Exception as e:
        print(f"[floability] Warning: Could not create metadata: {e}")

    # Setup workflow directory
    workflow_dir = instance_paths["workflow"]
    if getattr(args, "backpack_root", None):
        from ..instance_manager import copy_workflow_directory

        backpack_workflow_dir = Path(args.backpack_root) / "workflow"
        copy_workflow_directory(
            source_workflow_dir=backpack_workflow_dir,
            dest_workflow_dir=workflow_dir,
        )
        if args.notebook:
            args.notebook = str(workflow_dir / Path(args.notebook).name)
        if args.python_script:
            args.python_script = str(workflow_dir / Path(args.python_script).name)
    else:
        print(
            f"[floability] No backpack specified; created empty workflow directory at {workflow_dir}"
        )

    args.workflow_dir = str(workflow_dir)

    return InstanceContext(
        root=instance_root,
        paths=instance_paths,
        metadata_file=metadata_file,
        workflow_dir=workflow_dir,
        lock_acquired=True,
        is_new=True,
    )


def _normalize_base_and_cache_directories(args: argparse.Namespace) -> None:
    """Normalize base_dir and data cache directory paths."""
    raw_base = getattr(args, "base_dir", None) if hasattr(args, "base_dir") else None
    args.base_dir = str(normalize_cli_base_dir(raw_base))

    raw_cache_override = (
        getattr(args, "data_cache_dir", None)
        if hasattr(args, "data_cache_dir")
        else None
    )

    if raw_cache_override:
        cache_base_dir = Path(os.path.expanduser(raw_cache_override)).resolve()
        try:
            cache_base_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            print(
                f"[floability] Warning: Could not create specified data cache directory: {cache_base_dir}."
            )
    else:
        cache_base_dir = (Path(args.base_dir) / "floability-data-cache").resolve()
        try:
            cache_base_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            print(
                f"[floability] Warning: Could not create default data cache directory: {cache_base_dir}."
            )
    args.cache_base_dir = str(cache_base_dir)


def _prepare_existing_instance(args: argparse.Namespace) -> InstanceContext:
    """Prepare to use an existing instance.

    Returns:
        InstanceContext if successful.

    Raises:
        RuntimeError: If instance preparation fails.
    """
    instance_root = Path(args.instance).resolve()
    if not instance_root.is_dir():
        raise RuntimeError(f"Instance directory not found: {instance_root}")

    if is_instance_running(instance_root):
        raise RuntimeError("Instance already running (lock present).")

    if not acquire_instance_lock(instance_root):
        raise RuntimeError("Failed to acquire instance run lock.")

    print(f"[floability] Running on existing instance: {instance_root}")

    instance_paths = {
        "root": instance_root,
        "workflow": instance_root / "workflow",
        "logs": instance_root / "logs",
        "metrics": instance_root / "metrics",
        "metadata": instance_root / "metadata",
    }
    create_latest_symlink(args.base_dir, str(instance_root))

    metadata_file = instance_paths["metadata"] / "run.json"
    if not metadata_file.exists():
        print(f"[floability] Warning: Missing instance metadata at {metadata_file}")

    workflow_dir = instance_paths["workflow"]
    args.workflow_dir = str(workflow_dir)

    return InstanceContext(
        root=instance_root,
        paths=instance_paths,
        metadata_file=metadata_file,
        workflow_dir=workflow_dir,
        lock_acquired=True,
        is_new=False,
    )


def _register_new_instance(instance_root: Path, manager_name: str) -> None:
    """Register a newly created instance in global registry."""
    try:
        short_name = register_instance(instance_root, manager_name)
        print(f"[floability] Registered instance short name: {short_name}")
    except Exception as e:
        print(f"[floability] Warning: could not register instance short name: {e}")


def _materialize_data(
    args: argparse.Namespace,
    ctx: InstanceContext,
    perf: PerformanceTracker,
) -> None:
    """Materialize data into the instance workflow directory.

    Raises:
        RuntimeError: If data materialization fails and should abort.
    """
    if not ctx.is_new or not getattr(args, "data_spec", None):
        return

    print("[floability] data materialization")
    perf_enabled = perf.enabled

    if perf_enabled:
        perf.start_timer("total_data_materialization_time")
        perf.start_timer("data_operation")

    target_root = ctx.paths["workflow"]
    backpack_root_for_sources = (
        args.backpack_root if getattr(args, "backpack_root", None) else None
    )

    cache_dirs: list = []
    success = execute_default_data_operation(
        data_spec=args.data_spec,
        backpack_root=backpack_root_for_sources,
        verbose=True,
        force=False,
        data_profile=getattr(args, "data_profile", None),
        data_cache_mode=getattr(args, "data_cache_mode", "off"),
        force_data_cache=getattr(args, "force_data_cache", False),
        base_dir=Path(args.base_dir),
        cache_base_dir=Path(args.cache_base_dir),
        target_root=target_root,
        fingerprint_mode=getattr(args, "fingerprint_mode", "meta"),
        perf=perf if perf_enabled else None,
        _out_cache_dirs=cache_dirs,
    )

    if cache_dirs:
        try:
            add_data_cache_dirs(ctx.metadata_file, cache_dirs)
        except Exception as e:
            print(f"[floability] Warning: could not record data cache dirs: {e}")

    if perf_enabled:
        perf.end_timer(
            "data_operation", "Time to perform data operation (fetch/check/verify)"
        )
        perf.end_timer(
            "total_data_materialization_time",
            "Total time for data materialization (includes all data operations)",
        )

    if not success:
        print("[floability] WARNING: Data operation failed.")
        if not getattr(args, "continue_on_data_failure", False):
            raise RuntimeError("Data materialization failed.")


def _setup_environment(
    args: argparse.Namespace,
    ctx: InstanceContext,
    perf: PerformanceTracker,
) -> EnvironmentContext:
    """Setup manager and worker environments.

    Existing instance path:
      Reads per_instance_env + environment_spec from saved metadata to decide
      whether to point at current_conda_env (per-instance) or the shared base.

    New instance path:
      Delegates to setup_manager_and_worker_envs with the per_instance_env flag,
      then persists the decision to metadata so future re-runs can reconstruct it.
    """
    if not ctx.is_new:
        env_dir = _resolve_existing_instance_env(args, ctx)
        instance_env = _build_instance_env(args, ctx)
        return EnvironmentContext(env_dir=env_dir, instance_env=instance_env)

    per_instance_env = getattr(args, "per_instance_env", False)
    env_spec = getattr(args, "environment", None)

    if not env_spec:
        raise ValueError(
            "No environment spec provided. "
            "Use --environment to specify a path to environment.yml."
        )

    print("[floability] environment setup (manager & worker)")
    env_dir, worker_tar, manager_tar = setup_manager_and_worker_envs(
        environment_spec=env_spec,
        worker_environment_spec=getattr(args, "worker_environment", None),
        base_dir=args.base_dir,
        instance_root=str(ctx.root),
        per_instance_env=per_instance_env,
        perf=perf if perf.enabled else None,
    )

    _persist_env_metadata(
        ctx, env_dir, worker_tar, manager_tar, per_instance_env, env_spec
    )
    instance_env = _build_instance_env(args, ctx, env_dir)

    _display_env_info(env_dir, instance_env)

    return EnvironmentContext(
        env_dir=env_dir,
        worker_pack=worker_tar,
        manager_pack=manager_tar,
        instance_env=instance_env,
    )


def _send_catalog_event(
    args: argparse.Namespace,
    ctx: InstanceContext,
    mode: str,
    event: str = "startup",
) -> None:
    """Send catalog update event."""
    backpack_name = (
        Path(getattr(args, "backpack", "")).stem
        if getattr(args, "backpack", None)
        else None
    )
    notebook_name = (
        Path(args.notebook).name if getattr(args, "notebook", None) else None
    )
    send_catalog_update(
        manager_name=args.manager_name,
        jupyter_port=getattr(args, "jupyter_port", 8888),
        run_dir=str(ctx.paths["root"]),
        backpack_name=backpack_name,
        event=event,
        notebook_name=notebook_name,
        mode=mode,
    )


def _start_workers(
    args: argparse.Namespace,
    ctx: InstanceContext,
    env_ctx: EnvironmentContext,
    cleanup_manager: CleanupManager,
) -> Optional[Any]:
    """Start worker factory for the instance.

    Returns:
        Factory process if started, None otherwise.
    """
    if getattr(args, "no_worker", False):
        print("[floability] Workers disabled by --no-worker")
        return None

    print("[floability] worker factory startup")

    factory_proc = start_workers_for_instance(
        instance_path=ctx.root,
        cli_args=args,
        env_dir=env_ctx.env_dir,
        instance_env=env_ctx.instance_env,
    )
    if factory_proc:
        cleanup_manager.register_subprocess(factory_proc)
    return factory_proc


def _find_notebook(
    args: argparse.Namespace,
    ctx: InstanceContext,
    mode: str,
) -> Optional[str]:
    """Find the notebook to execute.

    Returns:
        Path to notebook if found, None if not found.

    Raises:
        RuntimeError: If no notebook found in execute mode.
    """
    notebook_path = getattr(args, "notebook", None)
    if ctx.is_new and notebook_path:
        notebook_path = Path(notebook_path).name

    if not notebook_path or mode == "execute":
        workflow_notebooks = list(ctx.workflow_dir.rglob("*.ipynb"))
        workflow_notebooks = [
            nb for nb in workflow_notebooks if ".ipynb_checkpoints" not in str(nb)
        ]

        if workflow_notebooks:
            if notebook_path:
                matching = [nb for nb in workflow_notebooks if nb.name == notebook_path]
                if matching:
                    notebook_path = str(matching[0])
                    print(f"[floability] Found notebook: {notebook_path}")
                else:
                    notebook_path = str(workflow_notebooks[0])
                    print(
                        f"[floability] Specified notebook not found, using: {notebook_path}"
                    )
            else:
                notebook_path = str(workflow_notebooks[0])
                print(
                    f"[floability] No notebook specified, auto-detected: {notebook_path}"
                )
        elif mode == "execute":
            raise RuntimeError(
                "No notebook found in workflow directory for execute mode."
            )

    return notebook_path


def _run_interactive(
    args: argparse.Namespace,
    ctx: InstanceContext,
    env_ctx: EnvironmentContext,
    cleanup_manager: CleanupManager,
    factory_proc: Optional[Any],
    perf: PerformanceTracker,
    notebook_path: Optional[str],
) -> None:
    """Run interactive mode with JupyterLab."""
    print("[floability] JupyterLab startup")
    jupyter_proc = start_jupyterlab(
        notebook_path=notebook_path,
        port=getattr(args, "jupyter_port", 8888),
        run_dir=str(ctx.paths["logs"]),
        conda_env_dir=env_ctx.env_dir,
        working_dir=str(ctx.workflow_dir),
        extra_env=env_ctx.instance_env,
    )
    if jupyter_proc:
        cleanup_manager.register_subprocess(jupyter_proc)

    # Monitor subprocesses
    try:
        while True:
            time.sleep(5)
            if (
                factory_proc is not None
                and getattr(factory_proc, "poll", lambda: None)() is not None
            ):
                print("[floability] Worker factory ended.")
                break
            if jupyter_proc is not None and jupyter_proc.poll() is not None:
                print("[floability] JupyterLab ended.")
    except KeyboardInterrupt:
        print("[floability] KeyboardInterrupt in main loop. Cleaning up...")
        cleanup_manager.cleanup()
    finally:
        _finalize_run(args, ctx, perf, sync_outputs=True)


def _execute_batch(
    args: argparse.Namespace,
    ctx: InstanceContext,
    env_ctx: EnvironmentContext,
    cleanup_manager: CleanupManager,
    perf: PerformanceTracker,
    notebook_path: Optional[str],
) -> None:
    """Execute batch mode (notebook or python script)."""
    script_path = getattr(args, "python_script", None)
    if ctx.is_new and script_path:
        script_path = Path(script_path).name

    execution_success = False

    if getattr(args, "prefer_python", False) and script_path:
        print("[floability] python script execution")
        execute_python_script(
            script_path=script_path,
            run_dir=str(ctx.paths["logs"]),
            conda_env_dir=env_ctx.env_dir,
            working_dir=str(ctx.workflow_dir),
            extra_env=env_ctx.instance_env,
        )
        execution_success = True
    elif notebook_path:
        print("[floability] notebook execution")
        if perf.enabled:
            perf.start_timer("notebook_execute_time")
        execution_success = execute_notebook(
            notebook_path=notebook_path,
            run_dir=str(ctx.paths["logs"]),
            conda_env_dir=env_ctx.env_dir,
            working_dir=str(ctx.workflow_dir),
            extra_env=env_ctx.instance_env,
        )
        if perf.enabled:
            perf.end_timer(
                "notebook_execute_time", "Time to execute notebook in execute mode"
            )

    if execution_success:
        _sync_outputs_if_needed(args, ctx)

    cleanup_manager.cleanup()
    _finalize_run(args, ctx, perf, sync_outputs=False)
    print("[floability] Exiting run.")


def _sync_outputs_if_needed(args: argparse.Namespace, ctx: InstanceContext) -> None:
    """Sync outputs back to backpack if appropriate."""
    if (
        ctx.is_new
        and getattr(args, "backpack", None)
        and not getattr(args, "no_update_backpack", False)
    ):
        backpack_workflow_dir = Path(args.backpack) / "workflow"
        sync_outputs_to_backpack(
            ctx.workflow_dir,
            backpack_workflow_dir,
            metadata_dir=ctx.paths["metadata"],
            verbose=True,
        )


def _finalize_run(
    args: argparse.Namespace,
    ctx: InstanceContext,
    perf: PerformanceTracker,
    sync_outputs: bool = False,
) -> None:
    """Finalize run: sync outputs, save metrics, release lock."""
    if sync_outputs:
        _sync_outputs_if_needed(args, ctx)

    if perf.enabled:
        perf.end_timer("total_run_time", "Total run time")
        perf.save_report()
        print(f"[floability] Performance report saved to {ctx.paths['metrics']}")

    try:
        finalize_instance_metadata(ctx.metadata_file, success=True)
    except Exception as e:
        print(f"[floability] Warning: Could not finalize metadata: {e}")

    if ctx.lock_acquired:
        release_instance_lock(ctx.root)


def _resolve_existing_instance_env(
    args: argparse.Namespace,
    ctx: InstanceContext,
) -> Optional[str]:
    """Resolve the correct conda env dir for an existing (reused) instance.

    Reads per_instance_env and environment_spec from the saved run.json so
    the same env strategy that was used at creation time is applied on re-run.
    """
    import json

    metadata: dict = {}
    if ctx.metadata_file.exists():
        try:
            with open(ctx.metadata_file) as f:
                metadata = json.load(f)
        except Exception:
            pass

    per_instance_env: bool = metadata.get("per_instance_env", False)
    env_spec: Optional[str] = metadata.get("environment_spec", None)

    if per_instance_env:
        env_dir = ctx.root / "current_conda_env"
        if not env_dir.exists():
            raise RuntimeError(
                f"Per-instance env expected at {env_dir} but not found. "
                "The environment directory may have been deleted."
            )
        print(f"[floability] Reusing per-instance environment: {env_dir}")
        return str(env_dir)

    # Shared env path: re-derive (or rebuild if cache was evicted).
    if env_spec:
        env_dir_str = _get_or_restore_shared_env(env_spec, args.base_dir)
        if env_dir_str:
            print(f"[floability] Using shared environment: {env_dir_str}")
        else:
            print(
                "[floability] No shared environment found; proceeding without conda env."
            )
        return env_dir_str

    print("[floability] No environment found; proceeding without conda env.")
    return None


def _get_or_restore_shared_env(env_spec: str, base_dir: str) -> Optional[str]:
    """Return the shared extracted env dir for a YAML env spec, rebuilding if needed.

    Calls ensure_shared_env so the cache is warm on return.
    Returns None if the env dir cannot be determined.
    """
    # YAML: warm the cache (no-op if already valid, rebuilds if evicted).
    cache_info = ensure_shared_env(
        env_spec, base_dir, is_worker_env=False, force=False, perf=None
    )
    return str(cache_info.shared_env_dir)


def _persist_env_metadata(
    ctx: InstanceContext,
    env_dir: Optional[str],
    worker_tar: Optional[str],
    manager_tar: Optional[str],
    per_instance_env: bool,
    env_spec: Optional[str],
) -> None:
    """Persist environment setup results to instance metadata.

    Stores per_instance_env and environment_spec so that _resolve_existing_instance_env
    can reconstruct the correct env path when an existing instance is reused.
    """
    try:
        update_instance_metadata(
            ctx.metadata_file,
            {
                **({"env_dir": str(env_dir)} if env_dir else {}),
                **({"worker_environment_pack": str(worker_tar)} if worker_tar else {}),
                **(
                    {"manager_environment_pack": str(manager_tar)}
                    if manager_tar
                    else {}
                ),
                "per_instance_env": per_instance_env,
                **({"environment_spec": str(env_spec)} if env_spec else {}),
            },
            merge=True,
        )
    except Exception as e:
        print(f"[floability] Warning: could not persist env metadata: {e}")


def _get_env_python_version(prefix: str) -> str:
    """
    Query the target conda prefix for its Python version.
    Returns string like '3.14'
    """
    result = subprocess.run(
        [
            "conda",
            "run",
            "--prefix",
            str(prefix),
            "python",
            "-c",
            "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _build_instance_env(
    args: argparse.Namespace,
    ctx: InstanceContext,
    env_dir: str,
) -> dict:
    """
    Build the per-instance subprocess environment dict.

    Ensures:
      - TaskVine identity vars
      - PyUser overlay (isolated pip --user installs)
      - Explicit PYTHONPATH injection (Conda disables user-site auto loading)
      - Proper PATH handling for pip-installed CLI tools
      - Correct Python version detection from target conda prefix
    """

    env = os.environ.copy()

    # -------------------------------------------------
    # TaskVine identity (per-instance)
    # -------------------------------------------------
    env["VINE_MANAGER_NAME"] = getattr(args, "manager_name", "") or ""
    env["VINE_MANAGER_PORTS"] = getattr(args, "manager_ports", "9123,9150")

    # -------------------------------------------------
    # PyUser overlay
    # -------------------------------------------------
    pyuser_dir = Path(ctx.root) / "pyuser"
    pyuser_dir.mkdir(exist_ok=True)

    env["PYTHONUSERBASE"] = str(pyuser_dir)
    env["PIP_USER"] = "1"

    # Add pyuser/bin to PATH
    pyuser_bin = str(pyuser_dir / "bin")
    env["PATH"] = pyuser_bin + os.pathsep + env.get("PATH", "")

    # -------------------------------------------------
    # Detect correct Python version from target env
    # -------------------------------------------------
    # ctx.env_dir should point to the conda prefix being used
    # (shared base, cloned env, etc.)
    python_version = _get_env_python_version(env_dir)

    pyuser_site = pyuser_dir / "lib" / f"python{python_version}" / "site-packages"
    pyuser_site.mkdir(parents=True, exist_ok=True)

    # Explicit injection (Conda disables user-site auto loading)
    existing_pythonpath = env.get("PYTHONPATH", "")
    if existing_pythonpath:
        env["PYTHONPATH"] = str(pyuser_site) + os.pathsep + existing_pythonpath
    else:
        env["PYTHONPATH"] = str(pyuser_site)

    # -------------------------------------------------
    # User-supplied --env-vars KEY=VALUE,...
    # -------------------------------------------------
    for pair in (getattr(args, "env_vars", None) or "").split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            env[k.strip()] = v.strip()

    return env


def _display_env_info(env_dir: Optional[str], instance_env: dict) -> None:
    """Display information about the active environment.

    Runs a short Python snippet inside the conda env (via conda run) to report
    sys.prefix, sys.path, CONDA_PREFIX, and ndcctools version.  Also prints the
    TaskVine manager identity from instance_env so it is easy to confirm which
    manager the workflow will connect to.
    """
    sep = "=" * 60
    print(f"\n{sep}")
    print("[floability] Instance Environment Info")
    print(sep)

    if not env_dir:
        print("  Conda env          : (none — using system Python)")
        print(sep + "\n")
        return

    snippet = (
        "import sys, os, platform\n"
        "print('Python Version:', platform.python_version())\n"
        "print('Python executable:', sys.executable)\n"
        "print('sys.prefix  :', sys.prefix)\n"
        "print('CONDA_PREFIX:', os.environ.get('CONDA_PREFIX', '(not set)'))\n"
        "print('VINE_MANAGER_NAME  :', os.environ.get('VINE_MANAGER_NAME', '(not set)'))\n"
        "print('VINE_MANAGER_PORTS :', os.environ.get('VINE_MANAGER_PORTS', '(not set)'))\n"
        "try:\n"
        "    import ndcctools.taskvine as vine\n"
        "    ver = getattr(vine, '__version__', None) or getattr(vine, 'version', '(unknown)')\n"
        "except ImportError:\n"
        "    ver = '(not installed)'\n"
        "print('ndcctools   :', ver)\n"
    )

    try:
        result = subprocess.run(
            [
                "conda",
                "run",
                "--prefix",
                env_dir,
                "--no-capture-output",
                "python",
                "-c",
                snippet,
            ],
            env=instance_env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        for line in result.stdout.strip().splitlines():
            print(f"  {line}")
        if result.returncode != 0 and result.stderr:
            print(f"  [warn] {result.stderr.strip().splitlines()[-1]}")
    except Exception as e:
        print(f"  [warn] Could not introspect conda env: {e}")

    print(sep + "\n")


def _cleanup_and_abort(
    cleanup_manager: CleanupManager,
    ctx: InstanceContext,
) -> None:
    """Cleanup resources and abort run."""
    cleanup_manager.cleanup()
    if ctx.lock_acquired:
        release_instance_lock(ctx.root)
