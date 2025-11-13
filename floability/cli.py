#!/usr/bin/env python3
"""
Floability CLI: main entry point for running distributed Jupyter-based workflows.
"""

import argparse

from .cleanup import CleanupManager, install_signal_handlers

from .ops.run import run_workflow, execute_python_script
from .ops.data import run_data_command
from .ops.instance import run_instance_command
from .ops.workers import run_workers_command
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
        "run",
        help="Deploy and run a Floability workflow from a backpack in interactive mode.",
    )
    _add_execution_args(run_parser)

    # execute sub-command
    execute_parser = subparsers.add_parser(
        "execute", help="Execute a Floability workflow from a backpack in batch mode."
    )
    _add_execution_args(execute_parser)

    # instance sub-command
    instance_parser = subparsers.add_parser(
        "instance",
        help="Instance management commands (create, list, status, etc.)",
    )
    _add_instance_args(instance_parser)

    # workers sub-command
    workers_parser = subparsers.add_parser(
        "workers",
        help="Worker management commands (start, stop, status)",
    )
    _add_workers_args(workers_parser)

    # data sub-command
    data_parser = subparsers.add_parser(
        "data",
        help="Data operations via mode flag: download, check (metadata), verify (download + integrity)",
    )
    _add_data_args(data_parser)

    # audit sub-command
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
        "--instance",
        required=False,
        help="Path to an existing Floability instance directory (reuses its environment; mutually exclusive with --backpack).",
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
        default="symlink",
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
        "--prefer-instance",
        action="store_true",
        help="For a new backpack-based run, skip environment setup and reuse current local environment (advanced).",
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


def _add_instance_args(parser: argparse.ArgumentParser) -> None:
    """
    Add arguments for the 'instance' sub-command.
    Supports: create
    """
    instance_subparsers = parser.add_subparsers(
        dest="instance_subcommand", help="Instance sub-commands"
    )

    # instance create sub-command
    create_parser = instance_subparsers.add_parser(
        "create", help="Create a Floability instance from a backpack"
    )
    create_parser.add_argument(
        "--backpack",
        required=True,
        help="Path to the Floability backpack directory (required).",
    )
    create_parser.add_argument(
        "--name",
        required=False,
        help="Optional short name to register for this instance (auto-generated if omitted).",
    )
    create_parser.add_argument(
        "--base-dir",
        default=".",
        help="Base directory for floability instance files (default='.').",
    )
    create_parser.add_argument(
        "--skip-data",
        action="store_true",
        help="Skip data fetch operation during instance creation.",
    )
    create_parser.add_argument(
        "--data-profile",
        help="Override the profile name in the data spec.",
    )
    create_parser.add_argument(
        "--data-cache-mode",
        default="off",
        choices=["off", "symlink", "hardlink", "copy"],
        help="Data caching mode (default: off).",
    )
    create_parser.add_argument(
        "--force-data-cache",
        action="store_true",
        help="Force rebuild of cache entries.",
    )
    create_parser.add_argument(
        "--environment",
        help="Path to environment.yml or environment.tar.gz (optional).",
    )
    create_parser.add_argument(
        "--worker-environment",
        help="Path to worker-environment.yml or worker-environment.tar.gz (optional).",
    )
    create_parser.add_argument(
        "--manager-name",
        help="TaskVine manager name (auto-generated if not provided).",
    )
    create_parser.add_argument(
        "--manager-ports",
        default="9123,9150",
        help="Comma-separated range for ports (default=9123,9150).",
    )
    create_parser.add_argument(
        "--env-vars",
        help="Comma-separated list of KEY=VALUE pairs to set in conda environment.",
    )
    create_parser.add_argument(
        "--measure-performance",
        action="store_true",
        help="Enable performance measurements.",
    )
    # These will be auto-resolved from backpack
    create_parser.add_argument("--notebook", help=argparse.SUPPRESS)
    create_parser.add_argument("--python-script", help=argparse.SUPPRESS)
    create_parser.add_argument("--data-spec", help=argparse.SUPPRESS)
    create_parser.add_argument("--compute-spec", help=argparse.SUPPRESS)

    # instance list sub-command
    list_parser = instance_subparsers.add_parser(
        "list", help="List registered Floability instances and their status"
    )
    list_parser.add_argument(
        "--show-paths",
        action="store_true",
        help="Include full paths (default shows short name and running state).",
    )
    list_parser.add_argument(
        "--all-details",
        action="store_true",
        help="Show extended metadata (created_at, last_seen, manager_name, tags).",
    )

    return None


def _add_workers_args(parser: argparse.ArgumentParser) -> None:
    """
    Add arguments for the 'workers' sub-command.
    Supports: start, stop, status
    """
    workers_subparsers = parser.add_subparsers(
        dest="workers_subcommand", help="Workers sub-commands"
    )

    # workers start sub-command
    start_parser = workers_subparsers.add_parser(
        "start", help="Start workers for a Floability instance"
    )
    start_parser.add_argument(
        "--instance",
        required=True,
        help="Path to the Floability instance directory (required).",
    )
    start_parser.add_argument(
        "--batch-type",
        choices=["local", "condor", "uge", "slurm"],
        help="Batch system for workers (overrides instance config).",
    )
    start_parser.add_argument(
        "--workers",
        type=int,
        help="Maximum number of workers (overrides instance config).",
    )
    start_parser.add_argument(
        "--cores-per-worker",
        type=int,
        help="Cores per worker (overrides instance config).",
    )
    start_parser.add_argument(
        "--batch-options",
        help="Batch system options (overrides instance config).",
    )
    start_parser.add_argument(
        "--compute-spec",
        help="Path to compute.yml (overrides instance config).",
    )
    start_parser.add_argument(
        "--debug-workers",
        action="store_true",
        help="Enable debug mode for workers.",
    )

    # workers stop sub-command
    stop_parser = workers_subparsers.add_parser(
        "stop", help="Stop workers for a Floability instance"
    )
    stop_parser.add_argument(
        "--instance",
        required=True,
        help="Path to the Floability instance directory (required).",
    )

    # workers status sub-command
    status_parser = workers_subparsers.add_parser(
        "status", help="Show worker status for a Floability instance"
    )
    status_parser.add_argument(
        "--instance",
        required=True,
        help="Path to the Floability instance directory (required).",
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

    elif args.command == "instance":
        run_instance_command(args)

    elif args.command == "workers":
        run_workers_command(args)

    elif args.command == "audit":
        run_audit_command(args)

    else:
        print("[floability] No command provided. Exiting.")
