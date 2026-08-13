"""
Detect local helper .py files used by a notebook during execution.

Scans strace_manager output for openat calls to .py files that live inside
the notebook's directory (not conda/system paths).
"""

import re
from pathlib import Path
from typing import List


_EXCLUDED_PREFIXES = (
    "/proc", "/sys", "/usr", "/lib", "/opt", "/tmp", "/var", "/etc",
)
_EXCLUDED_SUBSTRINGS = (
    "site-packages", "__pycache__", ".pyc",
    "vine-run-info", "ipykernel", "jupyter",
)


def _is_local_helper(path: str, notebook_dir: Path) -> bool:
    """Return True if path is a .py file inside notebook_dir, not a system file."""
    if not path.endswith(".py"):
        return False
    if any(path.startswith(p) for p in _EXCLUDED_PREFIXES):
        return False
    if any(s in path for s in _EXCLUDED_SUBSTRINGS):
        return False
    try:
        p = Path(path)
        p.relative_to(notebook_dir)
        return True
    except ValueError:
        return False


def detect_local_py_files(strace_manager: str, notebook_path: str) -> List[Path]:
    """
    Return local helper .py files opened during notebook execution.

    Args:
        strace_manager: Path to strace output from jupyter execute run.
        notebook_path: Path to the notebook (.ipynb).

    Returns:
        List of absolute Paths to local .py helper files (deduplicated, exist on disk).
    """
    notebook_dir = Path(notebook_path).resolve().parent
    found = []
    seen = set()

    try:
        with open(strace_manager, "r") as f:
            for line in f:
                if "openat" not in line:
                    continue
                m = re.search(r'"([^"]+)"', line)
                if not m:
                    continue
                path = m.group(1)
                if path in seen:
                    continue
                if not _is_local_helper(path, notebook_dir):
                    continue
                p = Path(path)
                if p.is_file():
                    found.append(p)
                    seen.add(path)
    except FileNotFoundError:
        print(f"[floability] Warning: strace file not found: {strace_manager}")

    return found
