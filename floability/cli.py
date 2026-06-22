#!/usr/bin/env python3
"""
Floability CLI: main entry point for running distributed Jupyter-based workflows.
"""

import argparse
import sys

from .cleanup import CleanupManager, install_signal_handlers
from .commands import get_all_commands

from . import __version__


def _collect_explicit_args(parser: argparse.ArgumentParser, argv: list[str]) -> set[str]:
    """Collect option dests that were explicitly supplied on the CLI."""
    explicit = set()

    def _visit(current_parser: argparse.ArgumentParser) -> None:
        for action in current_parser._actions:
            if action.option_strings:
                for option_string in action.option_strings:
                    for token in argv:
                        if token == option_string or token.startswith(f"{option_string}="):
                            explicit.add(action.dest)
                            break
            subparsers_action = getattr(argparse, "_SubParsersAction", None)
            if subparsers_action and isinstance(action, subparsers_action):
                for subparser in action.choices.values():
                    _visit(subparser)

    _visit(parser)
    return explicit


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
        "-v", "--version", action="version", version=f"%(prog)s {__version__}"
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
    args._explicit_args = _collect_explicit_args(parser, argv)

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

        # Execute the command
        command.execute(args, cleanup_manager)
    else:
        parser.print_help()
        print("\n[floability] No command provided. Use --help for usage information.")
