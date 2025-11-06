#!/usr/bin/env python3
"""
Floability CLI: main entry point for running distributed Jupyter-based workflows.
"""

import argparse

from .cleanup import CleanupManager, install_signal_handlers

from .ops.run import run_workflow, execute_python_script
from .ops.data import run_data_command
from .ops.setup import run_setup_command, run_provision_command
from .ops.audit import run_audit_command, cell_level_audit

from . import __version__


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

    # data sub-command
    data_parser = subparsers.add_parser(
        "data",
        help="Data operations via mode flag: download, check (metadata), verify (download + integrity)",
    )
    _add_data_args(data_parser)

    # setup sub-command
    setup_parser = subparsers.add_parser(
        "setup",
        help="Set up a backpack (prepare environment, fetch data, etc.)",
    )
    _add_setup_args(setup_parser)

    # provision sub-command
    provision_parser = subparsers.add_parser(
        "provision",
        help="Provision worker(s) for a backpack (start in background)",
    )
    _add_provision_args(provision_parser)

    # floability-env sub-command
    audit_parser = subparsers.add_parser(
        "audit", help="Generate environment and data dependencies for a notebook"
    )
    _add_audit_args(audit_parser)

    parser.add_argument(
        "-v", "--version", action="version", version=f"%(prog)s {__version__}"
    )

    return parser.parse_args()


def _add_audit_args(parser: argparse.ArgumentParser) -> None:
    """
    Add arguments specific to the 'audit' sub-command.
    This command generates environment and data dependencies for a notebook.
    """
    parser.add_argument(
        "--notebook",
        required=True,
        help="Path to the Jupyter notebook for which to generate environment and data dependencies.",
    )
    parser.add_argument(
        "--kernel",
        required=False,
        default=None,
        help="Kernel to use when analyzing the notebook.",
    )
    parser.add_argument(
        "--manager-port",
        required=False,
        default="9123",
        help="Port on which the TaskVine manager will listen (default=9123).",
    )
    parser.add_argument(
        "--manager-name",
        required=False,
        default=None,
        help="Name of the TaskVine manager",
    )
    parser.add_argument(
        "--cell-level",
        action="store_true",
        help="Generate dependencies at the cell level instead of notebook level",
    )


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
        "--jupyter-port",
        type=int,
        default=8888,
        help="Port on which JupyterLab will listen (default=8888).",
    )

    parser.add_argument(
        "--manager-ports",
        required=False,
        default="9123,9150",
        help="Comma-separated range for ports for the TaskVine manager (default=9123,9150).",
    )

    parser.add_argument(
        "--base-dir",
        default=".",
        help="Base directory for floability run directory files (default=/tmp).",
    )
    parser.add_argument(
        "--data-spec",
        help="Path to data.yml file specifying data to be fetched.",
    )
    parser.add_argument(
        "--data-profile",
        help="Override the profile name in the data spec (useful to select a profile other than default).",
    )
    parser.add_argument(
        "--backpack-root",
        default=".",
        help="Path to the root of the backpack (default='.').",
    )
    
    parser.add_argument(
        "--continue-on-data-failure",
        action="store_true",
        help="Continue workflow execution even if data operations fail (default: abort on data failure).",
    )
    
    parser.add_argument(
        "--run-in-place",
        action="store_true",
        help="Run directly in the backpack directory instead of creating an isolated instance sandbox (default: False).",
    )
    
    parser.add_argument(
        "--no-update-backpack",
        action="store_true",
        help="Disable syncing outputs from instance back to backpack (default: sync enabled).",
    )
    
    parser.add_argument(
        "--data-cache-mode",
        default="off",
        choices=["off", "symlink", "hardlink", "copy"],
        help="Data caching mode: off (no cache), symlink (default, read-only), hardlink (shared inode), copy (independent copy).",
    )
    
    parser.add_argument(
        "--force-data-cache",
        action="store_true",
        help="Force rebuild of cache entries even if they already exist.",
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

    parser.add_argument(
        "--env-vars",
        required=False,
        help="Comma-separated list of KEY=VALUE pairs to set inside the conda environment.",
    )

    # vine_factory specific arguments
    vf_group = parser.add_argument_group(
        "vine_factory",
        "Options for starting the vine_factor",
    )

    vf_group.add_argument(
        "--batch-type",
        default="local",
        choices=["local", "condor", "uge", "slurm"],
        help="Batch system for vine_factory (default=local).",
    )

    vf_group.add_argument(
        "--workers",
        type=int,
        default=5,
        help="Maximum number of workers for vine_factory (default=5).",
    )

    vf_group.add_argument(
        "--cores-per-worker",
        type=int,
        default=1,
        help="Cores requested per worker (default=1).",
    )

    vf_group.add_argument(
        "--manager-name", help="TaskVine manager name. Used for factory"
    )

    vf_group.add_argument(
        "--batch-options",
        help="Generic batch system options. This will be passed to the factory as is.",
    )

    vf_group.add_argument(
        "--compute-spec",
        help="Path to compute.yml file specifying resource requirements. CLI args will override the options from this file.",
    )

    vf_group.add_argument(
        "--debug-workers",
        action="store_true",
        help="Enable debug mode for workers",
    )


def _add_data_args(data_parser: argparse.ArgumentParser) -> None:
    """
    Register the top-level `data` command with a --mode flag and related arguments.
    """
    data_parser.add_argument(
        "--mode",
        choices=["check", "fetch", "verify"],
        default="check",
        help="Mode to run (default='check')",
    )
    data_parser.add_argument(
        "--data-spec",
        help="Path to data.yml file specifying data to operate on.",
    )
    data_parser.add_argument(
        "--backpack",
        help="Path to the root of the backpack for 'backpack' source_type files (default '.')",
    )
    data_parser.add_argument(
        "--check-details",
        action="store_true",
        help="After summary, print detailed metadata for each item (check mode only).",
    )
    data_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging for data operations (fetch/check/verify).",
    )
    data_parser.add_argument(
        "--force-fetch",
        action="store_true",
        help="Re-fetch (overwrite) targets even if they already exist.",
    )
    data_parser.add_argument(
        "--data-profile",
        help="Override the profile name in the data spec (useful to select a profile other than default).",
    )
    data_parser.add_argument(
        "--data-cache-mode",
        default="off",
        choices=["off", "symlink", "hardlink", "copy"],
        help="Data caching mode: off (no cache), symlink (default, read-only), hardlink (shared inode), copy (independent copy).",
    )
    data_parser.add_argument(
        "--force-data-cache",
        action="store_true",
        help="Force rebuild of cache entries even if they already exist.",
    )
    data_parser.add_argument(
        "--base-dir",
        default=".",
        help="Base directory for floability cache storage (default='.').",
    )
    return None


def _add_setup_args(parser: argparse.ArgumentParser) -> None:
    """
    Add arguments for the 'setup' sub-command.
    Intention: set up everything for a backpack (env, data, etc.).
    For now, only CLI args are added.
    """
    parser.add_argument(
        "--backpack",
        required=True,
        help="Path to the Floability backpack directory (required).",
    )
    parser.add_argument(
        "--data-profile",
        required=False,
        help="Optional data profile to use when setting up data.",
    )
    return None


def _add_provision_args(parser: argparse.ArgumentParser) -> None:
    """
    Add arguments for the 'provision' sub-command.
    Intention: start worker(s) for a backpack in the background.
    For now, only CLI args are added.
    """
    parser.add_argument(
        "--backpack",
        required=True,
        help="Path to the Floability backpack directory (required).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=5,
        help="Number of workers to provision (default=5).",
    )
    return None


def main():
    """
    Primary entry point for Floability CLI.
    """

    args = get_parsed_arguments()
    cleanup_manager = CleanupManager()
    install_signal_handlers(cleanup_manager)

    if args.command == "run":
        run_workflow(args, cleanup_manager)

    elif args.command == "execute":
        run_workflow(args, cleanup_manager, mode="execute")

    elif args.command == "data":
        run_data_command(args)

    elif args.command == "setup":
        run_setup_command(args)

    elif args.command == "provision":
        run_provision_command(args)

    elif args.command == "audit":
        run_audit_command(args)

    else:
        print("[floability] No command provided. Exiting.")
