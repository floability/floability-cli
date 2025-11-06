"""
Run and execute operations for Floability CLI.
"""

import argparse
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from ..cleanup import CleanupManager
from ..performance_tracker import PerformanceTracker
from ..environment import create_conda_pack_from_yml
from ..resource_provisioner import start_vine_factory
from ..jupyter_runner import start_jupyterlab, execute_notebook
from ..utils import create_unique_directory, safe_extract_tar, update_env_vars_in_conda
from ..catalog import send_catalog_update
from ..instance_metadata import (
    create_instance_metadata,
    update_instance_metadata,
    finalize_instance_metadata,
    record_sync_manifest,
    compute_file_hash,
)


def sync_outputs_to_backpack(workflow_dir, backpack_dir, metadata_dir=None, verbose=True):
    """
    Sync a narrow, explicit set of outputs from workflow instance back to backpack.
    
    Syncs:
      1. Executed notebooks (*.ipynb with outputs)
      2. workflow/outputs/ directory (if it exists)
    
    Records sync manifest in metadata/sync.json for auditability.
    
    Args:
        workflow_dir: Path to instance workflow directory
        backpack_dir: Path to backpack workflow directory
        metadata_dir: Path to metadata directory for recording sync manifest
        verbose: Print detailed sync information
    
    Returns:
        True if any files were synced, False otherwise
    """
    workflow_path = Path(workflow_dir)
    backpack_path = Path(backpack_dir)
    
    if not workflow_path.exists():
        print(f"[floability] Warning: Workflow directory does not exist: {workflow_dir}")
        return False
    
    if not backpack_path.exists():
        print(f"[floability] Warning: Backpack directory does not exist: {backpack_dir}")
        return False
    
    print(f"[floability] Syncing outputs from instance to backpack...")
    print(f"[floability]   Source: {workflow_dir}")
    print(f"[floability]   Target: {backpack_dir}")
    
    synced_files_manifest = []
    
    # 1. Sync executed notebooks (they now contain outputs)
    print(f"[floability]   Syncing notebooks...")
    for notebook in workflow_path.glob("*.ipynb"):
        target = backpack_path / notebook.name
        try:
            shutil.copy2(notebook, target)
            file_info = {
                "path": notebook.name,
                "type": "notebook",
                "size": notebook.stat().st_size,
                "hash": compute_file_hash(notebook),
            }
            synced_files_manifest.append(file_info)
            if verbose:
                print(f"[floability]     ✓ {notebook.name}")
        except Exception as e:
            print(f"[floability]     ✗ Failed to sync {notebook.name}: {e}")
    
    # 2. Sync workflow/outputs/ directory if it exists
    outputs_dir = workflow_path / "outputs"
    if outputs_dir.exists() and outputs_dir.is_dir():
        print(f"[floability]   Syncing outputs/ directory...")
        target_outputs = backpack_path / "outputs"
        target_outputs.mkdir(parents=True, exist_ok=True)
        
        # Recursively sync all files in outputs/
        for item in outputs_dir.rglob("*"):
            if item.is_file():
                rel_path = item.relative_to(outputs_dir)
                target = target_outputs / rel_path
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, target)
                    file_info = {
                        "path": f"outputs/{rel_path}",
                        "type": "output",
                        "size": item.stat().st_size,
                        "hash": compute_file_hash(item),
                    }
                    synced_files_manifest.append(file_info)
                    if verbose:
                        print(f"[floability]     ✓ outputs/{rel_path}")
                except Exception as e:
                    print(f"[floability]     ✗ Failed to sync outputs/{rel_path}: {e}")
    
    # Record sync manifest in metadata
    if metadata_dir and synced_files_manifest:
        try:
            record_sync_manifest(
                Path(metadata_dir),
                synced_files_manifest,
                workflow_path,
                backpack_path,
            )
            if verbose:
                print(f"[floability]   Recorded sync manifest: {metadata_dir}/sync.json")
        except Exception as e:
            print(f"[floability]   Warning: Could not record sync manifest: {e}")
    
    if synced_files_manifest:
        print(f"[floability] Successfully synced {len(synced_files_manifest)} file(s) to backpack")
        return True
    else:
        print(f"[floability] No files to sync")
        return False


def resolve_backpack_args(args):
    """
    Given the path to a backpack, fill in any missing arguments
    (data spec, compute spec, environment, notebook/script) from
    the backpack structure.
    """
    
    if not args.backpack:
        return
    backpack_dir = Path(args.backpack).resolve()
    backpack_name = str(backpack_dir.stem)

    print(f"Started processing backpack: {backpack_name}")
    
    if not backpack_dir.is_dir():
        print(f"Backpack directory not found: {backpack_dir}")
        return
    
    if not args.data_spec:
        data_spec = backpack_dir / "data" / "data.yml"
        if data_spec.is_file():
            args.data_spec = str(data_spec)
            print(f"Using data spec from backpack: {args.data_spec}")
    
    if not args.compute_spec:
        compute_spec = backpack_dir / "compute" / "compute.yml"
        if compute_spec.is_file():
            args.compute_spec = str(compute_spec)
            print(f"Using compute spec from backpack: {args.compute_spec}")
    
    if not args.environment:
        env_path = backpack_dir / "software" / "environment.yml"
        if env_path.is_file():
            args.environment = str(env_path)
            print(f"Using environment from backpack: {args.environment}")
    
    if not args.worker_environment:
        worker_env_path = backpack_dir / "software" / "worker-environment.yml"
        if worker_env_path.is_file():
            args.worker_environment = str(worker_env_path)
            print(f"Using worker environment from backpack: {args.worker_environment}")
    
    if not args.notebook and not args.python_script:
        workflow_dir = backpack_dir / "workflow"
        notebooks = list(workflow_dir.glob("*.ipynb"))
        python_scripts = list(workflow_dir.glob("*.py"))
        
        if python_scripts:
            if len(python_scripts) == 1:
                args.python_script = str(python_scripts[0])
                print(f"Using Python script from backpack: {args.python_script}")
            elif len(python_scripts) > 1:
                for script in python_scripts:
                    if script.stem == backpack_dir.stem:
                        args.python_script = str(script)
                        print(
                            f"Using Python script from backpack: {args.python_script}"
                        )
                        break
                if not args.python_script:
                    args.python_script = str(python_scripts[0])
                    print(f"Using Python script from backpack: {args.python_script}")
        
        elif notebooks:
            if len(notebooks) == 1:
                args.notebook = str(notebooks[0])
                print(f"Using notebook from backpack: {args.notebook}")
            elif len(notebooks) > 1:
                for notebook in notebooks:
                    if notebook.stem == backpack_dir.stem:
                        args.notebook = str(notebook)
                        print(f"Using notebook from backpack: {args.notebook}")
                        break
            else:
                print(
                    f"No notebook found in backpack: {workflow_dir}. Starting JupyterLab without a notebook."
                )
    
    args.backpack_root = str(backpack_dir)


def run_workflow(
    args: argparse.Namespace, cleanup_manager: CleanupManager, mode="run"
) -> None:
    """
    Main execution path for the 'run' sub-command.
    Orchestrates data fetching, environment creation/extraction, starting
    workers and JupyterLab, and manages cleanup.
    """
    # Resolve backpack arguments to fill in any missing specs or paths
    resolve_backpack_args(args)
    
    # Determine if we're using sandbox mode
    run_in_place = getattr(args, "run_in_place", False)
    update_backpack = not getattr(args, "no_update_backpack", False)  # Default: True

    # Create a unique instance directory where all logs and outputs will be stored
    instance_root = create_unique_directory(base_dir=args.base_dir, prefix="floability_instance")
    run_dir = instance_root  # Keep run_dir for backward compatibility
    
    # Create structured subdirectories
    instance_paths = {
        "root": Path(instance_root),
        "workflow": Path(instance_root) / "workflow",
        "logs": Path(instance_root) / "logs",
        "metrics": Path(instance_root) / "metrics",
        "metadata": Path(instance_root) / "metadata",
    }
    
    for subdir in ["workflow", "logs", "metrics", "metadata"]:
        instance_paths[subdir].mkdir(parents=True, exist_ok=True)
    
    print(f"[floability] Created instance structure at: {os.path.abspath(instance_root)}")
    print(f"[floability]   workflow/ - execution sandbox")
    print(f"[floability]   logs/     - execution logs")
    print(f"[floability]   metrics/  - performance data")
    print(f"[floability]   metadata/ - run metadata")

    # Create a symlink to the latest instance directory
    latest_run_symlink = Path(args.base_dir) / "latest_floability_instance"
    if latest_run_symlink.is_symlink() or latest_run_symlink.exists():
        latest_run_symlink.unlink()
    latest_run_symlink.symlink_to(instance_root)
    print(
        f"[floability] Created symlink to latest instance: {os.path.abspath(latest_run_symlink)}"
    )

    # Initialize performance tracking (output to metrics/)
    perf_enabled = args.measure_performance
    perf = PerformanceTracker(output_dir=str(instance_paths["metrics"]), enabled=perf_enabled)
    perf.start_timer("total_run_time")
    
    # Generate manager name if not provided
    if args.manager_name is None:
        args.manager_name = f"floability-{uuid.uuid4()}"
    
    # Create instance metadata
    backpack_path = Path(args.backpack) if args.backpack else None
    metadata_file = instance_paths["metadata"] / "run.json"
    
    try:
        initial_metadata = create_instance_metadata(
            instance_dir=instance_paths["root"],
            backpack_path=backpack_path,
            cli_args=vars(args),
            manager_name=args.manager_name,
            execution_mode=mode,
            environment_spec=Path(args.environment) if args.environment else None,
            worker_environment_spec=Path(args.worker_environment) if args.worker_environment else None,
            data_spec=Path(args.data_spec) if args.data_spec else None,
        )
        update_instance_metadata(metadata_file, initial_metadata, merge=False)
        print(f"[floability] Recorded instance metadata: {metadata_file}")
    except Exception as e:
        print(f"[floability] Warning: Could not create metadata: {e}")
    
    # Set up workflow execution directory (sandbox or in-place)
    if run_in_place:
        print("[floability] Running in-place (directly in backpack directory)")
        workflow_dir = Path(args.backpack_root) if args.backpack_root else Path.cwd()
        original_notebook_path = args.notebook
        original_script_path = args.python_script
    else:
        print("[floability] Setting up isolated instance sandbox")
        workflow_dir = instance_paths["workflow"]
        print(f"[floability] Workflow directory: {workflow_dir}")
        
        # Copy notebook or script into workflow directory
        original_notebook_path = args.notebook
        original_script_path = args.python_script
        
        if args.notebook:
            notebook_src = Path(args.notebook).resolve()
            notebook_dest = workflow_dir / notebook_src.name
            shutil.copy2(notebook_src, notebook_dest)
            args.notebook = str(notebook_dest)
            print(f"[floability] Copied notebook: {notebook_src.name} -> {notebook_dest}")
        
        if args.python_script:
            script_src = Path(args.python_script).resolve()
            script_dest = workflow_dir / script_src.name
            shutil.copy2(script_src, script_dest)
            args.python_script = str(script_dest)
            print(f"[floability] Copied script: {script_src.name} -> {script_dest}")
    
    # Store workflow_dir for later use
    args.workflow_dir = str(workflow_dir)

    # If data_spec is provided, fetch data before proceeding
    # 1) Fetch data if data_spec is provided --> fetch data
    if args.data_spec:
        print(f"[floability] Performing data operation from {args.data_spec}")
        perf.start_timer("data_operation")
        from ..data.data_handler import execute_default_data_operation

        # Materialize data into workflow_dir (sandbox) or backpack_root (in-place)
        # Note: data_cache_mode and base_dir are passed regardless of run-in-place mode
        # This ensures caching works in both sandbox and in-place execution
        # 
        # In sandbox mode: pass instance root as backpack_root so data_handler adds "/workflow"
        # In run-in-place mode: pass actual backpack_root
        data_materialization_root = str(instance_paths["root"]) if not run_in_place else args.backpack_root
        
        data_success = execute_default_data_operation(
            data_spec=args.data_spec,
            backpack_root=data_materialization_root,
            verbose=True,
            force=False,
            data_profile=getattr(args, "data_profile", None),
            data_cache_mode=getattr(args, "data_cache_mode", "off"),  # Cache works in both modes
            force_data_cache=getattr(args, "force_data_cache", False),
            base_dir=Path(args.base_dir),  # Centralized cache location
        )
        perf.end_timer("data_operation", "Time to perform data operation")
        
        # Check if data operation succeeded
        if not data_success:
            print("\n[floability] ERROR: Data operation failed!")
            
            # Check if we should continue despite failure
            continue_on_failure = getattr(args, "continue_on_data_failure", False)
            if continue_on_failure:
                print("[floability] WARNING: Continuing workflow despite data failure (--continue-on-data-failure enabled)")
            else:
                print("[floability] Aborting workflow. Use --continue-on-data-failure to proceed anyway.")
                cleanup_manager.cleanup()
                return
        else:
            print("[floability] Data operation completed successfully")

    environment_pack = None
    worker_environment_pack = None
    env_dir = None

    backpack_name = None
    if args.backpack:
        backpack_name = Path(args.backpack).stem

    notebook_name = None
    if args.notebook:
        notebook_name = Path(args.notebook).name

    # Send startup event to catalog
    send_catalog_update(
        manager_name=args.manager_name,
        jupyter_port=args.jupyter_port,
        run_dir=run_dir,
        backpack_name=backpack_name,
        event="startup",
        notebook_name=notebook_name,
        mode=mode,
    )

    # 2) Create or extract conda environment for manager --> setup environment
    if args.environment:
        env_file_path = Path(args.environment)
        ext = Path(args.environment).suffix

        if ext in ["tar", "gz"]:
            environment_pack = str(env_file_path.resolve())
            print(f"[floability] Using conda-pack from '{args.environment}'")
        else:
            print(f"[floability] Creating conda-pack from '{args.environment}'")

            perf.start_timer("manager_env_creation")
            environment_pack = create_conda_pack_from_yml(
                env_yml=args.environment,
                solver="libmamba",
                force=False,
                base_dir=args.base_dir,
                run_dir=run_dir,
                manager_name=args.manager_name,
            )
            perf.end_timer(
                "manager_env_creation", "Time to create manager conda environment"
            )
            perf.measure_file_size(environment_pack, "environment_pack")

        # Extract conda environment to instance root (not inside workflow)
        # Use absolute path to avoid issues with working directory changes
        env_dir = os.path.abspath(os.path.join(str(instance_paths["root"]), "current_conda_env"))
        os.makedirs(env_dir, exist_ok=True)
        print(f"[floability] Conda environment directory: {env_dir}")

        # 2a) Extract the environment
        try:
            perf.start_timer("extract_environment")
            safe_extract_tar(Path(environment_pack), Path(env_dir))
            perf.end_timer("extract_environment", "Time to extract conda environment")
            perf.measure_file_size(env_dir, "extracted_environment")
        except Exception as e:
            print(f"[floability] Error extracting environment: {e}")
            cleanup_manager.cleanup()
            return

        # 2b) Update the manager name in the environment
        update_env_vars_in_conda(
            env_dir, args.manager_name, args.manager_ports, args.env_vars
        )

        # 2c) Run conda-unpack.This fixes the path after extracting the environment
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
            print(f"[floability] Error running conda-unpack: {e}")
            cleanup_manager.cleanup()
            return

        cleanup_manager.register_directory(env_dir)

    else:
        print("[floability] No environment file provided, skipping conda-pack.")

    # 2d) Create or extract conda environment for workers --> setup worker environment
    if args.worker_environment:
        worker_env_file_path = Path(args.worker_environment)
        ext = Path(args.worker_environment).suffix
        if ext in ["tar", "gz"]:
            worker_environment_pack = str(worker_env_file_path.resolve())
            print(f"[floability] Using conda-pack from '{args.worker_environment}'")
        else:
            print(f"[floability] Creating conda-pack from '{args.worker_environment}'")
            perf.start_timer("worker_env_creation")
            worker_environment_pack = create_conda_pack_from_yml(
                env_yml=args.worker_environment,
                solver="libmamba",
                force=False,
                base_dir=args.base_dir,
                run_dir=run_dir,
                is_worker_env=True,
            )
            perf.end_timer(
                "worker_env_creation", "Time to create worker conda environment"
            )
            perf.measure_file_size(worker_environment_pack, "worker_environment_pack")
    else:
        worker_environment_pack = environment_pack
    if environment_pack != worker_environment_pack:
        print("[floability] Worker environment is different from main environment.")
        print(f"[floability] Worker environment pack: {worker_environment_pack}")

    # 3) Start vine_factory to provision workers --> start workers
    if not args.no_worker:
        print("[floability] Starting vine_factory...")
        factory_proc = start_vine_factory(
            batch_type=args.batch_type,
            manager_name=args.manager_name,
            min_workers=1,
            max_workers=args.workers,
            cores_per_worker=args.cores_per_worker,
            poncho_env=worker_environment_pack,
            run_dir=run_dir,
            scratch_dir=run_dir,
            batch_options=args.batch_options,
            config_yml=args.compute_spec,
            debug_workers=args.debug_workers,
        )
        cleanup_manager.register_subprocess(factory_proc)
    else:
        factory_proc = None
        print("[floability] vine_factory is disabled by --no-worker.")

    # 4) Start JupyterLab or execute notebook/script --> start Jupyter or execute
    # When using working_dir, convert paths to be relative to that directory
    notebook_path_for_exec = args.notebook
    script_path_for_exec = args.python_script
    
    if not run_in_place and args.notebook:
        # In sandbox mode, use just the filename since we're in the workflow directory
        notebook_path_for_exec = Path(args.notebook).name
    
    if not run_in_place and args.python_script:
        # In sandbox mode, use just the filename since we're in the workflow directory
        script_path_for_exec = Path(args.python_script).name
    
    if mode == "run":
        # Always start Jupyter, even if --notebook not provided
        # We'll pass None for the notebook_path if not given.
        print("[floability] Starting JupyterLab...")
        jupyter_proc = start_jupyterlab(
            notebook_path=notebook_path_for_exec,
            port=args.jupyter_port,
            run_dir=str(instance_paths["logs"]),
            conda_env_dir=env_dir,
            working_dir=str(workflow_dir),
        )
        cleanup_manager.register_subprocess(jupyter_proc)

    elif mode == "execute":
        execution_success = False
        
        if args.prefer_python and args.python_script:
            execute_python_script(
                script_path=script_path_for_exec,
                run_dir=str(instance_paths["logs"]),
                conda_env_dir=env_dir,
                working_dir=str(workflow_dir),
            )
            execution_success = True  # Python script execution doesn't return status
        elif args.notebook:
            perf.start_timer("notebook_execute_time")
            execution_success = execute_notebook(
                notebook_path=notebook_path_for_exec,
                run_dir=str(instance_paths["logs"]),
                conda_env_dir=env_dir,
                working_dir=str(workflow_dir),
            )
            perf.end_timer(
                "notebook_execute_time", "Time to execute notebook in execute mode"
            )
        
        # Sync outputs back to backpack if execution succeeded and not in run-in-place mode
        if execution_success and not run_in_place and update_backpack and args.backpack:
            backpack_workflow_dir = Path(args.backpack) / "workflow"
            sync_outputs_to_backpack(
                workflow_dir,
                backpack_workflow_dir,
                metadata_dir=instance_paths["metadata"],
                verbose=True
            )
        
        cleanup_manager.cleanup()

    # Main loop to monitor subprocesses
    try:
        while True:
            time.sleep(5)

            # Check if factory exited
            if factory_proc is not None and factory_proc.poll() is not None:
                print("[floability] vine_factory ended.")
                break

            # Check if jupyter ended
            if jupyter_proc is not None and jupyter_proc.poll() is not None:
                print("[floability] JupyterLab ended.")
    except KeyboardInterrupt:
        # The signal handler in cleanup.py typically handles this,
        # but if we get here, do a final fallback cleanup:
        print("[floability] KeyboardInterrupt in main loop. Cleaning up...")
        cleanup_manager.cleanup()
    finally:
        # Sync outputs back to backpack for run mode (after Jupyter closes)
        if mode == "run" and not run_in_place and update_backpack and args.backpack:
            backpack_workflow_dir = Path(args.backpack) / "workflow"
            sync_outputs_to_backpack(
                workflow_dir,
                backpack_workflow_dir,
                metadata_dir=instance_paths["metadata"],
                verbose=True
            )
        
        if perf_enabled:
            perf.end_timer("total_run_time", "Total run time")
            perf.save_report()
            print(
                f"[floability] Performance report saved to {instance_paths['metrics']}"
            )
        
        # Finalize metadata
        try:
            finalize_instance_metadata(metadata_file, success=True)
            print(f"[floability] Finalized instance metadata")
        except Exception as e:
            print(f"[floability] Warning: Could not finalize metadata: {e}")

    print("[floability] Exiting run.")


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
