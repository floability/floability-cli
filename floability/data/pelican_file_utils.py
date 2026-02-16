# pelican_file_utils.py
from __future__ import annotations
from pathlib import Path
from urllib.parse import urlparse
from typing import Dict, Any, Optional, Tuple
from pelicanfs.core import PelicanFileSystem


# ---------------- helpers ----------------
def _safe_basename(name_or_path: str) -> str:
    """Return a local-safe basename (drops any directories/absolute prefixes)."""
    return Path(name_or_path).name or "download.bin"


def _split_director_and_path(url: str) -> Tuple[str, str]:
    """
    Map OSDF/Pelican URLs to (director, path) for PelicanFS.
      - osdf:///ns/path  -> (pelican://osg-htc.org, /ns/path)
      - pelican://host/ns/path -> (pelican://host, /ns/path)
    """
    u = urlparse(url)
    if u.scheme == "osdf":
        director = "pelican://osg-htc.org"
        path = u.path or "/"
    elif u.scheme == "pelican":
        director = f"pelican://{u.netloc}"
        path = u.path or "/"
    else:
        raise ValueError(f"Expected osdf:// or pelican:// URL, got: {url}")
    return director, path


def _get_fs_and_path(url: str) -> Tuple[PelicanFileSystem, str]:
    director, path = _split_director_and_path(url)
    return PelicanFileSystem(director), path


# ---------------- metadata (no body) ----------------
def pelican_file_metadata(url: str) -> Dict[str, Any]:
    """
    Return metadata for a Pelican/OSDF object without downloading the body.

    Returns a dict with:
      - exists: bool
      - name:   suggested local filename (basename)
      - size:   integer bytes (if provided)
      - type:   file type (fsspec 'type': 'file'|'directory'|...)
      - raw:    full fsspec metadata dict (provider-specific fields)
    """
    try:
        fs, path = _get_fs_and_path(url)
        meta = fs.info(path)  # metadata only; no content
        # PelicanFS typically returns {'name', 'size', 'type', ...}
        # Some deployments return absolute names in 'name' → collapse to basename.
        name = _safe_basename(meta.get("name") or Path(path).name)
        return {
            "exists": True,
            "name": name,
            "size": meta.get("size"),
            "type": meta.get("type"),
            "raw": meta,
        }
    except FileNotFoundError:
        # Object not found
        # Use URL’s last path component as a best-effort filename
        u = urlparse(url)
        return {
            "exists": False,
            "name": _safe_basename(Path(u.path).name),
            "size": None,
            "type": None,
            "raw": {"error": "not found"},
        }
    except Exception as e:
        # Any other transport/discovery error (network, auth, etc.)
        u = urlparse(url)
        return {
            "exists": False,
            "name": _safe_basename(Path(u.path).name),
            "size": None,
            "type": None,
            "raw": {"error": str(e)},
        }


# ---------------- download with resume + atomic finalize ----------------
def pelican_file_download(
    url: str,
    dest_dir: str = ".",
    filename: Optional[str] = None,
    *,
    overwrite: bool = False,
    resume: bool = True,
    chunk_size: int = 16 * 1024 * 1024,
    show_progress: bool = True,
) -> Path:
    """
    Download a Pelican/OSDF object to disk with resume and atomic finalize.
    Writes <name>.part then renames to final when complete.
    """
    try:
        from tqdm import tqdm
    except Exception:
        tqdm = None
        show_progress = False

    fs, path = _get_fs_and_path(url)

    # Metadata first (for size + safe local name)
    meta = pelican_file_metadata(url)
    if not meta["exists"]:
        raise FileNotFoundError(f"Pelican object not found: {url}")
    size = int(meta["size"]) if meta.get("size") is not None else None

    # Local filename (always basename)
    name = _safe_basename(filename or meta["name"] or Path(path).name)
    dest_dir_p = Path(dest_dir)
    dest_dir_p.mkdir(parents=True, exist_ok=True)

    dest = dest_dir_p / name
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.parent.mkdir(parents=True, exist_ok=True)

    # Already fully present?
    if dest.exists() and not overwrite:
        if size is not None and dest.stat().st_size == size:
            return dest
        if not resume:
            raise FileExistsError(f"{dest} exists; set overwrite=True or resume=True")

    # Determine resume offset (Pelican/HTTP usually supports seek/range)
    offset = 0
    if resume and tmp.exists() and size is not None:
        offset = tmp.stat().st_size
        if offset > size:
            # Corrupted partial; restart clean
            tmp.unlink(missing_ok=True)
            offset = 0

    mode = "ab" if offset else "wb"
    read_total = offset

    with fs.open(path, "rb") as src, open(tmp, mode) as dst:
        # Try to seek if resuming
        if offset:
            try:
                src.seek(offset)
            except Exception:
                # Remote stream isn’t seekable: restart from scratch
                dst.close()
                tmp.unlink(missing_ok=True)
                offset = 0
                read_total = 0
                with fs.open(path, "rb") as src2, open(tmp, "wb") as dst2:
                    pbar = (
                        tqdm(
                            total=size or 0,
                            initial=0,
                            unit="B",
                            unit_scale=True,
                            desc=name,
                        )
                        if (show_progress and tqdm)
                        else None
                    )
                    for buf in iter(lambda: src2.read(chunk_size), b""):
                        dst2.write(buf)
                        read_total += len(buf)
                        if pbar:
                            pbar.update(len(buf))
                    if pbar:
                        pbar.close()
                if size is not None and read_total != size:
                    raise IOError(
                        f"incomplete download: got {read_total} bytes, expected {size}"
                    )
                tmp.replace(dest)  # atomic finalize
                return dest

        # Normal (or resumed) streaming
        pbar = (
            tqdm(total=size or 0, initial=offset, unit="B", unit_scale=True, desc=name)
            if (show_progress and tqdm)
            else None
        )
        for buf in iter(lambda: src.read(chunk_size), b""):
            dst.write(buf)
            read_total += len(buf)
            if pbar:
                pbar.update(len(buf))
        if pbar:
            pbar.close()

    # Size check when known
    if size is not None and read_total != size:
        raise IOError(f"incomplete download: got {read_total} bytes, expected {size}")

    tmp.replace(dest)  # atomic finalize
    return dest


# ---------------- directory operations ----------------
def pelican_list_directory(url: str, recursive: bool = True):
    """
    List all files in a Pelican directory.
    
    Args:
        url: Pelican directory URL (must end with / or be a directory)
        recursive: If True, recursively list all files in subdirectories
    
    Returns:
        List of dicts with keys: path (remote), size, type, name
    """
    fs, base_path = _get_fs_and_path(url)
    
    # Ensure base_path is treated as directory
    if not base_path.endswith('/'):
        base_path = base_path + '/'
    
    files = []
    
    if recursive:
        # Use walk to recursively traverse
        try:
            for dirpath, dirnames, filenames in fs.walk(base_path):
                for fname in filenames:
                    fpath = f"{dirpath.rstrip('/')}/{fname}"
                    try:
                        info = fs.info(fpath)
                        files.append({
                            'path': fpath,
                            'size': info.get('size'),
                            'type': info.get('type'),
                            'name': fname,
                        })
                    except Exception:
                        # Skip files that can't be accessed
                        pass
        except Exception as e:
            raise IOError(f"Failed to walk directory {url}: {e}")
    else:
        # List only immediate children
        try:
            entries = fs.ls(base_path, detail=True)
            for entry in entries:
                if entry.get('type') == 'file':
                    files.append({
                        'path': entry.get('name'),
                        'size': entry.get('size'),
                        'type': entry.get('type'),
                        'name': Path(entry.get('name', '')).name,
                    })
        except Exception as e:
            raise IOError(f"Failed to list directory {url}: {e}")
    
    return files


def pelican_directory_download(
    url: str,
    dest_dir: str = ".",
    *,
    overwrite: bool = False,
    show_progress: bool = True,
) -> Path:
    """
    Download all files from a Pelican directory recursively.
    
    Args:
        url: Pelican directory URL (should end with /)
        dest_dir: Local destination directory
        overwrite: Overwrite existing files
        show_progress: Show progress for individual files
    
    Returns:
        Path to destination directory
    """
    dest_path = Path(dest_dir)
    dest_path.mkdir(parents=True, exist_ok=True)
    
    # Get base path to compute relative paths
    fs, base_path = _get_fs_and_path(url)
    if not base_path.endswith('/'):
        base_path = base_path + '/'
    
    # List all files
    try:
        files = pelican_list_directory(url, recursive=True)
    except Exception as e:
        raise IOError(f"Failed to list directory {url}: {e}")
    
    if not files:
        print(f"[pelican] Warning: No files found in {url}")
        return dest_path
    
    # Download each file, preserving directory structure
    total_files = len(files)
    failed = []
    
    for idx, file_info in enumerate(files, 1):
        remote_path = file_info['path']
        
        # Compute relative path from base
        if remote_path.startswith(base_path):
            rel_path = remote_path[len(base_path):]
        else:
            rel_path = Path(remote_path).name
        
        # Construct full destination path
        local_file = dest_path / rel_path
        local_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Construct full Pelican URL for this file
        u = urlparse(url)
        file_url = f"{u.scheme}://{u.netloc}{remote_path}"
        
        if show_progress:
            print(f"[pelican] ({idx}/{total_files}) Downloading {rel_path}")
        
        try:
            pelican_file_download(
                file_url,
                dest_dir=str(local_file.parent),
                filename=local_file.name,
                overwrite=overwrite,
                show_progress=False,  # Don't show per-file progress for cleaner output
            )
        except Exception as e:
            failed.append((rel_path, str(e)))
            if show_progress:
                print(f"[pelican] Error downloading {rel_path}: {e}")
    
    if failed:
        print(f"[pelican] Warning: {len(failed)}/{total_files} files failed to download")
        for rel_path, error in failed[:5]:  # Show first 5 failures
            print(f"[pelican]   - {rel_path}: {error}")
        if len(failed) > 5:
            print(f"[pelican]   ... and {len(failed) - 5} more")
    
    return dest_path


def is_pelican_directory(url: str) -> bool:
    """
    Check if a Pelican URL points to a directory.
    
    Args:
        url: Pelican URL to check
    
    Returns:
        True if URL points to a directory, False if it's a file
    """
    # Quick heuristic: if URL ends with /, it's a directory
    if url.endswith('/'):
        return True
    
    # Otherwise, check metadata
    try:
        fs, path = _get_fs_and_path(url)
        info = fs.info(path)
        return info.get('type') == 'directory'
    except Exception:
        # If we can't determine, assume file
        return False
