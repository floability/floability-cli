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
            choices=["taskvine-data", "taskvine"],
            help=(
                "Bootstrap from a template. 'taskvine-data' demonstrates local "
                "and HTTP inputs; 'taskvine' has no managed data"
            ),
        )
        mode_group.add_argument(
            "--from-workflow",
            "-w",
            help=(
                "Path to an existing notebook (.ipynb), Python script (.py), "
                "or shell script (.sh) to use as the workflow entrypoint"
            ),
        )

        init_parser.add_argument(
            "--script",
            action="store_true",
            default=False,
            help=(
                "Create a Python script (.py) workflow instead of a Jupyter notebook (.ipynb). "
                "Only applies when using --from-template. "
                "In execute mode the script's stdout/stderr are tee'd to both the terminal "
                "and logs/workflow.log inside the instance directory."
            ),
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
            help=(
                "Also parse the entrypoint and perform live checks of configured "
                "data sources"
            ),
        )

        # backpack update-env sub-command
        update_env_parser = backpack_subparsers.add_parser(
            "update-env",
            help=(
                "Update backpack environment.yml from an instance with a prepared "
                "conda environment"
            ),
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

    def execute(self, args: argparse.Namespace, cleanup_manager=None) -> int:
        """Execute backpack command."""
        from ..ops.backpack import run_backpack_command

        return run_backpack_command(args)

    def get_examples(self) -> list:
        return [
            "floability backpack init --name my-workflow --from-template taskvine-data",
            "floability backpack init --name my-workflow --from-template taskvine",
            "floability backpack init --name my-workflow --from-template taskvine-data --script",
            "floability backpack init --name my-workflow --from-template taskvine --script",
            "floability backpack init --name my-workflow --from-workflow ./my-notebook.ipynb",
            "floability backpack validate ./my-workflow",
            "floability backpack update-env --from-instance fi_20260410-104122_a1b2c3d4",
            "floability backpack update-env --from-instance /path/to/instance ./my-workflow",
            "floability backpack update-env --from-instance fi_20260410-104122_a1b2c3d4 --versions-only",
        ]
