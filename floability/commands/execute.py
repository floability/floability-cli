"""
Execute command - run a workflow in batch mode.
"""

import argparse
from .base import BaseCommand
from .argument_groups import add_execution_args


class ExecuteCommand(BaseCommand):
    """Execute a Floability workflow from a backpack in batch mode."""

    @property
    def name(self) -> str:
        return "execute"

    @property
    def help(self) -> str:
        return "Execute a Floability workflow from a backpack in batch mode."

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add execute command arguments."""
        add_execution_args(parser)

    def execute(self, args: argparse.Namespace, cleanup_manager=None) -> None:
        """Execute command in batch mode."""
        from ..ops.run import run_workflow

        run_workflow(args, cleanup_manager, mode="execute")

    def get_examples(self) -> list:
        return [
            "floability execute --backpack example/rag-lite-bm25",
            "floability execute --backpack mypack --no-worker",
        ]
