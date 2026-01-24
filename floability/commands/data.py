"""
Data command - data operations (check, fetch, verify).
"""

import argparse
from .base import BaseCommand


class DataCommand(BaseCommand):
    """Data operations via mode flag: download, check (metadata), verify (download + integrity)."""
    
    @property
    def name(self) -> str:
        return "data"
    
    @property
    def help(self) -> str:
        return "Data operations via mode flag: download, check (metadata), verify (download + integrity)"
    
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add data command arguments."""
        parser.add_argument(
            "--mode",
            choices=["check", "fetch", "verify"],
            default="check",
            help="Mode to run (default='check')",
        )
        parser.add_argument(
            "--data-spec",
            help="Path to data.yml file specifying data to operate on.",
        )
        parser.add_argument(
            "--backpack",
            help="Path to the root of the backpack for 'backpack' source_type files (default '.')",
        )
        parser.add_argument(
            "--check-details",
            action="store_true",
            help="After summary, print detailed metadata for each item (check mode only).",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Enable verbose logging for data operations (fetch/check/verify).",
        )
        parser.add_argument(
            "--force-fetch",
            action="store_true",
            help="Re-fetch (overwrite) targets even if they already exist.",
        )
        parser.add_argument(
            "--data-profile",
            help="Override the profile name in the data spec (useful to select a profile other than default).",
        )
        parser.add_argument(
            "--data-cache-mode",
            default="off",
            choices=["off", "symlink", "hardlink", "copy"],
            help="Data caching mode: off (no cache), symlink (default, read-only), hardlink (shared inode), copy (independent copy).",
        )
        parser.add_argument(
            "--force-data-cache",
            action="store_true",
            help="Force rebuild of cache entries even if they already exist.",
        )
        parser.add_argument(
            "--fingerprint-mode",
            default="meta",
            choices=["meta", "sample", "strict"],
            help="Fingerprint mode for filesystem source validation: meta (fast, metadata only), sample (first N bytes), strict (full content hash).",
        )
        parser.add_argument(
            "--base-dir",
            default="~/floability-base-dir",
            help="Base directory for floability cache storage (default='~/floability-base-dir').",
        )
    
    def execute(self, args: argparse.Namespace, cleanup_manager=None) -> None:
        """Execute data command."""
        from ..ops.data import run_data_command
        run_data_command(args)
    
    def get_examples(self) -> list:
        return [
            "floability data --mode check --data-spec example/rag-lite-bm25/data/data.yml",
            "floability data --mode fetch --data-spec mydata.yml --data-cache-mode symlink",
            "floability data --mode verify --data-spec mydata.yml --verbose",
        ]
