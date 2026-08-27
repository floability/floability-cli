"""
Run and execute operations for Floability CLI.
"""

import argparse
import json
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
from ..environment_manager import setup_manager_and_worker_envs
from ..workers_manager import (
    WorkerStartupCleanupError,
    reconcile_workers_after_cleanup,
    start_workers_for_instance,
)
from ..backpack_manager import (
    require_executable_backpack,
    resolve_backpack_args,
    sync_workflow_to_backpack,
)
from ..instance_manager import (
    create_instance_structure,
    create_latest_symlink,
    record_initial_metadata,
)
from ..utils import (
    get_conda_executable,
    normalize_cli_base_dir,
    normalize_manager_ports,
)
from ..jupyter_runner import start_jupyterlab, execute_notebook
from ..instance_lock_manager import (
    acquire_instance_lock,
    is_instance_running,
    mark_instance_cleanup_incomplete,
    release_instance_lock,
)
from ..instance_registry import (
    record_instance_run,
    resolve_instance,
    register_instance,
)
from ..catalog import send_catalog_update
from ..instance_metadata import (
    add_data_cache_dirs,
    finalize_instance_metadata,
    persist_prepared_environment,
    read_prepared_environment,
    update_instance_metadata,
)
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
    entrypoint_path: Path | None = None
    entrypoint_message: str | None = None
    copied_workflow_paths: tuple[Path, ...] = field(default_factory=tuple)
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
) -> int:
    """Run or execute a workflow either by creating a new instance from a backpack
    or by reusing an existing instance (via --instance).
    """
    try:
        # Resolve the instance source before choosing the effective base. An
        # existing instance with no explicit --base-dir belongs to its parent,
        # not automatically to ~/floability-base-dir.
        raw_base = (
            getattr(args, "base_dir", None) if hasattr(args, "base_dir") else None
        )
        new_instance_required = _is_new_instance_required(args)
        explicit_base = "base_dir" in getattr(args, "_explicit_args", set())
        if new_instance_required:
            # Preserve the raw value until backpack preflight succeeds. The
            # normalizer creates directories and therefore belongs after all
            # source validation for a new instance.
            args.base_dir = raw_base
        elif explicit_base:
            args.base_dir = str(normalize_cli_base_dir(raw_base))
        else:
            args.base_dir = str(Path(args.instance).resolve().parent)

        # A TaskVine manager name identifies this execution attempt, not the
        # reusable instance directory. Respect an explicit CLI name; otherwise
        # give every run/execute attempt a fresh identity.
        _select_run_manager_name(args)

        # Step 3: Prepare instance (new or existing)
        if new_instance_required:
            ctx = _prepare_new_instance(args, mode)
        else:
            ctx = _prepare_existing_instance(args, mode)
            _restore_existing_manager_ports(args, ctx.metadata_file)

        # Workers may be started by a separate command and read their manager
        # name from run.json, so publish the effective identity before any
        # environment, catalog, factory, or workflow activity begins.
        _persist_run_identity(args, ctx)

        # Initialize performance tracking
        perf = PerformanceTracker(
            output_dir=str(ctx.paths["metrics"]),
            enabled=getattr(args, "measure_performance", False),
        )
        perf.start_timer("total_run_time")

        # Register new instance in global registry
        if ctx.is_new:
            _register_new_instance(ctx.root, args.manager_name)

        # Reaching this point means the instance is resolved, locked, and has a
        # durable execution identity. Failed setup and interrupted runs still
        # count as the most recent accepted run attempt.
        try:
            record_instance_run(
                ctx.root,
                ctx.root.parent,
                manager_name=args.manager_name,
            )
        except Exception as error:
            print(f"[floability] Warning: could not record run history: {error}")

        # Step 3: Materialize data
        _materialize_data(args, ctx, perf)

        # Step 4: Setup environment
        env_ctx = _setup_environment(args, ctx, perf)

        # Step 5: Use the entrypoint selected before instance mutation.
        entrypoint_path = _prepared_entrypoint(ctx)

        # Step 6: Send catalog event
        _send_catalog_event(args, ctx, mode, entrypoint_path)

        # Step 7: Start workers
        factory_proc = _start_workers(args, ctx, env_ctx, cleanup_manager)

        # Step 8: Run or execute
        execution_success = True
        if mode == "run":
            execution_success = _run_interactive(
                args, ctx, env_ctx, cleanup_manager, factory_proc, perf, entrypoint_path
            )
        else:
            execution_success = _execute_batch(
                args,
                ctx,
                env_ctx,
                cleanup_manager,
                perf,
                entrypoint_path,
            )

        print("[floability] Exiting run.")
        return 0 if execution_success else 1

    except ValueError as e:
        print(f"[floability] Error: {e}")
        if "ctx" in locals():
            _cleanup_and_abort(cleanup_manager, ctx, error=str(e))
        return 1
    except WorkerStartupCleanupError as e:
        print(f"[floability] Error: {e}")
        if "ctx" in locals():
            _cleanup_and_abort(
                cleanup_manager,
                ctx,
                error=str(e),
                cleanup_already_incomplete=True,
            )
        return 1
    except RuntimeError as e:
        print(f"[floability] Error: {e}")
        if "ctx" in locals():
            _cleanup_and_abort(cleanup_manager, ctx, error=str(e))
        return 1
    except Exception as e:
        print(f"[floability] Unexpected error: {e}")
        if "ctx" in locals():
            _cleanup_and_abort(cleanup_manager, ctx, error=str(e))
        raise


def execute_python_script(
    script_path, run_dir, conda_env_dir=None, working_dir=None, extra_env: dict = None
):
    """Execute a Python script, streaming stdout/stderr to both the terminal and a log file.

    Output routing
    --------------
    Script stdout and stderr are tee'd in real time to:
      - The terminal (so TaskVine task-status lines and print() calls are visible live)
      - logs/workflow.log inside the instance directory

    This differs from notebook execution, where outputs are embedded in the .ipynb
    cell outputs and nbconvert's own messages go to logs/jupyterlab.stdout.
    """
    script_abs_path = os.path.abspath(script_path)
    script_name = os.path.basename(script_abs_path)

    exec_dir = working_dir if working_dir else os.path.dirname(script_abs_path)

    print(f"[floability] Executing Python script: {script_name}")
    print(f"[floability] Working directory: {exec_dir}")
    log_file = os.path.join(run_dir, "workflow.log")
    print(f"[floability] Output log: {log_file}")

    if conda_env_dir:
        python_path = os.path.join(conda_env_dir, "bin", "python")
        cmd = [
            get_conda_executable(),
            "run",
            "--prefix",
            conda_env_dir,
            "--no-capture-output",
            python_path,
            "-u",
            script_name,
        ]
    else:
        cmd = ["python", "-u", script_name]

    print(f"[floability] Running: {' '.join(cmd)}")

    original_dir = os.getcwd()
    returncode = 1
    try:
        os.chdir(exec_dir)
        with open(log_file, "w") as log:
            log.write(f"[floability] script: {script_abs_path}\n")
            log.write(f"[floability] command: {' '.join(cmd)}\n\n")
            log.flush()

            proc = subprocess.Popen(
                cmd,
                env=extra_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            # Tee: write each line to both the log and the terminal live
            for line in proc.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                log.write(line)
                log.flush()

            proc.wait()
            returncode = proc.returncode

        if returncode == 0:
            print("[floability] Script completed successfully (exit 0)")
        else:
            print(f"[floability] Script exited with code {returncode}")
        print(f"[floability] Full output saved to: {log_file}")

    except Exception as e:
        print(f"[floability] Error executing Python script: {e}")
        print(f"[floability] Check logs at {log_file}")
    finally:
        os.chdir(original_dir)

    return returncode == 0


def execute_shell_script(
    script_path, run_dir, conda_env_dir=None, working_dir=None, extra_env: dict = None
):
    """Execute a shell entrypoint and stream its combined output to workflow.log."""
    script_abs_path = os.path.abspath(script_path)
    script_name = os.path.basename(script_abs_path)
    exec_dir = working_dir if working_dir else os.path.dirname(script_abs_path)

    print(f"[floability] Executing shell script: {script_name}")
    print(f"[floability] Working directory: {exec_dir}")
    log_file = os.path.join(run_dir, "workflow.log")
    print(f"[floability] Output log: {log_file}")

    shell_path = "/bin/bash"
    if conda_env_dir:
        cmd = [
            get_conda_executable(),
            "run",
            "--prefix",
            conda_env_dir,
            "--no-capture-output",
            shell_path,
            script_name,
        ]
    else:
        cmd = [shell_path, script_name]

    print(f"[floability] Running: {' '.join(cmd)}")

    original_dir = os.getcwd()
    returncode = 1
    try:
        os.chdir(exec_dir)
        with open(log_file, "w") as log:
            log.write(f"[floability] script: {script_abs_path}\n")
            log.write(f"[floability] command: {' '.join(cmd)}\n\n")
            log.flush()

            proc = subprocess.Popen(
                cmd,
                env=extra_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            for line in proc.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                log.write(line)
                log.flush()

            proc.wait()
            returncode = proc.returncode

        if returncode == 0:
            print("[floability] Shell script completed successfully (exit 0)")
        else:
            print(f"[floability] Shell script exited with code {returncode}")
        print(f"[floability] Full output saved to: {log_file}")

    except Exception as e:
        print(f"[floability] Error executing shell script: {e}")
        print(f"[floability] Check logs at {log_file}")
    finally:
        os.chdir(original_dir)

    return returncode == 0


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
        return False
    return True


def _prepare_new_instance(args: argparse.Namespace, mode: str) -> InstanceContext:
    """Create a new instance from a backpack.

    Returns:
        InstanceContext if successful.

    Raises:
        RuntimeError: If instance creation fails.
    """

    resolve_backpack_args(args)

    backpack_root = _source_backpack_root(args)
    require_executable_backpack(
        backpack_root,
        getattr(args, "environment", None),
    )
    source_entrypoint, entrypoint_message = _select_workflow_entrypoint(
        args,
        backpack_root / "workflow",
        mode,
    )
    entrypoint_relative_path = source_entrypoint.relative_to(
        backpack_root / "workflow"
    )

    print("[floability] Preparing new instance from backpack")

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
    create_latest_symlink(str(instance_root.parent), str(instance_root))

    if not acquire_instance_lock(instance_root):
        raise RuntimeError("Failed to acquire instance run lock for new instance.")

    metadata_file = instance_paths["metadata"] / "run.json"
    try:
        record_initial_metadata(args, instance_paths, mode=mode)
    except Exception as e:
        print(f"[floability] Warning: Could not create metadata: {e}")

    # Setup workflow directory
    workflow_dir = instance_paths["workflow"]
    copied_workflow_paths: list[Path] = []
    if getattr(args, "backpack_root", None):
        from ..instance_manager import copy_workflow_directory

        backpack_workflow_dir = Path(args.backpack_root) / "workflow"
        copy_workflow_directory(
            source_workflow_dir=backpack_workflow_dir,
            dest_workflow_dir=workflow_dir,
            copied_paths=copied_workflow_paths,
        )
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
        entrypoint_path=workflow_dir / entrypoint_relative_path,
        entrypoint_message=entrypoint_message,
        copied_workflow_paths=tuple(copied_workflow_paths),
        lock_acquired=True,
        is_new=True,
    )


def _source_backpack_root(args: argparse.Namespace) -> Path:
    """Resolve the source root without falling back from a bad --backpack."""
    requested_backpack = getattr(args, "backpack", None)
    if requested_backpack:
        return Path(requested_backpack).expanduser().resolve()
    return Path(getattr(args, "backpack_root", ".") or ".").expanduser().resolve()


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


def _prepare_existing_instance(
    args: argparse.Namespace,
    mode: str = "run",
) -> InstanceContext:
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

    metadata_file = instance_root / "metadata" / "run.json"
    metadata = _read_reusable_instance_metadata(metadata_file)
    preparation = metadata.get("preparation")
    if isinstance(preparation, dict):
        preparation_state = preparation.get("state")
        if preparation_state != "ready":
            detail = preparation.get("error")
            detail_suffix = f": {detail}" if detail else "."
            raise RuntimeError(
                "Instance preparation is not ready "
                f"(state={preparation_state or 'unknown'}){detail_suffix}"
            )

    instance_paths = {
        "root": instance_root,
        "workflow": instance_root / "workflow",
        "logs": instance_root / "logs",
        "metrics": instance_root / "metrics",
        "metadata": instance_root / "metadata",
    }
    workflow_dir = instance_paths["workflow"]
    entrypoint_path, entrypoint_message = _select_workflow_entrypoint(
        args,
        workflow_dir,
        mode,
    )

    if not acquire_instance_lock(instance_root):
        raise RuntimeError("Failed to acquire instance run lock.")

    print(f"[floability] Running on existing instance: {instance_root}")

    create_latest_symlink(str(instance_root.parent), str(instance_root))

    args.workflow_dir = str(workflow_dir)

    return InstanceContext(
        root=instance_root,
        paths=instance_paths,
        metadata_file=metadata_file,
        workflow_dir=workflow_dir,
        entrypoint_path=entrypoint_path,
        entrypoint_message=entrypoint_message,
        lock_acquired=True,
        is_new=False,
    )


def _read_reusable_instance_metadata(metadata_file: Path) -> dict:
    """Return valid instance metadata or raise an actionable reuse error."""

    if not metadata_file.is_file():
        raise RuntimeError(f"Missing reusable instance metadata: {metadata_file}")
    try:
        with open(metadata_file) as metadata_stream:
            metadata = json.load(metadata_stream)
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(
            f"Could not read reusable instance metadata at {metadata_file}: {error}"
        ) from error
    if not isinstance(metadata, dict):
        raise RuntimeError(
            f"Reusable instance metadata must be a JSON object: {metadata_file}"
        )
    return metadata


def _select_run_manager_name(args: argparse.Namespace) -> str:
    """Select the TaskVine manager name for one run/execute attempt."""
    manager_name = getattr(args, "manager_name", None)
    if not manager_name:
        manager_name = f"floability-{uuid.uuid4()}"
        args.manager_name = manager_name
    return manager_name


def _restore_existing_manager_ports(
    args: argparse.Namespace,
    metadata_file: Path,
) -> None:
    """Restore saved manager ports unless the user supplied them explicitly."""
    explicit_args = set(getattr(args, "_explicit_args", ()) or ())
    if "manager_ports" in explicit_args or not metadata_file.exists():
        return

    try:
        with open(metadata_file) as metadata_stream:
            metadata = json.load(metadata_stream)
    except (OSError, json.JSONDecodeError):
        return

    saved_ports = metadata.get("manager_ports")
    if saved_ports is None:
        saved_ports = (metadata.get("cli_args") or {}).get("manager_ports")
    if saved_ports and saved_ports != "None":
        args.manager_ports = normalize_manager_ports(saved_ports)


def _persist_run_identity(
    args: argparse.Namespace,
    ctx: InstanceContext,
) -> None:
    """Persist the effective TaskVine identity before runtime processes start."""
    manager_ports = normalize_manager_ports(
        getattr(args, "manager_ports", None) or "9123:9150"
    )
    args.manager_ports = manager_ports
    update_instance_metadata(
        ctx.metadata_file,
        {
            "manager_name": args.manager_name,
            "manager_ports": manager_ports,
            "cli_args": {
                "manager_name": args.manager_name,
                "manager_ports": manager_ports,
            },
        },
        merge=True,
    )


def _register_new_instance(instance_root: Path, manager_name: str) -> None:
    """Register a newly created instance in global registry."""
    try:
        short_name = register_instance(
            instance_root,
            manager_name,
            base_dir=instance_root.parent,
        )
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
        data_cache_mode=getattr(args, "data_cache_mode", "symlink"),
        force_data_cache=getattr(args, "force_data_cache", False),
        base_dir=Path(args.base_dir),
        cache_base_dir=Path(args.cache_base_dir),
        target_root=target_root,
        fingerprint_mode=getattr(args, "fingerprint_mode", "meta"),
        cache_lookup_mode=getattr(args, "cache_lookup_mode", "strict"),
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
        return _restore_existing_instance_environment(args, ctx, perf)

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

    persist_prepared_environment(
        ctx.metadata_file,
        env_dir=env_dir,
        worker_environment_pack=worker_tar,
        manager_environment_pack=manager_tar,
        environment_spec=env_spec,
        worker_environment_spec=getattr(args, "worker_environment", None),
        per_instance_env=per_instance_env,
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
    entrypoint_path: Optional[str],
    event: str = "startup",
) -> None:
    """Send catalog update event."""
    backpack_name = (
        Path(getattr(args, "backpack", "")).stem
        if getattr(args, "backpack", None)
        else None
    )
    entrypoint_name = (
        Path(entrypoint_path).name if entrypoint_path else None
    )
    send_catalog_update(
        manager_name=args.manager_name,
        jupyter_port=getattr(args, "jupyter_port", 8888),
        run_dir=str(ctx.paths["root"]),
        backpack_name=backpack_name,
        event=event,
        entrypoint_name=entrypoint_name,
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
    if factory_proc is None:
        raise RuntimeError(
            "Worker startup did not return a vine_factory process. "
            "Review the worker logs in the instance logs directory."
        )
    if factory_proc:
        cleanup_manager.register_subprocess(factory_proc)
        cleanup_manager.register_cleanup_callback(
            lambda cleanup_succeeded: reconcile_workers_after_cleanup(
                ctx.root,
                cleanup_succeeded=cleanup_succeeded,
                expected_factory_pid=factory_proc.pid,
                expected_factory_owner=getattr(
                    factory_proc,
                    "floability_identity",
                    None,
                ),
            )
        )
    return factory_proc


def _run_entrypoint_error(args: argparse.Namespace, entrypoint: Path) -> RuntimeError:
    """Build the actionable error for a script selected with interactive run."""
    backpack = getattr(args, "backpack", None)
    backpack_hint = f" --backpack {backpack}" if backpack else " --backpack <path>"
    return RuntimeError(
        f"Interactive 'floability run' requires a .ipynb entrypoint; "
        f"'{entrypoint.name}' is a {entrypoint.suffix} script. "
        f"Use 'floability execute{backpack_hint}' instead."
    )


def _resolve_entrypoint(
    args: argparse.Namespace,
    ctx: InstanceContext,
    mode: str,
) -> Optional[str]:
    """Resolve and validate the workflow entrypoint for the selected mode.

    Priority
    --------
    1. ``--entrypoint <filename>`` — explicit filename match.
    2. Auto-detect one eligible entrypoint.

    Interactive ``run`` accepts only ``.ipynb``. Batch ``execute`` accepts
    ``.ipynb``, ``.py``, and ``.sh`` entrypoints.

    Returns:
        Absolute path string to the entrypoint.

    Raises:
        RuntimeError: If selection is missing, ambiguous, or incompatible.
    """
    entrypoint, message = _select_workflow_entrypoint(
        args,
        ctx.workflow_dir,
        mode,
    )
    print(message)
    return str(entrypoint)


def _select_workflow_entrypoint(
    args: argparse.Namespace,
    workflow_dir: Path,
    mode: str,
) -> tuple[Path, str]:
    """Select a mode-compatible entrypoint from one workflow directory."""
    requested_entrypoint = getattr(args, "entrypoint", None)

    if mode not in {"run", "execute"}:
        raise ValueError(f"Unknown workflow mode: {mode}")

    # Collect all supported candidates from the workflow directory.
    all_notebooks = [
        path
        for path in workflow_dir.rglob("*.ipynb")
        if path.is_file() and ".ipynb_checkpoints" not in path.parts
    ]
    all_scripts = [
        path
        for path in workflow_dir.rglob("*.py")
        if path.is_file() and "__pycache__" not in path.parts
    ]
    all_shell_scripts = [
        path for path in workflow_dir.rglob("*.sh") if path.is_file()
    ]
    all_candidates = sorted(
        all_notebooks + all_scripts + all_shell_scripts,
        key=lambda path: str(path.relative_to(workflow_dir)),
    )
    eligible = all_notebooks if mode == "run" else all_candidates

    entrypoint: Path | None = None
    message: str | None = None

    # ── Priority 1: --entrypoint ─────────────────────────────────────────────
    if requested_entrypoint:
        matches = [
            path for path in all_candidates if path.name == requested_entrypoint
        ]
        if not matches:
            raise RuntimeError(
                f"Entrypoint '{requested_entrypoint}' was not found in workflow/."
            )
        if len(matches) > 1:
            raise RuntimeError(
                f"Entrypoint '{requested_entrypoint}' is ambiguous in workflow/."
            )
        entrypoint = matches[0]
        if mode == "run" and entrypoint.suffix != ".ipynb":
            raise _run_entrypoint_error(args, entrypoint)
        message = f"[floability] Using entrypoint: {entrypoint.name}"

    # ── Priority 2: auto-detect one eligible entrypoint ──────────────────────
    if entrypoint is None:
        if len(eligible) == 1:
            entrypoint = eligible[0]
            message = (
                f"[floability] Auto-detected entrypoint: {entrypoint.name}"
            )
        elif len(eligible) > 1:
            backpack_name = (
                Path(args.backpack).resolve().name
                if getattr(args, "backpack", None)
                else None
            )
            named_matches = [
                path for path in eligible if path.stem == backpack_name
            ]
            if len(named_matches) == 1:
                entrypoint = named_matches[0]
                message = (
                    "[floability] Auto-detected backpack-named entrypoint: "
                    f"{entrypoint.name}"
                )
            else:
                names = ", ".join(path.name for path in eligible)
                raise RuntimeError(
                    f"Multiple workflow entrypoints found: {names}. "
                    "Select one with --entrypoint."
                )

    if entrypoint is None and mode == "run" and all_candidates:
        raise _run_entrypoint_error(args, all_candidates[0])

    if entrypoint is None:
        expected = ".ipynb" if mode == "run" else ".ipynb, .py, or .sh"
        raise RuntimeError(
            "No workflow entrypoint found in workflow directory. "
            f"Expected {expected}."
        )

    assert message is not None
    return entrypoint, message


def _prepared_entrypoint(ctx: InstanceContext) -> str:
    """Return the preflight-selected instance path without rescanning."""
    entrypoint = ctx.entrypoint_path
    if entrypoint is None:
        raise RuntimeError("Instance context has no preflight-selected entrypoint.")
    if not entrypoint.is_file():
        raise RuntimeError(
            f"Preflight-selected entrypoint is missing from the instance: {entrypoint}"
        )
    if ctx.entrypoint_message:
        print(ctx.entrypoint_message)
    return str(entrypoint)


def _run_interactive(
    args: argparse.Namespace,
    ctx: InstanceContext,
    env_ctx: EnvironmentContext,
    cleanup_manager: CleanupManager,
    factory_proc: Optional[Any],
    perf: PerformanceTracker,
    entrypoint_path: Optional[str],
) -> bool:
    """Run interactive mode with JupyterLab."""
    interrupted = False
    session_success = False
    session_error = "Interactive session ended before JupyterLab completed."
    print("[floability] JupyterLab startup")
    # JupyterLab can only open a notebook at startup; pass None for .py entrypoints
    # so it launches in the workflow directory without trying to open the script.
    nb_for_jupyter = (
        entrypoint_path
        if entrypoint_path and entrypoint_path.endswith(".ipynb")
        else None
    )
    if entrypoint_path and not nb_for_jupyter:
        print(f"[floability] Script entrypoint detected ({Path(entrypoint_path).name}); "
              "JupyterLab will open in the workflow directory — run the script manually "
              "or use 'floability execute'.")
    jupyter_proc = start_jupyterlab(
        notebook_path=nb_for_jupyter,
        port=getattr(args, "jupyter_port", 8888),
        run_dir=str(ctx.paths["logs"]),
        conda_env_dir=env_ctx.env_dir,
        working_dir=str(ctx.workflow_dir),
        extra_env=env_ctx.instance_env,
    )
    if jupyter_proc:
        cleanup_manager.register_subprocess(jupyter_proc)
    else:
        raise RuntimeError(
            "JupyterLab startup did not return a process. "
            f"Review {ctx.paths['logs'] / 'jupyterlab.stdout'}."
        )

    # Monitor subprocesses
    try:
        while True:
            time.sleep(5)
            jupyter_status = jupyter_proc.poll()
            factory_status = (
                getattr(factory_proc, "poll", lambda: None)()
                if factory_proc is not None
                else None
            )

            # Jupyter owns the interactive session outcome. Check it first so
            # simultaneous observed exits are not misreported as factory-first.
            if jupyter_status is not None:
                print(
                    "[floability] JupyterLab ended with status "
                    f"{jupyter_status}."
                )
                if factory_status is not None:
                    print(
                        "[floability] Worker factory also ended with status "
                        f"{factory_status}."
                    )
                session_success = jupyter_status == 0
                session_error = (
                    None
                    if session_success
                    else f"JupyterLab exited with status {jupyter_status}."
                )
                break

            if factory_status is not None:
                session_error = (
                    "Worker factory exited before JupyterLab with status "
                    f"{factory_status}."
                )
                print(f"[floability] {session_error}")
                break
    except KeyboardInterrupt:
        interrupted = True
        raise
    finally:
        cleanup_succeeded = cleanup_manager.cleanup()
        _finalize_run(
            args,
            ctx,
            perf,
            cleanup_succeeded=cleanup_succeeded,
            owned_processes_stopped=cleanup_manager.owned_processes_stopped,
            sync_workflow=True,
            success=session_success and not interrupted,
            error="Interrupted by user" if interrupted else session_error,
            state="interrupted" if interrupted else None,
        )
    return session_success and cleanup_succeeded


def _execute_batch(
    args: argparse.Namespace,
    ctx: InstanceContext,
    env_ctx: EnvironmentContext,
    cleanup_manager: CleanupManager,
    perf: PerformanceTracker,
    entrypoint_path: Optional[str],
) -> bool:
    """Execute batch mode for a notebook, Python script, or shell script.

    Dispatch rules
    --------------
    1. entrypoint_path ends with .py  → execute_python_script
    2. entrypoint_path ends with .sh  → execute_shell_script
    3. entrypoint_path ends with .ipynb  → execute_notebook
    """
    execution_success = False

    # Selected .py entrypoint from the workflow directory
    if entrypoint_path and entrypoint_path.endswith(".py"):
        print("[floability] Python script execution (auto-detected .py entrypoint)")
        execution_success = execute_python_script(
            script_path=entrypoint_path,
            run_dir=str(ctx.paths["logs"]),
            conda_env_dir=env_ctx.env_dir,
            working_dir=str(ctx.workflow_dir),
            extra_env=env_ctx.instance_env,
        )
    elif entrypoint_path and entrypoint_path.endswith(".sh"):
        print("[floability] Shell script execution")
        execution_success = execute_shell_script(
            script_path=entrypoint_path,
            run_dir=str(ctx.paths["logs"]),
            conda_env_dir=env_ctx.env_dir,
            working_dir=str(ctx.workflow_dir),
            extra_env=env_ctx.instance_env,
        )
    elif entrypoint_path:
        print("[floability] notebook execution")
        if perf.enabled:
            perf.start_timer("notebook_execute_time")
        execution_success = execute_notebook(
            notebook_path=entrypoint_path,
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
        _sync_workflow_if_needed(args, ctx)

    cleanup_succeeded = cleanup_manager.cleanup()
    _finalize_run(
        args,
        ctx,
        perf,
        cleanup_succeeded=cleanup_succeeded,
        owned_processes_stopped=cleanup_manager.owned_processes_stopped,
        sync_workflow=False,
        success=execution_success,
        error=None if execution_success else "Workflow entrypoint execution failed",
    )

    if not execution_success:
        print("[floability] Workflow entrypoint execution failed.")

    return execution_success


def _sync_workflow_if_needed(args: argparse.Namespace, ctx: InstanceContext) -> None:
    """Copy selected workflow files back to the backpack when enabled."""
    if (
        ctx.is_new
        and getattr(args, "backpack", None)
        and not getattr(args, "no_update_backpack", False)
    ):
        backpack_workflow_dir = Path(args.backpack_root) / "workflow"
        sync_workflow_to_backpack(
            ctx.workflow_dir,
            backpack_workflow_dir,
            copied_paths=ctx.copied_workflow_paths,
            extra_paths=getattr(args, "sync_path", None),
            metadata_dir=ctx.paths["metadata"],
            verbose=True,
        )


def _finalize_run(
    args: argparse.Namespace,
    ctx: InstanceContext,
    perf: PerformanceTracker,
    cleanup_succeeded: bool,
    owned_processes_stopped: bool,
    sync_workflow: bool = False,
    success: bool = True,
    error: Optional[str] = None,
    state: Optional[str] = None,
) -> None:
    """Finalize metadata and release ownership only after complete cleanup."""
    if sync_workflow:
        _sync_workflow_if_needed(args, ctx)

    if perf.enabled:
        perf.end_timer("total_run_time", "Total run time")
        perf.save_report()
        print(f"[floability] Performance report saved to {ctx.paths['metrics']}")

    final_success = success and cleanup_succeeded
    final_state = state
    final_error = error
    if not cleanup_succeeded:
        final_state = "cleanup_incomplete"
        final_error = (
            f"{error}; cleanup incomplete"
            if error
            else "Cleanup incomplete; one or more owned processes remain."
        )

    try:
        finalize_instance_metadata(
            ctx.metadata_file,
            success=final_success,
            error=final_error,
            state=final_state,
        )
    except Exception as e:
        print(f"[floability] Warning: Could not finalize metadata: {e}")

    if not ctx.lock_acquired:
        return
    if not cleanup_succeeded:
        if not mark_instance_cleanup_incomplete(
            ctx.root,
            error=final_error,
            owned_processes_stopped=owned_processes_stopped,
        ):
            print(
                "[floability] Warning: could not record incomplete instance "
                "cleanup ownership."
            )
        return
    if not release_instance_lock(ctx.root):
        print("[floability] Warning: could not release the matching instance lock.")


def _restore_existing_instance_environment(
    args: argparse.Namespace,
    ctx: InstanceContext,
    perf: PerformanceTracker,
) -> EnvironmentContext:
    """Validate or rebuild the prepared manager and worker environments."""

    try:
        with open(ctx.metadata_file) as metadata_stream:
            metadata = json.load(metadata_stream)
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(
            f"Could not read reusable instance metadata at {ctx.metadata_file}: {error}"
        ) from error

    prepared = read_prepared_environment(metadata)
    environment_spec = prepared["environment_spec"]
    worker_environment_spec = prepared["worker_environment_spec"]
    per_instance_env = prepared["per_instance_env"]

    manager_spec_available = bool(
        environment_spec and Path(environment_spec).is_file()
    )
    worker_spec_available = bool(
        not worker_environment_spec or Path(worker_environment_spec).is_file()
    )

    if manager_spec_available and worker_spec_available:
        env_dir, worker_pack, manager_pack = setup_manager_and_worker_envs(
            environment_spec=environment_spec,
            worker_environment_spec=worker_environment_spec,
            base_dir=args.base_dir,
            instance_root=str(ctx.root),
            per_instance_env=per_instance_env,
            perf=perf if perf.enabled else None,
        )
        persist_prepared_environment(
            ctx.metadata_file,
            env_dir=env_dir,
            worker_environment_pack=worker_pack,
            manager_environment_pack=manager_pack,
            environment_spec=environment_spec,
            worker_environment_spec=worker_environment_spec,
            per_instance_env=per_instance_env,
        )
    else:
        env_dir = prepared["env_dir"]
        worker_pack = prepared["worker_environment_pack"]
        manager_pack = prepared["manager_environment_pack"]
        missing = []
        if not env_dir or not (Path(env_dir) / "bin" / "python").is_file():
            missing.append("manager environment")
        if not worker_pack or not Path(worker_pack).is_file():
            missing.append("worker environment pack")
        if not manager_pack or not Path(manager_pack).is_file():
            missing.append("manager environment pack")
        if missing:
            unavailable_specs = []
            if not manager_spec_available:
                unavailable_specs.append(
                    f"manager spec {environment_spec!r}"
                    if environment_spec
                    else "manager spec"
                )
            if not worker_spec_available:
                unavailable_specs.append(
                    f"worker spec {worker_environment_spec!r}"
                )
            raise RuntimeError(
                "Reusable instance is missing "
                + ", ".join(missing)
                + "; cannot rebuild because "
                + ", ".join(unavailable_specs)
                + " is unavailable."
            )
        if not env_dir:
            raise RuntimeError(
                "Reusable instance has no prepared manager environment and no "
                "rebuildable environment spec."
            )
        print(f"[floability] Using saved environment artifacts: {env_dir}")

    instance_env = _build_instance_env(args, ctx, env_dir)
    _display_env_info(env_dir, instance_env)
    return EnvironmentContext(
        env_dir=env_dir,
        worker_pack=worker_pack,
        manager_pack=manager_pack,
        instance_env=instance_env,
    )


def _get_env_python_version(prefix: str) -> str:
    """
    Query the target conda prefix for its Python version.
    Returns string like '3.14'
    """
    python_path = str(Path(prefix) / "bin" / "python")
    result = subprocess.run(
        [
            get_conda_executable(),
            "run",
            "--prefix",
            str(prefix),
            "--no-capture-output",
            python_path,
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

    # Do not leak the currently activated Conda environment into subprocesses
    # that will be activated with ``conda run --prefix``. Keep CONDA_EXE and
    # CONDA_PYTHON_EXE so the Conda installation itself remains discoverable.
    for key in (
        "CONDA_PREFIX",
        "CONDA_DEFAULT_ENV",
        "CONDA_PROMPT_MODIFIER",
        "CONDA_SHLVL",
        "_CE_CONDA",
        "_CE_M",
    ):
        env.pop(key, None)

    # Always resolve workflow tools from the selected backpack environment.
    # Keeping an already-active environment ahead of this prefix can make the
    # manager and workers use different Python versions.
    if env_dir is not None:
        env_bin = str(Path(env_dir) / "bin")
        env["PATH"] = env_bin + os.pathsep + env.get("PATH", "")

    # -------------------------------------------------
    # TaskVine identity (per-instance)
    # -------------------------------------------------
    env["VINE_MANAGER_NAME"] = getattr(args, "manager_name", "") or ""
    env["VINE_MANAGER_PORTS"] = normalize_manager_ports(
        getattr(args, "manager_ports", None) or "9123:9150"
    )
    env["FLOABILITY_WORKERS_ENABLED"] = (
        "0" if getattr(args, "no_worker", False) else "1"
    )

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
    if env_dir is not None:
        python_version = _get_env_python_version(env_dir)
    else:
        import sys
        python_version = f"{sys.version_info.major}.{sys.version_info.minor}"

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
                get_conda_executable(),
                "run",
                "--prefix",
                env_dir,
                "--no-capture-output",
                str(Path(env_dir) / "bin" / "python"),
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
    error: str,
    *,
    cleanup_already_incomplete: bool = False,
) -> None:
    """Clean up a failed run, finalize its metadata, and release its lock."""
    cleanup_succeeded = False
    try:
        cleanup_succeeded = cleanup_manager.cleanup()
    except Exception as cleanup_error:
        print(f"[floability] Warning: cleanup after failure was incomplete: {cleanup_error}")

    if cleanup_already_incomplete:
        cleanup_succeeded = False

    final_state = "failed" if cleanup_succeeded else "cleanup_incomplete"
    final_error = error if cleanup_succeeded else f"{error}; cleanup incomplete"
    try:
        finalize_instance_metadata(
            ctx.metadata_file,
            success=False,
            error=final_error,
            state=final_state,
        )
    except Exception as metadata_error:
        print(f"[floability] Warning: Could not finalize failed metadata: {metadata_error}")
    finally:
        if ctx.lock_acquired:
            if cleanup_succeeded:
                if not release_instance_lock(ctx.root):
                    print(
                        "[floability] Warning: could not release the matching "
                        "instance lock."
                    )
            elif not mark_instance_cleanup_incomplete(
                ctx.root,
                error=final_error,
                owned_processes_stopped=(
                    cleanup_manager.owned_processes_stopped
                ),
            ):
                print(
                    "[floability] Warning: could not record incomplete "
                    "instance cleanup ownership."
                )
