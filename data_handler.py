import os
import requests
import yaml
import shutil
import hashlib
from pathlib import Path
from utils import compute_md5
from typing import Optional, Dict, Any


# --------------------------------------------------------------------
# Utility / Helper Functions. We can move these to a separate module.
# --------------------------------------------------------------------
def compute_md5(file_path: Path, chunk_size: int = 4096) -> Optional[str]:
    """
    Compute MD5 checksum of a file and return the hex digest.
    Return None if file_path is not a file.
    """
    
    if not file_path.is_file():
        return None
    hasher = hashlib.md5()
    try:
        with file_path.open("rb") as f:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except IOError as e:
        print(f"Error computing MD5 for {file_path}: {e}")
        return None

def checksum_matches(file_path: Path, expected_checksum: str) -> bool:
    """
    Compare MD5 checksum of file_path with expected_checksum.
    Return False if file_path does not exist or checksums do not match.
    """
    
    actual = compute_md5(file_path)
    if actual is None:
        return False
    return actual == expected_checksum

def download_file(url: str, dest: Path, chunk_size: int = 8192) -> None:
    """
    Download a file from a URL to dest using streaming to limit memory usage.
    Uses a temporary file to avoid partial downloads in final location.
    """
    
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp_path = dest.with_suffix(".tmp")

    try:
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            with temp_path.open("wb") as f:
                for chunk in r.iter_content(chunk_size=chunk_size):
                    f.write(chunk)
        temp_path.replace(dest)
    except Exception as e:
        print(f"Failed to download {url} => {dest}: {e}")        
        if temp_path.exists():
            temp_path.unlink()
        raise


def copy_filesystem_source(source_path: Path, dest: Path) -> None:
    """
    Copy a file or directory from the filesystem/backpack to dest.
    """
    
    # Ensure parent directories exist
    dest.parent.mkdir(parents=True, exist_ok=True)

    if source_path.is_file():
        print(f"Copying file {source_path} => {dest}")
        shutil.copy2(source_path, dest)
    elif source_path.is_dir():
        print(f"Copying directory {source_path} => {dest}")
        shutil.copytree(source_path, dest, dirs_exist_ok=True)
    else:
        print(f"Source not found: {source_path}")

# --------------------------------------------------------------------
# Core Functions
# --------------------------------------------------------------------

def fetch_data_item(data_item: Dict[str, Any], backpack_root: Path) -> None:
    """
    Download or copy data item according to source_type.
    For 'backpack' source_type, treat `source` as relative to backpack_root.
    If verification checksum is present, verify after fetching.
    """
    
    name = data_item.get("name")
    source_type = data_item.get("source_type")
    source = data_item.get("source")
    target_location = data_item.get("target_location")
    verification_info = data_item.get("verification", {})
    expected_checksum = verification_info.get("checksum")

    if not name or not source_type or not source or not target_location:
        print(f"Data item is missing required fields.") # Todo: Add more details
        return

    target_path = Path(target_location)

    # Decide how to fetch
    if source_type == "url":
        print(f"Downloading from URL for '{name}'...")
        download_file(source, target_path)

    elif source_type == "filesystem":
        # ---------------------------------------------
        # Todo: The idea is allow filesystem paths like:
        # *.crc.nd.eddu:/path/to/file and this method will check if 
        # you are in the correct host and copy the file to the target location.
        # ---------------------------------------------
        # cleaned_source = source.replace("*.crc.nd.eddu:", "")
        # source_path = Path(cleaned_source)
        copy_filesystem_source(source, target_path)

    elif source_type == "backpack":
        source_in_backpack = (backpack_root / source.lstrip("/")).resolve()
        copy_filesystem_source(source_in_backpack, target_path)

    else:
        print(f"Unsupported source type: {source_type} for '{name}'")
        return

    # Skip checksum validation for directories. #Todo: Review this
    if target_path.is_dir():
        if expected_checksum:
            print(f"'{name}': target is a directory; skipping checksum validation.")
        return

    # Verify if we have a checksum
    #Todo: decide if we should raise an exception if checksum is missing and what to do if it fails
    if expected_checksum:
        if checksum_matches(target_path, expected_checksum):
            print(f"Checksum verified for '{name}' => {target_path}")
        else:
            print(f"Checksum mismatch for '{name}' => {target_path}")


def fetch_data_from_spec(data_yml_path: str, backpack_root: str = ".") -> None:
    """
    Fetch data from the specification file, if not already present or verified.
    Uses backpack_root as the root for any 'backpack' type sources.
    """
    
    spec_path = Path(data_yml_path)
    if not spec_path.is_file():
        print(f"Data spec file not found: {spec_path}")
        return

    # Load YAML data
    try:
        with spec_path.open("r", encoding="utf-8") as f:
            data_spec = yaml.safe_load(f)
    except Exception as e:
        print(f"Error reading data spec {spec_path}: {e}")
        return

    if not data_spec or "data" not in data_spec:
        print("No 'data' section found in data spec.")
        return

    backpack_root_path = Path(backpack_root).resolve()

    for item in data_spec["data"]:
        name = item.get("name", "<unnamed>")
        target_location = item.get("target_location")
        expected_checksum = item.get("verification", {}).get("checksum", None)

        if not target_location:
            print(f"Item '{name}' has no 'target_location'; skipping.")
            continue

        target_path = Path(target_location).resolve()
        already_exists = target_path.exists()

        # If item already exists, optionally verify checksum
        if already_exists and expected_checksum and target_path.is_file():
            if checksum_matches(target_path, expected_checksum):
                print(f"Data item '{name}' already exists and matches checksum.")
                continue
            else:
                print(f"Data item '{name}' exists but checksum mismatch; re-fetching.")

        # If item is missing or mismatch, fetch
        fetch_data_item(item, backpack_root_path)


def ensure_data_is_fetched(data_yml_path: str, backpack_root: str = ".") -> None:
    """
    Public API to ensure data from data.yml is present and correct.
    If not, fetches it using fetch_data_from_spec.
    """
    
    print("Ensuring data is fetched according to spec...")
    fetch_data_from_spec(data_yml_path, backpack_root)