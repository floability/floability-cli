from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pytest

from floability import cli
from floability.commands.base import BaseCommand
from floability.instance_metadata import finalize_instance_metadata


class _StatusCommand(BaseCommand):
    status = 0

    @property
    def name(self) -> str:
        return "status-test"

    @property
    def help(self) -> str:
        return "Test command status propagation."

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        pass

    def execute(self, args, cleanup_manager=None):
        return self.status


class _InterruptCommand(_StatusCommand):
    def execute(self, args, cleanup_manager=None):
        raise KeyboardInterrupt


class _CleanedInterruptCommand(_StatusCommand):
    def execute(self, args, cleanup_manager=None):
        cleanup_manager.cleanup()
        raise KeyboardInterrupt


@pytest.fixture
def isolated_cli(monkeypatch):
    monkeypatch.setattr(cli, "install_signal_handlers", lambda _manager: None)
    monkeypatch.setattr(sys, "argv", ["floability", "status-test"])


def test_cli_returns_command_status(monkeypatch, isolated_cli):
    _StatusCommand.status = 7
    monkeypatch.setattr(cli, "get_all_commands", lambda: [_StatusCommand])

    assert cli.main() == 7


def test_cli_returns_130_and_cleans_up_on_interrupt(
    monkeypatch, isolated_cli, capsys
):
    cleaned = []
    monkeypatch.setattr(cli, "get_all_commands", lambda: [_InterruptCommand])
    monkeypatch.setattr(
        cli.CleanupManager,
        "cleanup",
        lambda self: cleaned.append(True),
    )

    assert cli.main() == 130
    assert cleaned == [True]
    assert "Interrupted by user" in capsys.readouterr().out


def test_cli_does_not_repeat_completed_cleanup(monkeypatch, isolated_cli):
    cleaned = []
    monkeypatch.setattr(cli, "get_all_commands", lambda: [_CleanedInterruptCommand])

    def mark_cleaned(manager):
        manager._cleanup_complete = True
        cleaned.append(True)

    monkeypatch.setattr(cli.CleanupManager, "cleanup", mark_cleaned)

    assert cli.main() == 130
    assert cleaned == [True]


def test_metadata_can_record_interrupted_state(tmp_path):
    metadata_path = tmp_path / "run.json"
    metadata_path.write_text('{"status": {"state": "running"}}', encoding="utf-8")

    finalize_instance_metadata(
        metadata_path,
        success=False,
        error="Interrupted by user",
        state="interrupted",
    )

    status = json.loads(metadata_path.read_text(encoding="utf-8"))["status"]
    assert status["state"] == "interrupted"
    assert status["success"] is False
    assert status["error"] == "Interrupted by user"


@pytest.mark.parametrize(
    "removed_option",
    ["--notebook", "--entry-file", "--workflow-entry", "--python-script"],
)
def test_removed_workflow_options_are_rejected(removed_option):
    result = _run_installed_cli("run", removed_option, "workflow.ipynb")

    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr


def _run_installed_cli(*args):
    return subprocess.run(
        [str(Path(sys.executable).with_name("floability")), *args],
        capture_output=True,
        text=True,
        check=False,
    )
