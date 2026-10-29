import json
import tarfile
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

import floability.data.data_handler as data_handler
from floability.data.data_handler import (
    _fetch_single_item,
    _publish_cache_build,
    _publish_staged_result,
)


def _write_zip(path: Path, content: bytes = b"zip content") -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("dataset/file.txt", content)


def _write_tar(path: Path, content: bytes = b"tar content") -> None:
    member = tarfile.TarInfo("dataset/file.txt")
    member.size = len(content)
    with tarfile.open(path, "w:gz") as archive:
        archive.addfile(member, BytesIO(content))


@pytest.mark.unit
@pytest.mark.parametrize(
    ("operation", "writer", "expected"),
    [
        ("unzip", _write_zip, b"zip content"),
        ("untar", _write_tar, b"tar content"),
    ],
)
def test_uncached_fetch_post_processes_archive(
    tmp_path: Path, operation: str, writer, expected: bytes
):
    archive_path = tmp_path / "source.archive"
    writer(archive_path)
    workflow = tmp_path / "workflow"
    item = {
        "name": "archive",
        "source_type": "fs",
        "source": str(archive_path),
        "target_location": "data/result",
        "post_process": {"operation": operation},
    }

    result = _fetch_single_item(
        item,
        tmp_path,
        data_cache_mode="off",
        target_prefix=workflow,
    )

    assert result is item
    assert (workflow / "data/result/dataset/file.txt").read_bytes() == expected
    assert not (workflow / "data/.floability-data-staging").exists()


@pytest.mark.unit
def test_uncached_post_process_force_preserves_target_after_failure(tmp_path: Path):
    invalid_archive = tmp_path / "invalid.zip"
    invalid_archive.write_bytes(b"not a ZIP archive")
    workflow = tmp_path / "workflow"
    target = workflow / "data/result"
    target.mkdir(parents=True)
    existing_file = target / "existing.txt"
    existing_file.write_text("keep", encoding="utf-8")
    item = {
        "name": "archive",
        "source_type": "fs",
        "source": str(invalid_archive),
        "target_location": "data/result",
        "post_process": {"operation": "unzip"},
    }

    result = _fetch_single_item(
        item,
        tmp_path,
        force=True,
        data_cache_mode="off",
        target_prefix=workflow,
    )

    assert result is None
    assert existing_file.read_text(encoding="utf-8") == "keep"
    assert not (workflow / "data/.floability-data-staging").exists()


@pytest.mark.unit
def test_uncached_post_process_tries_next_source_only_after_download_failure(
    tmp_path: Path,
):
    valid_archive = tmp_path / "valid.zip"
    _write_zip(valid_archive)
    workflow = tmp_path / "workflow"
    item = {
        "name": "archive",
        "source_type": "multi",
        "sources": [
            {"source_type": "fs", "source": str(tmp_path / "missing.zip")},
            {"source_type": "fs", "source": str(valid_archive)},
        ],
        "target_location": "data/result",
        "post_process": {"operation": "unzip"},
    }

    result = _fetch_single_item(
        item,
        tmp_path,
        data_cache_mode="off",
        target_prefix=workflow,
    )

    assert result is item
    assert (workflow / "data/result/dataset/file.txt").is_file()


@pytest.mark.unit
def test_uncached_post_process_does_not_fallback_after_download(tmp_path: Path):
    invalid_archive = tmp_path / "invalid.zip"
    invalid_archive.write_bytes(b"not a ZIP archive")
    valid_archive = tmp_path / "valid.zip"
    _write_zip(valid_archive)
    workflow = tmp_path / "workflow"
    item = {
        "name": "archive",
        "source_type": "multi",
        "sources": [
            {"source_type": "fs", "source": str(invalid_archive)},
            {"source_type": "fs", "source": str(valid_archive)},
        ],
        "target_location": "data/result",
        "post_process": {"operation": "unzip"},
    }

    result = _fetch_single_item(
        item,
        tmp_path,
        data_cache_mode="off",
        target_prefix=workflow,
    )

    assert result is None
    assert not (workflow / "data/result").exists()
    assert not (workflow / "data/.floability-data-staging").exists()


@pytest.mark.unit
def test_uncached_post_process_warns_when_checksum_is_configured(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    archive_path = tmp_path / "source.zip"
    _write_zip(archive_path)
    item = {
        "name": "archive",
        "source_type": "fs",
        "source": str(archive_path),
        "target_location": "data/result",
        "checksum": "sha256:not-validated",
        "post_process": {"operation": "unzip"},
    }

    assert _fetch_single_item(
        item,
        tmp_path,
        data_cache_mode="off",
        target_prefix=tmp_path / "workflow",
    )

    output = capsys.readouterr().out
    assert "checksum validation is not currently supported" in output


@pytest.mark.unit
def test_uncached_regular_file_force_preserves_target_after_failure(tmp_path: Path):
    workflow = tmp_path / "workflow"
    target = workflow / "data/file.txt"
    target.parent.mkdir(parents=True)
    target.write_text("keep", encoding="utf-8")
    item = {
        "name": "file",
        "source_type": "fs",
        "source": str(tmp_path / "missing.txt"),
        "target_location": "data/file.txt",
    }

    result = _fetch_single_item(
        item,
        tmp_path,
        force=True,
        data_cache_mode="off",
        target_prefix=workflow,
    )

    assert result is None
    assert target.read_text(encoding="utf-8") == "keep"
    assert not (workflow / "data/.floability-data-staging").exists()


@pytest.mark.unit
def test_uncached_regular_file_force_replaces_target_after_download(tmp_path: Path):
    source = tmp_path / "source.txt"
    source.write_text("replacement", encoding="utf-8")
    workflow = tmp_path / "workflow"
    target = workflow / "data/file.txt"
    target.parent.mkdir(parents=True)
    target.write_text("old", encoding="utf-8")
    item = {
        "name": "file",
        "source_type": "fs",
        "source": str(source),
        "target_location": "data/file.txt",
    }

    result = _fetch_single_item(
        item,
        tmp_path,
        force=True,
        data_cache_mode="off",
        target_prefix=workflow,
    )

    assert result is item
    assert target.read_text(encoding="utf-8") == "replacement"
    assert not (workflow / "data/.floability-data-staging").exists()


@pytest.mark.unit
def test_uncached_directory_force_replaces_without_stale_files(tmp_path: Path):
    source = tmp_path / "source-directory"
    source.mkdir()
    (source / "fresh.txt").write_text("fresh", encoding="utf-8")
    workflow = tmp_path / "workflow"
    target = workflow / "data/directory"
    target.mkdir(parents=True)
    (target / "stale.txt").write_text("stale", encoding="utf-8")
    item = {
        "name": "directory",
        "source_type": "fs",
        "source": str(source),
        "target_location": "data/directory",
    }

    result = _fetch_single_item(
        item,
        tmp_path,
        force=True,
        data_cache_mode="off",
        target_prefix=workflow,
    )

    assert result is item
    assert (target / "fresh.txt").read_text(encoding="utf-8") == "fresh"
    assert not (target / "stale.txt").exists()
    assert not (workflow / "data/.floability-data-staging").exists()


@pytest.mark.unit
def test_publish_staged_result_restores_target_after_rename_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    staged_result = build_dir / "new-result"
    staged_result.write_text("new", encoding="utf-8")
    target = tmp_path / "target"
    target.write_text("old", encoding="utf-8")
    original_rename = Path.rename

    def fail_new_result_rename(path: Path, destination: Path):
        if path == staged_result:
            raise OSError("injected publication failure")
        return original_rename(path, destination)

    monkeypatch.setattr(Path, "rename", fail_new_result_rename)

    with pytest.raises(OSError, match="injected publication failure"):
        _publish_staged_result(staged_result, target, build_dir, force=True)

    assert target.read_text(encoding="utf-8") == "old"
    assert staged_result.read_text(encoding="utf-8") == "new"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("operation", "writer", "expected"),
    [
        ("unzip", _write_zip, b"zip content"),
        ("untar", _write_tar, b"tar content"),
    ],
)
def test_cached_fetch_builds_and_materializes_extracted_result(
    tmp_path: Path, operation: str, writer, expected: bytes
):
    archive_path = tmp_path / "source.archive"
    writer(archive_path)
    cache_dir = tmp_path / "floability-data-cache"
    workflow = tmp_path / "workflow"
    item = {
        "name": "archive",
        "source_type": "fs",
        "source": str(archive_path),
        "target_location": "data/result",
        "post_process": {"operation": operation},
    }

    result = _fetch_single_item(
        item,
        tmp_path,
        data_cache_mode="symlink",
        cache_base_dir=cache_dir,
        target_prefix=workflow,
    )

    target = workflow / "data/result"
    assert result is item
    assert target.is_symlink()
    assert (target / "dataset/file.txt").read_bytes() == expected

    metadata_files = list(cache_dir.glob("*/*/.meta.json"))
    assert len(metadata_files) == 1
    metadata = json.loads(metadata_files[0].read_text(encoding="utf-8"))
    assert metadata["status"] == "complete"
    assert metadata["post_process"]["result_path"] == "cached_data/result"
    assert metadata["post_process"]["file_count"] == 1
    assert (metadata_files[0].parent / "cached_data/result").is_dir()


@pytest.mark.unit
def test_cached_extracted_result_is_reused_for_another_target_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    archive_path = tmp_path / "source.zip"
    _write_zip(archive_path)
    cache_dir = tmp_path / "floability-data-cache"
    workflow = tmp_path / "workflow"
    item = {
        "name": "archive",
        "source_type": "fs",
        "source": str(archive_path),
        "target_location": "data/first",
        "post_process": {"operation": "unzip"},
    }

    assert _fetch_single_item(
        item,
        tmp_path,
        data_cache_mode="symlink",
        cache_base_dir=cache_dir,
        target_prefix=workflow,
    )

    def fail_if_extracted(*args, **kwargs):
        raise AssertionError("cache hit should not extract the archive again")

    monkeypatch.setattr(data_handler, "extract_archive", fail_if_extracted)
    second_item = {**item, "target_location": "other/location"}

    assert _fetch_single_item(
        second_item,
        tmp_path,
        data_cache_mode="symlink",
        cache_base_dir=cache_dir,
        target_prefix=workflow,
    )
    assert (workflow / "other/location/dataset/file.txt").is_file()
    assert len(list(cache_dir.glob("*/*/.meta.json"))) == 1


@pytest.mark.unit
@pytest.mark.parametrize(
    "invalid_part",
    ["metadata", "artifact_spec", "source_key", "result"],
)
def test_incomplete_extracted_cache_entry_is_rebuilt(
    tmp_path: Path, invalid_part: str, monkeypatch: pytest.MonkeyPatch
):
    archive_path = tmp_path / "source.zip"
    _write_zip(archive_path)
    cache_dir = tmp_path / "floability-data-cache"
    workflow = tmp_path / "workflow"
    item = {
        "name": "archive",
        "source_type": "fs",
        "source": str(archive_path),
        "target_location": "data/result",
        "post_process": {"operation": "unzip"},
    }
    assert _fetch_single_item(
        item,
        tmp_path,
        data_cache_mode="symlink",
        cache_base_dir=cache_dir,
        target_prefix=workflow,
    )

    target = workflow / "data/result"
    target.unlink()
    metadata_path = next(cache_dir.glob("*/*/.meta.json"))
    if invalid_part != "result":
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if invalid_part == "metadata":
            metadata["status"] = "building"
        elif invalid_part == "artifact_spec":
            metadata["artifact_spec"]["source"] = "https://invalid.example/data.zip"
        else:
            metadata["source_key"] = "wrong-source-key"
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    else:
        result_dir = metadata_path.parent / "cached_data/result"
        for child in sorted(result_dir.rglob("*"), reverse=True):
            child.unlink() if child.is_file() else child.rmdir()
        result_dir.rmdir()

    extraction_calls = 0
    original_extract = data_handler.extract_archive

    def count_extraction(*args, **kwargs):
        nonlocal extraction_calls
        extraction_calls += 1
        return original_extract(*args, **kwargs)

    monkeypatch.setattr(data_handler, "extract_archive", count_extraction)

    assert _fetch_single_item(
        item,
        tmp_path,
        data_cache_mode="symlink",
        cache_base_dir=cache_dir,
        target_prefix=workflow,
    )
    assert extraction_calls == 1
    assert (target / "dataset/file.txt").is_file()


@pytest.mark.unit
def test_current_limits_reject_larger_cached_extraction(tmp_path: Path):
    archive_path = tmp_path / "source.zip"
    _write_zip(archive_path, content=b"content exceeds limit")
    cache_dir = tmp_path / "floability-data-cache"
    workflow = tmp_path / "workflow"
    item = {
        "name": "archive",
        "source_type": "fs",
        "source": str(archive_path),
        "target_location": "data/result",
        "post_process": {"operation": "unzip"},
    }
    assert _fetch_single_item(
        item,
        tmp_path,
        data_cache_mode="symlink",
        cache_base_dir=cache_dir,
        target_prefix=workflow,
    )

    (workflow / "data/result").unlink()
    limited_item = {
        **item,
        "post_process": {
            "operation": "unzip",
            "limits": {"max_extracted_bytes": 1},
        },
    }

    assert _fetch_single_item(
        limited_item,
        tmp_path,
        data_cache_mode="symlink",
        cache_base_dir=cache_dir,
        target_prefix=workflow,
    ) is None
    assert not (workflow / "data/result").exists()


@pytest.mark.unit
def test_failed_extracted_cache_build_leaves_no_complete_entry(tmp_path: Path):
    archive_path = tmp_path / "invalid.zip"
    archive_path.write_bytes(b"not a ZIP archive")
    cache_dir = tmp_path / "floability-data-cache"
    item = {
        "name": "archive",
        "source_type": "fs",
        "source": str(archive_path),
        "target_location": "data/result",
        "post_process": {"operation": "unzip"},
    }

    assert _fetch_single_item(
        item,
        tmp_path,
        data_cache_mode="symlink",
        cache_base_dir=cache_dir,
        target_prefix=tmp_path / "workflow",
    ) is None
    assert not list(cache_dir.rglob(".meta.json"))
    assert not list(cache_dir.rglob(".verify.lock"))
    assert not list(cache_dir.rglob("build-*"))


@pytest.mark.unit
def test_cache_publication_restores_previous_entry_after_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cache_dir = tmp_path / "cache-entry"
    old_data = cache_dir / "cached_data/result"
    old_data.mkdir(parents=True)
    (old_data / "old.txt").write_text("old", encoding="utf-8")
    old_meta = cache_dir / ".meta.json"
    old_meta.write_text('{"generation": "old"}', encoding="utf-8")

    build_dir = cache_dir / ".staging/build-test"
    new_data = build_dir / "cached_data/result"
    new_data.mkdir(parents=True)
    (new_data / "new.txt").write_text("new", encoding="utf-8")
    staged_meta = build_dir / ".meta.json"
    staged_meta.write_text('{"generation": "new"}', encoding="utf-8")
    original_rename = Path.rename

    def fail_new_metadata(path: Path, destination: Path):
        if path == staged_meta:
            raise OSError("injected cache publication failure")
        return original_rename(path, destination)

    monkeypatch.setattr(Path, "rename", fail_new_metadata)

    with pytest.raises(OSError, match="injected cache publication failure"):
        _publish_cache_build(build_dir, cache_dir)

    assert (cache_dir / "cached_data/result/old.txt").read_text() == "old"
    assert json.loads(old_meta.read_text())["generation"] == "old"
