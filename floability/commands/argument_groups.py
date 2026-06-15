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
        help="Path to environment.yml. Required for new instances unless auto-resolved from backpack's software/environment.yml.",
    )
    parser.add_argument(
        "--worker-environment",
        help="Path to worker-environment.yml (optional).",
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
        help="Optional prefix for the instance directory name (always starts with 'fi_'; e.g., 'experiment1' creates fi_experiment1_<timestamp>).",
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
        "--entry-file",
        default=None,
        metavar="FILENAME",
        help=(
            "Filename of the workflow entrypoint inside the backpack's workflow/ directory "
            "(e.g. 'my_script.py' or 'my_notebook.ipynb'). "
            "Takes precedence over --prefer-python and --notebook. "
            "Provide only the filename, not the full path."
        ),
    )
    parser.add_argument(
        "--prefer-python",
        action="store_true",
        help=(
            "Prefer a Python script (.py) over a notebook (.ipynb) when both exist in "
            "the workflow/ directory. Has no effect when --entry-file is provided."
        ),
    )
    parser.add_argument(
        "--python-script",
        help="Path to a Python (.py) file to execute (optional). Legacy; prefer --entry-file.",
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
    
    parser.add_argument(
        "--per-instance-env",
        action="store_true",
        help="Use a separate conda environment for each instance (default: use shared environment).",
    )

    # vine_factory specific arguments
    vf_group = parser.add_argument_group(
        "vine_factory",
        "Options for starting the vine_factory",
    )

    vf_group.add_argument(
        "--batch-type",
        default=None,
        choices=["local", "condor", "uge", "slurm"],
        help="Batch system for vine_factory. If omitted, vine_factory uses 'local'.",
    )

    vf_group.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Maximum number of workers for vine_factory. If omitted, vine_factory uses 5.",
    )

    vf_group.add_argument(
        "--cores-per-worker",
        type=int,
        default=None,
        help="Cores requested per worker. If omitted, vine_factory uses 1.",
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
    
    vf_group.add_argument(
        "--worker-transfer-ports",
        required=False,
        help="Port range for worker-worker transfers (e.g. 10000:11000). Passed as --transfer-port to vine_factory",
    )

