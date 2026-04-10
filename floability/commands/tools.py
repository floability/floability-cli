"""
Tools command - utility tooling for Floability.
"""

import argparse
from .base import BaseCommand


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
            dest="tools_subcommand", help="Tools sub-commands"
        )

        # tools clean sub-command
        clean_parser = tools_subparsers.add_parser(
            "clean", help="Clean Floability cache directories and instance data"
        )
        clean_parser.add_argument(
            "--base-dir",
            default=None,
            help="Base directory for Floability files (default: ~/floability-base-dir).",
        )
        clean_parser.add_argument(
            "--data-cache-dir",
            default=None,
            help="Path to data cache directory (overrides default <base-dir>/floability-data-cache).",
        )

        scope_group = clean_parser.add_mutually_exclusive_group()
        scope_group.add_argument(
            "--data-only",
            action="store_true",
            help="Clean only the data cache.",
        )
        scope_group.add_argument(
            "--env-only",
            action="store_true",
            help="Clean only the conda environment cache (extracted envs + tarballs).",
        )
        scope_group.add_argument(
            "--data-and-env",
            action="store_true",
            help="Clean both data and environment cache (default when no scope is specified).",
        )
        scope_group.add_argument(
            "--instances-only",
            action="store_true",
            help="Clean only instance directories.",
        )
        scope_group.add_argument(
            "--all",
            action="store_true",
            help="Clean everything: data cache, env cache, and instance directories.",
        )
        scope_group.add_argument(
            "--keep-last",
            action="store_true",
            help=(
                "Clean everything except the latest instance and its dependencies "
                "(env cache entries and data cache dirs it used)."
            ),
        )

        clean_parser.add_argument(
            "--yes",
            "-y",
            action="store_true",
            help="Skip confirmation prompt.",
        )
        clean_parser.add_argument(
            "--parallel",
            action="store_true",
            help=(
                "Use parallel file deletion via find+xargs (faster for large conda envs). "
                "Requires find, xargs, rm on PATH. Default: Python rmtree."
            ),
        )

    def execute(self, args: argparse.Namespace, cleanup_manager=None) -> None:
        """Execute tools command."""
        from ..ops.tools import run_tools_command

        run_tools_command(args)

    def get_examples(self) -> list:
        return [
            "floability tools clean",
            "floability tools clean --env-only",
            "floability tools clean --data-only --base-dir /scratch/myuser",
            "floability tools clean --instances-only",
            "floability tools clean --all --yes",
            "floability tools clean --keep-last --yes",
        ]
