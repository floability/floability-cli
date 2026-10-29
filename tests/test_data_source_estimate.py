from pathlib import Path

import pytest

import floability.data.data_handler as data_handler
from floability.data.data_handler import SourceEstimate


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
