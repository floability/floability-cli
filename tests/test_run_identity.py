from __future__ import annotations

import json
from argparse import Namespace
from types import SimpleNamespace

from floability import workers_manager
from floability.ops import run as run_ops


def test_generated_manager_name_is_fresh_for_each_run_attempt():
    first_args = Namespace(manager_name=None)
    second_args = Namespace(manager_name=None)

    first_name = run_ops._select_run_manager_name(first_args)
    second_name = run_ops._select_run_manager_name(second_args)

    assert first_name.startswith("floability-")
    assert second_name.startswith("floability-")
    assert first_name != second_name


def test_explicit_manager_name_is_respected():
    args = Namespace(manager_name="tutorial-manager")

    assert run_ops._select_run_manager_name(args) == "tutorial-manager"
    assert args.manager_name == "tutorial-manager"


def test_saved_manager_ports_are_restored_for_an_existing_instance(tmp_path):
    metadata_file = tmp_path / "run.json"
    metadata_file.write_text(
        json.dumps({"cli_args": {"manager_ports": "10000,11000"}}),
        encoding="utf-8",
    )
    args = Namespace(manager_ports="9123,9150", _explicit_args=set())

    run_ops._restore_existing_manager_ports(args, metadata_file)

    assert args.manager_ports == "10000,11000"


def test_explicit_manager_ports_override_saved_ports(tmp_path):
    metadata_file = tmp_path / "run.json"
    metadata_file.write_text(
        json.dumps({"manager_ports": "10000,11000"}),
        encoding="utf-8",
    )
    args = Namespace(
        manager_ports="12000,12100",
        _explicit_args={"manager_ports"},
    )

    run_ops._restore_existing_manager_ports(args, metadata_file)

    assert args.manager_ports == "12000,12100"


def test_persisted_run_identity_is_used_by_manager_and_factory(
    tmp_path,
    monkeypatch,
):
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    metadata_file = metadata_dir / "run.json"
    metadata_file.write_text("{}", encoding="utf-8")
    workflow_dir = tmp_path / "workflow"
    workflow_dir.mkdir()
    ctx = run_ops.InstanceContext(
        root=tmp_path,
        paths={"metadata": metadata_dir},
        metadata_file=metadata_file,
        workflow_dir=workflow_dir,
    )
    args = Namespace(
        manager_name="current-run-manager",
        manager_ports="10000:11000",
        no_worker=False,
        env_vars=None,
    )

    run_ops._persist_run_identity(args, ctx)
    monkeypatch.setattr(run_ops, "_get_env_python_version", lambda _prefix: "3.12")
    instance_env = run_ops._build_instance_env(args, ctx, "/backpack/env")

    factory_call = {}

    def capture_factory_start(**kwargs):
        factory_call.update(kwargs)

        def keep_running(timeout):
            raise workers_manager.subprocess.TimeoutExpired("vine_factory", timeout)

        return SimpleNamespace(pid=12345, wait=keep_running)

    monkeypatch.setattr(workers_manager, "_start_vine_factory", capture_factory_start)
    monkeypatch.setattr(workers_manager.os, "getpgid", lambda _pid: 12345)
    monkeypatch.setattr(
        workers_manager,
        "capture_process_identity",
        lambda pid: {
            "pid": pid,
            "pgid": 12345,
            "start_ticks": 100,
            "boot_id": "test-boot",
        },
    )

    workers_manager.start_workers_for_instance(
        tmp_path,
        cli_args=Namespace(),
        instance_env=instance_env,
    )

    persisted = json.loads(metadata_file.read_text(encoding="utf-8"))
    assert persisted["manager_name"] == "current-run-manager"
    assert persisted["manager_ports"] == "10000,11000"
    assert instance_env["VINE_MANAGER_NAME"] == "current-run-manager"
    assert instance_env["VINE_MANAGER_PORTS"] == "10000,11000"
    assert factory_call["manager_name"] == "current-run-manager"


def test_run_workflow_persists_identity_before_environment_setup(
    tmp_path,
    monkeypatch,
):
    metadata_dir = tmp_path / "metadata"
    workflow_dir = tmp_path / "workflow"
    logs_dir = tmp_path / "logs"
    metrics_dir = tmp_path / "metrics"
    for directory in (metadata_dir, workflow_dir, logs_dir, metrics_dir):
        directory.mkdir()

    metadata_file = metadata_dir / "run.json"
    metadata_file.write_text(
        json.dumps({"manager_name": "previous-run-manager"}),
        encoding="utf-8",
    )
    ctx = run_ops.InstanceContext(
        root=tmp_path,
        paths={
            "metadata": metadata_dir,
            "workflow": workflow_dir,
            "logs": logs_dir,
            "metrics": metrics_dir,
        },
        metadata_file=metadata_file,
        workflow_dir=workflow_dir,
        is_new=False,
    )
    args = Namespace(
        instance=str(tmp_path),
        base_dir=str(tmp_path),
        manager_name=None,
        manager_ports="9123,9150",
        measure_performance=False,
        _explicit_args=set(),
    )

    monkeypatch.setattr(run_ops, "_is_new_instance_required", lambda _args: False)
    monkeypatch.setattr(run_ops, "_prepare_existing_instance", lambda _args: ctx)
    monkeypatch.setattr(run_ops, "_resolve_entrypoint", lambda *_args: "workflow.py")
    monkeypatch.setattr(run_ops, "_send_catalog_event", lambda *_args: None)
    monkeypatch.setattr(run_ops, "_start_workers", lambda *_args: None)
    monkeypatch.setattr(run_ops, "_execute_batch", lambda *_args: True)
    recorded_run = {}

    def capture_run(instance_path, base_dir, manager_name=None):
        persisted = json.loads(metadata_file.read_text(encoding="utf-8"))
        assert persisted["manager_name"] == manager_name
        recorded_run.update(
            instance_path=instance_path,
            base_dir=base_dir,
            manager_name=manager_name,
        )

    monkeypatch.setattr(run_ops, "record_instance_run", capture_run)

    def verify_identity_before_setup(current_args, *_args):
        persisted = json.loads(metadata_file.read_text(encoding="utf-8"))
        assert persisted["manager_name"] == current_args.manager_name
        assert persisted["manager_name"] != "previous-run-manager"
        return run_ops.EnvironmentContext()

    monkeypatch.setattr(run_ops, "_setup_environment", verify_identity_before_setup)

    result = run_ops.run_workflow(
        args,
        cleanup_manager=SimpleNamespace(),
        mode="execute",
    )

    assert result == 0
    assert recorded_run == {
        "instance_path": tmp_path,
        "base_dir": tmp_path.parent,
        "manager_name": args.manager_name,
    }
