#!/usr/bin/env python3
"""
floability-cli.py - Main entry point for Floability.

Example usage:
  python floability-cli.py \
      --environment environment.yml \
      --notebook my_notebook.ipynb \
      --batch-type condor \
      --workers 10 \
      --cores-per-worker 4 \
      --jupyter-port 9999
"""

import argparse
import time
import tarfile
import os
import subprocess
import uuid

from environment import create_conda_pack_from_yml
from resource_provisioner import start_vine_factory
from cleanup import CleanupManager, install_signal_handlers
from jupyter_runner import start_jupyterlab
from utils import create_unique_directory
from utils import get_system_information
from pathlib import Path

def update_manager_name_in_env(env_dir: str, manager_name: str):
    env_vars_dir = os.path.join(env_dir, "etc", "conda", "activate.d")
    os.makedirs(env_vars_dir, exist_ok=True)
    env_vars_file = os.path.join(env_vars_dir, "env_vars.sh")
    with open(env_vars_file, "a") as f:
        f.write(f"\nexport VINE_MANAGER_NAME={manager_name}\n")
    print(
        f"[environment] Updated environment variable VINE_MANAGER_NAME={manager_name} in {env_vars_file}"
    )


def get_parsed_arguments():
    parser = argparse.ArgumentParser(
        description="Floability CLI: run distributed Jupyter-based workflows with TaskVine."
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Floability sub-commands")
    
    run_parser = subparsers.add_parser("run", help="Run a notebook or Floability backpack")
    run_parser.add_argument(
        "--environment",
        help="Path to environment.yml or environment.tar.gz (optional).",
    )
    run_parser.add_argument("--notebook", help="Path to a .ipynb file (optional).")
    run_parser.add_argument(
        "--batch-type",
        default="local",
        choices=["local", "condor", "uge", "slurm"],
        help="Batch system for vine_factory (default=local).",
    )
    run_parser.add_argument(
        "--workers",
        type=int,
        default=5,
        help="Number of workers for vine_factory (default=5).",
    )
    run_parser.add_argument(
        "--cores-per-worker",
        type=int,
        default=1,
        help="Cores requested per worker (default=1).",
    )
    run_parser.add_argument(
        "--manager-name", help="TaskVine manager naem. Used for factory"
    )
    run_parser.add_argument(
        "--jupyter-port",
        type=int,
        default=8888,
        help="Port on which JupyterLab will listen (default=8888).",
    )

    run_parser.add_argument(
        "--base-dir",
        default="/tmp",
        help="Base directory for floability run directory files (default=/tmp).",
    )
    
    pack_parser = subparsers.add_parser("pack", help="Package a notebook into a Floability backpack")
    verify_parser = subparsers.add_parser("verify", help="Verify a Floability backpack")
     
    return parser.parse_args()


def run_floability(args, cleanup_manager):
    run_dir = create_unique_directory(base_dir=args.base_dir, prefix="floability_run")

    print(
        f"[floability] Floability run directory: {run_dir}. All logs will be stored here."
    )

    poncho_env = None
    env_dir = None
    
    if args.manager_name is None:
        args.manager_name = f"floability-{uuid.uuid4()}"

    print(f"[floability] Manager name: {args.manager_name}")

    if args.environment:
        ext = Path(args.environment).suffix
        
        if ext in ['tar', 'gz']:
            poncho_env = args.environment
        else:
            print(f"[floability] Creating conda-pack from '{args.environment}'")
            
            poncho_env = create_conda_pack_from_yml(
                env_yml=args.environment,
                solver="libmamba",
                force=False,
                base_dir=args.base_dir,
                run_dir=run_dir,
                manager_name=args.manager_name,
            )
        
        env_dir = os.path.join(run_dir, "current_conda_env")
        os.makedirs(env_dir, exist_ok=True)
        with tarfile.open(poncho_env, "r:gz") as tar:
            tar.extractall(path=env_dir)

        update_manager_name_in_env(env_dir, args.manager_name)
        cleanup_manager.register_directory(env_dir)

        # This fixes the path after extracting the environment
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

    else:
        print("[floability] No environment file provided, skipping conda-pack.")

    # 2) Start vine_factory
    factory_proc = start_vine_factory(
        batch_type=args.batch_type,
        manager_name=args.manager_name,
        min_workers=1,
        max_workers=args.workers,
        cores_per_worker=args.cores_per_worker,
        poncho_env=poncho_env,
        run_dir=run_dir,
        scratch_dir=run_dir,
    )
    cleanup_manager.register_subprocess(factory_proc)
    
    # 3) Always start Jupyter, even if --notebook not provided
    #    We'll pass None for the notebook_path if not given.
    jupyter_proc = start_jupyterlab(
        notebook_path=args.notebook,  # None if no notebook is specified
        port=args.jupyter_port,
        run_dir=run_dir,
        conda_env_dir=env_dir,
    )
    cleanup_manager.register_subprocess(jupyter_proc)
    
    # 4) Main loop
    try:
        while True:
            time.sleep(5)

            # Check if factory exited
            if factory_proc.poll() is not None:
                print("[floability] vine_factory ended.")
                break

            # Check if jupyter ended
            if jupyter_proc.poll() is not None:
                print("[floability] JupyterLab ended.")
                # Optionally break if you want the entire system to stop
                # break
    except KeyboardInterrupt:
        # The signal handler in cleanup.py typically handles this,
        # but if we get here, do a final fallback cleanup:
        print("[floability] KeyboardInterrupt in main loop. Cleaning up...")
        cleanup_manager.cleanup()

    print("[floability] Exiting main.")


def main():
    args = get_parsed_arguments()

    cleanup_manager = CleanupManager()
    install_signal_handlers(cleanup_manager)
    
    if args.command == "run":
        run_floability(args, cleanup_manager)
    elif args.command == "pack":
        print("[floability] 'pack' command not yet implemented.")
    elif args.command == "verify":
        print("[floability] 'verify' command not yet implemented.")
    else:
        print("[floability] No command provided. Exiting.")


if __name__ == "__main__":
    main()
