"""
Run command - deploy and run a workflow in interactive mode.
"""

import argparse
from .base import BaseCommand
from .argument_groups import add_execution_args


class RunCommand(BaseCommand):
    """Deploy and run a Floability workflow from a backpack in interactive mode."""

    @property
    def name(self) -> str:
        return "run"

    @property
    def help(self) -> str:
        return (
            "Deploy and run a Floability workflow from a backpack in interactive mode."
        )

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add run command arguments."""
        add_execution_args(parser)

    def execute(self, args: argparse.Namespace, cleanup_manager=None) -> None:
        """Execute run command."""
        from floability.sites import apply_site_defaults
        from ..ops.run import run_workflow

        apply_site_defaults(args, explicit_args=getattr(args, "_explicit_args", None))
        run_workflow(args, cleanup_manager)

    def get_examples(self) -> list:
        return [
            "floability run --backpack example/matrix-multiplication",
            "floability run --backpack mypack --data-cache-mode symlink",
            "floability run --backpack mypack --batch-type slurm",
        ]
