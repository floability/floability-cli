"""
Floability command classes.

Each command is implemented as a class that handles its own:
- Argument parsing
- Validation
- Execution
- Help text
"""

from .base import BaseCommand
from .run import RunCommand
from .execute import ExecuteCommand
from .instance import InstanceCommand
from .data import DataCommand
from .workers import WorkersCommand
from .audit import AuditCommand


def get_all_commands():
    """Return list of all available command classes."""
    return [
        RunCommand,
        ExecuteCommand,
        InstanceCommand,
        DataCommand,
        WorkersCommand,
        AuditCommand,
    ]


__all__ = [
    "BaseCommand",
    "RunCommand",
    "ExecuteCommand",
    "InstanceCommand",
    "DataCommand",
    "WorkersCommand",
    "AuditCommand",
    "get_all_commands",
]
