"""
Backpack command - backpack initialization and validation.
"""

import argparse
from .base import BaseCommand


class BackpackCommand(BaseCommand):
    """Backpack management commands (init, validate)."""

    @property
    def name(self) -> str:
        return "backpack"

    @property
    def help(self) -> str:
        return "Backpack management commands (bootstrap new backpack or validate structure)"

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add backpack command arguments."""
        backpack_subparsers = parser.add_subparsers(
            dest="backpack_subcommand", help="Backpack sub-commands"
        )

        # backpack init sub-command
        init_parser = backpack_subparsers.add_parser(
            "init", help="Initialize a new Floability backpack"
        )
        init_parser.add_argument(
            "--name",
            required=True,
            help="Backpack name or path. If a path is given, the leaf directory becomes the backpack name.",
        )

        # Mutually exclusive group for mode selection
        mode_group = init_parser.add_mutually_exclusive_group(required=True)
        mode_group.add_argument(
            "--from-template",
            "-t",
            choices=["taskvine", "taskvine-data"],
            help="Bootstrap from a template. 'taskvine' (no data) or 'taskvine-data' (with data example)",
        )
        mode_group.add_argument(
            "--from-workflow",
            "-w",
            help="Path to existing notebook (.ipynb) or Python script (.py) to use as the workflow entrypoint",
        )

        init_parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite existing backpack directory if it exists",
        )

        # backpack validate sub-command
        validate_parser = backpack_subparsers.add_parser(
            "validate", help="Validate a Floability backpack structure"
        )
        validate_parser.add_argument(
            "path",
            nargs="?",
            default=".",
            help="Path to backpack directory (default: current directory)",
        )
        validate_parser.add_argument(
            "--strict",
            action="store_true",
            help="(Not yet implemented) Reserved for strict validation including run-readiness checks",
        )

        # backpack update-env sub-command
        update_env_parser = backpack_subparsers.add_parser(
            "update-env",
            help="Update backpack environment.yml from a completed instance's conda environment",
        )
        update_env_parser.add_argument(
            "--from-instance",
            required=True,
            metavar="PATH_OR_NAME",
            help="Instance directory path or registered short name to export the environment from",
        )
        update_env_parser.add_argument(
            "--versions-only",
            action="store_true",
            default=False,
            help=(
                "Only update versions of packages already listed in the backpack environment.yml "
                "rather than replacing the full dependency list"
            ),
        )
        update_env_parser.add_argument(
            "path",
            nargs="?",
            default=".",
            help="Path to backpack directory to update (default: current directory)",
        )

    def execute(self, args: argparse.Namespace, cleanup_manager=None) -> None:
        """Execute backpack command."""
        from ..ops.backpack import run_backpack_command

        run_backpack_command(args)

    def get_examples(self) -> list:
        return [
            "floability backpack init --name my-workflow --from-template taskvine",
            "floability backpack init --name my-workflow --from-template taskvine-data",
            "floability backpack init --name my-workflow --from-workflow ./my-notebook.ipynb",
            "floability backpack validate ./my-workflow",
            "floability backpack update-env --from-instance fi_20260410_104122_618078",
            "floability backpack update-env --from-instance /path/to/instance ./my-workflow",
            "floability backpack update-env --from-instance fi_20260410_104122_618078 --versions-only",
        ]
