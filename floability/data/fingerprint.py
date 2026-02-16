"""
Filesystem fingerprinting for cache validation.

Provides source-type specific fingerprinting to validate cached data
without changing the existing cache-key scheme.
"""

from __future__ import annotations
import os
import hashlib
from pathlib import Path
from typing import Dict, Any, List, Tuple


def compute_fingerprint(
    source_path: str,
    mode: str,  # "meta" | "sample" | "strict"
    *,
    sample_bytes: int = 200,
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    Compute a fingerprint for a filesystem path (file or directory).

    Args:
        source_path: Path to file or directory
        mode: Fingerprint mode - "meta", "sample", or "strict"
        sample_bytes: Number of bytes to sample for "sample" mode
        verbose: Print progress messages

    Returns:
        Dict containing:
        {
          "fingerprint": "<hex>",
          "mode": "meta|sample|strict",
          "params": {...}
        }

    Raises:
        ValueError: If mode is invalid or path doesn't exist
    """
    if mode not in ("meta", "sample", "strict"):
        raise ValueError(f"Invalid fingerprint mode: {mode}")

    path = Path(source_path)
    if not path.exists():
        raise ValueError(f"Source path does not exist: {source_path}")

    if path.is_file():
        if verbose:
            print(f"[fingerprint] Computing {mode} fingerprint for file: {path}")
        return _fingerprint_file(path, mode, sample_bytes, verbose)
    elif path.is_dir():
        if verbose:
            print(f"[fingerprint] Computing {mode} fingerprint for directory: {path}")
        return _fingerprint_directory(path, mode, sample_bytes, verbose)
    else:
        raise ValueError(f"Path is neither file nor directory: {source_path}")


def _fingerprint_file(
    path: Path, mode: str, sample_bytes: int, verbose: bool
) -> Dict[str, Any]:
    """Compute fingerprint for a single file."""
    if mode == "meta":
        return fs_fingerprint_file_meta(path, verbose)
    elif mode == "sample":
        return fs_fingerprint_file_sample(path, sample_bytes, verbose)
    elif mode == "strict":
        return fs_fingerprint_file_strict(path, verbose)
    else:
        raise ValueError(f"Invalid mode: {mode}")


def _fingerprint_directory(
    path: Path, mode: str, sample_bytes: int, verbose: bool
) -> Dict[str, Any]:
    """Compute fingerprint for a directory."""
    if mode == "meta":
        return fs_fingerprint_dir_meta(path, verbose)
    elif mode == "sample":
        return fs_fingerprint_dir_sample(path, sample_bytes, verbose)
    elif mode == "strict":
        return fs_fingerprint_dir_strict(path, verbose)
    else:
        raise ValueError(f"Invalid mode: {mode}")


# ==================== File Fingerprints ====================


def fs_fingerprint_file_meta(path: Path, verbose: bool = False) -> Dict[str, Any]:
    """
    Compute metadata-based fingerprint for a file.

    Uses: size, mtime_ns

    Args:
        path: Path to file
        verbose: Print progress messages

    Returns:
        Fingerprint dict
    """
    stat = path.stat()
    size = stat.st_size
    mtime_ns = stat.st_mtime_ns

    # Create canonical representation
    record = f"size:{size}|mtime_ns:{mtime_ns}"
    fingerprint = hashlib.sha256(record.encode("utf-8")).hexdigest()

    if verbose:
        print(f"[fingerprint:meta] File: {path.name}")
        print(f"[fingerprint:meta]   size={size}, mtime_ns={mtime_ns}")
        print(f"[fingerprint:meta]   fingerprint={fingerprint[:16]}...")

    return {
        "fingerprint": fingerprint,
        "mode": "meta",
        "params": {"size": size, "mtime_ns": mtime_ns},
    }


def fs_fingerprint_file_sample(
    path: Path, sample_bytes: int, verbose: bool = False
) -> Dict[str, Any]:
    """
    Compute sample-based fingerprint for a file.

    Uses: size, mtime_ns, sha256(first N bytes)

    Args:
        path: Path to file
        sample_bytes: Number of bytes to sample from start
        verbose: Print progress messages

    Returns:
        Fingerprint dict
    """
    stat = path.stat()
    size = stat.st_size
    mtime_ns = stat.st_mtime_ns

    # Read first N bytes
    h = hashlib.sha256()
    bytes_read = 0
    with path.open("rb") as f:
        chunk = f.read(min(sample_bytes, size))
        h.update(chunk)
        bytes_read = len(chunk)

    sample_hash = h.hexdigest()

    # Create canonical representation
    record = f"size:{size}|mtime_ns:{mtime_ns}|sample_sha256:{sample_hash}|sample_bytes:{bytes_read}"
    fingerprint = hashlib.sha256(record.encode("utf-8")).hexdigest()

    if verbose:
        print(f"[fingerprint:sample] File: {path.name}")
        print(
            f"[fingerprint:sample]   size={size}, mtime_ns={mtime_ns}, sample={bytes_read}B"
        )
        print(f"[fingerprint:sample]   fingerprint={fingerprint[:16]}...")

    return {
        "fingerprint": fingerprint,
        "mode": "sample",
        "params": {
            "size": size,
            "mtime_ns": mtime_ns,
            "sample_bytes": bytes_read,
            "sample_sha256": sample_hash,
        },
    }


def fs_fingerprint_file_strict(path: Path, verbose: bool = False) -> Dict[str, Any]:
    """
    Compute strict content-based fingerprint for a file.

    Uses: sha256(full content)

    Args:
        path: Path to file
        verbose: Print progress messages

    Returns:
        Fingerprint dict
    """
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)  # 1MB chunks
            if not chunk:
                break
            h.update(chunk)
            size += len(chunk)

    content_hash = h.hexdigest()

    if verbose:
        print(f"[fingerprint:strict] File: {path.name}")
        print(f"[fingerprint:strict]   size={size}, content_sha256={content_hash[:16]}...")
        print(f"[fingerprint:strict]   fingerprint={content_hash[:16]}...")

    return {
        "fingerprint": content_hash,
        "mode": "strict",
        "params": {"size": size, "content_sha256": content_hash},
    }


# ==================== Directory Fingerprints ====================


def _collect_directory_records(
    root: Path, include_content: bool = False, sample_bytes: int = 0, verbose: bool = False
) -> List[Tuple[str, int, int, str]]:
    """
    Collect file records from directory recursively.

    Args:
        root: Root directory path
        include_content: Whether to compute content hashes
        sample_bytes: If >0, hash only first N bytes (sample mode)
        verbose: Print progress messages

    Returns:
        List of tuples: (relpath, size, mtime_ns, content_hash)
        content_hash is "" if include_content=False
    """
    records = []
    file_count = 0

    for dirpath, dirnames, filenames in os.walk(root):
        # Sort for deterministic order
        dirnames.sort()
        filenames.sort()

        for filename in filenames:
            filepath = Path(dirpath) / filename

            # Skip symlinks
            if filepath.is_symlink():
                if verbose:
                    print(f"[fingerprint] Skipping symlink: {filepath}")
                continue

            # Get metadata
            try:
                stat = filepath.stat()
                size = stat.st_size
                mtime_ns = stat.st_mtime_ns
            except OSError as e:
                if verbose:
                    print(f"[fingerprint] Warning: Cannot stat {filepath}: {e}")
                continue

            # Compute content hash if requested
            content_hash = ""
            if include_content:
                try:
                    h = hashlib.sha256()
                    with filepath.open("rb") as f:
                        if sample_bytes > 0:
                            # Sample mode: read only first N bytes
                            chunk = f.read(min(sample_bytes, size))
                            h.update(chunk)
                        else:
                            # Strict mode: read full content
                            while True:
                                chunk = f.read(1024 * 1024)
                                if not chunk:
                                    break
                                h.update(chunk)
                    content_hash = h.hexdigest()
                except OSError as e:
                    if verbose:
                        print(f"[fingerprint] Warning: Cannot read {filepath}: {e}")
                    continue

            # Relative path from root
            relpath = filepath.relative_to(root)
            records.append((str(relpath), size, mtime_ns, content_hash))
            file_count += 1

    if verbose:
        print(f"[fingerprint] Collected {file_count} files from directory")

    # Sort by relative path for deterministic order
    records.sort(key=lambda x: x[0])
    return records


def fs_fingerprint_dir_meta(root: Path, verbose: bool = False) -> Dict[str, Any]:
    """
    Compute metadata-based fingerprint for a directory.

    Uses: (relpath, size, mtime_ns) for each file

    Args:
        root: Root directory path
        verbose: Print progress messages

    Returns:
        Fingerprint dict
    """
    records = _collect_directory_records(root, include_content=False, verbose=verbose)

    # Create canonical representation
    h = hashlib.sha256()
    for relpath, size, mtime_ns, _ in records:
        record = f"{relpath}|{size}|{mtime_ns}\n"
        h.update(record.encode("utf-8"))

    fingerprint = h.hexdigest()
    total_size = sum(r[1] for r in records)
    file_count = len(records)

    if verbose:
        print(f"[fingerprint:meta] Directory: {root.name}")
        print(
            f"[fingerprint:meta]   files={file_count}, total_size={total_size}"
        )
        print(f"[fingerprint:meta]   fingerprint={fingerprint[:16]}...")

    return {
        "fingerprint": fingerprint,
        "mode": "meta",
        "params": {"file_count": file_count, "total_size": total_size},
    }


def fs_fingerprint_dir_sample(
    root: Path, sample_bytes: int, verbose: bool = False
) -> Dict[str, Any]:
    """
    Compute sample-based fingerprint for a directory.

    Uses: (relpath, size, mtime_ns, sha256(first N bytes)) for each file

    Args:
        root: Root directory path
        sample_bytes: Number of bytes to sample from each file
        verbose: Print progress messages

    Returns:
        Fingerprint dict
    """
    records = _collect_directory_records(
        root, include_content=True, sample_bytes=sample_bytes, verbose=verbose
    )

    # Create canonical representation
    h = hashlib.sha256()
    for relpath, size, mtime_ns, content_hash in records:
        record = f"{relpath}|{size}|{mtime_ns}|{content_hash}\n"
        h.update(record.encode("utf-8"))

    fingerprint = h.hexdigest()
    total_size = sum(r[1] for r in records)
    file_count = len(records)

    if verbose:
        print(f"[fingerprint:sample] Directory: {root.name}")
        print(
            f"[fingerprint:sample]   files={file_count}, total_size={total_size}, sample={sample_bytes}B/file"
        )
        print(f"[fingerprint:sample]   fingerprint={fingerprint[:16]}...")

    if file_count > 1000:
        print(
            f"[fingerprint:sample] Warning: Directory has {file_count} files, sampling may take time"
        )

    return {
        "fingerprint": fingerprint,
        "mode": "sample",
        "params": {
            "file_count": file_count,
            "total_size": total_size,
            "sample_bytes": sample_bytes,
        },
    }


def fs_fingerprint_dir_strict(root: Path, verbose: bool = False) -> Dict[str, Any]:
    """
    Compute strict content-based fingerprint for a directory.

    Uses: (relpath, sha256(full content)) for each file

    Args:
        root: Root directory path
        verbose: Print progress messages

    Returns:
        Fingerprint dict
    """
    records = _collect_directory_records(
        root, include_content=True, sample_bytes=0, verbose=verbose
    )

    # Create canonical representation (Merkle-like)
    h = hashlib.sha256()
    for relpath, size, _, content_hash in records:
        record = f"{relpath}|{content_hash}\n"
        h.update(record.encode("utf-8"))

    fingerprint = h.hexdigest()
    total_size = sum(r[1] for r in records)
    file_count = len(records)

    if verbose:
        print(f"[fingerprint:strict] Directory: {root.name}")
        print(
            f"[fingerprint:strict]   files={file_count}, total_size={total_size}"
        )
        print(f"[fingerprint:strict]   fingerprint={fingerprint[:16]}...")

    if total_size > 100 * 1024 * 1024:  # 100MB
        print(
            f"[fingerprint:strict] Warning: Directory is {total_size / (1024*1024):.1f} MB, strict mode will read all content"
        )

    return {
        "fingerprint": fingerprint,
        "mode": "strict",
        "params": {
            "file_count": file_count,
            "total_size": total_size,
        },
    }


# ==================== Future Extension Hooks ====================


def compute_http_fingerprint(
    url: str, mode: str, sample_bytes: int = 200, verbose: bool = False
) -> Dict[str, Any]:
    """
    TODO: Compute fingerprint for HTTP source.

    Could use:
    - meta: ETag, Last-Modified, Content-Length headers
    - sample: HEAD + partial GET (Range request)
    - strict: Full GET + SHA256

    Args:
        url: HTTP/HTTPS URL
        mode: Fingerprint mode
        sample_bytes: Sample size for sample mode
        verbose: Print progress

    Returns:
        Fingerprint dict

    Raises:
        NotImplementedError: Not yet implemented
    """
    raise NotImplementedError("HTTP fingerprinting not yet implemented")


def compute_s3_fingerprint(
    bucket: str,
    key: str,
    mode: str,
    sample_bytes: int = 200,
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    TODO: Compute fingerprint for S3 source.

    Could use:
    - meta: ETag, LastModified, Size from head_object
    - sample: get_object with Range
    - strict: Full get_object + SHA256

    Args:
        bucket: S3 bucket name
        key: S3 object key
        mode: Fingerprint mode
        sample_bytes: Sample size for sample mode
        verbose: Print progress

    Returns:
        Fingerprint dict

    Raises:
        NotImplementedError: Not yet implemented
    """
    raise NotImplementedError("S3 fingerprinting not yet implemented")


def compute_pelican_fingerprint(
    url: str, mode: str, sample_bytes: int = 200, verbose: bool = False
) -> Dict[str, Any]:
    """
    TODO: Compute fingerprint for Pelican source.

    Could use Pelican-specific APIs or fall back to HTTP methods.

    Args:
        url: Pelican URL
        mode: Fingerprint mode
        sample_bytes: Sample size for sample mode
        verbose: Print progress

    Returns:
        Fingerprint dict

    Raises:
        NotImplementedError: Not yet implemented
    """
    raise NotImplementedError("Pelican fingerprinting not yet implemented")
