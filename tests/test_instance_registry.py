from __future__ import annotations

import json
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from floability import instance_registry
from floability.ops.instance import go_to_latest_instance


def _isolated_registry(tmp_path, monkeypatch) -> Path:
    xdg_data_home = tmp_path / "xdg"
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg_data_home))
    return xdg_data_home / "floability"


def _make_instance(base_dir: Path, name: str) -> Path:
    instance_path = base_dir / name
    (instance_path / "metadata").mkdir(parents=True)
    return instance_path


def test_registered_but_never_run_instance_sorts_after_run_instances(
    tmp_path,
    monkeypatch,
):
    _isolated_registry(tmp_path, monkeypatch)
    base_dir = tmp_path / "base"
    never_run = _make_instance(base_dir, "fi_never")
    older_run = _make_instance(base_dir, "fi_older")
    newer_run = _make_instance(base_dir, "fi_newer")

    instance_registry.register_instance(never_run, "never-manager")
    instance_registry.record_instance_run(
        older_run,
        base_dir,
        ran_at="2026-08-24T10:00:00Z",
    )
    instance_registry.record_instance_run(
        newer_run,
        base_dir,
        ran_at="2026-08-24T11:00:00Z",
    )

    statuses = instance_registry.get_registered_instances_status()

    assert list(statuses) == ["fi_newer", "fi_older", "fi_never"]
    assert statuses["fi_never"]["last_run_at"] is None
    assert statuses["fi_newer"]["base_dir"] == str(base_dir.resolve())


def test_registering_created_instance_does_not_mark_base_as_recent(
    tmp_path,
    monkeypatch,
):
    registry_dir = _isolated_registry(tmp_path, monkeypatch)
    base_dir = tmp_path / "base"
    instance_path = _make_instance(base_dir, "fi_created")

    instance_registry.register_instance(
        instance_path,
        "create-manager",
        base_dir=base_dir,
    )

    assert instance_registry.get_recent_base_directories() == []
    assert not (registry_dir / "base-directories.json").exists()


def test_recent_bases_sort_by_timestamp_and_retain_only_ten(
    tmp_path,
    monkeypatch,
):
    _isolated_registry(tmp_path, monkeypatch)
    expected = []
    for day in range(1, 13):
        base_dir = tmp_path / f"base-{day:02d}"
        instance_path = _make_instance(base_dir, f"fi_{day:02d}")
        instance_registry.record_instance_run(
            instance_path,
            base_dir,
            ran_at=f"2026-08-{day:02d}T12:00:00Z",
        )
        expected.insert(0, str(base_dir.resolve()))

    registry_path = instance_registry.base_directories_registry_path()
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    data["base_directories"].reverse()
    registry_path.write_text(json.dumps(data), encoding="utf-8")

    entries = instance_registry.get_recent_base_directories()

    assert [entry["path"] for entry in entries] == expected[:10]
    assert len(entries) == instance_registry.MAX_RECENT_BASE_DIRECTORIES


def test_recent_base_pruning_fills_history_with_older_valid_entries(
    tmp_path,
    monkeypatch,
):
    registry_dir = _isolated_registry(tmp_path, monkeypatch)
    entries = []
    for day in range(1, 12):
        base_dir = tmp_path / f"base-{day:02d}"
        base_dir.mkdir()
        entries.append(
            {
                "path": str(base_dir),
                "last_used_at": f"2026-08-{day:02d}T12:00:00Z",
            }
        )
    newest_base = Path(entries[-1]["path"])
    newest_base.rmdir()
    registry_dir.mkdir(parents=True, exist_ok=True)
    (registry_dir / "base-directories.json").write_text(
        json.dumps({"schema_version": 1, "base_directories": entries}),
        encoding="utf-8",
    )

    maintained = instance_registry.get_recent_base_directories()

    assert len(maintained) == instance_registry.MAX_RECENT_BASE_DIRECTORIES
    assert str(newest_base.resolve()) not in {
        entry["path"] for entry in maintained
    }


def test_reusing_base_updates_timestamp_without_duplicate(tmp_path, monkeypatch):
    _isolated_registry(tmp_path, monkeypatch)
    base_dir = tmp_path / "base"
    first = _make_instance(base_dir, "fi_first")
    second = _make_instance(base_dir, "fi_second")

    instance_registry.record_instance_run(
        first,
        base_dir,
        ran_at="2026-08-24T10:00:00Z",
    )
    instance_registry.record_instance_run(
        second,
        base_dir,
        ran_at="2026-08-24T12:00:00Z",
    )

    entries = instance_registry.get_recent_base_directories()
    assert entries == [
        {
            "path": str(base_dir.resolve()),
            "last_used_at": "2026-08-24T12:00:00Z",
        }
    ]


def test_latest_explicit_base_selects_its_last_run_without_changing_current_base(
    tmp_path,
    monkeypatch,
    capsys,
):
    _isolated_registry(tmp_path, monkeypatch)
    base_a = tmp_path / "base-a"
    base_b = tmp_path / "base-b"
    old_a = _make_instance(base_a, "fi_old_a")
    new_a = _make_instance(base_a, "fi_new_a")
    new_b = _make_instance(base_b, "fi_new_b")
    instance_registry.record_instance_run(
        old_a, base_a, ran_at="2026-08-24T09:00:00Z"
    )
    instance_registry.record_instance_run(
        new_a, base_a, ran_at="2026-08-24T10:00:00Z"
    )
    instance_registry.record_instance_run(
        new_b, base_b, ran_at="2026-08-24T11:00:00Z"
    )

    result = go_to_latest_instance(
        Namespace(base_dir=str(base_a), _explicit_args={"base_dir"})
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.out == f"{new_a.resolve()}\n"
    assert captured.err == ""
    assert instance_registry.get_recent_base_directories()[0]["path"] == str(
        base_b.resolve()
    )


def test_latest_without_base_uses_most_recent_timestamp_not_file_order(
    tmp_path,
    monkeypatch,
    capsys,
):
    _isolated_registry(tmp_path, monkeypatch)
    older_base = tmp_path / "older"
    newer_base = tmp_path / "newer"
    older = _make_instance(older_base, "fi_older")
    newer = _make_instance(newer_base, "fi_newer")
    instance_registry.record_instance_run(
        older, older_base, ran_at="2026-08-24T10:00:00Z"
    )
    instance_registry.record_instance_run(
        newer, newer_base, ran_at="2026-08-24T11:00:00Z"
    )
    registry_path = instance_registry.base_directories_registry_path()
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    data["base_directories"].reverse()
    registry_path.write_text(json.dumps(data), encoding="utf-8")

    result = go_to_latest_instance(Namespace(base_dir=None, _explicit_args=set()))

    captured = capsys.readouterr()
    assert result == 0
    assert captured.out == f"{newer.resolve()}\n"
    assert captured.err == ""


def test_latest_repairs_partially_updated_base_history(
    tmp_path,
    monkeypatch,
    capsys,
):
    registry_dir = _isolated_registry(tmp_path, monkeypatch)
    older_base = tmp_path / "older"
    newer_base = tmp_path / "newer"
    older = _make_instance(older_base, "fi_older")
    newer = _make_instance(newer_base, "fi_newer")
    instance_registry.record_instance_run(
        older, older_base, ran_at="2026-08-24T10:00:00Z"
    )
    instance_registry.record_instance_run(
        newer, newer_base, ran_at="2026-08-24T11:00:00Z"
    )
    (registry_dir / "base-directories.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "base_directories": [
                    {
                        "path": str(older_base.resolve()),
                        "last_used_at": "2026-08-24T10:00:00Z",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = go_to_latest_instance(Namespace(base_dir=None, _explicit_args=set()))

    captured = capsys.readouterr()
    assert result == 0
    assert captured.out == f"{newer.resolve()}\n"


def test_latest_missing_explicit_base_does_not_create_it(
    tmp_path,
    monkeypatch,
    capsys,
):
    _isolated_registry(tmp_path, monkeypatch)
    missing_base = tmp_path / "missing"

    result = go_to_latest_instance(
        Namespace(base_dir=str(missing_base), _explicit_args={"base_dir"})
    )

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert "Base directory not found" in captured.err
    assert not missing_base.exists()


def test_legacy_completed_run_is_migrated_but_created_instance_is_not(
    tmp_path,
    monkeypatch,
):
    registry_dir = _isolated_registry(tmp_path, monkeypatch)
    base_dir = tmp_path / "base"
    completed = _make_instance(base_dir, "fi_completed")
    created = _make_instance(base_dir, "fi_created")
    (completed / "metadata" / "run.json").write_text(
        json.dumps(
            {
                "status": {
                    "completed_at": "2026-08-24T12:00:00Z",
                }
            }
        ),
        encoding="utf-8",
    )
    (created / "metadata" / "run.json").write_text(
        json.dumps({"status": {"completed_at": None}}),
        encoding="utf-8",
    )
    registry_dir.mkdir(parents=True)
    (registry_dir / "instances.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "instances": {
                    "completed": {
                        "path": str(completed),
                        "created_at": "2026-08-24T08:00:00Z",
                        "last_seen": "2026-08-24T08:00:00Z",
                    },
                    "created": {
                        "path": str(created),
                        "created_at": "2026-08-24T09:00:00Z",
                        "last_seen": "2026-08-24T09:00:00Z",
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    statuses = instance_registry.get_registered_instances_status()

    assert statuses["completed"]["last_run_at"] == "2026-08-24T12:00:00Z"
    assert statuses["created"]["last_run_at"] is None
    assert statuses["completed"]["base_dir"] == str(base_dir.resolve())


def test_missing_instances_are_pruned_but_unknown_paths_are_retained(
    tmp_path,
    monkeypatch,
):
    registry_dir = _isolated_registry(tmp_path, monkeypatch)
    inaccessible = tmp_path / "inaccessible" / "fi_unknown"
    missing = tmp_path / "missing" / "fi_missing"
    registry_dir.mkdir(parents=True)
    registry_path = registry_dir / "instances.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "instances": {
                    "unknown": {"path": str(inaccessible), "last_run_at": None},
                    "missing": {"path": str(missing), "last_run_at": None},
                },
            }
        ),
        encoding="utf-8",
    )
    real_path_state = instance_registry._path_state
    monkeypatch.setattr(
        instance_registry,
        "_path_state",
        lambda path: (
            "unknown" if path == inaccessible.resolve() else real_path_state(path)
        ),
    )

    statuses = instance_registry.get_registered_instances_status()

    assert list(statuses) == ["unknown"]
    persisted = json.loads(registry_path.read_text(encoding="utf-8"))
    assert list(persisted["instances"]) == ["unknown"]


def test_corrupt_base_registry_is_preserved_and_latest_returns_nonzero(
    tmp_path,
    monkeypatch,
    capsys,
):
    registry_dir = _isolated_registry(tmp_path, monkeypatch)
    base_dir = tmp_path / "base"
    instance_path = _make_instance(base_dir, "fi_test")
    instance_registry.record_instance_run(
        instance_path,
        base_dir,
        ran_at="2026-08-24T12:00:00Z",
    )
    base_registry = registry_dir / "base-directories.json"
    base_registry.write_text("{not-json", encoding="utf-8")

    result = go_to_latest_instance(Namespace(base_dir=None, _explicit_args=set()))

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert "Could not read registry" in captured.err
    assert base_registry.read_text(encoding="utf-8") == "{not-json"


def test_concurrent_run_updates_preserve_all_instances(tmp_path, monkeypatch):
    _isolated_registry(tmp_path, monkeypatch)
    base_dir = tmp_path / "base"
    instances = [_make_instance(base_dir, f"fi_{index}") for index in range(8)]

    def record(index: int) -> None:
        instance_registry.record_instance_run(
            instances[index],
            base_dir,
            ran_at=f"2026-08-24T12:00:{index:02d}Z",
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(record, range(len(instances))))

    statuses = instance_registry.get_registered_instances_status()
    assert set(statuses) == {f"fi_{index}" for index in range(8)}
    assert list(statuses)[0] == "fi_7"
