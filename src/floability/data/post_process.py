"""Validation helpers for data-item post-processing specifications."""

from __future__ import annotations

import os
import shutil
import stat
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Dict, Optional


_IMPLEMENTATION_VERSIONS = {"untar": 1, "unzip": 1}
SUPPORTED_OPERATIONS = frozenset(_IMPLEMENTATION_VERSIONS)
_POST_PROCESS_FIELDS = frozenset({"limits", "operation"})
_LIMIT_FIELDS = frozenset({"max_entries", "max_extracted_bytes"})


class PostProcessError(ValueError):
    """Raised when a post-process input is unsafe or invalid."""


@dataclass(frozen=True)
class ArchiveSummary:
    """Structural information collected without extracting an archive."""

    file_count: int
    directory_count: int
    total_uncompressed_bytes: int
    largest_file_bytes: int

    @property
    def entry_count(self) -> int:
        """Return the number of filesystem entries extraction would create."""
        return self.file_count + self.directory_count


def validate_post_process_spec(spec: Any, *, item_label: str) -> None:
    """Validate one ``post_process`` mapping from a data item."""
    field_label = f"{item_label} post_process"

    if not isinstance(spec, dict):
        raise ValueError(f"{field_label} must be a mapping")

    unknown_fields = sorted(set(spec) - _POST_PROCESS_FIELDS)
    if unknown_fields:
        fields = ", ".join(unknown_fields)
        raise ValueError(f"{field_label} has unknown field(s): {fields}")

    operation = spec.get("operation")
    if not isinstance(operation, str) or not operation:
        raise ValueError(f"{field_label}.operation is required")
    if operation not in SUPPORTED_OPERATIONS:
        supported = ", ".join(sorted(SUPPORTED_OPERATIONS))
        raise ValueError(
            f"{field_label}.operation must be one of: {supported}; got {operation!r}"
        )

    limits = spec.get("limits")
    if limits is None:
        return
    if not isinstance(limits, dict):
        raise ValueError(f"{field_label}.limits must be a mapping")

    unknown_limits = sorted(set(limits) - _LIMIT_FIELDS)
    if unknown_limits:
        fields = ", ".join(unknown_limits)
        raise ValueError(f"{field_label}.limits has unknown field(s): {fields}")

    for name, value in limits.items():
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(
                f"{field_label}.limits.{name} must be a positive integer"
            )


def post_process_cache_identity(spec: Dict[str, Any]) -> Dict[str, Any]:
    """Return the post-process fields that affect cached result bytes."""
    operation = spec["operation"]
    return {
        "operation": operation,
        "implementation_version": _IMPLEMENTATION_VERSIONS[operation],
    }


def inspect_archive(
    archive_path: Path,
    post_process_spec: Dict[str, Any],
    *,
    item_label: str = "Data item",
) -> ArchiveSummary:
    """Validate a post-process spec and inspect its declared archive type."""
    validate_post_process_spec(post_process_spec, item_label=item_label)
    operation = post_process_spec["operation"]
    limits = post_process_spec.get("limits")

    if operation == "unzip":
        return inspect_zip_archive(archive_path, limits)
    if operation == "untar":
        return inspect_tar_archive(archive_path, limits)

    raise AssertionError(f"Unhandled validated post-process operation: {operation}")


def extract_archive(
    archive_path: Path,
    result_dir: Path,
    post_process_spec: Dict[str, Any],
    *,
    item_label: str = "Data item",
) -> ArchiveSummary:
    """Validate a post-process spec and safely extract its declared archive type."""
    validate_post_process_spec(post_process_spec, item_label=item_label)
    operation = post_process_spec["operation"]
    limits = post_process_spec.get("limits")

    if operation == "unzip":
        return extract_zip_archive(archive_path, result_dir, limits)
    if operation == "untar":
        return extract_tar_archive(archive_path, result_dir, limits)

    raise AssertionError(f"Unhandled validated post-process operation: {operation}")


def inspect_zip_archive(
    archive_path: Path, limits: Optional[Dict[str, int]] = None
) -> ArchiveSummary:
    """Inspect a ZIP archive without extracting or reading member contents."""
    path_types: Dict[str, str] = {}
    explicit_paths = set()
    total_uncompressed_bytes = 0
    largest_file_bytes = 0
    file_count = 0

    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            for member in archive.infolist():
                normalized, is_directory = _validate_zip_member(
                    member, path_types, explicit_paths
                )
                if normalized is None:
                    continue

                if not is_directory:
                    if member.file_size < 0:
                        raise PostProcessError(
                            f"ZIP member has a negative size: {member.filename!r}"
                        )
                    file_count += 1
                    total_uncompressed_bytes += member.file_size
                    largest_file_bytes = max(largest_file_bytes, member.file_size)
    except zipfile.BadZipFile as error:
        raise PostProcessError(f"Invalid ZIP archive: {archive_path}") from error

    return _create_archive_summary(
        path_types=path_types,
        file_count=file_count,
        total_uncompressed_bytes=total_uncompressed_bytes,
        largest_file_bytes=largest_file_bytes,
        limits=limits,
    )


def ensure_filesystem_capacity(
    destination: Path,
    *,
    required_bytes: int,
    required_entries: int = 0,
    purpose: str,
) -> None:
    """Ensure the destination filesystem can hold a planned operation."""
    existing_path = Path(destination)
    while not existing_path.exists():
        parent = existing_path.parent
        if parent == existing_path:
            raise PostProcessError(
                f"Cannot locate a filesystem for destination: {destination}"
            )
        existing_path = parent

    free_bytes = shutil.disk_usage(existing_path).free
    if required_bytes > free_bytes:
        raise PostProcessError(
            f"Insufficient space for {purpose} at {destination}: "
            f"requires {required_bytes} bytes, {free_bytes} bytes available"
        )

    filesystem = os.statvfs(existing_path)
    if (
        required_entries
        and filesystem.f_files > 0
        and required_entries > filesystem.f_favail
    ):
        raise PostProcessError(
            f"Insufficient inodes for {purpose} at {destination}: "
            f"requires {required_entries}, {filesystem.f_favail} available"
        )


def extract_zip_archive(
    archive_path: Path,
    result_dir: Path,
    limits: Optional[Dict[str, int]] = None,
) -> ArchiveSummary:
    """Safely extract a ZIP archive into a new result directory."""
    result_dir = Path(result_dir)
    if result_dir.exists() or result_dir.is_symlink():
        raise PostProcessError(
            f"ZIP extraction result already exists: {result_dir}"
        )

    summary = inspect_zip_archive(archive_path, limits)
    ensure_filesystem_capacity(
        result_dir.parent,
        required_bytes=summary.total_uncompressed_bytes,
        required_entries=summary.entry_count + 1,
        purpose="ZIP extraction",
    )
    path_types: Dict[str, str] = {}
    explicit_paths = set()
    total_written = 0
    created_result = False

    try:
        result_dir.parent.mkdir(parents=True, exist_ok=True)
        result_dir.mkdir()
        created_result = True

        with zipfile.ZipFile(archive_path, "r") as archive:
            for member in archive.infolist():
                normalized, is_directory = _validate_zip_member(
                    member, path_types, explicit_paths
                )
                if normalized is None:
                    continue

                destination = result_dir.joinpath(*normalized.parts)
                if is_directory:
                    destination.mkdir(parents=True, exist_ok=True)
                    continue

                destination.parent.mkdir(parents=True, exist_ok=True)
                member_written = 0
                with (
                    archive.open(member, "r") as source,
                    destination.open("xb") as target,
                ):
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break

                        member_written += len(chunk)
                        total_written += len(chunk)
                        if member_written > member.file_size:
                            raise PostProcessError(
                                "ZIP member exceeded its declared size: "
                                f"{member.filename!r}"
                            )
                        if (
                            limits
                            and limits.get("max_extracted_bytes") is not None
                            and total_written > limits["max_extracted_bytes"]
                        ):
                            raise PostProcessError(
                                "ZIP extraction exceeded "
                                "post_process.limits.max_extracted_bytes"
                            )
                        target.write(chunk)

                if member_written != member.file_size:
                    raise PostProcessError(
                        "ZIP member size did not match its declaration: "
                        f"{member.filename!r}"
                    )

        if total_written != summary.total_uncompressed_bytes:
            raise PostProcessError(
                "ZIP extraction size did not match the inspected archive summary"
            )
        return summary
    except BaseException:
        if created_result:
            shutil.rmtree(result_dir, ignore_errors=True)
        raise


def inspect_tar_archive(
    archive_path: Path, limits: Optional[Dict[str, int]] = None
) -> ArchiveSummary:
    """Inspect a TAR archive without extracting or reading member contents."""
    path_types: Dict[str, str] = {}
    explicit_paths = set()
    total_uncompressed_bytes = 0
    largest_file_bytes = 0
    file_count = 0

    try:
        with tarfile.open(archive_path, "r:*") as archive:
            for member in archive:
                normalized, is_directory = _validate_tar_member(
                    member, path_types, explicit_paths
                )
                if normalized is None:
                    continue

                if not is_directory:
                    if member.size < 0:
                        raise PostProcessError(
                            f"TAR member has a negative size: {member.name!r}"
                        )
                    file_count += 1
                    total_uncompressed_bytes += member.size
                    largest_file_bytes = max(largest_file_bytes, member.size)
    except tarfile.TarError as error:
        raise PostProcessError(f"Invalid TAR archive: {archive_path}") from error

    return _create_archive_summary(
        path_types=path_types,
        file_count=file_count,
        total_uncompressed_bytes=total_uncompressed_bytes,
        largest_file_bytes=largest_file_bytes,
        limits=limits,
    )


def extract_tar_archive(
    archive_path: Path,
    result_dir: Path,
    limits: Optional[Dict[str, int]] = None,
) -> ArchiveSummary:
    """Safely extract a TAR archive into a new result directory."""
    result_dir = Path(result_dir)
    if result_dir.exists() or result_dir.is_symlink():
        raise PostProcessError(
            f"TAR extraction result already exists: {result_dir}"
        )

    summary = inspect_tar_archive(archive_path, limits)
    ensure_filesystem_capacity(
        result_dir.parent,
        required_bytes=summary.total_uncompressed_bytes,
        required_entries=summary.entry_count + 1,
        purpose="TAR extraction",
    )
    path_types: Dict[str, str] = {}
    explicit_paths = set()
    total_written = 0
    created_result = False

    try:
        result_dir.parent.mkdir(parents=True, exist_ok=True)
        result_dir.mkdir()
        created_result = True

        with tarfile.open(archive_path, "r:*") as archive:
            for member in archive:
                normalized, is_directory = _validate_tar_member(
                    member, path_types, explicit_paths
                )
                if normalized is None:
                    continue

                destination = result_dir.joinpath(*normalized.parts)
                if is_directory:
                    destination.mkdir(parents=True, exist_ok=True)
                    continue

                source = archive.extractfile(member)
                if source is None:
                    raise PostProcessError(
                        f"TAR member could not be read: {member.name!r}"
                    )

                destination.parent.mkdir(parents=True, exist_ok=True)
                member_written = 0
                with source, destination.open("xb") as target:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break

                        member_written += len(chunk)
                        total_written += len(chunk)
                        if member_written > member.size:
                            raise PostProcessError(
                                "TAR member exceeded its declared size: "
                                f"{member.name!r}"
                            )
                        if (
                            limits
                            and limits.get("max_extracted_bytes") is not None
                            and total_written > limits["max_extracted_bytes"]
                        ):
                            raise PostProcessError(
                                "TAR extraction exceeded "
                                "post_process.limits.max_extracted_bytes"
                            )
                        target.write(chunk)

                if member_written != member.size:
                    raise PostProcessError(
                        "TAR member size did not match its declaration: "
                        f"{member.name!r}"
                    )

        if total_written != summary.total_uncompressed_bytes:
            raise PostProcessError(
                "TAR extraction size did not match the inspected archive summary"
            )
        return summary
    except BaseException:
        if created_result:
            shutil.rmtree(result_dir, ignore_errors=True)
        raise


def _validate_zip_member(
    member: zipfile.ZipInfo,
    path_types: Dict[str, str],
    explicit_paths: set,
) -> tuple[Optional[PurePosixPath], bool]:
    """Validate one ZIP member and return its normalized path and type."""
    if member.flag_bits & 0x1:
        raise PostProcessError(
            f"Encrypted ZIP member is not supported: {member.filename!r}"
        )

    is_directory = member.is_dir()
    member_type = stat.S_IFMT(member.external_attr >> 16)
    if member_type == stat.S_IFLNK:
        raise PostProcessError(f"ZIP links are not supported: {member.filename!r}")
    allowed_types = (0, stat.S_IFDIR) if is_directory else (0, stat.S_IFREG)
    if member_type not in allowed_types:
        raise PostProcessError(
            f"ZIP special entry is not supported: {member.filename!r}"
        )

    normalized = _normalize_member_path(
        member.filename, is_directory=is_directory
    )
    if normalized is not None:
        _record_archive_path(
            normalized,
            "directory" if is_directory else "file",
            path_types,
            explicit_paths,
        )
    return normalized, is_directory


def _validate_tar_member(
    member: tarfile.TarInfo,
    path_types: Dict[str, str],
    explicit_paths: set,
) -> tuple[Optional[PurePosixPath], bool]:
    """Validate one TAR member and return its normalized path and type."""
    if member.issym() or member.islnk():
        raise PostProcessError(f"TAR links are not supported: {member.name!r}")

    is_directory = member.isdir()
    if not is_directory and not member.isreg():
        raise PostProcessError(
            f"TAR special entry is not supported: {member.name!r}"
        )

    normalized = _normalize_member_path(member.name, is_directory=is_directory)
    if normalized is not None:
        _record_archive_path(
            normalized,
            "directory" if is_directory else "file",
            path_types,
            explicit_paths,
        )
    return normalized, is_directory


def _normalize_member_path(
    member_name: str, *, is_directory: bool
) -> Optional[PurePosixPath]:
    """Return one safe, normalized archive-relative path."""
    if not member_name:
        raise PostProcessError("Archive member has an empty path")
    if "\\" in member_name:
        raise PostProcessError(
            f"Archive member uses an ambiguous backslash path: {member_name!r}"
        )

    path = PurePosixPath(member_name)
    if path.is_absolute():
        raise PostProcessError(
            f"Archive member path is POSIX absolute: {member_name!r}"
        )
    if PureWindowsPath(member_name).drive:
        raise PostProcessError(
            f"Archive member path uses a Windows drive: {member_name!r}"
        )
    if ".." in path.parts:
        raise PostProcessError(
            f"Archive member path contains parent traversal: {member_name!r}"
        )

    parts = path.parts
    if not parts:
        if is_directory:
            return None
        raise PostProcessError(f"Archive file has no output path: {member_name!r}")
    return PurePosixPath(*parts)


def _record_archive_path(
    path: PurePosixPath,
    entry_type: str,
    path_types: Dict[str, str],
    explicit_paths: set,
) -> None:
    """Record one member and reject duplicate or conflicting paths."""
    normalized = path.as_posix()
    if normalized in explicit_paths:
        raise PostProcessError(f"Archive contains duplicate path: {normalized!r}")

    parts = path.parts
    for index in range(1, len(parts)):
        parent = PurePosixPath(*parts[:index]).as_posix()
        if path_types.get(parent) == "file":
            raise PostProcessError(
                f"Archive path conflicts with file parent: {normalized!r}"
            )
        path_types[parent] = "directory"

    existing_type = path_types.get(normalized)
    if existing_type is not None and existing_type != entry_type:
        raise PostProcessError(f"Archive path type conflict: {normalized!r}")

    path_types[normalized] = entry_type
    explicit_paths.add(normalized)


def _create_archive_summary(
    *,
    path_types: Dict[str, str],
    file_count: int,
    total_uncompressed_bytes: int,
    largest_file_bytes: int,
    limits: Optional[Dict[str, int]],
) -> ArchiveSummary:
    """Create an archive summary and enforce optional extraction limits."""
    summary = ArchiveSummary(
        file_count=file_count,
        directory_count=sum(
            entry_type == "directory" for entry_type in path_types.values()
        ),
        total_uncompressed_bytes=total_uncompressed_bytes,
        largest_file_bytes=largest_file_bytes,
    )
    _enforce_limits(summary, limits or {})
    return summary


def _enforce_limits(summary: ArchiveSummary, limits: Dict[str, int]) -> None:
    """Reject an archive summary that exceeds user-configured limits."""
    max_bytes = limits.get("max_extracted_bytes")
    if max_bytes is not None and summary.total_uncompressed_bytes > max_bytes:
        raise PostProcessError(
            "Archive exceeds post_process.limits.max_extracted_bytes: "
            f"{summary.total_uncompressed_bytes} > {max_bytes}"
        )

    max_entries = limits.get("max_entries")
    if max_entries is not None and summary.entry_count > max_entries:
        raise PostProcessError(
            "Archive exceeds post_process.limits.max_entries: "
            f"{summary.entry_count} > {max_entries}"
        )
