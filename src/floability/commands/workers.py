"""
Workers command - worker management (start, stop, status).
"""

import argparse

from ..utils import normalize_worker_transfer_ports
from .base import BaseCommand


class WorkersCommand(BaseCommand):
    """Worker management commands (start, stop, status)."""

    @property
    def name(self) -> str:
        return "workers"

    @property
    def help(self) -> str:
        return "Worker management commands (start, stop, status)"

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add workers command arguments."""
        workers_subparsers = parser.add_subparsers(
            dest="workers_subcommand",
            help="Workers sub-commands",
            required=True,
        )

        # workers start sub-command
        start_parser = workers_subparsers.add_parser(
            "start", help="Start workers for a Floability instance"
        )
        start_parser.add_argument(
            "--instance",
            required=True,
            help="Path to the Floability instance directory (required).",
        )
        start_parser.add_argument(
            "--batch-type",
            choices=["local", "condor", "uge", "slurm"],
            help="Batch system for workers (overrides instance config).",
        )
        start_parser.add_argument(
            "--workers",
            type=int,
            help="Maximum number of workers (overrides instance config).",
        )
        start_parser.add_argument(
            "--cores-per-worker",
            type=int,
            help="Cores per worker (overrides instance config).",
        )
        start_parser.add_argument(
            "--batch-options",
            help="Batch system options (overrides instance config).",
        )
        start_parser.add_argument(
            "--compute-spec",
            help="Path to compute.yml (overrides instance config).",
        )
        start_parser.add_argument(
            "--debug-workers",
            action="store_true",
            help="Enable debug mode for workers.",
        )
        start_parser.add_argument(
            "--worker-transfer-ports",
            type=normalize_worker_transfer_ports,
            help=(
                "Port range for worker-worker transfers (START:END; legacy "
                "START,END is accepted). Passed as --transfer-port to vine_factory."
            ),
        )

        # workers stop sub-command
        stop_parser = workers_subparsers.add_parser(
            "stop", help="Stop workers for a Floability instance"
        )
        stop_parser.add_argument(
            "--instance",
            required=True,
            help="Path to the Floability instance directory (required).",
        )

        # workers status sub-command
        status_parser = workers_subparsers.add_parser(
            "status", help="Show worker status for a Floability instance"
        )
        status_parser.add_argument(
            "--instance",
            required=True,
            help="Path to the Floability instance directory (required).",
        )

    def execute(self, args: argparse.Namespace, cleanup_manager=None) -> int:
        """Execute workers command."""
        from ..ops.workers import run_workers_command

        return run_workers_command(args)

    def get_examples(self) -> list:
        return [
            "floability workers start --instance flo_instances/run_20260124_123456",
            "floability workers stop --instance flo_instances/run_20260124_123456",
            "floability workers status --instance flo_instances/run_20260124_123456",
        ]
