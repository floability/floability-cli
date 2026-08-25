import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from floability.commands.tools import ToolsCommand
from floability.instance_lock_manager import (
    acquire_instance_lock,
    release_instance_lock,
)
from floability.instance_registry import record_instance_run, register_instance
from floability.ops import tools as tools_ops


def _args(**overrides):
    values = {
        "tools_subcommand": "clean",
        "base_dir": None,
        "all_registered_bases": False,
        "data_cache_dir": None,
        "data_only": False,
        "env_only": False,
        "data_and_env": False,
        "instances_only": False,
        "all": False,
        "keep_last": False,
        "yes": False,
        "dry_run": False,
        "jobs": 1,
        "parallel": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _write_instance(
    base_dir: Path,
    name: str,
    *,
    data_entry: Path | None = None,
    env_dir: Path | None = None,
    env_archive: Path | None = None,
) -> Path:
    instance = base_dir / name
    metadata_dir = instance / "metadata"
    metadata_dir.mkdir(parents=True)
    metadata = {
        "status": {"state": "completed"},
        "data": {
            "cache_dirs": [str(data_entry / "source-key")] if data_entry else []
        },
        "env_dir": str(env_dir) if env_dir else None,
        "manager_environment_pack": str(env_archive) if env_archive else None,
        "worker_environment_pack": str(env_archive) if env_archive else None,
    }
    (metadata_dir / "run.json").write_text(json.dumps(metadata))
    (instance / "workflow").mkdir()
    (instance / "workflow" / "workflow.py").write_text("print('ok')\n")
    return instance


def _make_data_entry(base_dir: Path, name: str) -> Path:
    cache_key = hashlib.sha256(name.encode()).hexdigest()
    entry = base_dir / "floability-data-cache" / cache_key
    leaf = entry / "source-key"
    leaf.mkdir(parents=True)
    (leaf / "data.bin").write_bytes(b"data")
    return entry


def _make_environment(base_dir: Path, name: str) -> tuple[Path, Path]:
    env_dir = base_dir / "flo_common_env" / "extracted_envs" / name
    archive = base_dir / "flo_common_env" / "tarballs" / f"{name}.tar.gz"
    (env_dir / "bin").mkdir(parents=True)
    (env_dir / "bin" / "python").write_text("executable")
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(b"archive")
    return env_dir, archive


def _register_run(
    instance: Path,
    base_dir: Path,
    *,
    ran_at: str,
) -> None:
    register_instance(instance, "manager", base_dir=base_dir)
    record_instance_run(instance, base_dir, manager_name="manager", ran_at=ran_at)


def test_default_clean_removes_only_unreferenced_data_entries(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    base_dir = tmp_path / "base"
    base_dir.mkdir()
    kept_data = _make_data_entry(base_dir, "kept-data")
    removed_data = _make_data_entry(base_dir, "removed-data")
    kept_env, kept_archive = _make_environment(base_dir, "kept-env")
    removed_env, removed_archive = _make_environment(base_dir, "removed-env")
    instance = _write_instance(
        base_dir,
        "fi_kept",
        data_entry=kept_data,
        env_dir=kept_env,
        env_archive=kept_archive,
    )
    _register_run(instance, base_dir, ran_at="2026-08-25T01:00:00Z")

    result = tools_ops.run_tools_command(
        _args(base_dir=str(base_dir), yes=True, jobs=1)
    )

    assert result == 0
    assert instance.is_dir()
    assert kept_data.is_dir()
    assert kept_env.is_dir()
    assert kept_archive.is_file()
    assert not removed_data.exists()
    assert removed_env.is_dir()
    assert removed_archive.is_file()


def test_data_and_env_removes_unreferenced_entries(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    base_dir = tmp_path / "base"
    base_dir.mkdir()
    removed_data = _make_data_entry(base_dir, "removed-data")
    removed_env, removed_archive = _make_environment(base_dir, "removed-env")

    result = tools_ops.run_tools_command(
        _args(base_dir=str(base_dir), data_and_env=True, yes=True, jobs=1)
    )

    assert result == 0
    assert not removed_data.exists()
    assert not removed_env.exists()
    assert not removed_archive.exists()


def test_keep_last_uses_last_run_and_preserves_its_dependencies(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    base_dir = tmp_path / "base"
    base_dir.mkdir()

    old_data = _make_data_entry(base_dir, "old-data")
    old_env, old_archive = _make_environment(base_dir, "old-env")
    old_instance = _write_instance(
        base_dir,
        "fi_old",
        data_entry=old_data,
        env_dir=old_env,
        env_archive=old_archive,
    )
    _register_run(old_instance, base_dir, ran_at="2026-08-25T01:00:00Z")

    latest_data = _make_data_entry(base_dir, "latest-data")
    latest_env, latest_archive = _make_environment(base_dir, "latest-env")
    latest_instance = _write_instance(
        base_dir,
        "fi_latest",
        data_entry=latest_data,
        env_dir=latest_env,
        env_archive=latest_archive,
    )
    _register_run(latest_instance, base_dir, ran_at="2026-08-25T02:00:00Z")

    result = tools_ops.run_tools_command(
        _args(base_dir=str(base_dir), keep_last=True, yes=True, jobs=1)
    )

    assert result == 0
    assert latest_instance.is_dir()
    assert latest_data.is_dir()
    assert latest_env.is_dir()
    assert latest_archive.is_file()
    assert not old_instance.exists()
    assert not old_data.exists()
    assert not old_env.exists()
    assert not old_archive.exists()


def test_no_base_uses_most_recent_registered_base(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    old_base = tmp_path / "old-base"
    recent_base = tmp_path / "recent-base"
    old_base.mkdir()
    recent_base.mkdir()
    old_instance = _write_instance(old_base, "fi_old")
    recent_instance = _write_instance(recent_base, "fi_recent")
    _register_run(old_instance, old_base, ran_at="2026-08-25T01:00:00Z")
    _register_run(recent_instance, recent_base, ran_at="2026-08-25T02:00:00Z")

    result = tools_ops.run_tools_command(_args(dry_run=True))
    output = capsys.readouterr().out

    assert result == 0
    assert f"Base: {recent_base}" in output
    assert f"Base: {old_base}" not in output
    assert "most recently used base directory" in output


def test_all_registered_bases_are_planned_with_registry_caveat(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    bases = [tmp_path / "base-a", tmp_path / "base-b"]
    for index, base_dir in enumerate(bases):
        base_dir.mkdir()
        instance = _write_instance(base_dir, f"fi_{index}")
        _register_run(
            instance,
            base_dir,
            ran_at=f"2026-08-25T0{index + 1}:00:00Z",
        )

    result = tools_ops.run_tools_command(
        _args(all_registered_bases=True, dry_run=True)
    )
    output = capsys.readouterr().out

    assert result == 0
    assert all(f"Base: {base_dir}" in output for base_dir in bases)
    assert "Older or unregistered bases may not be included" in output


def test_cleanup_refuses_active_instance(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    base_dir = tmp_path / "base"
    base_dir.mkdir()
    orphan = _make_data_entry(base_dir, "orphan")
    instance = _write_instance(base_dir, "fi_active")
    _register_run(instance, base_dir, ran_at="2026-08-25T01:00:00Z")
    assert acquire_instance_lock(instance)
    try:
        result = tools_ops.run_tools_command(
            _args(base_dir=str(base_dir), yes=True)
        )
    finally:
        assert release_instance_lock(instance)

    error = capsys.readouterr().err
    assert result == 1
    assert "refusing cleanup" in error
    assert orphan.is_dir()


def test_custom_cache_root_rejects_broad_destructive_path(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    base_dir = tmp_path / "base"
    base_dir.mkdir()

    result = tools_ops.run_tools_command(
        _args(
            base_dir=str(base_dir),
            data_cache_dir="/",
            data_only=True,
            dry_run=True,
        )
    )

    assert result == 1


def test_parallel_cleanup_handles_read_only_tree_and_does_not_follow_symlink(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    base_dir = tmp_path / "base"
    base_dir.mkdir()
    readonly_env, _archive = _make_environment(base_dir, "readonly-env")
    readonly_env.chmod(0o555)
    (readonly_env / "bin").chmod(0o555)

    external = tmp_path / "external"
    external.mkdir()
    external_file = external / "keep.txt"
    external_file.write_text("keep")
    data_root = base_dir / "floability-data-cache"
    data_root.mkdir()
    link_name = "f" * 64
    (data_root / link_name).symlink_to(external, target_is_directory=True)

    result = tools_ops.run_tools_command(
        _args(
            base_dir=str(base_dir),
            data_and_env=True,
            yes=True,
            jobs=2,
        )
    )

    assert result == 0
    assert not readonly_env.exists()
    assert not (data_root / link_name).exists()
    assert external_file.read_text() == "keep"


def test_failed_delete_is_nonzero_and_staged_for_retry(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    base_dir = tmp_path / "base"
    base_dir.mkdir()
    orphan = _make_data_entry(base_dir, "orphan")

    def fail_delete(_path, _jobs):
        raise OSError("simulated deletion failure")

    monkeypatch.setattr(tools_ops, "_delete_staged_path", fail_delete)
    result = tools_ops.run_tools_command(
        _args(base_dir=str(base_dir), data_only=True, yes=True)
    )

    assert result == 1
    assert not orphan.exists()
    staged = list((base_dir / "floability-data-cache").glob(".floability-delete-*"))
    assert len(staged) == 1


def test_jobs_default_is_bounded_and_one_selects_serial_mode():
    parser = argparse.ArgumentParser()
    ToolsCommand().add_arguments(parser)

    defaults = parser.parse_args(["clean"])
    serial = parser.parse_args(["clean", "--jobs", "1"])

    assert defaults.jobs == min(os.cpu_count() or 1, 4)
    assert serial.jobs == 1


def test_custom_cache_root_must_match_floability_layout(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    base_dir = tmp_path / "base"
    base_dir.mkdir()
    unrelated = tmp_path / "unrelated"
    (unrelated / "project-files").mkdir(parents=True)

    result = tools_ops.run_tools_command(
        _args(
            base_dir=str(base_dir),
            data_cache_dir=str(unrelated),
            data_only=True,
            yes=True,
        )
    )

    assert result == 1
    assert (unrelated / "project-files").is_dir()


def test_public_cli_prints_plan_and_removes_only_unreferenced_data(
    tmp_path, monkeypatch
):
    xdg_data_home = tmp_path / "xdg"
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg_data_home))
    base_dir = tmp_path / "base"
    base_dir.mkdir()
    kept_data = _make_data_entry(base_dir, "kept")
    removed_data = _make_data_entry(base_dir, "removed")
    instance = _write_instance(base_dir, "fi_kept", data_entry=kept_data)
    _register_run(instance, base_dir, ran_at="2026-08-25T01:00:00Z")

    executable = Path(sys.executable).parent / "floability"
    assert executable.is_file()
    environment = dict(os.environ)
    environment["XDG_DATA_HOME"] = str(xdg_data_home)
    result = subprocess.run(
        [
            str(executable),
            "tools",
            "clean",
            "--base-dir",
            str(base_dir),
            "--data-only",
            "--yes",
            "--jobs",
            "1",
        ],
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    assert "Cleanup plan" in result.stdout
    assert "Delete: 0 instance(s), 1 data entry/entries" in result.stdout
    assert kept_data.is_dir()
    assert not removed_data.exists()


def test_custom_cache_preserves_references_from_other_registered_base(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    selected_base = tmp_path / "selected-base"
    other_base = tmp_path / "other-base"
    custom_cache = tmp_path / "floability-data-cache"
    selected_base.mkdir()
    other_base.mkdir()

    cache_key = hashlib.sha256(b"shared").hexdigest()
    shared_entry = custom_cache / cache_key
    (shared_entry / "source-key").mkdir(parents=True)
    (shared_entry / "source-key" / "data.bin").write_bytes(b"shared")
    instance = _write_instance(other_base, "fi_other", data_entry=shared_entry)
    _register_run(instance, other_base, ran_at="2026-08-25T01:00:00Z")

    result = tools_ops.run_tools_command(
        _args(
            base_dir=str(selected_base),
            data_cache_dir=str(custom_cache),
            data_only=True,
            yes=True,
        )
    )

    assert result == 0
    assert shared_entry.is_dir()


def test_keep_last_across_registered_bases_preserves_cross_base_data(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    data_base = tmp_path / "data-base"
    latest_base = tmp_path / "latest-base"
    data_base.mkdir()
    latest_base.mkdir()
    shared_entry = _make_data_entry(data_base, "shared")
    orphan_entry = _make_data_entry(data_base, "orphan")

    old_instance = _write_instance(data_base, "fi_old")
    _register_run(old_instance, data_base, ran_at="2026-08-25T01:00:00Z")
    latest_instance = _write_instance(
        latest_base,
        "fi_latest",
        data_entry=shared_entry,
    )
    _register_run(latest_instance, latest_base, ran_at="2026-08-25T02:00:00Z")

    result = tools_ops.run_tools_command(
        _args(all_registered_bases=True, keep_last=True, yes=True)
    )

    assert result == 0
    assert latest_instance.is_dir()
    assert shared_entry.is_dir()
    assert not orphan_entry.exists()
    assert not old_instance.exists()
