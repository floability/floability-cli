import io
import stat
import tarfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from floability.data.data_handler import (
    _compute_spec_key,
    _create_artifact_spec,
    load_and_validate_spec,
)
from floability.data.post_process import (
    ArchiveSummary,
    PostProcessError,
    extract_archive,
    extract_tar_archive,
    extract_zip_archive,
    ensure_filesystem_capacity,
    inspect_archive,
    inspect_tar_archive,
    inspect_zip_archive,
    post_process_cache_identity,
    validate_post_process_spec,
)


def _write_data_spec(tmp_path: Path, post_process) -> Path:
    spec_path = tmp_path / "data.yml"
    spec = {
        "default_profile": "test",
        "profiles": {
            "test": {
                "data": [
                    {
                        "name": "archive",
                        "source": "https://example.org/archive.zip",
                        "target_location": "data/archive",
                        "post_process": post_process,
                    }
                ]
            }
        },
    }
    spec_path.write_text(yaml.safe_dump(spec), encoding="utf-8")
    return spec_path


@pytest.mark.unit
@pytest.mark.parametrize("operation", ["unzip", "untar"])
def test_supported_post_process_operations_are_valid(operation: str):
    validate_post_process_spec(
        {"operation": operation}, item_label="Spec item #1"
    )


@pytest.mark.unit
def test_post_process_limits_are_valid():
    validate_post_process_spec(
        {
            "operation": "unzip",
            "limits": {
                "max_extracted_bytes": 1024,
                "max_entries": 10,
            },
        },
        item_label="Spec item #1",
    )


@pytest.mark.unit
@pytest.mark.parametrize("post_process", [None, "unzip", ["unzip"]])
def test_post_process_must_be_a_mapping(post_process):
    with pytest.raises(ValueError, match="post_process must be a mapping"):
        validate_post_process_spec(post_process, item_label="Spec item #1")


@pytest.mark.unit
@pytest.mark.parametrize("operation", [None, "", "gunzip", "UNZIP"])
def test_post_process_operation_is_required_and_supported(operation):
    with pytest.raises(ValueError, match="post_process.operation"):
        validate_post_process_spec(
            {"operation": operation}, item_label="Spec item #1"
        )


@pytest.mark.unit
def test_post_process_rejects_unknown_fields():
    with pytest.raises(ValueError, match=r"unknown field\(s\): output_name"):
        validate_post_process_spec(
            {"operation": "unzip", "output_name": "data"},
            item_label="Spec item #1",
        )


@pytest.mark.unit
def test_post_process_limits_must_be_a_mapping():
    with pytest.raises(ValueError, match="limits must be a mapping"):
        validate_post_process_spec(
            {"operation": "unzip", "limits": 100},
            item_label="Spec item #1",
        )


@pytest.mark.unit
def test_post_process_rejects_unknown_limit_fields():
    with pytest.raises(ValueError, match=r"unknown field\(s\): max_depth"):
        validate_post_process_spec(
            {"operation": "unzip", "limits": {"max_depth": 2}},
            item_label="Spec item #1",
        )


@pytest.mark.unit
@pytest.mark.parametrize("value", [0, -1, 1.5, "100", True])
def test_post_process_limits_must_be_positive_integers(value):
    with pytest.raises(ValueError, match="must be a positive integer"):
        validate_post_process_spec(
            {"operation": "unzip", "limits": {"max_entries": value}},
            item_label="Spec item #1",
        )


@pytest.mark.unit
def test_data_spec_validation_checks_post_process(tmp_path: Path):
    spec_path = _write_data_spec(
        tmp_path,
        {"operation": "unzip", "limits": {"max_entries": 0}},
    )

    with pytest.raises(
        ValueError,
        match=r"Spec validation failed: Spec item #1 post_process\.limits"
        r"\.max_entries must be a positive integer",
    ):
        load_and_validate_spec(str(spec_path), backpack_root=tmp_path)


@pytest.mark.unit
@pytest.mark.parametrize("operation", ["unzip", "untar"])
def test_post_process_cache_identity_contains_implementation_version(operation: str):
    assert post_process_cache_identity({"operation": operation}) == {
        "operation": operation,
        "implementation_version": 1,
    }


@pytest.mark.unit
def test_post_process_limits_do_not_change_cache_identity(tmp_path: Path):
    item = {
        "source_type": "http",
        "source": "https://example.org/archive.zip",
        "post_process": {"operation": "unzip"},
    }
    limited_item = {
        **item,
        "post_process": {
            "operation": "unzip",
            "limits": {"max_entries": 10, "max_extracted_bytes": 1024},
        },
    }

    artifact = _create_artifact_spec(item, tmp_path)
    limited_artifact = _create_artifact_spec(limited_item, tmp_path)

    assert artifact == limited_artifact
    assert _compute_spec_key(artifact) == _compute_spec_key(limited_artifact)


@pytest.mark.unit
def test_post_process_operation_changes_cache_identity(tmp_path: Path):
    base_item = {
        "source_type": "http",
        "source": "https://example.org/archive",
    }
    unzip_artifact = _create_artifact_spec(
        {**base_item, "post_process": {"operation": "unzip"}}, tmp_path
    )
    untar_artifact = _create_artifact_spec(
        {**base_item, "post_process": {"operation": "untar"}}, tmp_path
    )

    assert _compute_spec_key(unzip_artifact) != _compute_spec_key(untar_artifact)


def _write_zip(tmp_path: Path, members) -> Path:
    archive_path = tmp_path / "fixture.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name, content in members:
            archive.writestr(name, content)
    return archive_path


@pytest.mark.unit
def test_inspect_zip_archive_reports_nested_layout(tmp_path: Path):
    archive_path = _write_zip(
        tmp_path,
        [
            ("nested/group-a/observations.txt", b"alpha\n"),
            ("nested/group-b/deeper/measurements.txt", b"beta\n"),
        ],
    )

    assert inspect_zip_archive(archive_path) == ArchiveSummary(
        file_count=2,
        directory_count=4,
        total_uncompressed_bytes=11,
        largest_file_bytes=6,
    )


@pytest.mark.unit
def test_inspect_zip_archive_reports_single_file(tmp_path: Path):
    archive_path = _write_zip(tmp_path, [("single-file.txt", b"content")])

    assert inspect_zip_archive(archive_path) == ArchiveSummary(
        file_count=1,
        directory_count=0,
        total_uncompressed_bytes=7,
        largest_file_bytes=7,
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "member_name",
    ["../escape.txt", "/absolute.txt", "C:/windows.txt", "nested\\windows.txt"],
)
def test_inspect_zip_archive_rejects_unsafe_paths(
    tmp_path: Path, member_name: str
):
    archive_path = _write_zip(tmp_path, [(member_name, b"unsafe")])

    with pytest.raises(PostProcessError, match="Archive member"):
        inspect_zip_archive(archive_path)


@pytest.mark.unit
def test_inspect_zip_archive_rejects_links(tmp_path: Path):
    archive_path = tmp_path / "fixture.zip"
    link = zipfile.ZipInfo("link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(link, "target")

    with pytest.raises(PostProcessError, match="links are not supported"):
        inspect_zip_archive(archive_path)


@pytest.mark.unit
def test_inspect_zip_archive_rejects_special_directory_entries(tmp_path: Path):
    archive_path = tmp_path / "fixture.zip"
    special = zipfile.ZipInfo("special/")
    special.create_system = 3
    special.external_attr = (stat.S_IFIFO | 0o755) << 16
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(special, "")

    with pytest.raises(PostProcessError, match="special entry is not supported"):
        inspect_zip_archive(archive_path)


@pytest.mark.unit
def test_inspect_zip_archive_rejects_duplicate_paths(tmp_path: Path):
    archive_path = tmp_path / "fixture.zip"
    with pytest.warns(UserWarning, match="Duplicate name"):
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("duplicate.txt", "first")
            archive.writestr("duplicate.txt", "second")

    with pytest.raises(PostProcessError, match="duplicate path"):
        inspect_zip_archive(archive_path)


@pytest.mark.unit
def test_inspect_zip_archive_rejects_file_directory_conflicts(tmp_path: Path):
    archive_path = _write_zip(
        tmp_path,
        [("data", b"file"), ("data/member.txt", b"nested")],
    )

    with pytest.raises(PostProcessError, match="conflicts with file parent"):
        inspect_zip_archive(archive_path)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("limits", "error_field"),
    [
        ({"max_extracted_bytes": 3}, "max_extracted_bytes"),
        ({"max_entries": 1}, "max_entries"),
    ],
)
def test_inspect_zip_archive_enforces_limits(
    tmp_path: Path, limits, error_field: str
):
    archive_path = _write_zip(tmp_path, [("directory/file.txt", b"four")])

    with pytest.raises(PostProcessError, match=error_field):
        inspect_zip_archive(archive_path, limits)


@pytest.mark.unit
def test_inspect_zip_archive_rejects_invalid_zip(tmp_path: Path):
    archive_path = tmp_path / "invalid.zip"
    archive_path.write_bytes(b"not a zip archive")

    with pytest.raises(PostProcessError, match="Invalid ZIP archive"):
        inspect_zip_archive(archive_path)


def _write_tar(tmp_path: Path, members, mode: str = "w:gz") -> Path:
    suffixes = {
        "w": ".tar",
        "w:gz": ".tar.gz",
        "w:bz2": ".tar.bz2",
        "w:xz": ".tar.xz",
    }
    suffix = suffixes[mode]
    archive_path = tmp_path / f"fixture{suffix}"
    with tarfile.open(archive_path, mode) as archive:
        for name, content in members:
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
    return archive_path


@pytest.mark.unit
@pytest.mark.parametrize("mode", ["w", "w:gz", "w:bz2", "w:xz"])
def test_inspect_tar_archive_reports_nested_layout(tmp_path: Path, mode: str):
    archive_path = _write_tar(
        tmp_path,
        [
            ("nested/group-a/observations.txt", b"alpha\n"),
            ("nested/group-b/deeper/measurements.txt", b"beta\n"),
        ],
        mode=mode,
    )

    assert inspect_tar_archive(archive_path) == ArchiveSummary(
        file_count=2,
        directory_count=4,
        total_uncompressed_bytes=11,
        largest_file_bytes=6,
    )


@pytest.mark.unit
@pytest.mark.parametrize("member_type", [tarfile.SYMTYPE, tarfile.LNKTYPE])
def test_inspect_tar_archive_rejects_links(tmp_path: Path, member_type: bytes):
    archive_path = tmp_path / "link.tar"
    link = tarfile.TarInfo("link")
    link.type = member_type
    link.linkname = "target"
    with tarfile.open(archive_path, "w") as archive:
        archive.addfile(link)

    with pytest.raises(PostProcessError, match="links are not supported"):
        inspect_tar_archive(archive_path)


@pytest.mark.unit
def test_inspect_tar_archive_rejects_special_entries(tmp_path: Path):
    archive_path = tmp_path / "fifo.tar"
    fifo = tarfile.TarInfo("fifo")
    fifo.type = tarfile.FIFOTYPE
    with tarfile.open(archive_path, "w") as archive:
        archive.addfile(fifo)

    with pytest.raises(PostProcessError, match="special entry is not supported"):
        inspect_tar_archive(archive_path)


@pytest.mark.unit
def test_inspect_tar_archive_rejects_unsafe_paths(tmp_path: Path):
    archive_path = _write_tar(tmp_path, [("../escape.txt", b"unsafe")], mode="w")

    with pytest.raises(PostProcessError, match="parent traversal"):
        inspect_tar_archive(archive_path)


@pytest.mark.unit
def test_inspect_tar_archive_rejects_duplicate_paths(tmp_path: Path):
    archive_path = _write_tar(
        tmp_path,
        [("duplicate.txt", b"first"), ("duplicate.txt", b"second")],
        mode="w",
    )

    with pytest.raises(PostProcessError, match="duplicate path"):
        inspect_tar_archive(archive_path)


@pytest.mark.unit
def test_inspect_tar_archive_enforces_limits(tmp_path: Path):
    archive_path = _write_tar(
        tmp_path, [("directory/file.txt", b"four")], mode="w"
    )

    with pytest.raises(PostProcessError, match="max_entries"):
        inspect_tar_archive(archive_path, {"max_entries": 1})


@pytest.mark.unit
def test_inspect_tar_archive_rejects_invalid_tar(tmp_path: Path):
    archive_path = tmp_path / "invalid.tar"
    archive_path.write_bytes(b"not a tar archive")

    with pytest.raises(PostProcessError, match="Invalid TAR archive"):
        inspect_tar_archive(archive_path)


@pytest.mark.unit
def test_inspect_archive_dispatches_unzip(tmp_path: Path):
    archive_path = _write_zip(tmp_path, [("file.txt", b"zip")])

    assert inspect_archive(archive_path, {"operation": "unzip"}) == ArchiveSummary(
        file_count=1,
        directory_count=0,
        total_uncompressed_bytes=3,
        largest_file_bytes=3,
    )


@pytest.mark.unit
def test_inspect_archive_dispatches_untar(tmp_path: Path):
    archive_path = _write_tar(tmp_path, [("file.txt", b"tar")], mode="w")

    assert inspect_archive(archive_path, {"operation": "untar"}) == ArchiveSummary(
        file_count=1,
        directory_count=0,
        total_uncompressed_bytes=3,
        largest_file_bytes=3,
    )


@pytest.mark.unit
def test_inspect_archive_forwards_limits(tmp_path: Path):
    archive_path = _write_zip(tmp_path, [("file.txt", b"content")])

    with pytest.raises(PostProcessError, match="max_extracted_bytes"):
        inspect_archive(
            archive_path,
            {
                "operation": "unzip",
                "limits": {"max_extracted_bytes": 3},
            },
        )


@pytest.mark.unit
def test_inspect_archive_rejects_mismatched_operation(tmp_path: Path):
    archive_path = _write_zip(tmp_path, [("file.txt", b"content")])

    with pytest.raises(PostProcessError, match="Invalid TAR archive"):
        inspect_archive(archive_path, {"operation": "untar"})


@pytest.mark.unit
def test_extract_zip_archive_writes_nested_files(tmp_path: Path):
    archive_path = _write_zip(
        tmp_path,
        [
            ("nested/group-a/observations.txt", b"alpha\n"),
            ("nested/group-b/deeper/measurements.txt", b"beta\n"),
        ],
    )
    result_dir = tmp_path / "result"

    summary = extract_zip_archive(archive_path, result_dir)

    assert summary.file_count == 2
    assert (result_dir / "nested/group-a/observations.txt").read_bytes() == b"alpha\n"
    assert (
        result_dir / "nested/group-b/deeper/measurements.txt"
    ).read_bytes() == b"beta\n"


@pytest.mark.unit
def test_extract_zip_archive_keeps_single_file_inside_result_directory(
    tmp_path: Path,
):
    archive_path = _write_zip(tmp_path, [("single-file.txt", b"content")])
    result_dir = tmp_path / "result"

    extract_zip_archive(archive_path, result_dir)

    assert result_dir.is_dir()
    assert (result_dir / "single-file.txt").read_bytes() == b"content"


@pytest.mark.unit
def test_extract_zip_archive_preserves_existing_result(tmp_path: Path):
    archive_path = _write_zip(tmp_path, [("file.txt", b"replacement")])
    result_dir = tmp_path / "result"
    result_dir.mkdir()
    existing_file = result_dir / "existing.txt"
    existing_file.write_text("keep", encoding="utf-8")

    with pytest.raises(PostProcessError, match="result already exists"):
        extract_zip_archive(archive_path, result_dir)

    assert existing_file.read_text(encoding="utf-8") == "keep"


@pytest.mark.unit
def test_extract_zip_archive_cleans_partial_result_after_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    archive_path = _write_zip(tmp_path, [("file.txt", b"content")])
    result_dir = tmp_path / "result"

    def fail_to_open(*_args, **_kwargs):
        raise OSError("injected read failure")

    monkeypatch.setattr(zipfile.ZipFile, "open", fail_to_open)

    with pytest.raises(OSError, match="injected read failure"):
        extract_zip_archive(archive_path, result_dir)

    assert not result_dir.exists()


@pytest.mark.unit
def test_extract_zip_archive_checks_limits_before_creating_result(tmp_path: Path):
    archive_path = _write_zip(tmp_path, [("file.txt", b"content")])
    result_dir = tmp_path / "result"

    with pytest.raises(PostProcessError, match="max_extracted_bytes"):
        extract_zip_archive(
            archive_path,
            result_dir,
            {"max_extracted_bytes": 3},
        )

    assert not result_dir.exists()


@pytest.mark.unit
@pytest.mark.parametrize("mode", ["w", "w:gz", "w:bz2", "w:xz"])
def test_extract_tar_archive_writes_nested_files(tmp_path: Path, mode: str):
    archive_path = _write_tar(
        tmp_path,
        [
            ("nested/group-a/observations.txt", b"alpha\n"),
            ("nested/group-b/deeper/measurements.txt", b"beta\n"),
        ],
        mode=mode,
    )
    result_dir = tmp_path / "result"

    summary = extract_tar_archive(archive_path, result_dir)

    assert summary.file_count == 2
    assert (result_dir / "nested/group-a/observations.txt").read_bytes() == b"alpha\n"
    assert (
        result_dir / "nested/group-b/deeper/measurements.txt"
    ).read_bytes() == b"beta\n"


@pytest.mark.unit
def test_extract_tar_archive_keeps_single_file_inside_result_directory(
    tmp_path: Path,
):
    archive_path = _write_tar(
        tmp_path, [("single-file.txt", b"content")], mode="w"
    )
    result_dir = tmp_path / "result"

    extract_tar_archive(archive_path, result_dir)

    assert result_dir.is_dir()
    assert (result_dir / "single-file.txt").read_bytes() == b"content"


@pytest.mark.unit
def test_extract_tar_archive_preserves_existing_result(tmp_path: Path):
    archive_path = _write_tar(
        tmp_path, [("file.txt", b"replacement")], mode="w"
    )
    result_dir = tmp_path / "result"
    result_dir.mkdir()
    existing_file = result_dir / "existing.txt"
    existing_file.write_text("keep", encoding="utf-8")

    with pytest.raises(PostProcessError, match="result already exists"):
        extract_tar_archive(archive_path, result_dir)

    assert existing_file.read_text(encoding="utf-8") == "keep"


@pytest.mark.unit
def test_extract_tar_archive_cleans_partial_result_after_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    archive_path = _write_tar(tmp_path, [("file.txt", b"content")], mode="w")
    result_dir = tmp_path / "result"

    def fail_to_extract(*_args, **_kwargs):
        raise OSError("injected read failure")

    monkeypatch.setattr(tarfile.TarFile, "extractfile", fail_to_extract)

    with pytest.raises(OSError, match="injected read failure"):
        extract_tar_archive(archive_path, result_dir)

    assert not result_dir.exists()


@pytest.mark.unit
def test_extract_tar_archive_checks_limits_before_creating_result(tmp_path: Path):
    archive_path = _write_tar(tmp_path, [("file.txt", b"content")], mode="w")
    result_dir = tmp_path / "result"

    with pytest.raises(PostProcessError, match="max_extracted_bytes"):
        extract_tar_archive(
            archive_path,
            result_dir,
            {"max_extracted_bytes": 3},
        )

    assert not result_dir.exists()


@pytest.mark.unit
def test_extract_archive_dispatches_unzip(tmp_path: Path):
    archive_path = _write_zip(tmp_path, [("file.txt", b"zip")])
    result_dir = tmp_path / "zip-result"

    summary = extract_archive(
        archive_path,
        result_dir,
        {"operation": "unzip"},
    )

    assert summary.file_count == 1
    assert (result_dir / "file.txt").read_bytes() == b"zip"


@pytest.mark.unit
def test_extract_archive_dispatches_untar(tmp_path: Path):
    archive_path = _write_tar(tmp_path, [("file.txt", b"tar")], mode="w")
    result_dir = tmp_path / "tar-result"

    summary = extract_archive(
        archive_path,
        result_dir,
        {"operation": "untar"},
    )

    assert summary.file_count == 1
    assert (result_dir / "file.txt").read_bytes() == b"tar"


@pytest.mark.unit
def test_extract_archive_rejects_mismatched_operation_without_result(tmp_path: Path):
    archive_path = _write_zip(tmp_path, [("file.txt", b"content")])
    result_dir = tmp_path / "result"

    with pytest.raises(PostProcessError, match="Invalid TAR archive"):
        extract_archive(
            archive_path,
            result_dir,
            {"operation": "untar"},
        )

    assert not result_dir.exists()


@pytest.mark.unit
def test_ensure_filesystem_capacity_rejects_insufficient_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        "floability.data.post_process.shutil.disk_usage",
        lambda _path: SimpleNamespace(free=99),
    )

    with pytest.raises(
        PostProcessError, match="requires 100 bytes, 99 bytes available"
    ):
        ensure_filesystem_capacity(
            tmp_path / "not-created",
            required_bytes=100,
            purpose="test operation",
        )


@pytest.mark.unit
def test_ensure_filesystem_capacity_rejects_insufficient_inodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        "floability.data.post_process.shutil.disk_usage",
        lambda _path: SimpleNamespace(free=1000),
    )
    monkeypatch.setattr(
        "floability.data.post_process.os.statvfs",
        lambda _path: SimpleNamespace(f_files=100, f_favail=2),
    )

    with pytest.raises(PostProcessError, match="requires 3, 2 available"):
        ensure_filesystem_capacity(
            tmp_path,
            required_bytes=100,
            required_entries=3,
            purpose="test operation",
        )


@pytest.mark.unit
def test_ensure_filesystem_capacity_accepts_unlimited_inode_reporting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        "floability.data.post_process.shutil.disk_usage",
        lambda _path: SimpleNamespace(free=1000),
    )
    monkeypatch.setattr(
        "floability.data.post_process.os.statvfs",
        lambda _path: SimpleNamespace(f_files=0, f_favail=0),
    )

    ensure_filesystem_capacity(
        tmp_path,
        required_bytes=100,
        required_entries=3,
        purpose="test operation",
    )


@pytest.mark.unit
def test_extract_zip_archive_checks_capacity_before_creating_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    archive_path = _write_zip(tmp_path, [("file.txt", b"content")])
    result_dir = tmp_path / "result"
    monkeypatch.setattr(
        "floability.data.post_process.shutil.disk_usage",
        lambda _path: SimpleNamespace(free=3),
    )

    with pytest.raises(PostProcessError, match="Insufficient space"):
        extract_zip_archive(archive_path, result_dir)

    assert not result_dir.exists()
