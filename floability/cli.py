#!/usr/bin/env python3
"""
Floability CLI: main entry point for running distributed Jupyter-based workflows.
"""

import argparse
import time
import os
import subprocess
import uuid
from pathlib import Path

from .environment import create_conda_pack_from_yml
from .resource_provisioner import start_vine_factory
from .cleanup import CleanupManager, install_signal_handlers
from .jupyter_runner import start_jupyterlab, execute_notebook
from .utils import create_unique_directory, safe_extract_tar, update_manager_name_in_env
from .data_handler import ensure_data_is_fetched
from .performance_tracker import PerformanceTracker


def get_parsed_arguments() -> argparse.Namespace:
    """
    Parse command-line arguments for the Floability CLI.
    """

    parser = argparse.ArgumentParser(
        description="Floability CLI: run distributed Jupyter-based workflows with TaskVine."
    )

    subparsers = parser.add_subparsers(dest="command", help="Floability sub-commands")

    # run sub-command
    run_parser = subparsers.add_parser(
        "run", help="Run a notebook or Floability backpack"
    )
    _add_execution_args(run_parser)

    # execute sub-command
    execute_parser = subparsers.add_parser(
        "execute", help="Execute a notebook in a Floability backpack"
    )
    _add_execution_args(execute_parser)

    # fetch sub-command
    fetch_parser = subparsers.add_parser(
        "fetch", help="Fetch data from a data.yml spec"
    )
    fetch_parser.add_argument(
        "--data-spec",
        help="Path to data.yml file specifying data to be fetched.",
        required=True,
    )
    fetch_parser.add_argument(
        "--backpack-root",
        default=".",
        help="Path to the root of the backpack for 'backpack' source_type files (default='.')",
    )

    # pack sub-command
    pack_parser = subparsers.add_parser(
        "pack", help="Package a notebook into a Floability backpack"
    )

    # verify sub-command
    verify_parser = subparsers.add_parser("verify", help="Verify a Floability backpack")

    return parser.parse_args()


def _add_execution_args(parser: argparse.ArgumentError) -> None:
    parser.add_argument(
        "--backpack",
        required=False,
        help="Path to the Floability backpack directory (optional).",
    )
    parser.add_argument(
        "--environment",
        help="Path to environment.yml or environment.tar.gz (optional).",
    )
    
    parser.add_argument(
        "--worker-environment",
        help="Path to worker-environment.yml or worker-environment.tar.gz (optional).",
    )
    
    parser.add_argument("--notebook", help="Path to a .ipynb file (optional).")
    parser.add_argument(
        "--batch-type",
        default="local",
        choices=["local", "condor", "uge", "slurm"],
        help="Batch system for vine_factory (default=local).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=5,
        help="Maximum number of workers for vine_factory (default=5).",
    )
    parser.add_argument(
        "--cores-per-worker",
        type=int,
        default=1,
        help="Cores requested per worker (default=1).",
    )
    parser.add_argument(
        "--manager-name", help="TaskVine manager name. Used for factory"
    )
    parser.add_argument(
        "--jupyter-port",
        type=int,
        default=8888,
        help="Port on which JupyterLab will listen (default=8888).",
    )
    parser.add_argument(
        "--base-dir",
        default="/tmp",
        help="Base directory for floability run directory files (default=/tmp).",
    )
    parser.add_argument(
        "--data-spec",
        help="Path to data.yml file specifying data to be fetched.",
    )
    parser.add_argument(
        "--backpack-root",
        default=".",
        help="Path to the root of the backpack (default='.').",
    )
    parser.add_argument(
        "--compute-spec",
        help="Path to compute.yml file specifying resource requirements.",
    )
    parser.add_argument(
        "--no-worker",
        action="store_true",
        help="Skip starting workers (optional).",
    )
    
    parser.add_argument(
        "--prefer-python",
        action="store_true",
        help="Prefer Python script over notebook when both are available.",
    )
    parser.add_argument(
        "--python-script", 
        help="Path to a Python (.py) file to execute (optional).",
    )
    
    parser.add_argument(
        "--measure-performance",
        action="store_true",
        help="Enable performance measurements and generate a report.",
    )


def resolve_backpack_args(args: argparse.Namespace) -> None:
    """
    Resolve the backpack arguments for the 'run' sub-command.
    """

    if not args.backpack:
        return

    backpack_dir = Path(args.backpack).resolve()
    backpack_name = str(backpack_dir.stem)

    print(f"Started processing backpack: {backpack_name}")

    if not backpack_dir.is_dir():
        print(
            f"Backpack directory not found: {backpack_dir}"
        )  # Todo: decide if we should raise an exception
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
        # todo: add support for environment.tar.gz and other formats
        # todo: add support for other names

        if env_path.is_file():
            args.environment = str(env_path)
            print(f"Using environment from backpack: {args.environment}")
    
    if not args.worker_environment:
        worker_env_path = backpack_dir / "software" / "worker-environment.yml"
        # todo: add support for environment.tar.gz and other formats
        # todo: add support for other names
        
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
                # Try to find script with same name as backpack
                for script in python_scripts:
                    if script.stem == backpack_dir.stem:
                        args.python_script = str(script)
                        print(f"Using Python script from backpack: {args.python_script}")
                        break
                # If no matching name found, use first script
                if not args.python_script:
                    args.python_script = str(python_scripts[0])
                    print(f"Using Python script from backpack: {args.python_script}")
        
        elif notebooks:
            if len(notebooks) == 1:
                args.notebook = str(notebooks[0])
                print(f"Using notebook from backpack: {args.notebook}")
            elif len(notebooks) > 1:  # take that has the same name as the backpack
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


def run_floability(
    args: argparse.Namespace, cleanup_manager: CleanupManager, mode="run"
) -> None:
    """
    Main execution path for the 'run' sub-command.
    Orchestrates data fetching, environment creation/extraction, starting
    workers and JupyterLab, and manages cleanup.
    """
    resolve_backpack_args(args)    
    
    run_dir = create_unique_directory(base_dir=args.base_dir, prefix="floability_run")

    perf_enabled = args.measure_performance
    perf = PerformanceTracker(output_dir=run_dir, enabled=perf_enabled)
    
    perf.start_timer("total_run_time")

    print(
        f"[floability] Floability run directory: {run_dir}. All logs will be stored here."
    )

    # 1) Fetch data if data_spec is provided
    if args.data_spec:
        print(f"[floability] Fetching data from {args.data_spec}")
        perf.start_timer("data_fetch")
        ensure_data_is_fetched(args.data_spec, args.backpack_root)
        perf.end_timer("data_fetch", "Time to fetch data from spec")

    # Generate a unique manager name if none is provided
    if args.manager_name is None:
        args.manager_name = f"floability-{uuid.uuid4()}"

    print(f"[floability] Manager name: {args.manager_name}")

    environment_pack = None
    worker_environment_pack = None
    env_dir = None

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
            perf.end_timer("manager_env_creation", "Time to create manager conda environment")
            perf.measure_file_size(environment_pack, "environment_pack")


        env_dir = os.path.join(run_dir, "current_conda_env")
        os.makedirs(env_dir, exist_ok=True)

        # 2a) Extract the environment
        try:
            perf.start_timer("extract_environment")
            safe_extract_tar(Path(environment_pack), Path(env_dir))
            perf.end_timer("extract_environment", "Time to extract conda environment")
            perf.measure_file_size(env_dir, "extracted_environment")
        except Exception as e:
            print(f"[floability] Error extracting environment: {e}")
            # perf.record_metric("errors", "environment_extraction", str(e))
            cleanup_manager.cleanup()
            return

        # 2b) Update the manager name in the environment
        update_manager_name_in_env(env_dir, args.manager_name)

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
            perf.end_timer("worker_env_creation", "Time to create worker conda environment")
            perf.measure_file_size(worker_environment_pack, "worker_environment_pack")
    else:
        worker_environment_pack = environment_pack
        
    if environment_pack != worker_environment_pack:
        print("[floability] Worker environment is different from main environment.")
        print(f"[floability] Worker environment pack: {worker_environment_pack}")

    # 3) Start vine_factory
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
            config_yml=args.compute_spec,
        )
        cleanup_manager.register_subprocess(factory_proc)
    else:
        factory_proc = None
        print("[floability] vine_factory is disabled by --no-worker.")

    if mode == "run":
        # 4) Always start Jupyter, even if --notebook not provided
        #    We'll pass None for the notebook_path if not given.
        print("[floability] Starting JupyterLab...")
        jupyter_proc = start_jupyterlab(
            notebook_path=args.notebook,  # None if no notebook is specified
            port=args.jupyter_port,
            run_dir=run_dir,
            conda_env_dir=env_dir,
        )
        cleanup_manager.register_subprocess(jupyter_proc)
    elif mode == "execute":
        if args.prefer_python and args.python_script:
            execute_python_script(
                script_path=args.python_script, run_dir=run_dir, conda_env_dir=env_dir,
            )
        elif args.notebook:
            perf.start_timer("notebook_execute_time")
            execute_notebook(
                notebook_path=args.notebook, run_dir=run_dir, conda_env_dir=env_dir,
            )
            perf.end_timer("notebook_execute_time", "Time to execute notebook in execute mode")
        cleanup_manager.cleanup()

    # 4) Main loop
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
                # Optionally break if you want the entire system to stop
                # break
    except KeyboardInterrupt:
        # The signal handler in cleanup.py typically handles this,
        # but if we get here, do a final fallback cleanup:
        print("[floability] KeyboardInterrupt in main loop. Cleaning up...")
        cleanup_manager.cleanup()
    finally:
        if perf_enabled:
            perf.end_timer("total_run_time", "Total run time")
            perf.save_report()
            print(f"[floability] Performance report saved to {run_dir}")

    print("[floability] Exiting main.")

def execute_python_script(
    script_path: str, run_dir: str, conda_env_dir: str = None
) -> None:
    """
    Execute a Python script.
    
    Args:
        script_path: Path to the Python script to execute.
        run_dir: Directory for run-related files.
        conda_env_dir: Path to the conda environment directory, if any.
    """
    script_abs_path = os.path.abspath(script_path)
    script_dir = os.path.dirname(script_abs_path)
    script_name = os.path.basename(script_abs_path)
    
    print(f"[floability] Changing directory to: {script_dir}")

    print(f"[floability] Executing Python script: {script_name}")
    
    log_file = os.path.join(run_dir, "python_execution.log")
    
    print(f"[floability] Logging to: {log_file}")
    
    with open(log_file, "w") as log:
        original_dir = os.getcwd()
        
        try:
            # Change to the script's directory
            os.chdir(script_dir)
            log.write(f"[floability] Changed working directory to: {script_dir}\n")
            
            cmd = []
            if conda_env_dir:
                # If using a conda environment
                cmd = [
                    "conda", "run", 
                    "--prefix", conda_env_dir, 
                    "--no-capture-output",
                    "python", script_name  # Use just the filename since we're in the right directory
                ]
            else:
                # Using system Python
                cmd = ["python", script_name]  # Use just the filename
            
            cmd_str = " ".join(cmd)
            print(f"[floability] Running command: {cmd_str}")
            log.write(f"[floability] Running command: {cmd_str}\n")
            log.flush()
            
            result = subprocess.run(
                cmd,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
                text=True,
            )
            print(f"[floability] Python script execution completed with exit code {result.returncode}")
            print(f"[floability] Logs saved to {log_file}")
            
        except subprocess.CalledProcessError as e:
            print(f"[floability] Error executing Python script: {e}")
            print(f"[floability] Check logs at {log_file}")
        finally:
            # Restore the original working directory
            os.chdir(original_dir)

def main():
    """
    Primary entry point for Floability CLI.
    """

    args = get_parsed_arguments()
    cleanup_manager = CleanupManager()
    install_signal_handlers(cleanup_manager)

    if args.command == "run":
        run_floability(args, cleanup_manager)

    elif args.command == "execute":
        run_floability(args, cleanup_manager, mode="execute")

    elif args.command == "fetch":
        if not args.data_spec:
            print(
                "[floability] No data spec provided. Use --data-spec path/to/data.yml."
            )
            return
        ensure_data_is_fetched(args.data_spec, args.backpack_root)
    elif args.command == "pack":
        print("[floability] 'pack' command not yet implemented.")
    elif args.command == "verify":
        print("[floability] 'verify' command not yet implemented.")
    else:
        print("[floability] No command provided. Exiting.")
