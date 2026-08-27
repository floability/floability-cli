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
        parser.add_argument(
            "--conda-env",
            required=False,
            default=None,
            help=(
                "Path to a conda environment prefix to use when executing the notebook "
                "(e.g. /shared/miniconda3/envs/my-env). The notebook's dependencies "
                "must be installed in this environment."
            ),
        )
        parser.add_argument(
            "--backpack-name",
            required=True,
            default=None,
            help=(
                "Required name or path for the complete backpack generated from "
                "the audit outputs."
            ),
        )
        parser.add_argument(
            "--force",
            action="store_true",
            default=False,
            help="Overwrite existing backpack directory if it exists (only used with --backpack-name).",
        )
        parser.add_argument(
            "--no-worker",
            action="store_true",
            default=False,
            help=(
                "Skip starting a vine_worker during audit. Use for non-distributed "
                "notebooks that do not use TaskVine."
            ),
        )
        parser.add_argument(
            "--data-dirs",
            nargs="+",
            default=None,
            metavar="PATH",
            help=(
                "One or more directories containing data files accessed by the notebook "
                "(e.g. --data-dirs ./data ./inputs). Paths relative to the notebook "
                "directory or absolute. Used to detect data dependencies directly from "
                "strace output instead of relying on Python-level open() tracing."
            ),
        )

    def execute(self, args: argparse.Namespace, cleanup_manager=None) -> None:
        """Execute audit command."""
        from floability.sites import apply_site_defaults
        from ..ops.audit import run_audit_command

        apply_site_defaults(args, explicit_args=getattr(args, "_explicit_args", None))
        run_audit_command(args)

    def get_examples(self) -> list:
        return [
            "floability audit --notebook mynotebook.ipynb --backpack-name my-workflow",
            "floability audit --notebook mynotebook.ipynb --backpack-name my-workflow --cell-level",
            "floability audit --notebook mynotebook.ipynb --conda-env /path/to/conda/env --backpack-name my-workflow",
            "floability audit --notebook mynotebook.ipynb --conda-env /path/to/conda/env --backpack-name my-workflow --force",
            "floability audit --notebook mynotebook.ipynb --data-dirs ./data ./inputs --backpack-name my-workflow",
            "floability audit --notebook mynotebook.ipynb --no-worker --conda-env /path/to/env --backpack-name my-workflow",
        ]
