"""
Instance command - instance management (create, list, stop).
"""

import argparse
from .base import BaseCommand


class InstanceCommand(BaseCommand):
    """Instance management commands (create, list, status, etc.)."""

    @property
    def name(self) -> str:
        return "instance"

    @property
    def help(self) -> str:
        return "Instance management commands (create, list, status, etc.)."

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add instance command arguments."""
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
            default=None,
            help="Base directory for floability instance files (default: create ~/floability-base-dir if omitted).",
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
            "--fingerprint-mode",
            default="meta",
            choices=["meta", "sample", "strict"],
            help="Fingerprint mode for filesystem source validation: meta (fast, metadata only), sample (first N bytes), strict (full content hash).",
        )
        create_parser.add_argument(
            "--environment",
            help="Path to environment.yml (optional).",
        )
        create_parser.add_argument(
            "--worker-environment",
            help="Path to worker-environment.yml (optional).",
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

        # instance stop sub-command
        stop_parser = instance_subparsers.add_parser(
            "stop", help="Stop a running Floability instance (Jupyter/manager/workers)"
        )
        stop_parser.add_argument(
            "instance",
            help="Instance short name or path to the instance directory.",
        )

        # instance latest sub-command
        latest_parser = instance_subparsers.add_parser(
            "latest",
            help="Print the path of the latest instance (use with: cd $(floability instance latest))",
        )
        latest_parser.add_argument(
            "--base-dir",
            default=None,
            help="Base directory to look for the latest symlink (default: ~/floability-base-dir).",
        )

    def execute(self, args: argparse.Namespace, cleanup_manager=None) -> None:
        """Execute instance command."""
        from floability.sites import apply_site_defaults
        from ..ops.instance import run_instance_command

        apply_site_defaults(args, explicit_args=getattr(args, "_explicit_args", None))
        run_instance_command(args)

    def get_examples(self) -> list:
        return [
            "floability instance create --backpack example/matrix-multiplication",
            "floability instance list --all-details",
            "floability instance stop my-instance",
            "floability instance latest",
            "cd $(floability instance latest)",
        ]
