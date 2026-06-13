"""
XRootD file utilities for Floability data operations.

Provides metadata fetching and file downloads from XRootD servers using the
native xrootd Python bindings. Mirrors the interface of s3_file_utils.py and
pelican_file_utils.py.

URL scheme: root://server//path/to/file  or  root://server:port//path/to/file

Downloads use XRootD.client.File to stream chunks directly, writing to a
.part temp file and atomically renaming on completion.
"""
from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List


# ── URI helpers ───────────────────────────────────────────────────────────────

def parse_xrootd_uri(uri: str) -> Tuple[str, str]:
    """Parse a root:// URI into (server, path).

    Examples:
        root://cmsxrootd.crc.nd.edu//store/user/foo/bar.root
            → ('root://cmsxrootd.crc.nd.edu', '/store/user/foo/bar.root')
        root://server:1094//path/to/dir/
            → ('root://server:1094', '/path/to/dir/')

    Raises:
        ValueError: If the URI is not a valid root:// URI.
    """
    if not uri.startswith("root://"):
        raise ValueError(f"Invalid XRootD URI (expected root://): {uri}")

    rest = uri[len("root://"):]
    if not rest:
        raise ValueError(f"Missing server in XRootD URI: {uri}")

    slash = rest.find("/")
    if slash == -1:
        return f"root://{rest}", "/"

    server = rest[:slash]
    path = rest[slash:]

    # Normalise double-slash (root://server//path) to single leading slash.
    if path.startswith("//"):
        path = path[1:]

    return f"root://{server}", path or "/"


def _full_uri(server: str, path: str) -> str:
    """Reconstruct a full root:// URI from server and path.

    path starts with '/', so f"{server}/{path}" yields root://server//path.
    """
    return f"{server}/{path}"


def _get_fs(server: str):
    """Return an XRootD FileSystem client for *server*."""
    try:
        from XRootD import client as xrd_client
    except ImportError:
        raise ImportError(
            "xrootd Python bindings are required. "
            "Install with: conda install -c conda-forge xrootd"
        )
    return xrd_client.FileSystem(server)


def _safe_basename(path: str) -> str:
    return Path(path).name or "download.bin"


# ── Checksum query ────────────────────────────────────────────────────────────

def _query_checksum(fs, path: str) -> Optional[str]:
    """Query XRootD server for file checksum. Returns 'alg:hex' or None.

    Response format from server: "md5 923c3f8c..." → normalised to "md5:923c3f8c..."
    """
    try:
        from XRootD.client.flags import QueryCode
        status, response = fs.query(QueryCode.CHECKSUM, path)
        if not status.ok or not response:
            return None
        raw = response.decode("utf-8", errors="replace").strip().rstrip("\x00").strip()
        if " " in raw:
            alg, hexval = raw.split(None, 1)
            hexval = hexval.strip()
            if hexval.lower() == "none":
                return None
            return f"{alg.lower()}:{hexval}"
        return raw or None
    except Exception:
        return None


# ── File metadata (no body transfer) ─────────────────────────────────────────

def xrootd_file_metadata(uri: str) -> Dict[str, Any]:
    """Return metadata for an XRootD object without downloading the body.

    Returns dict with: exists, name, size, mtime, checksum, type, raw
    """
    try:
        server, path = parse_xrootd_uri(uri)
    except ValueError as e:
        return {"exists": False, "name": "invalid", "size": None,
                "mtime": None, "checksum": None, "type": None,
                "raw": {"error": str(e)}}

    try:
        from XRootD.client.flags import StatInfoFlags
        fs = _get_fs(server)

        status, stat = fs.stat(path)
        if not status.ok:
            return {"exists": False, "name": _safe_basename(path),
                    "size": None, "mtime": None, "checksum": None,
                    "type": None, "raw": {"error": status.message}}

        is_dir = bool(stat.flags & StatInfoFlags.IS_DIR)
        checksum = None if is_dir else _query_checksum(fs, path)

        return {
            "exists": True,
            "name": _safe_basename(path),
            "size": stat.size,
            "mtime": stat.modtime,
            "checksum": checksum,
            "type": "directory" if is_dir else "file",
            "raw": {"id": stat.id, "flags": stat.flags, "modtimestr": stat.modtimestr},
        }

    except Exception as e:
        return {"exists": False, "name": _safe_basename(path),
                "size": None, "mtime": None, "checksum": None,
                "type": None, "raw": {"error": str(e)}}


# ── Directory detection ───────────────────────────────────────────────────────

def is_xrootd_directory(uri: str) -> bool:
    """Return True if the XRootD URI points to a directory."""
    if uri.endswith("/"):
        return True
    try:
        from XRootD.client.flags import StatInfoFlags
        server, path = parse_xrootd_uri(uri)
        fs = _get_fs(server)
        status, stat = fs.stat(path)
        if not status.ok:
            return False
        return bool(stat.flags & StatInfoFlags.IS_DIR)
    except Exception:
        return False


# ── Directory listing ─────────────────────────────────────────────────────────

def xrootd_list_objects(
    uri: str,
    recursive: bool = True,
    fetch_checksums: bool = True,
) -> List[Dict[str, Any]]:
    """List files under an XRootD directory URI.

    Returns a list of dicts with:
      exists, name, path, rel_path, size, mtime, checksum, type, uri

    fetch_checksums: query per-file checksum (fast on pre-storing servers,
                     one round-trip per file after the directory listing).
    """
    server, base_path = parse_xrootd_uri(uri)
    if not base_path.endswith("/"):
        base_path += "/"

    fs = _get_fs(server)
    results: List[Dict[str, Any]] = []
    _collect_entries(fs, server, base_path, base_path, results, recursive, fetch_checksums)
    return results


def _collect_entries(
    fs,
    server: str,
    base_path: str,
    current_path: str,
    results: List[Dict[str, Any]],
    recursive: bool,
    fetch_checksums: bool,
) -> None:
    """Recursively collect file entries under current_path into results."""
    from XRootD.client.flags import DirListFlags, StatInfoFlags

    status, listing = fs.dirlist(current_path, DirListFlags.STAT)
    if not status.ok or listing is None:
        return

    for entry in listing:
        entry_path = f"{current_path.rstrip('/')}/{entry.name}"
        stat = entry.statinfo
        is_dir = stat is not None and bool(stat.flags & StatInfoFlags.IS_DIR)

        if is_dir:
            if recursive:
                _collect_entries(
                    fs, server, base_path, entry_path + "/",
                    results, recursive, fetch_checksums,
                )
        else:
            rel_path = entry_path[len(base_path):]
            checksum = _query_checksum(fs, entry_path) if fetch_checksums else None
            results.append({
                "exists": True,
                "name": entry.name,
                "path": entry_path,
                "rel_path": rel_path,
                "size": stat.size if stat else None,
                "mtime": stat.modtime if stat else None,
                "checksum": checksum,
                "type": "file",
                "uri": _full_uri(server, entry_path),
            })


# ── File download ─────────────────────────────────────────────────────────────

def xrootd_file_download(
    uri: str,
    dest_dir: str = ".",
    filename: Optional[str] = None,
    *,
    overwrite: bool = False,
    resume: bool = True,
    chunk_size: int = 8 * 1024 * 1024,
    show_progress: bool = True,
) -> Path:
    """Download an XRootD file by streaming chunks via XRootD.client.File.

    Writes to a .part temp file then atomically renames on completion.
    Supports resume (append to existing .part) and overwrite.
    """
    try:
        from tqdm import tqdm as _tqdm
    except ImportError:
        _tqdm = None

    from XRootD import client as xrd_client

    server, path = parse_xrootd_uri(uri)
    local_filename = filename or _safe_basename(path)
    dest_dir_p = Path(dest_dir)
    dest_dir_p.mkdir(parents=True, exist_ok=True)

    dest = dest_dir_p / local_filename
    tmp = dest.with_suffix(dest.suffix + ".part")

    # Get remote size for progress and completeness check
    fs = _get_fs(server)
    status, stat = fs.stat(path)
    if not status.ok:
        raise FileNotFoundError(f"XRootD file not found: {uri} — {status.message}")
    size = stat.size

    # Already fully present
    if dest.exists() and not overwrite:
        if dest.stat().st_size == size:
            return dest

    # Resume offset
    offset = 0
    if resume and not overwrite and tmp.exists():
        offset = tmp.stat().st_size
        if offset >= size:
            tmp.replace(dest)
            return dest

    mode = "ab" if offset else "wb"

    f = xrd_client.File()
    status, _ = f.open(uri)
    if not status.ok:
        raise IOError(f"Cannot open {uri}: {status.message}")

    pbar = (
        _tqdm(total=size, initial=offset, unit="B", unit_scale=True, desc=local_filename)
        if (show_progress and _tqdm)
        else None
    )

    read_total = offset
    try:
        with open(tmp, mode) as dst:
            current = offset
            while current < size:
                to_read = min(chunk_size, size - current)
                status, data = f.read(offset=current, size=to_read)
                if not status.ok or not data:
                    break
                dst.write(data)
                n = len(data)
                read_total += n
                current += n
                if pbar:
                    pbar.update(n)
    finally:
        if pbar:
            pbar.close()
        f.close()

    if read_total != size:
        raise IOError(f"Incomplete download of {uri}: got {read_total} bytes, expected {size}")

    tmp.replace(dest)
    return dest


# ── Directory download ────────────────────────────────────────────────────────

def xrootd_directory_download(
    uri: str,
    dest_dir: str = ".",
    *,
    overwrite: bool = False,
    resume: bool = True,
    chunk_size: int = 8 * 1024 * 1024,
    show_progress: bool = True,
) -> Path:
    """Download all files from an XRootD directory, preserving relative structure."""
    dest_path = Path(dest_dir)
    dest_path.mkdir(parents=True, exist_ok=True)

    objects = xrootd_list_objects(uri, recursive=True, fetch_checksums=False)

    if not objects:
        print(f"[xrootd] Warning: No files found in {uri}")
        return dest_path

    total = len(objects)
    print(f"[xrootd] Found {total} files to download from {uri}")

    failed = []
    for idx, obj in enumerate(objects, 1):
        rel = obj["rel_path"]
        local_file = dest_path / rel
        if show_progress:
            print(f"[xrootd] ({idx}/{total}) {rel}")
        try:
            xrootd_file_download(
                obj["uri"],
                dest_dir=str(local_file.parent),
                filename=local_file.name,
                overwrite=overwrite,
                resume=resume,
                chunk_size=chunk_size,
                show_progress=False,
            )
        except Exception as e:
            failed.append((rel, str(e)))
            print(f"[xrootd]   ERROR: {e}")

    if failed:
        print(f"[xrootd] Warning: {len(failed)}/{total} files failed")

    return dest_path


# ── Source metadata for cache key computation ─────────────────────────────────

def xrootd_source_metadata(uri: str) -> Dict[str, Any]:
    """Normalized XRootD source metadata for cache key computation. No body transfer.

    For files:       object_type, size, mtime, checksum
    For directories: object_type, file_count, total_size,
                     files[] each with rel_path, size, mtime, checksum

    Returns dict with 'ok' bool.
    """
    if is_xrootd_directory(uri):
        try:
            objects = xrootd_list_objects(uri, recursive=True, fetch_checksums=True)
            files = sorted(
                [
                    {k: v for k, v in {
                        "rel_path": obj["rel_path"],
                        "size": obj["size"],
                        "mtime": obj["mtime"],
                        "checksum": obj["checksum"],
                    }.items() if v is not None}
                    for obj in objects
                ],
                key=lambda f: f.get("rel_path", ""),
            )
            return {
                "ok": True,
                "object_type": "directory",
                "file_count": len(files),
                "total_size": sum(f.get("size") or 0 for f in files),
                "files": files,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    meta = xrootd_file_metadata(uri)
    return {
        "ok": meta.get("exists", False),
        "object_type": "file",
        "size": meta.get("size"),
        "mtime": meta.get("mtime"),
        "checksum": meta.get("checksum"),
    }
