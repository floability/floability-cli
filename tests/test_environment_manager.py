from __future__ import annotations

import os

from floability.environment_manager import (
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
