#!/usr/bin/env python3
"""
Floability CLI: main entry point for running distributed Jupyter-based workflows.
"""

import argparse
import sys

from .cleanup import CleanupManager, install_signal_handlers
from .commands import get_all_commands
from .cli_utils import collect_explicit_args
from .version_info import concise_version, verbose_version


def main():
    """
    Primary entry point for Floability CLI.

    Parses arguments and dispatches to appropriate command class.
    """

    # Parse arguments
    parser = argparse.ArgumentParser(
        description="Floability CLI: run distributed Jupyter-based workflows with TaskVine.",
        epilog="Use 'floability <command> --help' for more information on a specific command.",
    )

    parser.add_argument(
        "-v",
        "--version",
        action="store_true",
        help="Show version information and exit.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="With --version, include build, platform, and tool information.",
    )

    subparsers = parser.add_subparsers(dest="command", help="Floability sub-commands")

    # Register all commands from command classes
    command_map = {}
    for command_class in get_all_commands():
        cmd = command_class()
        cmd_parser = subparsers.add_parser(cmd.name, help=cmd.help)
        cmd.add_arguments(cmd_parser)
        command_map[cmd.name] = cmd

    argv = sys.argv[1:]
    args = parser.parse_args(argv)
    args._explicit_args = collect_explicit_args(parser, args, argv)

    if args.version:
        output = verbose_version() if args.verbose else concise_version()
        print(output)
        return 0

    if args.verbose:
        parser.error("--verbose is only valid with --version")

    # Setup cleanup manager for signal handling
    cleanup_manager = CleanupManager()
    install_signal_handlers(cleanup_manager)

    # Execute command
    if args.command:
        command = command_map[args.command]

        # Validate arguments if command has custom validation
        error = command.validate_args(args)
        if error:
            print(f"[floability] Error: {error}")
            return 1

        # Execute the command. Commands may return an explicit process status;
        # legacy commands that return None are successful.
        try:
            result = command.execute(args, cleanup_manager)
        except KeyboardInterrupt:
            if cleanup_manager.cleanup_complete:
                print("\n[floability] Interrupted by user.")
            else:
                print("\n[floability] Interrupted by user. Cleaning up...")
                cleanup_manager.cleanup()
            return 130

        return result if isinstance(result, int) else 0
    else:
        parser.print_help()
        print("\n[floability] No command provided. Use --help for usage information.")
        return 1
