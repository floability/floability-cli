from __future__ import annotations

import os
import stat
import subprocess

import pytest

from floability.environment_manager import (
    EnvironmentStorageError,
    _create_conda_env,
    _ensure_runtime_dependencies,
    _pack_conda_env,
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
        "floability.environment_manager.subprocess.run",
        lambda command, check: calls.append((command, check)),
    )

    _pack_conda_env(str(env_path), str(tar_path))

    assert history_file.stat().st_mtime > 0
    assert calls == [
        (
            [
                "conda-pack",
                "-p",
                str(env_path),
                "-o",
                str(tar_path),
                "--force",
            ],
            True,
        )
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
    monkeypatch.setattr(
        "floability.environment_manager.get_conda_executable",
        lambda: str(fake_conda),
    )

    with pytest.raises(EnvironmentStorageError) as captured:
        _create_conda_env(str(env_yml), str(env_path), is_worker_env=False)

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
    monkeypatch.setattr(
        "floability.environment_manager.get_conda_executable",
        lambda: str(fake_conda),
    )

    with pytest.raises(subprocess.CalledProcessError):
        _create_conda_env(str(env_yml), str(env_path), is_worker_env=False)

    assert "PackagesNotFoundError" in capsys.readouterr().out
