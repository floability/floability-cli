from __future__ import annotations

import argparse
import json
import signal
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

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


class _TerminationCommand(_StatusCommand):
    def execute(self, args, cleanup_manager=None):
        raise cli.TerminationRequested(signal.SIGTERM)


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


def test_cli_returns_signal_status_and_cleans_up(
    monkeypatch,
    isolated_cli,
    capsys,
):
    cleaned = []
    monkeypatch.setattr(cli, "get_all_commands", lambda: [_TerminationCommand])
    monkeypatch.setattr(
        cli.CleanupManager,
        "cleanup",
        lambda self: cleaned.append(True),
    )

    assert cli.main() == 143
    assert cleaned == [True]
    assert "Terminated by signal 15" in capsys.readouterr().out


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


@pytest.mark.parametrize("command", ["instance", "workers"])
def test_management_commands_require_a_subcommand(command):
    result = _run_installed_cli(command)

    assert result.returncode == 2
    assert "the following arguments are required" in result.stderr


@pytest.mark.parametrize(
    "args",
    [
        ("instance", "stop", "missing-instance-for-exit-code-test"),
        (
            "workers",
            "status",
            "--instance",
            "missing-instance-for-exit-code-test",
        ),
    ],
)
def test_management_commands_return_nonzero_for_a_missing_instance(args):
    result = _run_installed_cli(*args)

    assert result.returncode == 1
    assert "Error" in result.stdout


def test_workers_status_returns_zero_for_an_existing_instance_directory(tmp_path):
    result = _run_installed_cli(
        "workers", "status", "--instance", str(tmp_path)
    )

    assert result.returncode == 0
    assert "Status for instance" in result.stdout


def test_data_check_returns_nonzero_for_a_missing_spec(tmp_path):
    result = _run_installed_cli(
        "data",
        "--mode",
        "check",
        "--data-spec",
        str(tmp_path / "missing.yml"),
        "--base-dir",
        str(tmp_path / "base"),
    )

    assert result.returncode == 1
    assert "Data check operation FAILED" in result.stdout


def test_data_check_returns_zero_for_valid_local_data(tmp_path):
    backpack = _write_local_data_backpack(tmp_path)
    result = _run_installed_cli(
        "data",
        "--mode",
        "check",
        "--backpack",
        str(backpack),
        "--base-dir",
        str(tmp_path / "base"),
    )

    assert result.returncode == 0
    assert "Data check operation completed successfully" in result.stdout


def test_backpack_init_returns_nonzero_without_overwriting_existing_backpack(
    tmp_path,
):
    destination = tmp_path / "duplicate"
    init_args = (
        "backpack",
        "init",
        "--name",
        str(destination),
        "--from-template",
        "taskvine",
    )

    first = _run_installed_cli(*init_args)
    assert first.returncode == 0
    assert "floability run --backpack" in first.stdout

    workflow = destination / "workflow" / "duplicate.ipynb"
    original_workflow = workflow.read_bytes()
    second = _run_installed_cli(*init_args)

    assert second.returncode == 1
    assert "Backpack directory already exists" in second.stdout
    assert workflow.read_bytes() == original_workflow


def test_backpack_init_returns_nonzero_for_missing_workflow(tmp_path):
    destination = tmp_path / "invalid-workflow"
    result = _run_installed_cli(
        "backpack",
        "init",
        "--name",
        str(destination),
        "--from-workflow",
        str(tmp_path / "missing.py"),
    )

    assert result.returncode == 1
    assert "Workflow source file not found" in result.stdout
    assert not destination.exists()


def test_script_template_recommends_execute(tmp_path):
    result = _run_installed_cli(
        "backpack",
        "init",
        "--name",
        str(tmp_path / "script-template"),
        "--from-template",
        "taskvine",
        "--script",
    )

    assert result.returncode == 0
    assert "floability execute --backpack" in result.stdout


def test_shell_workflow_recommends_execute(tmp_path):
    workflow = tmp_path / "workflow.sh"
    workflow.write_text("#!/bin/sh\necho test\n", encoding="utf-8")
    result = _run_installed_cli(
        "backpack",
        "init",
        "--name",
        str(tmp_path / "shell-workflow"),
        "--from-workflow",
        str(workflow),
        input_text="3\nn\n",
    )

    assert result.returncode == 0
    assert "floability execute --backpack" in result.stdout


@pytest.mark.parametrize(
    ("template_variant", "workflow_suffix", "expected_sample_count"),
    (
        ("taskvine", ".ipynb", 0),
        ("taskvine", ".py", 0),
        ("taskvine-data", ".ipynb", 1),
        ("taskvine-data", ".py", 1),
    ),
)
def test_backpack_template_init_creates_complete_valid_backpack(
    tmp_path, template_variant, workflow_suffix, expected_sample_count
):
    entrypoint_type = "script" if workflow_suffix == ".py" else "notebook"
    destination = tmp_path / f"valid-{template_variant}-{entrypoint_type}-backpack"
    init_args = [
        "backpack",
        "init",
        "--name",
        str(destination),
        "--from-template",
        template_variant,
    ]
    if workflow_suffix == ".py":
        init_args.append("--script")

    initialized = _run_installed_cli(*init_args)

    valid = _run_installed_cli("backpack", "validate", str(destination))

    workflow = destination / "workflow" / f"{destination.name}{workflow_suffix}"
    environment = destination / "software" / "environment.yml"
    compute = destination / "compute" / "compute.yml"
    data_spec = destination / "data" / "data.yml"
    sample_files = sorted((destination / "data" / "text_data").glob("*.txt"))

    assert initialized.returncode == 0, initialized.stdout + initialized.stderr
    assert workflow.is_file()
    assert environment.is_file()
    assert compute.is_file()

    if workflow_suffix == ".ipynb":
        notebook = json.loads(workflow.read_text(encoding="utf-8"))
        code = "\n".join(
            "".join(cell.get("source", []))
            for cell in notebook["cells"]
            if cell.get("cell_type") == "code"
        )
    else:
        code = workflow.read_text(encoding="utf-8")
        compile(code, str(workflow), "exec")
    assert "VINE_MANAGER_NAME" in code
    assert "VINE_MANAGER_PORTS" in code
    assert "vine.Manager" in code
    assert "vine.PythonTask" in code

    assert data_spec.is_file() is bool(expected_sample_count)
    assert len(sample_files) == expected_sample_count
    if expected_sample_count:
        manifest = yaml.safe_load(data_spec.read_text(encoding="utf-8"))
        profile = manifest["profiles"][manifest["default_profile"]]
        entries = {item["name"]: item for item in profile["data"]}

        assert entries["local_sample"]["source_type"] == "backpack"
        assert entries["local_sample"]["checksum"].startswith("sha256:")
        assert entries["war_and_peace"] == {
            "name": "war_and_peace",
            "source_type": "http",
            "source": "https://www.gutenberg.org/cache/epub/2600/pg2600.txt",
            "content_type": "text/plain",
            "target_location": "data/text_data/war-and-peace.txt",
        }
    assert valid.returncode == 0, valid.stdout + valid.stderr
    assert "Backpack Validation: VALID" in valid.stdout


def test_backpack_validate_returns_nonzero_for_missing_backpack(tmp_path):
    invalid = _run_installed_cli(
        "backpack", "validate", str(tmp_path / "missing-backpack")
    )

    assert invalid.returncode == 1


def test_backpack_requires_a_subcommand():
    result = _run_installed_cli("backpack")

    assert result.returncode == 1
    assert "Unknown backpack subcommand" in result.stdout


def test_backpack_update_env_preserves_nonzero_failure_status(tmp_path):
    result = _run_installed_cli(
        "backpack",
        "update-env",
        "--from-instance",
        "missing-instance-for-update-exit-code-test",
        str(tmp_path),
    )

    assert result.returncode == 1
    assert "Error updating environment" in result.stdout


def _write_local_data_backpack(root: Path) -> Path:
    backpack = root / "local-data"
    data_dir = backpack / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "input.txt").write_text("local-data\n", encoding="utf-8")
    (data_dir / "data.yml").write_text(
        """\
schema_version: 1.0
default_profile: local
profiles:
  local:
    data:
      - name: input
        source_type: backpack
        source: data/input.txt
        target_location: data/input.txt
""",
        encoding="utf-8",
    )
    return backpack


def _run_installed_cli(*args, input_text=None):
    return subprocess.run(
        [str(Path(sys.executable).with_name("floability")), *args],
        capture_output=True,
        text=True,
        input=input_text,
        check=False,
    )
