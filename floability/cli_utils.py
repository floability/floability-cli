# floability/cli_utils.py

from __future__ import annotations

import argparse
from argparse import Namespace


def collect_explicit_args(
    parser: argparse.ArgumentParser,
    args: Namespace,
    argv: list[str],
) -> set[str]:
    """Return argparse dest names for optional arguments explicitly supplied by the user."""
    explicit: set[str] = set()

    def option_was_supplied(action: argparse.Action) -> bool:
        return any(
            token == option_string or token.startswith(f"{option_string}=")
            for option_string in action.option_strings
            for token in argv
        )

    def visit(current_parser: argparse.ArgumentParser) -> None:
        for action in current_parser._actions:
            if action.option_strings and option_was_supplied(action):
                explicit.add(action.dest)

            if isinstance(action, argparse._SubParsersAction):
                selected_command = getattr(args, action.dest, None)
                if selected_command and selected_command in action.choices:
                    visit(action.choices[selected_command])

    visit(parser)
    return explicit