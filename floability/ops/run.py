"""
Run and execute operations for Floability CLI.
"""

import argparse
import os
import subprocess
import time
import uuid
from pathlib import Path
from ..cleanup import CleanupManager
from ..performance_tracker import PerformanceTracker
from ..environment_manager import setup_manager_and_worker_envs
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
from ..instance_registry import resolve_instance, touch_instance, register_instance
from ..catalog import send_catalog_update
from ..instance_metadata import finalize_instance_metadata, update_instance_metadata


def run_workflow(
    args: argparse.Namespace, cleanup_manager: CleanupManager, mode="run"
) -> None:
    """Run or execute a workflow either by creating a new instance from a backpack
    or by reusing an existing instance (via --instance).
    """
    # Mutual exclusion: can't specify both
    if getattr(args, "backpack", None) and getattr(args, "instance", None):
        print("[floability] Error: --backpack and --instance cannot be used together.")
        return

    # Resolve short-name to path if necessary
    if getattr(args, "instance", None):
        resolved = resolve_instance(args.instance)
        if not resolved:
            print(f"[floability] Error: instance reference not found: {args.instance}")
            return
        args.instance = resolved
        using_existing_instance = True
        touch_instance(args.instance)
    else:
        using_existing_instance = False
    lock_acquired = False

    ################### Step 1: Prepare instance (new or existing) ###################
    if not using_existing_instance:
        # Ensure manager name early so it's recorded in metadata
        if getattr(args, "manager_name", None) is None:
            args.manager_name = f"floability-{uuid.uuid4()}"
        resolve_backpack_args(args)

        if getattr(args, "backpack", None):
            validate_backpack_structure(args.backpack, require_workflow=False)

        # Normalize base_dir and data cache dir
        raw_base = (
            getattr(args, "base_dir", None) if hasattr(args, "base_dir") else None
        )
        args.base_dir = str(normalize_cli_base_dir(raw_base))

        # Determine data cache directory: allow CLI override, else use base_dir/floability-data-cache
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
                pass
        else:
            cache_base_dir = (Path(args.base_dir) / "floability-data-cache").resolve()
            try:
                cache_base_dir.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
        args.cache_base_dir = str(cache_base_dir)

        # Build instance prefix
        instance_prefix = "floability_instance"
        if getattr(args, "instance_prefix", None):
            instance_prefix = f"floability_instance_{args.instance_prefix}"

        instance_paths = create_instance_structure(
            args.base_dir, prefix=instance_prefix
        )
        instance_root = str(instance_paths["root"])
        create_latest_symlink(args.base_dir, instance_root)
        # Acquire instance lock for new instance runs to prevent concurrent starts
        if not acquire_instance_lock(Path(instance_root)):
            print(
                "[floability] Failed to acquire instance run lock for new instance. Abort."
            )
            return
        lock_acquired = True
        metadata_file = instance_paths["metadata"] / "run.json"
        try:
            record_initial_metadata(args, instance_paths, mode=mode)
        except Exception as e:
            print(f"[floability] Warning: Could not create metadata: {e}")

    else:
        instance_root = str(Path(args.instance).resolve())
        if not Path(instance_root).is_dir():
            print(f"[floability] Error: Instance directory not found: {instance_root}")
            return
        if is_instance_running(Path(instance_root)):
            print("[floability] Instance already running (lock present). Abort.")
            return
        if not acquire_instance_lock(Path(instance_root)):
            print("[floability] Failed to acquire instance run lock. Abort.")
            return
        lock_acquired = True
        print(f"[floability] Running on existing instance: {instance_root}")
        # Load paths map
        instance_paths = {
            "root": Path(instance_root),
            "workflow": Path(instance_root) / "workflow",
            "logs": Path(instance_root) / "logs",
            "metrics": Path(instance_root) / "metrics",
            "metadata": Path(instance_root) / "metadata",
        }
        # Metadata file may already exist
        metadata_file = instance_paths["metadata"] / "run.json"
        if not metadata_file.exists():
            print(f"[floability] Warning: Missing instance metadata at {metadata_file}")

    # Initialize performance tracking
    perf_enabled = getattr(args, "measure_performance", False)
    perf = PerformanceTracker(
        output_dir=str(instance_paths["metrics"]), enabled=perf_enabled
    )
    perf.start_timer("total_run_time")

    # Manager name already ensured for new instances; for existing instances,
    # do not override whatever is in metadata.

    # Register newly created instance in global registry (short name)
    if not using_existing_instance:
        try:
            short_name = register_instance(Path(instance_root), args.manager_name)
            print(f"[floability] Registered instance short name: {short_name}")
        except Exception as e:
            print(f"[floability] Warning: could not register instance short name: {e}")

    # Workflow directory preparation / sandbox
    if using_existing_instance:
        workflow_dir = instance_paths["workflow"]
    else:
        print("[floability] workflow sandbox setup")
        # Copy entire workflow directory from backpack to instance
        workflow_dir = instance_paths["workflow"]
        if getattr(args, "backpack_root", None):
            from ..instance_manager import copy_workflow_directory

            backpack_workflow_dir = Path(args.backpack_root) / "workflow"
            copy_workflow_directory(
                source_workflow_dir=backpack_workflow_dir,
                dest_workflow_dir=workflow_dir,
            )

            # Update paths to point to copied files in instance
            if args.notebook:
                args.notebook = str(workflow_dir / Path(args.notebook).name)
            if args.python_script:
                args.python_script = str(workflow_dir / Path(args.python_script).name)
    args.workflow_dir = str(workflow_dir)

    ##################### Step 2: Data materialization ####################
    if not using_existing_instance and getattr(args, "data_spec", None):
        print("[floability] data materialization")
        if perf_enabled:
            perf.start_timer("total_data_materialization_time")
            perf.start_timer("data_operation")
        from ..data.data_handler import execute_default_data_operation

        # Materialize data into instance workflow
        target_root = instance_paths["workflow"]

        # backpack_root is used only for resolving source paths
        backpack_root_for_sources = (
            args.backpack_root if getattr(args, "backpack_root", None) else None
        )

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
        )
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
                print("[floability] Aborting due to data failure.")
                cleanup_manager.cleanup()
                if lock_acquired:
                    release_instance_lock(Path(instance_root))
                return

    ################# Step 3: Environment setup ####################
    if using_existing_instance or getattr(args, "prefer_instance", False):
        env_candidate = Path(instance_root) / "current_conda_env"
        env_dir = str(env_candidate) if env_candidate.exists() else None
        worker_environment_pack = None
        if env_dir:
            print(f"[floability] Using existing environment: {env_dir}")
        else:
            print("[floability] No environment found; proceeding without conda env.")
            # todo: warn or fail?
    else:
        print("[floability] environment setup (manager & worker)")
        env_dir, worker_environment_pack, manager_environment_pack = (
            setup_manager_and_worker_envs(
                environment_spec=getattr(args, "environment", None),
                worker_environment_spec=getattr(args, "worker_environment", None),
                base_dir=args.base_dir,
                instance_root=instance_root,
                manager_name=args.manager_name,
                manager_ports=getattr(args, "manager_ports", "9123,9150"),
                env_vars=getattr(args, "env_vars", None),
                force=False,
                perf=perf if perf_enabled else None,
            )
        )
        # Persist environment pack info for workers fallback
        try:
            update_instance_metadata(
                metadata_file,
                {
                    **({"env_dir": str(env_dir)} if env_dir else {}),
                    **(
                        {"worker_environment_pack": str(worker_environment_pack)}
                        if worker_environment_pack
                        else {}
                    ),
                    **(
                        {"manager_environment_pack": str(manager_environment_pack)}
                        if manager_environment_pack
                        else {}
                    ),
                },
                merge=True,
            )
        except Exception:
            pass

    # Startup catalog event
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
        run_dir=str(instance_paths["root"]),
        backpack_name=backpack_name,
        event="startup",
        notebook_name=notebook_name,
        mode=mode,
    )

    ################# Step 4: Provision workers ####################
    if not getattr(args, "no_worker", False):
        print("[floability] worker factory startup")
        factory_proc = start_workers_for_instance(
            instance_path=Path(instance_root),
            batch_type=getattr(args, "batch_type", None),
            workers=getattr(args, "workers", None),
            cores_per_worker=getattr(args, "cores_per_worker", None),
            batch_options=getattr(args, "batch_options", None),
            compute_spec=getattr(args, "compute_spec", None),
            debug_workers=getattr(args, "debug_workers", False),
        )
        if factory_proc:
            cleanup_manager.register_subprocess(factory_proc)
    else:
        factory_proc = None
        print("[floability] Workers disabled by --no-worker")

    ################# Step 5: Run or execute ####################
    notebook_path_for_exec = getattr(args, "notebook", None)
    script_path_for_exec = getattr(args, "python_script", None)
    if not using_existing_instance:
        if notebook_path_for_exec:
            notebook_path_for_exec = Path(notebook_path_for_exec).name
        if script_path_for_exec:
            script_path_for_exec = Path(script_path_for_exec).name

    # If no notebook specified or not found, search for any .ipynb in workflow dir
    if not notebook_path_for_exec or mode == "execute":
        workflow_notebooks = list(Path(workflow_dir).rglob("*.ipynb"))
        # Filter out checkpoint notebooks
        workflow_notebooks = [
            nb for nb in workflow_notebooks if ".ipynb_checkpoints" not in str(nb)
        ]
        if workflow_notebooks:
            if notebook_path_for_exec:
                # Try to find the specified notebook
                matching = [
                    nb for nb in workflow_notebooks if nb.name == notebook_path_for_exec
                ]
                if matching:
                    notebook_path_for_exec = str(matching[0])
                    print(f"[floability] Found notebook: {notebook_path_for_exec}")
                else:
                    # Use the first notebook found
                    notebook_path_for_exec = str(workflow_notebooks[0])
                    print(
                        f"[floability] Specified notebook not found, using: {notebook_path_for_exec}"
                    )
            else:
                # Use the first notebook found
                notebook_path_for_exec = str(workflow_notebooks[0])
                print(
                    f"[floability] No notebook specified, auto-detected: {notebook_path_for_exec}"
                )
        elif mode == "execute":
            print(
                "[floability] ERROR: No notebook found in workflow directory for execute mode"
            )
            cleanup_manager.cleanup()
            if lock_acquired:
                release_instance_lock(Path(instance_root))
            return

    if mode == "run":
        print("[floability] JupyterLab startup")
        jupyter_proc = start_jupyterlab(
            notebook_path=notebook_path_for_exec,
            port=getattr(args, "jupyter_port", 8888),
            run_dir=str(instance_paths["logs"]),
            conda_env_dir=env_dir,
            working_dir=str(workflow_dir),
        )
        if jupyter_proc:
            cleanup_manager.register_subprocess(jupyter_proc)
    else:
        jupyter_proc = None
        execution_success = False
        if getattr(args, "prefer_python", False) and script_path_for_exec:
            print("[floability] python script execution")
            execute_python_script(
                script_path=script_path_for_exec,
                run_dir=str(instance_paths["logs"]),
                conda_env_dir=env_dir,
                working_dir=str(workflow_dir),
            )
            execution_success = True
        elif notebook_path_for_exec:
            print("[floability] notebook execution")
            if perf_enabled:
                perf.start_timer("notebook_execute_time")
            execution_success = execute_notebook(
                notebook_path=notebook_path_for_exec,
                run_dir=str(instance_paths["logs"]),
                conda_env_dir=env_dir,
                working_dir=str(workflow_dir),
            )
            if perf_enabled:
                perf.end_timer(
                    "notebook_execute_time", "Time to execute notebook in execute mode"
                )
        if (
            execution_success
            and not using_existing_instance
            and getattr(args, "backpack", None)
            and not getattr(args, "no_update_backpack", False)
        ):
            backpack_workflow_dir = Path(args.backpack) / "workflow"
            sync_outputs_to_backpack(
                workflow_dir,
                backpack_workflow_dir,
                metadata_dir=instance_paths["metadata"],
                verbose=True,
            )
        cleanup_manager.cleanup()
        if lock_acquired:
            release_instance_lock(Path(instance_root))
        if perf_enabled:
            perf.end_timer("total_run_time", "Total run time")
            perf.save_report()
        try:
            finalize_instance_metadata(metadata_file, success=True)
        except Exception as e:
            print(f"[floability] Warning: Could not finalize metadata: {e}")
        print("[floability] Exiting run.")
        return

    # Monitor subprocesses (run mode)
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
        if (
            mode == "run"
            and not using_existing_instance
            and getattr(args, "backpack", None)
            and not getattr(args, "no_update_backpack", False)
        ):
            backpack_workflow_dir = Path(args.backpack) / "workflow"
            sync_outputs_to_backpack(
                workflow_dir,
                backpack_workflow_dir,
                metadata_dir=instance_paths["metadata"],
                verbose=True,
            )
        if perf_enabled:
            perf.end_timer("total_run_time", "Total run time")
            perf.save_report()
            print(
                f"[floability] Performance report saved to {instance_paths['metrics']}"
            )
        try:
            finalize_instance_metadata(metadata_file, success=True)
        except Exception as e:
            print(f"[floability] Warning: Could not finalize metadata: {e}")
        if lock_acquired:
            release_instance_lock(Path(instance_root))
    print("[floability] Exiting run.")


# todo: revist and make unified execution for any scripts
def execute_python_script(script_path, run_dir, conda_env_dir=None, working_dir=None):
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
                cmd, stdout=log, stderr=subprocess.STDOUT, check=True, text=True
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
