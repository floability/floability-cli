from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from floability.environment_manager import EnvCacheInfo, setup_manager_and_worker_envs
from floability.ops import instance as instance_ops
from floability.ops import run as run_ops
from floability.performance_tracker import PerformanceTracker


def _create_backpack(tmp_path: Path) -> Path:
    backpack = tmp_path / "test-backpack"
    (backpack / "workflow").mkdir(parents=True)
    (backpack / "software").mkdir()
    (backpack / "workflow" / "test-backpack.py").write_text(
        "print('ok')\n",
        encoding="utf-8",
    )
    (backpack / "software" / "environment.yml").write_text(
        "name: test\ndependencies:\n  - python=3.12\n",
        encoding="utf-8",
    )
    return backpack


def _create_args(backpack: Path, base_dir: Path) -> Namespace:
    return Namespace(
        backpack=str(backpack),
        backpack_root=None,
        base_dir=str(base_dir),
        data_cache_dir=None,
        data_spec=None,
        compute_spec=None,
        environment=None,
        worker_environment=None,
        manager_name=None,
        manager_ports="9123,9150",
        name="prepared-test",
        skip_data=True,
        data_profile=None,
        data_cache_mode="off",
        force_data_cache=False,
        fingerprint_mode="meta",
        per_instance_env=False,
        measure_performance=False,
    )


def _prepared_artifacts(tmp_path: Path) -> tuple[str, str, str]:
    env_dir = tmp_path / "prepared-env"
    (env_dir / "bin").mkdir(parents=True)
    (env_dir / "bin" / "python").touch()
    worker_pack = tmp_path / "worker.tar.gz"
    manager_pack = tmp_path / "manager.tar.gz"
    worker_pack.touch()
    manager_pack.touch()
    return str(env_dir), str(worker_pack), str(manager_pack)


def _only_instance(base_dir: Path) -> Path:
    instances = [path for path in base_dir.glob("fi_*") if path.is_dir()]
    assert len(instances) == 1
    return instances[0]


def test_instance_create_finishes_ready_with_rebuildable_environment_metadata(
    tmp_path,
    monkeypatch,
):
    backpack = _create_backpack(tmp_path)
    base_dir = tmp_path / "base"
    args = _create_args(backpack, base_dir)
    artifacts = _prepared_artifacts(tmp_path)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(
        instance_ops,
        "setup_manager_and_worker_envs",
        lambda **_kwargs: artifacts,
    )

    assert instance_ops.create_instance(args) == 0

    instance_root = _only_instance(base_dir)
    metadata = json.loads(
        (instance_root / "metadata" / "run.json").read_text(encoding="utf-8")
    )
    assert metadata["status"]["state"] == "ready"
    assert metadata["status"]["success"] is True
    assert metadata["status"]["completed_at"]
    assert metadata["preparation"]["state"] == "ready"
    assert metadata["environment_spec"] == str(
        (backpack / "software" / "environment.yml").resolve()
    )
    assert metadata["worker_environment_spec"] is None
    assert metadata["per_instance_env"] is False
    assert metadata["environment"]["strategy"] == "shared"
    assert metadata["env_dir"] == str(Path(artifacts[0]).resolve())
    assert metadata["worker_environment_pack"] == str(Path(artifacts[1]).resolve())
    assert metadata["manager_environment_pack"] == str(Path(artifacts[2]).resolve())


def test_instance_create_failure_is_retained_and_finalized(tmp_path, monkeypatch):
    backpack = _create_backpack(tmp_path)
    base_dir = tmp_path / "base"
    args = _create_args(backpack, base_dir)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))

    def fail_environment(**_kwargs):
        raise RuntimeError("environment build failed")

    monkeypatch.setattr(
        instance_ops,
        "setup_manager_and_worker_envs",
        fail_environment,
    )

    assert instance_ops.create_instance(args) == 1

    instance_root = _only_instance(base_dir)
    metadata = json.loads(
        (instance_root / "metadata" / "run.json").read_text(encoding="utf-8")
    )
    assert metadata["status"]["state"] == "failed"
    assert metadata["status"]["success"] is False
    assert metadata["status"]["error"] == "environment build failed"
    assert metadata["preparation"]["state"] == "failed"
    assert metadata["preparation"]["completed_at"]


def test_instance_create_data_failure_is_retained_and_finalized(
    tmp_path,
    monkeypatch,
):
    backpack = _create_backpack(tmp_path)
    (backpack / "data").mkdir()
    (backpack / "data" / "data.yml").write_text(
        "version: 1\nitems: []\n",
        encoding="utf-8",
    )
    base_dir = tmp_path / "base"
    args = _create_args(backpack, base_dir)
    args.skip_data = False
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(
        "floability.data.data_handler.execute_default_data_operation",
        lambda **_kwargs: False,
    )
    monkeypatch.setattr(
        instance_ops,
        "setup_manager_and_worker_envs",
        lambda **_kwargs: pytest.fail("environment setup followed failed data"),
    )

    assert instance_ops.create_instance(args) == 1

    instance_root = _only_instance(base_dir)
    metadata = json.loads(
        (instance_root / "metadata" / "run.json").read_text(encoding="utf-8")
    )
    assert metadata["status"]["state"] == "failed"
    assert metadata["status"]["error"] == "Data materialization failed."
    assert metadata["preparation"]["state"] == "failed"


def test_failed_preparation_is_rejected_before_instance_lock(tmp_path):
    metadata_dir = tmp_path / "metadata"
    workflow_dir = tmp_path / "workflow"
    metadata_dir.mkdir()
    workflow_dir.mkdir()
    (metadata_dir / "run.json").write_text(
        json.dumps(
            {
                "preparation": {
                    "state": "failed",
                    "error": "environment build failed",
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="preparation is not ready"):
        run_ops._prepare_existing_instance(Namespace(instance=str(tmp_path)))

    assert not (metadata_dir / "instance.lock").exists()


def test_existing_instance_restores_manager_and_distinct_worker_artifacts(
    tmp_path,
    monkeypatch,
):
    manager_spec = tmp_path / "manager.yml"
    worker_spec = tmp_path / "worker.yml"
    manager_spec.touch()
    worker_spec.touch()
    metadata_dir = tmp_path / "metadata"
    workflow_dir = tmp_path / "workflow"
    metadata_dir.mkdir()
    workflow_dir.mkdir()
    metadata_file = metadata_dir / "run.json"
    metadata_file.write_text(
        json.dumps(
            {
                "environment": {
                    "strategy": "per-instance",
                    "manager_spec": str(manager_spec),
                    "worker_spec": str(worker_spec),
                }
            }
        ),
        encoding="utf-8",
    )
    ctx = run_ops.InstanceContext(
        root=tmp_path,
        paths={"metadata": metadata_dir, "workflow": workflow_dir},
        metadata_file=metadata_file,
        workflow_dir=workflow_dir,
        is_new=False,
    )
    artifacts = _prepared_artifacts(tmp_path)
    setup_call = {}

    def restore_artifacts(**kwargs):
        setup_call.update(kwargs)
        return artifacts

    monkeypatch.setattr(run_ops, "setup_manager_and_worker_envs", restore_artifacts)
    monkeypatch.setattr(run_ops, "_build_instance_env", lambda *_args: {"OK": "1"})
    monkeypatch.setattr(run_ops, "_display_env_info", lambda *_args: None)

    result = run_ops._restore_existing_instance_environment(
        Namespace(base_dir=str(tmp_path)),
        ctx,
        PerformanceTracker(output_dir=str(tmp_path), enabled=False),
    )

    assert setup_call["environment_spec"] == str(manager_spec)
    assert setup_call["worker_environment_spec"] == str(worker_spec)
    assert setup_call["per_instance_env"] is True
    assert result.env_dir == artifacts[0]
    assert result.worker_pack == artifacts[1]
    persisted = json.loads(metadata_file.read_text(encoding="utf-8"))
    assert persisted["worker_environment_spec"] == str(worker_spec.resolve())
    assert persisted["worker_environment_pack"] == str(Path(artifacts[1]).resolve())


def test_per_instance_setup_reuses_a_valid_extracted_environment(
    tmp_path,
    monkeypatch,
):
    env_spec = tmp_path / "environment.yml"
    env_spec.touch()
    shared_env = tmp_path / "shared-env"
    shared_tar = tmp_path / "shared.tar.gz"
    current_env = tmp_path / "instance" / "current_conda_env"
    (current_env / "bin").mkdir(parents=True)
    (current_env / "bin" / "python").touch()
    cache_info = EnvCacheInfo("hash", shared_env, shared_tar)
    monkeypatch.setattr(
        "floability.environment_manager.ensure_shared_env",
        lambda *_args, **_kwargs: cache_info,
    )
    monkeypatch.setattr(
        "floability.environment_manager.extract_env_to_instance",
        lambda *_args, **_kwargs: pytest.fail("valid environment was re-extracted"),
    )

    env_dir, worker_pack, manager_pack = setup_manager_and_worker_envs(
        environment_spec=str(env_spec),
        worker_environment_spec=None,
        base_dir=str(tmp_path),
        instance_root=str(tmp_path / "instance"),
        per_instance_env=True,
    )

    assert env_dir == str(current_env)
    assert worker_pack == str(shared_tar)
    assert manager_pack == str(shared_tar)
