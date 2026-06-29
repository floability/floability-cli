import re
import sys
import os
from pathlib import Path
from typing import List, Optional, Set, Dict

import yaml


def scan_strace_for_data_files(
    strace_file: str,
    data_dir_prefixes: List[str],
    notebook_dir: Optional[str] = None,
) -> Set[str]:
    """
    Scan a strace log for openat calls under any of the given directory prefixes.

    Strace records paths exactly as passed to the syscall — both absolute and
    relative paths may appear. Relative paths are resolved against notebook_dir
    (the directory the notebook ran from) before prefix-matching.

    Args:
        strace_file: Path to strace output file.
        data_dir_prefixes: List of absolute directory paths to filter by.
        notebook_dir: Directory the notebook executed from, used to resolve
                      relative paths found in strace output.

    Returns:
        Set of absolute file paths that were opened under those directories.
    """
    found: Set[str] = set()
    nb_dir = Path(notebook_dir).resolve() if notebook_dir else None

    try:
        with open(strace_file, "r") as f:
            for line in f:
                if "openat" not in line:
                    continue
                m = re.search(r'"([^"]+)"', line)
                if not m:
                    continue
                path = m.group(1)

                # Resolve relative paths using notebook_dir
                # Skip files opened for writing (output/runtime artifacts, not input data)
                if any(flag in line for flag in ("O_WRONLY", "O_CREAT", "O_TRUNC")):
                    continue

                if not path.startswith("/"):
                    if nb_dir is None:
                        continue
                    abs_path = str((nb_dir / path).resolve())
                else:
                    abs_path = path

                if any(abs_path.startswith(prefix) for prefix in data_dir_prefixes):
                    found.add(abs_path)
    except FileNotFoundError:
        print(f"Error: File '{strace_file}' not found")
    except Exception as e:
        print(f"Error scanning strace file: {e}")
    return found


def process_strace_log(file_path: str, data_dep_list: List[str]) -> Set[str]:
    """Filter strace openat calls to only those matching data_dep_list (exact path match)."""
    seen: Set[str] = set()
    try:
        with open(file_path, "r") as file:
            for line in file:
                if "openat" not in line:
                    continue
                start = line.index('"') + 1
                end = line.index('"', start)
                full_path = line[start:end].strip()
                if not any(dep == full_path for dep in data_dep_list):
                    continue
                if full_path in seen:
                    continue
                seen.add(full_path)
    except FileNotFoundError:
        print(f"Error: File '{file_path}' not found")
    except Exception as e:
        print(f"Error processing file: {e}")
    return seen


def get_list_of_files(file_path: str) -> List[str]:
    """Read data file list from open_trace.log, filtering out system/infra paths."""
    excluded_paths = ["/proc", "/sys", "/usr", "/lib", "/opt", "/tmp", "/var", "/etc"]
    excluded_substrings = [
        "/site-packages",
        "/vine-run-info",
        "/open_trace.log",
        "/dask",
    ]
    with open(file_path, "r") as f:
        lines = f.readlines()
    lines = [line.strip() for line in lines]
    lines = [l for l in lines if not any(l.startswith(p) for p in excluded_paths)]
    lines = [l for l in lines if not any(s in l for s in excluded_substrings)]
    return lines


def extract_file_sizes(log_file_name: str, target_file_list) -> Dict[str, int]:
    """
    Extract file sizes for target files from a strace log.

    Args:
        log_file_name: Path to strace output file.
        target_file_list: Collection of absolute file paths to look up.

    Returns:
        Dict mapping file path to size in bytes (or "Unknown").
    """
    target_paths = set(item.strip() for item in target_file_list if item.strip())
    if not target_paths:
        return {}

    def resolve_target(opened_path: str) -> Optional[str]:
        """Return the absolute target path that matches opened_path, or None."""
        # Strip leading './' so './data/file.csv' matches against absolute targets
        normalized = opened_path[2:] if opened_path.startswith("./") else opened_path
        for target in target_paths:
            if opened_path.endswith(target) or target.endswith(normalized):
                return target
        return None

    open_files = []

    with open(log_file_name, "r") as f:
        for line in f:
            pid_match = re.match(r"^\s*(\d+)", line)
            if not pid_match:
                continue
            pid = int(pid_match.group(1))

            open_match = re.search(r'openat\(.*?"(.*?)".*?= (\d+)', line)
            if open_match:
                path, fd = open_match.groups()
                matched = resolve_target(path)
                if matched:
                    open_files.append(
                        {"pid": pid, "fd": int(fd), "path": matched, "size": "Unknown"}
                    )

            fstat_match = re.search(r"fstat\((\d+), \{.*?st_size=(\d+)", line)
            if fstat_match:
                fd, size = map(int, fstat_match.groups())
                for entry in reversed(open_files):
                    if entry["pid"] == pid and entry["fd"] == fd and entry["size"] == "Unknown":
                        entry["size"] = size
                        break

            nfstat_match = re.search(r'newfstatat\((\d+), "", \{.*?st_size=(\d+)', line)
            if nfstat_match:
                fd, size = map(int, nfstat_match.groups())
                for entry in reversed(open_files):
                    if entry["pid"] == pid and entry["fd"] == fd and entry["size"] == "Unknown":
                        entry["size"] = size
                        break

    unique_files: Dict[str, int] = {}
    for entry in open_files:
        path = entry["path"]
        size = entry["size"]
        if path not in unique_files or (unique_files[path] == "Unknown" and size != "Unknown"):
            unique_files[path] = size

    return unique_files


def main(
    open_trace_log: str,
    strace_manager: str,
    strace_worker: str,
    data_dirs: Optional[List[str]] = None,
    notebook_dir: Optional[str] = None,
) -> Dict[str, int]:
    """
    Detect data dependencies and write manager/worker YAML files.

    Args:
        open_trace_log: Path to open_trace.log from injected notebook cell.
        strace_manager: Path to manager strace output.
        strace_worker: Path to worker strace output.
        data_dirs: Optional list of absolute directory paths. When provided,
                   strace is scanned directly for files under those directories
                   (catches worker-only files missed by open_trace.log).
                   When None, falls back to open_trace.log-gated detection.

    Returns:
        Consolidated dict mapping absolute file path to size in bytes (or "Unknown"),
        combining manager and worker dependencies (union, worker fills gaps).
    """
    if data_dirs:
        manager_files = scan_strace_for_data_files(strace_manager, data_dirs, notebook_dir)
        worker_files = scan_strace_for_data_files(strace_worker, data_dirs, notebook_dir)
    else:
        data_dep_list = get_list_of_files(open_trace_log)
        manager_files = process_strace_log(strace_manager, data_dep_list)
        worker_files = process_strace_log(strace_worker, data_dep_list)

    manager_list_with_size = extract_file_sizes(strace_manager, manager_files)
    worker_list_with_size = extract_file_sizes(strace_worker, worker_files)

    manager_dependencies = [
        {"name": path, "size": size} for path, size in manager_list_with_size.items()
    ]
    with open("manager_data_dependencies.yml", "w") as f:
        yaml.dump({"data_dependencies": manager_dependencies}, f, sort_keys=False)

    worker_dependencies = [
        {"name": path, "size": size} for path, size in worker_list_with_size.items()
    ]
    with open("worker_data_dependencies.yml", "w") as f:
        yaml.dump({"data_dependencies": worker_dependencies}, f, sort_keys=False)

    consolidated: Dict[str, int] = dict(manager_list_with_size)
    for path, size in worker_list_with_size.items():
        if path not in consolidated or consolidated[path] == "Unknown":
            consolidated[path] = size

    return consolidated
