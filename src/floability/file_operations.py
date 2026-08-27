import os
import shutil
import tarfile
import zipfile
from pathlib import Path
from typing import Dict, Any, Callable, Optional

REGISTERED_OPERATIONS = {}


def register_operation(name: str):
    """Decorator to register post-fetch operations"""

    def decorator(func):
        REGISTERED_OPERATIONS[name] = func
        return func

    return decorator


@register_operation("unzip")
def unzip_files(source_path: Path, params: Dict[str, Any] = None) -> Path:
    """
    Unzip the source file

    Parameters:
    - source_path: Path to the zip file
    - params: Optional parameters dict with:
        - extract_dir: Directory to extract to (default: same name as zip without extension)
        - overwrite: Whether to overwrite existing files (default: False)

    Returns:
        Path to the extraction directory
    """
    params = params or {}

    if not source_path.is_file() or source_path.suffix.lower() != ".zip":
        raise ValueError(f"Source is not a zip file: {source_path}")

    extract_dir = params.get("extract_dir", source_path.stem)
    extract_path = source_path.parent / extract_dir

    if extract_path.exists() and not params.get("overwrite", False):
        print(f"Extraction directory already exists: {extract_path}")
        return extract_path

    # Create extraction directory
    extract_path.mkdir(parents=True, exist_ok=True)

    # Extract files
    with zipfile.ZipFile(source_path, "r") as zip_ref:
        zip_ref.extractall(extract_path)

    return extract_path


@register_operation("untar")
def extract_tar(source_path: Path, params: Dict[str, Any] = None) -> Path:
    """
    Extract a tar archive

    Parameters:
    - source_path: Path to the tar file
    - params: Optional parameters dict with:
        - extract_dir: Directory to extract to (default: None, meaning same dir as tar)
        - overwrite: Whether to overwrite existing files (default: False)

    Returns:
        Path to the extraction directory
    """
    params = params or {}

    if not source_path.is_file() or not (
        source_path.suffix.lower() == ".tar"
        or source_path.name.lower().endswith((".tar.gz", ".tar.bz2", ".tar.xz"))
    ):
        raise ValueError(f"Source is not a tar file: {source_path}")

    extract_dir = params.get("extract_dir")

    if extract_dir:
        # Remove second .tar if it's a .tar.gz file
        if extract_dir.lower().endswith(".tar"):
            extract_dir = extract_dir[:-4]

        extract_path = source_path.parent / extract_dir

        if extract_path.exists() and not params.get("overwrite", False):
            print(f"Extraction directory already exists: {extract_path}")
            return extract_path
    else:
        # Default to the same directory as the tar file
        extract_path = source_path.parent

    # Create extraction directory
    extract_path.mkdir(parents=True, exist_ok=True)

    # Extract files
    with tarfile.open(source_path, "r:*") as tar:
        tar.extractall(path=extract_path)

    return extract_path


def execute_operation(
    operation_name: str, source_path: Path, params: Dict[str, Any] = None
) -> Optional[Path]:
    """
    Execute a registered post-fetch operation

    Parameters:
    - operation_name: Name of the registered operation
    - source_path: Path to the source file/directory
    - params: Operation-specific parameters

    Returns:
        Path to the operation result or None if operation not found
    """
    operation = REGISTERED_OPERATIONS.get(operation_name)
    if not operation:
        print(f"Operation not found: {operation_name}")
        return None

    try:
        return operation(source_path, params)
    except Exception as e:
        print(f"Error executing operation '{operation_name}': {e}")
        return None
