from __future__ import annotations

import os
import subprocess
import sys
from argparse import Namespace

from floability.commands.instance import InstanceCommand
from floability.instance_registry import record_instance_run
from floability.ops.instance import run_instance_command


def test_instance_latest_skips_site_defaults(monkeypatch):
    command = InstanceCommand()
    args = Namespace(instance_subcommand="latest", _explicit_args={"base_dir"})
    applied = []

    monkeypatch.setattr(
        "floability.sites.apply_site_defaults",
        lambda parsed_args, explicit_args=None: applied.append(
            (parsed_args, explicit_args)
        ),
    )
    monkeypatch.setattr(
        "floability.ops.instance.run_instance_command",
        lambda parsed_args: 0,
    )

    assert command.execute(args) == 0
    assert applied == []


def test_instance_create_still_applies_site_defaults(monkeypatch):
    command = InstanceCommand()
    args = Namespace(instance_subcommand="create", _explicit_args={"base_dir"})
    applied = []

    monkeypatch.setattr(
        "floability.sites.apply_site_defaults",
        lambda parsed_args, explicit_args=None: applied.append(
            (parsed_args, explicit_args)
        ),
    )
    monkeypatch.setattr(
        "floability.ops.instance.run_instance_command",
        lambda parsed_args: 0,
    )

    assert command.execute(args) == 0
    assert applied == [(args, {"base_dir"})]


def test_instance_latest_stdout_contains_only_resolved_path(tmp_path, monkeypatch):
    base_dir = tmp_path / "base"
    instance_path = base_dir / "fi_test_instance"
    instance_path.mkdir(parents=True)
    xdg_data_home = tmp_path / "xdg"
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg_data_home))
    record_instance_run(
        instance_path,
        base_dir,
        manager_name="test-manager",
        ran_at="2026-08-24T12:00:00Z",
    )

    environment = dict(os.environ)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "floability",
            "instance",
            "latest",
            "--base-dir",
            str(base_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )

    assert result.returncode == 0
    assert result.stdout == f"{instance_path.resolve()}\n"
    assert result.stderr == ""


def test_instance_list_is_global_and_sorted_by_last_run(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    older_base = tmp_path / "older-base"
    newer_base = tmp_path / "newer-base"
    older = older_base / "fi_older"
    newer = newer_base / "fi_newer"
    older.mkdir(parents=True)
    newer.mkdir(parents=True)
    record_instance_run(older, older_base, ran_at="2026-08-24T10:00:00Z")
    record_instance_run(newer, newer_base, ran_at="2026-08-24T11:00:00Z")

    result = run_instance_command(
        Namespace(
            instance_subcommand="list",
            show_paths=True,
            all_details=False,
        )
    )

    output = capsys.readouterr().out
    assert result == 0
    assert str(newer.resolve()) in output
    assert str(older.resolve()) in output
    assert output.index("fi_newer") < output.index("fi_older")
