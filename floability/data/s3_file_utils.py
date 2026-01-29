# s3_file_utils.py
"""
S3 file utilities for Floability data operations.

Provides metadata fetching and file downloads from S3 buckets using boto3.
Mirrors the interface of http_file_utils.py and pelican_file_utils.py.
"""
from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import os


def _get_boto3_client(anonymous: bool = False):
    """
    Get or create boto3 S3 client.
    
    Args:
        anonymous: If True, use anonymous access (no credentials required).
                  Useful for public buckets.
    
    Uses default AWS credential chain (env vars, ~/.aws/credentials, IAM roles).
    For HPC environments without AWS config, set environment variables:
        AWS_ACCESS_KEY_ID
        AWS_SECRET_ACCESS_KEY
        AWS_DEFAULT_REGION (optional)
    
    For public buckets without credentials, set anonymous=True or use
    environment variable AWS_NO_SIGN_REQUEST=true
    """
    try:
        import boto3
        from botocore import UNSIGNED
        from botocore.config import Config
        
        # Check if anonymous access is requested via env var
        if os.environ.get('AWS_NO_SIGN_REQUEST', '').lower() in ('true', '1', 'yes'):
            anonymous = True
        
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
            f"Failed to create S3 client. Check AWS credentials or use anonymous=True for public buckets: {e}"
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
    
    Examples:
        >>> parse_s3_uri("s3://mybucket/data/file.txt")
        ('mybucket', 'data/file.txt')
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
                  If None, auto-detect from AWS_NO_SIGN_REQUEST env var
    
    Returns:
        Dict with keys:
            - exists: bool (True if object exists)
            - name: str (basename of key)
            - size: int or None (object size in bytes)
            - type: str or None (content type)
            - etag: str or None (S3 ETag for versioning)
            - last_modified: str or None (ISO timestamp)
            - raw: dict (full boto3 head_object response or error info)
    
    Examples:
        >>> meta = s3_file_metadata("s3://mybucket/data/file.txt")
        >>> meta['exists']
        True
        >>> meta['size']
        1024
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
            anonymous = os.environ.get('AWS_NO_SIGN_REQUEST', '').lower() in ('true', '1', 'yes')
        
        client = _get_boto3_client(anonymous=anonymous)
        config = Config(connect_timeout=timeout, read_timeout=timeout)
        
        # HEAD request to get metadata
        response = client.head_object(Bucket=bucket, Key=key)
        
        # Extract metadata
        size = response.get("ContentLength")
        content_type = response.get("ContentType")
        etag = response.get("ETag", "").strip('"')  # Remove quotes from ETag
        last_modified = response.get("LastModified")
        
        # Convert datetime to ISO string
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
        # Handle various boto3 exceptions
        error_code = getattr(e, "response", {}).get("Error", {}).get("Code", "Unknown")
        
        # Check if it's a 404/NoSuchKey error
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
    
    Args:
        uri: S3 URI (s3://bucket/key)
        dest_dir: Local directory to save file
        filename: Optional custom filename (default: basename of key)
        overwrite: If True, re-download even if file exists
        resume: If True, resume partial downloads
        chunk_size: Download chunk size in bytes (default: 8MB)
        show_progress: Show progress bar during download
        anonymous: If True, use anonymous access (no credentials required).
                  If None, auto-detect from AWS_NO_SIGN_REQUEST env var
    
    Returns:
        Path to downloaded file
    
    Raises:
        ValueError: If URI is invalid
        FileExistsError: If file exists and overwrite=False and resume=False
        IOError: If download fails or size mismatch
    
    Examples:
        >>> dest = s3_file_download("s3://mybucket/data/file.txt", dest_dir="/tmp")
        >>> dest.exists()
        True
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
        anonymous = os.environ.get('AWS_NO_SIGN_REQUEST', '').lower() in ('true', '1', 'yes')
    
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
            raise FileExistsError(
                f"{dest} exists; set overwrite=True or resume=True"
            )
    
    # Determine resume offset
    offset = 0
    if resume and tmp.exists() and size is not None:
        offset = tmp.stat().st_size
        if offset >= size:
            # Partial file is already complete or corrupted
            if offset == size:
                # Complete, just rename
                tmp.replace(dest)
                return dest
            else:
                # Corrupted, restart
                tmp.unlink(missing_ok=True)
                offset = 0
    
    # Create boto3 client
    client = _get_boto3_client(anonymous=anonymous)
    
    # Download with optional resume
    mode = "ab" if offset > 0 else "wb"
    read_total = offset
    
    try:
        # Prepare range parameter for resume
        kwargs = {"Bucket": bucket, "Key": key}
        if offset > 0:
            kwargs["Range"] = f"bytes={offset}-"
        
        # Stream download
        response = client.get_object(**kwargs)
        body = response["Body"]
        
        # Setup progress bar
        pbar = None
        if show_progress and tqdm and size:
            pbar = tqdm(
                total=size,
                initial=offset,
                unit="B",
                unit_scale=True,
                desc=local_filename,
            )
        
        # Download in chunks
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
        
        # Verify size if known
        if size is not None and read_total != size:
            raise IOError(
                f"Incomplete download: got {read_total} bytes, expected {size}"
            )
        
        # Atomic rename
        tmp.replace(dest)
        return dest
    
    except Exception as e:
        # Clean up partial file on error (optional)
        # tmp.unlink(missing_ok=True)
        raise IOError(f"S3 download failed: {e}") from e


def s3_list_objects(
    uri: str,
    recursive: bool = True,
    anonymous: bool = None,
) -> list[Dict[str, Any]]:
    """
    List objects in an S3 bucket/prefix (for directory support).
    
    Args:
        uri: S3 URI (s3://bucket/prefix/)
        recursive: If True, list recursively; if False, list only direct children
        anonymous: If True, use anonymous access (no credentials required).
                  If None, auto-detect from AWS_NO_SIGN_REQUEST env var
    
    Returns:
        List of object metadata dicts (same format as s3_file_metadata)
    
    Examples:
        >>> objects = s3_list_objects("s3://mybucket/data/")
        >>> len(objects)
        5
    """
    bucket, prefix = parse_s3_uri(uri)
    
    # Ensure prefix ends with / for directory listing
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    
    # Auto-detect anonymous from env if not specified
    if anonymous is None:
        anonymous = os.environ.get('AWS_NO_SIGN_REQUEST', '').lower() in ('true', '1', 'yes')
    
    client = _get_boto3_client(anonymous=anonymous)
    
    results = []
    paginator = client.get_paginator("list_objects_v2")
    
    # Build paginate parameters
    paginate_params = {
        "Bucket": bucket,
        "Prefix": prefix,
    }
    
    # Add delimiter for non-recursive listing
    if not recursive:
        paginate_params["Delimiter"] = "/"
    
    page_iterator = paginator.paginate(**paginate_params)
    
    for page in page_iterator:
        # Get objects (files)
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
        
        # Get common prefixes (subdirectories) if non-recursive
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
