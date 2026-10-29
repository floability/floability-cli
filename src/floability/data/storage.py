"""Generic filesystem-capacity checks for data operations."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


class StorageCapacityError(RuntimeError):
    """Raised when a filesystem cannot hold a planned data operation."""


def ensure_filesystem_capacity(
    destination: Path,
    *,
    required_bytes: int,
    required_entries: int = 0,
    purpose: str,
) -> None:
    """Check available bytes and, when reported, available inodes."""

    existing_path = Path(destination)

    while not existing_path.exists():
        parent = existing_path.parent
        if parent == existing_path:
            raise StorageCapacityError(
                f"Cannot locate a filesystem for destination: {destination}"
            )
        existing_path = parent

    free_bytes = shutil.disk_usage(existing_path).free
    if required_bytes > free_bytes:
        raise StorageCapacityError(
            f"Insufficient space for {purpose} at {destination}: "
            f"requires {required_bytes} bytes, "
            f"{free_bytes} bytes available"
        )

    filesystem = os.statvfs(existing_path)

    if (
        required_entries
        and filesystem.f_files > 0
        and required_entries > filesystem.f_favail
    ):
        raise StorageCapacityError(
            f"Insufficient inodes for {purpose} at {destination}: "
            f"requires {required_entries}, "
            f"{filesystem.f_favail} available"
        )
