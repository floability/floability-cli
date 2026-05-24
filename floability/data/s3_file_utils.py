"""
S3 file utilities for Floability data operations.

Provides metadata fetching and file downloads from S3 buckets using boto3.
Mirrors the interface of http_file_utils.py and pelican_file_utils.py.
"""
from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import os
import time


def _env_aws_no_sign_request() -> bool:
    """
    Determine whether AWS requests should be unsigned (no-signing).

    Behavior: default to unsigned (return True) unless the environment
    variable `DISABLE_AWS_NO_SIGN_REQUEST` is explicitly set to a truthy
    value ('true', '1', 'yes'), in which case unsigned requests are
    disabled (return False).
    """
    val = os.environ.get("DISABLE_AWS_NO_SIGN_REQUEST")
    if val is None:
        return True
    return val.strip().lower() not in ("true", "1", "yes")


def _get_boto3_client(anonymous: Optional[bool] = None):
    """
    Get or create boto3 S3 client.

    Args:
        anonymous: If True, use anonymous access (no credentials required).
                   If None, derive behavior from `DISABLE_AWS_NO_SIGN_REQUEST`.

    Uses default AWS credential chain (env vars, ~/.aws/credentials, IAM roles).
    For HPC environments without AWS config, set environment variables:
        AWS_ACCESS_KEY_ID
        AWS_SECRET_ACCESS_KEY
        AWS_DEFAULT_REGION (optional)

    Default behavior: requests are unsigned (anonymous) unless the
    environment variable `DISABLE_AWS_NO_SIGN_REQUEST` is set to a truthy
    value to explicitly disable the no-sign behavior.
    """
    try:
        import boto3
        from botocore import UNSIGNED
        from botocore.config import Config

        # If caller didn't specify, derive anonymous behavior from env
        if anonymous is None:
            anonymous = _env_aws_no_sign_request()

        if anonymous:
            # Anonymous access for public buckets
            return boto3.client("s3", config=Config(signature_version=UNSIGNED))
        else:
            # Use default credential chain
            return boto3.client("s3")
    except ImportError:
        raise ImportError(
            "boto3 is required for S3 support. Install with: pip install boto3"
        )
    except Exception as e:
        raise RuntimeError(
            f"Failed to create S3 client. Check AWS credentials or set DISABLE_AWS_NO_SIGN_REQUEST to disable unsigned access: {e}"
        )


def parse_s3_uri(uri: str) -> Tuple[str, str]:
    """
    Parse S3 URI into bucket and key.

    Args:
        uri: S3 URI in format s3://bucket/key or s3://bucket/prefix/key

    Returns:
        Tuple of (bucket, key)

    Raises:
        ValueError: If URI is not a valid S3 URI
    """
    if not uri.startswith("s3://"):
        raise ValueError(f"Invalid S3 URI: {uri} (expected format: s3://bucket/key)")

    # Remove s3:// prefix
    path = uri[5:]

    if not path:
        raise ValueError(f"Invalid S3 URI format: {uri} (missing bucket/key)")

    # Split into bucket and key
    if "/" in path:
        parts = path.split("/", 1)
        bucket = parts[0]
        key = parts[1]
    else:
        bucket = path
        key = ""

    if not bucket:
        raise ValueError(f"Missing bucket in S3 URI: {uri}")

    return bucket, key


def _safe_basename(key: str) -> str:
    """Extract basename from S3 key, handling paths."""
    if not key:
        return "download.bin"
    basename = Path(key).name
    return basename if basename else "download.bin"


def s3_file_metadata(
    uri: str,
    timeout: int = 30,
    anonymous: bool = None,
) -> Dict[str, Any]:
    """
    Fetch metadata for an S3 object without downloading the body.

    Args:
        uri: S3 URI (s3://bucket/key)
        timeout: Request timeout in seconds (passed to boto3 config)
        anonymous: If True, use anonymous access (no credentials required).
                  If None, auto-detect from `DISABLE_AWS_NO_SIGN_REQUEST` env var

    Returns:
        Dict with keys: exists, name, size, type, etag, last_modified, raw
    """
    try:
        bucket, key = parse_s3_uri(uri)
    except ValueError as e:
        return {
            "exists": False,
            "name": "invalid",
            "size": None,
            "type": None,
            "etag": None,
            "last_modified": None,
            "raw": {"error": str(e)},
        }

    try:
        from botocore.config import Config

        # Auto-detect anonymous from env if not specified
        if anonymous is None:
            anonymous = _env_aws_no_sign_request()

        client = _get_boto3_client(anonymous=anonymous)
        config = Config(connect_timeout=timeout, read_timeout=timeout)

        # HEAD request to get metadata
        response = client.head_object(Bucket=bucket, Key=key)

        # Extract metadata
        size = response.get("ContentLength")
        content_type = response.get("ContentType")
        etag = response.get("ETag", "").strip('"')
        last_modified = response.get("LastModified")

        last_modified_str = None
        if last_modified:
            last_modified_str = last_modified.isoformat()

        return {
            "exists": True,
            "name": _safe_basename(key),
            "size": size,
            "type": content_type or "application/octet-stream",
            "etag": etag,
            "last_modified": last_modified_str,
            "raw": response,
        }

    except Exception as e:
        error_code = getattr(e, "response", {}).get("Error", {}).get("Code", "Unknown")

        if error_code in ("404", "NoSuchKey", "NotFound"):
            exists = False
        else:
            exists = False

        return {
            "exists": exists,
            "name": _safe_basename(key),
            "size": None,
            "type": None,
            "etag": None,
            "last_modified": None,
            "raw": {
                "error": str(e),
                "error_code": error_code,
            },
        }


def s3_file_download(
    uri: str,
    dest_dir: str = ".",
    filename: Optional[str] = None,
    *,
    overwrite: bool = False,
    resume: bool = True,
    chunk_size: int = 8 * 1024 * 1024,
    show_progress: bool = True,
    anonymous: bool = None,
) -> Path:
    """
    Download an S3 object to local disk with resume support and atomic finalization.

    Downloads to <filename>.part then renames to final name when complete.
    """
    try:
        from tqdm import tqdm
    except ImportError:
        tqdm = None
        show_progress = False

    # Parse URI
    bucket, key = parse_s3_uri(uri)

    # Auto-detect anonymous from env if not specified
    if anonymous is None:
        anonymous = _env_aws_no_sign_request()

    # Get metadata for size information
    meta = s3_file_metadata(uri, anonymous=anonymous)
    if not meta["exists"]:
        raise FileNotFoundError(f"S3 object not found: {uri}")

    size = meta.get("size")

    # Determine local filename
    local_filename = filename or _safe_basename(key)
    dest_dir_p = Path(dest_dir)
    dest_dir_p.mkdir(parents=True, exist_ok=True)

    dest = dest_dir_p / local_filename
    tmp = dest.with_suffix(dest.suffix + ".part")

    # Check if already present
    if dest.exists() and not overwrite:
        if size is not None and dest.stat().st_size == size:
            return dest
        if not resume:
            raise FileExistsError(f"{dest} exists; set overwrite=True or resume=True")

    # Determine resume offset
    offset = 0
    if resume and tmp.exists() and size is not None:
        offset = tmp.stat().st_size
        if offset >= size:
            if offset == size:
                tmp.replace(dest)
                return dest
            else:
                tmp.unlink(missing_ok=True)
                offset = 0

    # Create boto3 client
    client = _get_boto3_client(anonymous=anonymous)

    mode = "ab" if offset > 0 else "wb"
    read_total = offset

    try:
        kwargs = {"Bucket": bucket, "Key": key}
        if offset > 0:
            kwargs["Range"] = f"bytes={offset}-"

        response = client.get_object(**kwargs)
        body = response["Body"]

        pbar = None
        if show_progress and tqdm and size:
            pbar = tqdm(total=size, initial=offset, unit="B", unit_scale=True, desc=local_filename)

        with open(tmp, mode) as f:
            while True:
                chunk = body.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                read_total += len(chunk)
                if pbar:
                    pbar.update(len(chunk))

        if pbar:
            pbar.close()

        if size is not None and read_total != size:
            raise IOError(f"Incomplete download: got {read_total} bytes, expected {size}")

        tmp.replace(dest)
        return dest

    except Exception as e:
        raise IOError(f"S3 download failed: {e}") from e


def is_s3_directory(uri: str, anonymous: bool = None) -> bool:
    """
    Check if an S3 URI represents a directory (prefix with multiple objects).

    Detection logic:
    1. If URI ends with "/", assume it's a directory
    2. Otherwise, try to list objects with the prefix
    3. If multiple objects exist or object ends with "/", it's a directory
    """
    if uri.endswith("/"):
        return True

    try:
        bucket, prefix = parse_s3_uri(uri)

        if anonymous is None:
            anonymous = _env_aws_no_sign_request()

        client = _get_boto3_client(anonymous=anonymous)

        response = client.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=2)

        contents = response.get("Contents", [])

        if not contents:
            return False

        if len(contents) == 1 and contents[0]["Key"] == prefix:
            return False

        return True

    except Exception:
        return False


def s3_directory_download(
    uri: str,
    dest_dir: str = ".",
    *,
    overwrite: bool = False,
    resume: bool = True,
    chunk_size: int = 8 * 1024 * 1024,
    show_progress: bool = True,
    anonymous: bool = None,
    preserve_structure: bool = True,
) -> Path:
    """
    Download an entire S3 directory (prefix) recursively.
    """
    bucket, prefix = parse_s3_uri(uri)

    if prefix and not prefix.endswith("/"):
        prefix += "/"

    dest_dir_p = Path(dest_dir)
    dest_dir_p.mkdir(parents=True, exist_ok=True)

    objects = s3_list_objects(f"s3://{bucket}/{prefix}", recursive=True, anonymous=anonymous)

    if not objects:
        print(f"Warning: No objects found in {uri}")
        return dest_dir_p

    print(f"Found {len(objects)} objects to download from {uri}")

    for obj in objects:
        obj_key = obj["key"]

        if obj_key.endswith("/"):
            continue

        if preserve_structure:
            rel_path = obj_key[len(prefix):] if obj_key.startswith(prefix) else obj_key
            local_path = dest_dir_p / rel_path
        else:
            local_path = dest_dir_p / Path(obj_key).name

        local_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            obj_uri = obj["uri"]
            s3_file_download(
                uri=obj_uri,
                dest_dir=str(local_path.parent),
                filename=local_path.name,
                overwrite=overwrite,
                resume=resume,
                chunk_size=chunk_size,
                show_progress=show_progress,
                anonymous=anonymous,
            )
        except Exception as e:
            print(f"Warning: Failed to download {obj_key}: {e}")

    return dest_dir_p


def s3_list_objects(
    uri: str,
    recursive: bool = True,
    anonymous: bool = None,
) -> list[Dict[str, Any]]:
    """
    List objects in an S3 bucket/prefix (for directory support).
    """
    bucket, prefix = parse_s3_uri(uri)

    if prefix and not prefix.endswith("/"):
        prefix += "/"

    if anonymous is None:
        anonymous = _env_aws_no_sign_request()

    client = _get_boto3_client(anonymous=anonymous)

    results: list[Dict[str, Any]] = []
    paginator = client.get_paginator("list_objects_v2")

    paginate_params = {"Bucket": bucket, "Prefix": prefix}

    if not recursive:
        paginate_params["Delimiter"] = "/"

    page_iterator = paginator.paginate(**paginate_params)

    for page in page_iterator:
        for obj in page.get("Contents", []):
            key = obj["Key"]
            size = obj.get("Size")
            last_modified = obj.get("LastModified")
            etag = obj.get("ETag", "").strip('"')

            last_modified_str = None
            if last_modified:
                last_modified_str = last_modified.isoformat()

            results.append({
                "exists": True,
                "name": _safe_basename(key),
                "key": key,
                "size": size,
                "type": "application/octet-stream",
                "etag": etag,
                "last_modified": last_modified_str,
                "uri": f"s3://{bucket}/{key}",
                "raw": obj,
            })

        if not recursive:
            for prefix_obj in page.get("CommonPrefixes", []):
                prefix_key = prefix_obj["Prefix"]
                results.append({
                    "exists": True,
                    "name": _safe_basename(prefix_key.rstrip("/")),
                    "key": prefix_key,
                    "size": None,
                    "type": "directory",
                    "etag": None,
                    "last_modified": None,
                    "uri": f"s3://{bucket}/{prefix_key}",
                    "raw": prefix_obj,
                })

    return results


# ──────────────────────────────────────────────────────────────────────────────
# Source metadata for cache key computation
# ──────────────────────────────────────────────────────────────────────────────

def s3_source_metadata(uri: str, anonymous: bool = None) -> Dict[str, Any]:
    """Normalized S3 source metadata for cache key computation. No body transfer.

    For files: reuses s3_file_metadata (HEAD only).
    For directories: reuses s3_list_objects (paginated listing) and strips the
    prefix to produce stable rel_path values.

    Returns dict with 'ok' bool and fingerprint fields:
      file      → object_type, etag, size, last_modified
      directory → object_type, file_count, total_size, files[]

    Timing is not included — callers should wrap with perf.start_timer/end_timer.
    """
    if anonymous is None:
        anonymous = _env_aws_no_sign_request()

    if is_s3_directory(uri, anonymous=anonymous):
        try:
            _, prefix = parse_s3_uri(uri)
            if prefix and not prefix.endswith("/"):
                prefix += "/"

            objects = s3_list_objects(uri, recursive=True, anonymous=anonymous)
            files = []
            for obj in objects:
                key = obj["key"]
                if key.endswith("/"):
                    continue
                rel = key[len(prefix):] if key.startswith(prefix) else key
                files.append({
                    "rel_path": rel,
                    "etag": obj.get("etag"),
                    "size": obj.get("size"),
                    "last_modified": obj.get("last_modified"),
                })
            files.sort(key=lambda f: f["rel_path"])
            return {
                "ok": True,
                "object_type": "directory",
                "file_count": len(files),
                "total_size": sum(f["size"] or 0 for f in files),
                "files": files,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    meta = s3_file_metadata(uri, anonymous=anonymous)
    return {
        "ok": meta.get("exists", False),
        "object_type": "file",
        "etag": meta.get("etag"),
        "size": meta.get("size"),
        "last_modified": meta.get("last_modified"),
    }
