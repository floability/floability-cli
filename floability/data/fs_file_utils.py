from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, Optional
import os
import shutil
import stat as statmod

__all__ = [
    "fs_file_metadata",
    "fs_file_download",
]


def _safe_basename(p: str) -> str:
    return Path(p).name or "file.bin"


def fs_file_metadata(path: str) -> Dict[str, Any]:
    """Return metadata for a local filesystem path without reading contents.

    Similar shape to http_file_metadata / pelican_file_metadata.
    For directories, size is None and type is 'directory'.
    """
    p = Path(path)
    if not p.exists():
        return {
            "exists": False,
            "name": _safe_basename(path),
            "size": None,
            "type": None,
            "raw": {"error": "not found"},
        }

    try:
        st = p.stat()
        mode = st.st_mode
        if statmod.S_ISDIR(mode):
            ftype = "directory"
            fsize = None
        elif statmod.S_ISREG(mode):
            ftype = "file"
            fsize = st.st_size
        else:
            # Could be symlink/block/char/socket; treat generically
            ftype = "other"
            fsize = st.st_size if hasattr(st, "st_size") else None

        raw = {
            "mode": mode,
            "inode": getattr(st, "st_ino", None),
            "device": getattr(st, "st_dev", None),
            "nlink": getattr(st, "st_nlink", None),
            "uid": getattr(st, "st_uid", None),
            "gid": getattr(st, "st_gid", None),
            "size": getattr(st, "st_size", None),
            "atime": getattr(st, "st_atime", None),
            "mtime": getattr(st, "st_mtime", None),
            "ctime": getattr(st, "st_ctime", None),
        }

        return {
            "exists": True,
            "name": _safe_basename(path),
            "size": fsize,
            "type": ftype,
            "raw": raw,
        }
    except OSError as e:
        return {
            "exists": False,
            "name": _safe_basename(path),
            "size": None,
            "type": None,
            "raw": {"error": str(e)},
        }


def fs_file_copy(
    src: str,
    dest_dir: str = ".",
    filename: Optional[str] = None,
    *,
    overwrite: bool = False,
    resume: bool = True,
    chunk_size: int = 16 * 1024 * 1024,
    show_progress: bool = True,
) -> Path:
    """Copy a local file to dest_dir with optional resume + atomic finalize.

    Behavior parallels http_file_download / pelican_file_download for consistency.
    Directories are not supported (raise if src is a directory).
    """
    try:
        from tqdm import tqdm
    except Exception:
        tqdm = None
        show_progress = False

    src_p = Path(src)
    if not src_p.exists():
        raise FileNotFoundError(f"Source not found: {src}")
    if src_p.is_dir():
        raise IsADirectoryError(f"Source is a directory (not supported): {src}")

    size = src_p.stat().st_size
    name = Path(filename).name if filename else src_p.name

    dest_dir_p = Path(dest_dir)
    dest_dir_p.mkdir(parents=True, exist_ok=True)
    dest = dest_dir_p / name
    tmp = dest.with_suffix(dest.suffix + ".part")

    # Already present and matching size
    if dest.exists() and not overwrite:
        if dest.stat().st_size == size:
            return dest
        if not resume:
            raise FileExistsError(f"{dest} exists; set overwrite=True or resume=True")

    # Determine resume offset
    offset = 0
    if resume and tmp.exists():
        existing = tmp.stat().st_size
        if existing < size:
            offset = existing
        elif existing == size:
            # Already complete but not finalized
            tmp.replace(dest)
            return dest
        else:
            # Larger than source? discard
            tmp.unlink(missing_ok=True)

    mode = "ab" if offset else "wb"
    copied = offset

    pbar = None
    if show_progress and tqdm:
        pbar = tqdm(total=size, initial=offset, unit="B", unit_scale=True, desc=name)

    with open(src_p, "rb") as s, open(tmp, mode) as d:
        if offset:
            s.seek(offset)
        while True:
            buf = s.read(chunk_size)
            if not buf:
                break
            d.write(buf)
            copied += len(buf)
            if pbar:
                pbar.update(len(buf))
    if pbar:
        pbar.close()

    if copied != size:
        raise IOError(f"Incomplete copy: got {copied}, expected {size}")

    tmp.replace(dest)
    return dest
