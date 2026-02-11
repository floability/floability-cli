"""
Audit command - generate environment and data dependencies.
"""

import argparse
from .base import BaseCommand


class AuditCommand(BaseCommand):
    """Generate environment and data dependencies for a notebook."""

    @property
    def name(self) -> str:
        return "audit"

    @property
    def help(self) -> str:
        return "Generate environment and data dependencies for a notebook"

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add audit command arguments."""
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

    def execute(self, args: argparse.Namespace, cleanup_manager=None) -> None:
        """Execute audit command."""
        from ..ops.audit import run_audit_command

        run_audit_command(args)

    def get_examples(self) -> list:
        return [
            "floability audit --notebook example/matrix-multiplication/workflow/matrix-multiplication.ipynb",
            "floability audit --notebook mynotebook.ipynb --cell-level",
        ]
