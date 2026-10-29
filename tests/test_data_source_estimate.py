from pathlib import Path

import pytest

import floability.data.data_handler as data_handler
from floability.data.data_handler import SourceEstimate
from floability.data.storage import StorageCapacityError


def _estimate() -> SourceEstimate:
    return SourceEstimate(
        source_type="http",
        source="https://example.test/data.bin",
        object_type="file",
        required_bytes=12,
        required_entries=1,
        size_basis="remote metadata",
        metadata={"ok": True, "object_type": "file", "size": 12},
    )


@pytest.mark.unit
def test_fetch_prepares_http_metadata_once_before_direct_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    metadata_calls = []

    def fake_metadata(source):
        metadata_calls.append(source)
        return {
            "exists": True,
            "name": "data.bin",
            "size": 12,
            "type": "application/octet-stream",
            "accepts_ranges": False,
            "raw": {},
        }

    def fake_download(_source, dest_dir, filename, **_kwargs):
        destination = Path(dest_dir) / filename
        destination.write_bytes(b"test content")
        return destination

    monkeypatch.setattr(data_handler, "http_file_metadata", fake_metadata)
    monkeypatch.setattr(data_handler, "http_file_download", fake_download)

    item = {
        "name": "test-data",
        "source_type": "http",
        "source": "https://example.test/data.bin",
        "target_location": "data/data.bin",
    }

    result = data_handler._fetch_single_item(
        item,
        tmp_path,
        data_cache_mode="off",
        target_prefix=tmp_path / "workflow",
    )

    assert result is item
    assert metadata_calls == ["https://example.test/data.bin"]


@pytest.mark.unit
def test_missing_remote_size_uses_expected_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    capacity_checks = []

    monkeypatch.setattr(
        data_handler,
        "http_file_metadata",
        lambda _source: {
            "exists": True,
            "name": "data.bin",
            "size": None,
            "type": "application/octet-stream",
            "accepts_ranges": False,
            "raw": {},
        },
    )

    def fake_download(_source, dest_dir, filename, **_kwargs):
        destination = Path(dest_dir) / filename
        destination.write_bytes(b"content")
        return destination

    monkeypatch.setattr(data_handler, "http_file_download", fake_download)
    monkeypatch.setattr(
        data_handler,
        "ensure_filesystem_capacity",
        lambda _destination, **kwargs: capacity_checks.append(kwargs),
    )

    item = {
        "name": "test-data",
        "source_type": "http",
        "source": "https://example.test/data.bin",
        "expected_size": 123,
        "target_location": "data/data.bin",
    }

    assert data_handler._fetch_single_item(
        item,
        tmp_path,
        data_cache_mode="off",
        target_prefix=tmp_path / "workflow",
    ) is item
    assert capacity_checks[0]["required_bytes"] == 123


@pytest.mark.unit
def test_missing_remote_and_expected_size_fails_before_download(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    download_calls = []
    monkeypatch.setattr(
        data_handler,
        "http_file_metadata",
        lambda _source: {
            "exists": True,
            "name": "data.bin",
            "size": None,
            "type": "application/octet-stream",
            "accepts_ranges": False,
            "raw": {},
        },
    )
    monkeypatch.setattr(
        data_handler,
        "http_file_download",
        lambda *_args, **_kwargs: download_calls.append(True),
    )

    item = {
        "name": "test-data",
        "source_type": "http",
        "source": "https://example.test/data.bin",
        "target_location": "data/data.bin",
    }

    assert data_handler._fetch_single_item(
        item,
        tmp_path,
        data_cache_mode="off",
        target_prefix=tmp_path / "workflow",
    ) is None
    assert download_calls == []
    assert "add an integer expected_size" in capsys.readouterr().out


@pytest.mark.unit
def test_capacity_failure_prevents_downloader_invocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    download_calls = []
    monkeypatch.setattr(
        data_handler,
        "http_file_metadata",
        lambda _source: {
            "exists": True,
            "name": "data.bin",
            "size": 100,
            "type": "application/octet-stream",
            "accepts_ranges": False,
            "raw": {},
        },
    )
    monkeypatch.setattr(
        data_handler,
        "ensure_filesystem_capacity",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            StorageCapacityError("insufficient test space")
        ),
    )
    monkeypatch.setattr(
        data_handler,
        "http_file_download",
        lambda *_args, **_kwargs: download_calls.append(True),
    )

    with pytest.raises(StorageCapacityError, match="insufficient test space"):
        data_handler._fetch_single_item(
            {
                "name": "test-data",
                "source_type": "http",
                "source": "https://example.test/data.bin",
                "target_location": "data/data.bin",
            },
            tmp_path,
            data_cache_mode="off",
            target_prefix=tmp_path / "workflow",
        )

    assert download_calls == []


@pytest.mark.unit
def test_multi_source_fallback_recomputes_estimate_and_cache_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    first_source = "https://example.test/first.bin"
    second_source = "https://example.test/second.bin"
    metadata_calls = []
    download_calls = []
    capacity_sizes = []

    def fake_metadata(source):
        metadata_calls.append(source)
        return {
            "exists": True,
            "name": Path(source).name,
            "size": 10 if source == first_source else 20,
            "type": "application/octet-stream",
            "accepts_ranges": False,
            "raw": {},
        }

    def fake_download(source, dest_dir, filename, **_kwargs):
        download_calls.append(source)
        if source == first_source:
            raise OSError("first source unavailable")
        destination = Path(dest_dir) / filename
        destination.write_bytes(b"second source content")
        return destination

    def fake_source_key(metadata, _source_type):
        return (
            "first-source"
            if metadata["used_source"] == first_source
            else "second-source"
        )

    monkeypatch.setattr(data_handler, "http_file_metadata", fake_metadata)
    monkeypatch.setattr(data_handler, "http_file_download", fake_download)
    monkeypatch.setattr(data_handler, "_compute_source_key", fake_source_key)
    monkeypatch.setattr(
        data_handler,
        "ensure_filesystem_capacity",
        lambda _destination, **kwargs: capacity_sizes.append(
            kwargs["required_bytes"]
        ),
    )

    item = {
        "name": "test-data",
        "source_type": "multi",
        "sources": [
            {"source_type": "http", "source": first_source},
            {"source_type": "http", "source": second_source},
        ],
        "target_location": "data/data.bin",
    }
    cache_root = tmp_path / "floability-data-cache"

    assert data_handler._fetch_single_item(
        item,
        tmp_path,
        data_cache_mode="symlink",
        cache_base_dir=cache_root,
        target_prefix=tmp_path / "workflow",
    ) is item

    metadata_files = list(cache_root.glob("*/*/.meta.json"))
    assert len(metadata_files) == 1
    assert metadata_files[0].parent.name == "second-source"
    assert metadata_calls == [first_source, second_source]
    assert download_calls == [first_source, second_source]
    assert capacity_sizes == [10, 20]


@pytest.mark.unit
def test_cache_capacity_check_occurs_after_lock_and_recheck(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    events = []
    estimate = _estimate()
    cache_context = {
        "artifact_spec": {"source_type": "http"},
        "spec_key": "spec-key",
        "source_key": "source-key",
        "source_meta": estimate.metadata,
    }

    monkeypatch.setattr(data_handler, "_find_cache_hit", lambda *_a, **_k: None)
    monkeypatch.setattr(
        data_handler,
        "_acquire_cache_lock",
        lambda *_a, **_k: events.append("lock") or True,
    )
    monkeypatch.setattr(
        data_handler,
        "_validate_cache_dir",
        lambda *_a, **_k: events.append("recheck") or None,
    )
    monkeypatch.setattr(
        data_handler,
        "ensure_filesystem_capacity",
        lambda *_a, **_k: events.append("capacity"),
    )
    monkeypatch.setattr(
        data_handler,
        "_build_cache_entry",
        lambda *_a, **_k: events.append("build") or True,
    )
    monkeypatch.setattr(data_handler, "_read_cache_metadata", lambda _path: {})
    monkeypatch.setattr(
        data_handler,
        "_release_cache_lock",
        lambda _path: events.append("release"),
    )

    result = data_handler._get_or_build_cache_entry(
        {
            "name": "test-data",
            "source_type": "http",
            "source": estimate.source,
        },
        tmp_path,
        tmp_path / "cache",
        cache_ctx=cache_context,
        source_estimate=estimate,
        data_cache_mode="symlink",
        force_data_cache=False,
        cache_lookup_mode="strict",
    )

    assert result is not None
    assert events == ["lock", "recheck", "capacity", "build", "release"]


@pytest.mark.unit
def test_cache_recheck_avoids_capacity_check_and_rebuild(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    estimate = _estimate()
    cached_metadata = {"status": "complete"}
    capacity_calls = []
    build_calls = []

    monkeypatch.setattr(data_handler, "_find_cache_hit", lambda *_a, **_k: None)
    monkeypatch.setattr(data_handler, "_acquire_cache_lock", lambda *_a, **_k: True)
    monkeypatch.setattr(
        data_handler, "_validate_cache_dir", lambda *_a, **_k: cached_metadata
    )
    monkeypatch.setattr(
        data_handler,
        "ensure_filesystem_capacity",
        lambda *_a, **_k: capacity_calls.append(True),
    )
    monkeypatch.setattr(
        data_handler,
        "_build_cache_entry",
        lambda *_a, **_k: build_calls.append(True) or True,
    )
    monkeypatch.setattr(data_handler, "_release_cache_lock", lambda _path: None)

    result = data_handler._get_or_build_cache_entry(
        {
            "name": "test-data",
            "source_type": "http",
            "source": estimate.source,
        },
        tmp_path,
        tmp_path / "cache",
        cache_ctx={
            "artifact_spec": {"source_type": "http"},
            "spec_key": "spec-key",
            "source_key": "source-key",
            "source_meta": estimate.metadata,
        },
        source_estimate=estimate,
        data_cache_mode="symlink",
        force_data_cache=False,
        cache_lookup_mode="strict",
    )

    assert result is not None
    assert result[1] is cached_metadata
    assert capacity_calls == []
    assert build_calls == []
