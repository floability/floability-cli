"""
Shared argument groups for Floability commands.

These functions add commonly-used argument groups to parsers.
"""

import argparse


def add_execution_args(parser: argparse.ArgumentParser) -> None:
    """
    Add execution-related arguments (used by run/execute commands).
    
    Args:
        parser: ArgumentParser to add arguments to
    """
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
        default=None,
        help="Base directory for floability run directory files (default: create ~/floability-base-dir if omitted).",
    )
    parser.add_argument(
        "--instance-prefix",
        default=None,
        help="Optional prefix to append to instance directory name (e.g., 'experiment1' creates floability_instance_experiment1_<timestamp>).",
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
        "--data-cache-dir",
        default=None,
        help="Path to data cache directory (overrides default <base-dir>/floability-data-cache).",
    )

    parser.add_argument(
        "--force-data-cache",
        action="store_true",
        help="Force rebuild of cache entries even if they already exist.",
    )

    parser.add_argument(
        "--fingerprint-mode",
        default="meta",
        choices=["meta", "sample", "strict"],
        help="Fingerprint mode for filesystem source validation: meta (fast, metadata only), sample (first N bytes), strict (full content hash).",
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
