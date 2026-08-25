"""
Tools command - utility tooling for Floability.
"""

import argparse
import os

from .base import BaseCommand


def _positive_jobs(value: str) -> int:
    jobs = int(value)
    if jobs < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return jobs


class ToolsCommand(BaseCommand):
    """Utility tools for managing Floability cache and resources."""

    @property
    def name(self) -> str:
        return "tools"

    @property
    def help(self) -> str:
        return "Utility tools for managing Floability cache and resources."

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add tools command arguments."""
        tools_subparsers = parser.add_subparsers(
            dest="tools_subcommand", help="Tools sub-commands", required=True
        )

        # tools clean sub-command
        clean_parser = tools_subparsers.add_parser(
            "clean", help="Clean Floability cache directories and instance data"
        )
        base_group = clean_parser.add_mutually_exclusive_group()
        base_group.add_argument(
            "--base-dir",
            default=None,
            help=(
                "Clean this exact Floability base directory (default: the most "
                "recently used existing base found in the registry)."
            ),
        )
        base_group.add_argument(
            "--all-registered-bases",
            action="store_true",
            help=(
                "Clean all existing base directories currently recorded in "
                "Floability's recent-base registry."
            ),
        )
        clean_parser.add_argument(
            "--data-cache-dir",
            default=None,
            help=(
                "Path to data cache directory "
                "(overrides default <base-dir>/floability-data-cache)."
            ),
        )

        scope_group = clean_parser.add_mutually_exclusive_group()
        scope_group.add_argument(
            "--data-only",
            action="store_true",
            help="Clean only unreferenced data-cache entries.",
        )
        scope_group.add_argument(
            "--env-only",
            action="store_true",
            help="Clean only unreferenced environment directories and archives.",
        )
        scope_group.add_argument(
            "--data-and-env",
            action="store_true",
            help=(
                "Clean unreferenced data and environment entries."
            ),
        )
        scope_group.add_argument(
            "--instances-only",
            action="store_true",
            help="Remove inactive instance directories but leave caches unchanged.",
        )
        scope_group.add_argument(
            "--all",
            action="store_true",
            help="Remove all inactive instances and their unreferenced cache entries.",
        )
        scope_group.add_argument(
            "--keep-last",
            action="store_true",
            help=(
                "Clean everything except the most recently run instance and its "
                "dependencies according to the run registry."
            ),
        )

        clean_parser.add_argument(
            "--yes",
            "-y",
            action="store_true",
            help="Skip confirmation prompt.",
        )
        clean_parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print the cleanup plan without changing files.",
        )
        default_jobs = min(os.cpu_count() or 1, 4)
        clean_parser.add_argument(
            "--jobs",
            type=_positive_jobs,
            default=default_jobs,
            help=(
                "Parallel file-deletion jobs (default: min(CPU count, 4); "
                "use 1 for serial deletion)."
            ),
        )
        clean_parser.add_argument(
            "--parallel",
            action="store_true",
            help=argparse.SUPPRESS,
        )

    def execute(self, args: argparse.Namespace, cleanup_manager=None) -> int:
        """Execute tools command."""
        from ..ops.tools import run_tools_command

        return run_tools_command(args)

    def get_examples(self) -> list:
        return [
            "floability tools clean",
            "floability tools clean --env-only",
            "floability tools clean --data-only --base-dir /scratch/myuser",
            "floability tools clean --dry-run",
            "floability tools clean --instances-only",
            "floability tools clean --all --yes",
            "floability tools clean --keep-last --yes",
        ]
