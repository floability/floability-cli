from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from floability.environment_manager import (
    EnvironmentSetupError,
    EnvironmentStorageError,
    _create_conda_env,
    _ensure_runtime_dependencies,
    _pack_conda_env,
    _resolve_env_cache_paths,
    _run_streaming_command,
    _select_pixi_prefix,
    _validate_pixi_compatible_spec,
    ensure_shared_env,
)
from floability.environment_toolchain import EnvironmentPlan, EnvironmentTool


def _conda_plan() -> EnvironmentPlan:
    return EnvironmentPlan(
        environment_type="python",
        spec_format="conda-yaml",
        creator=EnvironmentTool("create", "conda", "/tools/conda", "test"),
        artifact_format="conda-pack",
        packer=EnvironmentTool("pack", "conda-pack", "/tools/conda-pack", "test"),
        unpacker=EnvironmentTool("unpack", "conda-unpack", None),
        runner=EnvironmentTool("run", "prefix-activation", "/bin/bash"),
    )


def test_versioned_manager_dependencies_are_preserved():
    dependencies = [
        "python=3.11",
        "jupyter>=1.0",
        "cloudpickle=3.0",
        "ndcctools=7.16.0",
        {"pip": ["fastjet==3.4.2.1"]},
    ]
    original_dependencies = list(dependencies)

    warnings = _ensure_runtime_dependencies(dependencies, is_worker_env=False)

    assert dependencies == original_dependencies
    assert warnings == []


def test_channel_qualified_specs_are_recognized():
    dependencies = [
        "conda-forge::python=3.11",
        "conda-forge::jupyter=1.1.1",
        "conda-forge::cloudpickle=3.1.2",
        "conda-forge::ndcctools=7.17.1",
    ]

    warnings = _ensure_runtime_dependencies(dependencies, is_worker_env=False)

    assert len(dependencies) == 4
    assert warnings == []


def test_missing_manager_dependencies_are_added_with_warnings():
    dependencies = [{"pip": ["fastjet==3.4.2.1"]}]

    warnings = _ensure_runtime_dependencies(dependencies, is_worker_env=False)

    assert dependencies == [
        {"pip": ["fastjet==3.4.2.1"]},
        "python=3.12",
        "jupyter",
        "cloudpickle",
    ]
    assert warnings == [
        "'ndcctools' is not in environment.yml. Add "
        "'ndcctools=7.17.1' if this workflow uses TaskVine.",
        "'python' is not in environment.yml. Floability added 'python=3.12'.",
        "'jupyter' is not in environment.yml. Floability added 'jupyter'.",
        "'cloudpickle' is not in environment.yml. Floability added 'cloudpickle'.",
    ]


def test_worker_environment_does_not_add_jupyter_or_ndcctools():
    dependencies = []

    warnings = _ensure_runtime_dependencies(dependencies, is_worker_env=True)

    assert dependencies == ["python=3.12", "cloudpickle"]
    assert any("ndcctools=7.17.1" in warning for warning in warnings)
    assert all("Floability added 'jupyter'" not in warning for warning in warnings)


def test_environment_name_does_not_change_cache_identity(tmp_path):
    first = tmp_path / "first.yml"
    second = tmp_path / "second.yml"
    first.write_text("name: first\ndependencies:\n  - python=3.12\n")
    second.write_text("name: second\ndependencies:\n  - python=3.12\n")

    first_cache = _resolve_env_cache_paths(str(first), str(tmp_path / "base"))
    second_cache = _resolve_env_cache_paths(str(second), str(tmp_path / "base"))

    assert first_cache.file_hash == second_cache.file_hash
    assert first_cache.shared_env_dir == second_cache.shared_env_dir


def test_creator_and_platform_identity_separate_pixi_from_conda(tmp_path):
    spec = tmp_path / "environment.yml"
    spec.write_text("name: example\ndependencies:\n  - python=3.12\n")
    conda_cache = _resolve_env_cache_paths(str(spec), str(tmp_path / "base"), "conda")
    pixi_cache = _resolve_env_cache_paths(str(spec), str(tmp_path / "base"), "pixi")

    assert conda_cache.file_hash != pixi_cache.file_hash
    assert pixi_cache.root.name.startswith("env_pixi_")
    assert pixi_cache.shared_env_dir == pixi_cache.root / ".pixi/envs/default"


def test_pixi_rejects_yaml_variables_without_rejecting_runtime_variables():
    with pytest.raises(EnvironmentSetupError, match="top-level 'variables:'") as error:
        _validate_pixi_compatible_spec(
            {
                "dependencies": ["python=3.12"],
                "variables": {"STATIC_SETTING": "value"},
            },
            "environment.yml",
        )
    assert "manager, port, and --env-vars values are unaffected" in str(error.value)


@pytest.mark.parametrize(
    "pip_entry",
    [
        "-r requirements.txt",
        "--extra-index-url https://example.invalid/simple",
        "-e .",
        "git+https://example.invalid/project.git",
    ],
)
def test_pixi_rejects_unsupported_pip_import_forms(pip_entry):
    with pytest.raises(EnvironmentSetupError, match="environment-creator conda"):
        _validate_pixi_compatible_spec(
            {"dependencies": [{"pip": [pip_entry]}]},
            "environment.yml",
        )


def test_pixi_accepts_regular_pip_requirements_with_extras():
    _validate_pixi_compatible_spec(
        {"dependencies": [{"pip": ["tqdm[notebook]>=4"]}]},
        "environment.yml",
    )


def test_pixi_prefix_must_be_default_and_inside_cache(tmp_path):
    root = tmp_path / "cache-entry"
    prefix = root / ".pixi" / "envs" / "default"
    (prefix / "bin").mkdir(parents=True)
    (prefix / "bin" / "python").touch()

    assert _select_pixi_prefix(
        {"environments_info": [{"name": "default", "prefix": str(prefix)}]},
        root,
    ) == prefix.resolve()

    outside = tmp_path / "detached" / "default"
    (outside / "bin").mkdir(parents=True)
    (outside / "bin" / "python").touch()
    with pytest.raises(EnvironmentSetupError, match="outside"):
        _select_pixi_prefix(
            {"environments_info": [{"name": "default", "prefix": str(outside)}]},
            root,
        )


def test_recreated_prefix_always_rebuilds_existing_archive(tmp_path, monkeypatch):
    spec = tmp_path / "environment.yml"
    spec.write_text("name: example\ndependencies:\n  - python=3.12\n")
    base = tmp_path / "base"
    cache = _resolve_env_cache_paths(str(spec), str(base), "conda")
    cache.tar_path.touch()
    packed = []

    def create_environment(_spec, env_path, _is_worker, **_kwargs):
        python = Path(env_path) / "bin" / "python"
        python.parent.mkdir(parents=True)
        python.touch()

    def pack_environment(env_path, tar_path, **_kwargs):
        packed.append((env_path, tar_path))

    monkeypatch.setattr(
        "floability.environment_manager._create_conda_env",
        create_environment,
    )
    monkeypatch.setattr(
        "floability.environment_manager._pack_conda_env",
        pack_environment,
    )
    monkeypatch.setattr(
        "floability.environment_manager._make_dir_readonly",
        lambda _path: None,
    )

    result = ensure_shared_env(str(spec), str(base), plan=_conda_plan())

    assert result.shared_env_dir == cache.shared_env_dir
    assert packed == [(str(cache.shared_env_dir), str(cache.tar_path))]


def test_failed_creation_removes_partial_cache_entry(tmp_path, monkeypatch):
    spec = tmp_path / "environment.yml"
    spec.write_text("name: example\ndependencies:\n  - python=3.12\n")
    base = tmp_path / "base"
    cache = _resolve_env_cache_paths(str(spec), str(base), "conda")

    def fail_creation(_spec, env_path, _is_worker, **_kwargs):
        partial = Path(env_path) / "bin"
        partial.mkdir(parents=True)
        raise EnvironmentSetupError("creation stopped")

    monkeypatch.setattr(
        "floability.environment_manager._create_conda_env",
        fail_creation,
    )

    with pytest.raises(EnvironmentSetupError, match="creation stopped"):
        ensure_shared_env(str(spec), str(base), plan=_conda_plan())

    assert not cache.root.exists()


def test_pack_repairs_only_conda_history_and_ignores_dangling_symlinks(
    tmp_path,
    monkeypatch,
    capsys,
):
    env_path = tmp_path / "environment"
    history_file = env_path / "conda-meta" / "history"
    history_file.parent.mkdir(parents=True)
    history_file.touch()
    os.utime(history_file, (0, 0))
    (env_path / "dangling-documentation-link").symlink_to("missing-target")
    tar_path = tmp_path / "environment.tar.gz"
    calls = []

    monkeypatch.setattr(
        "floability.environment_manager._run_streaming_command",
        lambda command: calls.append(command),
    )

    _pack_conda_env(str(env_path), str(tar_path))

    assert history_file.stat().st_mtime > 0
    assert calls == [
        [
            "conda-pack",
            "-p",
            str(env_path),
            "-o",
            str(tar_path),
            "--force",
        ]
    ]
    assert "Could not fix timestamp" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "failure_text",
    [
        "OSError: [Errno 28] No space left on device",
        "OSError: [Errno 122] Disk quota exceeded",
    ],
)
def test_conda_storage_failure_has_actionable_cleanup_guidance(
    tmp_path,
    monkeypatch,
    capsys,
    failure_text,
):
    fake_conda = tmp_path / "fake-conda"
    fake_conda.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' '{failure_text}'\n"
        "exit 1\n"
    )
    fake_conda.chmod(fake_conda.stat().st_mode | stat.S_IXUSR)
    env_yml = tmp_path / "environment.yml"
    env_yml.write_text(
        "name: storage-test\n"
        "channels:\n"
        "  - conda-forge\n"
        "dependencies:\n"
        "  - python=3.12\n"
        "  - jupyter\n"
        "  - cloudpickle\n"
    )
    base_dir = tmp_path / "floability-base"
    env_path = base_dir / "flo_common_env" / "extracted_envs" / "env_test"
    with pytest.raises(EnvironmentStorageError) as captured:
        _create_conda_env(
            str(env_yml),
            str(env_path),
            is_worker_env=False,
            conda_executable=str(fake_conda),
        )

    message = str(captured.value)
    output = capsys.readouterr().out
    assert failure_text in output
    assert "no available space or the account quota was exceeded" in message
    assert f"--base-dir {base_dir}" in message
    assert "--mode data-and-env --dry-run" in message
    assert "original Conda output appears above" in message


def test_unrelated_conda_failure_is_not_reported_as_storage_exhaustion(
    tmp_path,
    monkeypatch,
    capsys,
):
    fake_conda = tmp_path / "fake-conda"
    fake_conda.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' 'PackagesNotFoundError: missing-package'\n"
        "exit 1\n"
    )
    fake_conda.chmod(fake_conda.stat().st_mode | stat.S_IXUSR)
    env_yml = tmp_path / "environment.yml"
    env_yml.write_text(
        "name: solver-test\n"
        "dependencies:\n"
        "  - python=3.12\n"
        "  - jupyter\n"
        "  - cloudpickle\n"
    )
    env_path = tmp_path / "base" / "flo_common_env" / "extracted_envs" / "env"
    with pytest.raises(EnvironmentSetupError, match="creation failed"):
        _create_conda_env(
            str(env_yml),
            str(env_path),
            is_worker_env=False,
            conda_executable=str(fake_conda),
        )

    assert "PackagesNotFoundError" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("output", "error_type", "message"),
    [
        (
            "OSError: [Errno 28] No space left on device",
            EnvironmentStorageError,
            "pack the workflow environment",
        ),
        (
            "CondaPackError: editable package",
            EnvironmentSetupError,
            "Environment packing failed",
        ),
    ],
)
def test_environment_pack_failure_is_actionable(
    tmp_path,
    monkeypatch,
    output,
    error_type,
    message,
):
    env_path = tmp_path / "base" / "flo_common_env" / "extracted_envs" / "env"
    history = env_path / "conda-meta" / "history"
    history.parent.mkdir(parents=True)
    history.touch()
    tar_path = tmp_path / "base" / "flo_common_env" / "tarballs" / "env.tar.gz"

    def fail_pack(command):
        raise subprocess.CalledProcessError(1, command, output=output)

    monkeypatch.setattr(
        "floability.environment_manager._run_streaming_command",
        fail_pack,
    )

    with pytest.raises(error_type, match=message):
        _pack_conda_env(str(env_path), str(tar_path))


def test_missing_environment_command_has_activation_guidance(monkeypatch):
    def missing_command(*_args, **_kwargs):
        raise FileNotFoundError("missing")

    monkeypatch.setattr(
        "floability.environment_manager.subprocess.Popen",
        missing_command,
    )

    with pytest.raises(EnvironmentSetupError) as captured:
        _run_streaming_command(["conda-pack", "--version"])

    message = str(captured.value)
    assert "Required environment command was not found: conda-pack" in message
    assert "floability --version --verbose" in message
