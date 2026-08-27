from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from floability.backpack_manager import sync_workflow_to_backpack
from floability.commands.argument_groups import add_execution_args
from floability.instance_manager import copy_workflow_directory


def _make_workflow_pair(tmp_path: Path):
    backpack_workflow = tmp_path / "backpack" / "workflow"
    instance_workflow = tmp_path / "instance" / "workflow"
    backpack_workflow.mkdir(parents=True)
    instance_workflow.mkdir(parents=True)
    return backpack_workflow, instance_workflow


def test_default_sync_only_copies_original_workflow_files(tmp_path):
    backpack_workflow, instance_workflow = _make_workflow_pair(tmp_path)
    (backpack_workflow / "workflow.ipynb").write_text("original notebook")
    (backpack_workflow / "helpers").mkdir()
    (backpack_workflow / "helpers" / "analysis.py").write_text("original helper")

    copied_paths = []
    copy_workflow_directory(
        backpack_workflow,
        instance_workflow,
        copied_paths=copied_paths,
    )

    (instance_workflow / "workflow.ipynb").write_text("executed notebook")
    (instance_workflow / "helpers" / "analysis.py").write_text("updated helper")
    (instance_workflow / "data").mkdir()
    (instance_workflow / "data" / "input.root").write_text("staged input")
    (instance_workflow / "outputs").mkdir()
    (instance_workflow / "outputs" / "result.txt").write_text("generated output")

    assert sync_workflow_to_backpack(
        instance_workflow,
        backpack_workflow,
        copied_paths=copied_paths,
        verbose=False,
    )

    assert (backpack_workflow / "workflow.ipynb").read_text() == "executed notebook"
    assert (
        backpack_workflow / "helpers" / "analysis.py"
    ).read_text() == "updated helper"
    assert not (backpack_workflow / "data").exists()
    assert not (backpack_workflow / "outputs").exists()


def test_explicit_sync_path_can_copy_generated_directory(tmp_path):
    backpack_workflow, instance_workflow = _make_workflow_pair(tmp_path)
    output_file = instance_workflow / "outputs" / "nested" / "result.txt"
    output_file.parent.mkdir(parents=True)
    output_file.write_text("result")
    (instance_workflow / "data").mkdir()
    (instance_workflow / "data" / "input.root").write_text("staged input")

    assert sync_workflow_to_backpack(
        instance_workflow,
        backpack_workflow,
        extra_paths=["outputs"],
        verbose=False,
    )

    assert (
        backpack_workflow / "outputs" / "nested" / "result.txt"
    ).read_text() == "result"
    assert not (backpack_workflow / "data").exists()


def test_sync_rejects_paths_outside_workflow(tmp_path):
    backpack_workflow, instance_workflow = _make_workflow_pair(tmp_path)
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("outside")
    (instance_workflow / "escape").symlink_to(outside_file)

    outside_directory = tmp_path / "outside-directory"
    outside_directory.mkdir()
    (backpack_workflow / "redirect").symlink_to(
        outside_directory, target_is_directory=True
    )
    (instance_workflow / "redirect").mkdir()
    (instance_workflow / "redirect" / "result.txt").write_text("result")

    assert not sync_workflow_to_backpack(
        instance_workflow,
        backpack_workflow,
        extra_paths=["../outside.txt", "escape", "redirect/result.txt"],
        verbose=False,
    )
    assert not (backpack_workflow / "escape").exists()
    assert not (outside_directory / "result.txt").exists()


def test_sync_path_cli_is_repeatable_and_rejects_parent_paths():
    parser = argparse.ArgumentParser()
    add_execution_args(parser)

    args = parser.parse_args(
        ["--sync-path", "outputs", "--sync-path", "reports/summary.json"]
    )
    assert args.sync_path == ["outputs", "reports/summary.json"]

    with pytest.raises(SystemExit):
        parser.parse_args(["--sync-path", "../outside"])
