# http_file_utils.py
from __future__ import annotations
from pathlib import Path
from urllib.parse import urlparse, unquote
from typing import Optional, Dict, Any
import requests, re

# ---- helpers ----
_CD_RE = re.compile(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';]+)')

def _name_from_cd(cd: Optional[str]) -> Optional[str]:
    if not cd:
        return None
    m = _CD_RE.search(cd)
    return Path(unquote(m.group(1))).name if m else None

def _basename_from_url(url: str, fallback: str = "download.bin") -> str:
    return Path(unquote(urlparse(url).path)).name or fallback

# ---- metadata (no body) ----
def http_file_metadata(url: str, timeout: int = 30) -> Dict[str, Any]:
    """
    Return metadata for an HTTP/HTTPS resource without downloading the body.
    Fields: exists, name, size, type, accepts_ranges, raw
    """
    try:
        r = requests.head(url, allow_redirects=True, timeout=timeout)
        # Fallback for servers that don't implement HEAD
        if r.status_code in (405, 501):
            r = requests.get(url, headers={"Range": "bytes=0-0"}, stream=True, timeout=timeout)

        headers = r.headers
        exists = r.status_code in (200, 206)  # OK or Partial Content

        # Prefer filename from Content-Disposition; else from the FINAL URL
        fname = _name_from_cd(headers.get("Content-Disposition")) or _basename_from_url(getattr(r, "url", url))

        size = None
        if "Content-Length" in headers:
            try:
                size = int(headers["Content-Length"])
            except (ValueError, TypeError):
                size = None

        ctype = headers.get("Content-Type")
        accepts_ranges = headers.get("Accept-Ranges") == "bytes"

        return {
            "exists": exists,
            "name": Path(fname).name,
            "size": size,
            "type": ctype,
            "accepts_ranges": accepts_ranges,
            "raw": {
                "status": r.status_code,
                "final_url": getattr(r, "url", url),
                "headers": dict(headers),
            },
        }

    except requests.RequestException as e:
        # Network/timeout/DNS/etc.
        return {
            "exists": False,
            "name": _basename_from_url(url),
            "size": None,
            "type": None,
            "accepts_ranges": False,
            "raw": {"error": str(e), "status": None, "final_url": url, "headers": {}},
        }

# ---- download with resume + atomic finalize ----
def http_file_download(url: str,
                       dest_dir: str = ".",
                       filename: Optional[str] = None,
                       *,
                       overwrite: bool = False,
                       resume: bool = True,
                       chunk_size: int = 8 * 1024 * 1024,
                       show_progress: bool = True,
                       timeout: int = 30) -> Path:
    """
    Download HTTP/HTTPS URL to disk with resume support.
    Writes <name>.part then atomically renames to final.
    """
    try:
        from tqdm import tqdm
    except Exception:
        tqdm = None
        show_progress = False

    meta = http_file_metadata(url, timeout=timeout)
    if not meta["exists"]:
        raise FileNotFoundError(f"URL not accessible: {meta['raw'].get('final_url', url)} "
                                f"(status {meta['raw'].get('status')})")

    size = meta["size"]
    accepts_ranges = bool(meta["accepts_ranges"])

    # Local name (always basename)
    name = Path(filename or meta["name"]).name
    dest_dir_p = Path(dest_dir); dest_dir_p.mkdir(parents=True, exist_ok=True)
    dest = dest_dir_p / name
    tmp = dest.with_suffix(dest.suffix + ".part")

    # Already present?
    if dest.exists() and not overwrite:
        if size is not None and dest.stat().st_size == size:
            return dest
        if not resume:
            raise FileExistsError(f"{dest} exists; set overwrite=True or resume=True")

    # Resume offset
    offset = 0
    if resume and tmp.exists() and size is not None and accepts_ranges:
        offset = tmp.stat().st_size
        if offset > size:
            tmp.unlink(missing_ok=True)
            offset = 0

    mode = "ab" if offset else "wb"
    headers: Dict[str, str] = {}
    if offset:
        headers["Range"] = f"bytes={offset}-"

    downloaded = offset

    with requests.get(url, headers=headers, stream=True, timeout=timeout) as r:
        # If server ignored Range, restart clean
        if offset and r.status_code != 206:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            offset = 0
            mode = "wb"
            downloaded = 0
            headers.pop("Range", None)
            with requests.get(url, headers=headers, stream=True, timeout=timeout) as r2:
                r2.raise_for_status()
                with open(tmp, mode) as f:
                    pbar = tqdm(total=size or 0, initial=0, unit="B", unit_scale=True, desc=name) if (show_progress and tqdm) else None
                    for chunk in r2.iter_content(chunk_size=chunk_size):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if pbar: pbar.update(len(chunk))
                    if pbar: pbar.close()
        else:
            r.raise_for_status()
            with open(tmp, mode) as f:
                pbar = tqdm(total=size or 0, initial=offset, unit="B", unit_scale=True, desc=name) if (show_progress and tqdm) else None
                for chunk in r.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if pbar: pbar.update(len(chunk))
                if pbar: pbar.close()

    # (Optional) size check if server provided Content-Length (some compress on the fly)
    if size is not None and downloaded != size:
        # Not fatal by default; you can raise if you require exact match:
        # raise IOError(f"Incomplete download: got {downloaded}, expected {size}")
        pass

    tmp.replace(dest)  # atomic finalize
    return dest
