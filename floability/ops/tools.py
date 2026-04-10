"""
Tools operations for Floability CLI.
"""

import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Set, Tuple

from ..utils import normalize_cli_base_dir
from ..environment_manager import _make_dir_writable


def run_tools_command(args) -> None:
    subcommand = getattr(args, "tools_subcommand", None)
    if subcommand == "clean":
        _run_clean(args)
    else:
        print("[floability tools] No sub-command specified. Use 'floability tools --help'.")


def _run_clean(args) -> None:
    base_dir = normalize_cli_base_dir(getattr(args, "base_dir", None))

    raw_cache_override = getattr(args, "data_cache_dir", None)
    if raw_cache_override:
        data_cache_dir = Path(os.path.expanduser(raw_cache_override)).resolve()
    else:
        data_cache_dir = base_dir / "floability-data-cache"

    env_cache_dir = base_dir / "flo_common_env"

    # Determine scope — default (nothing specified) is data + env
    data_only = getattr(args, "data_only", False)
    env_only = getattr(args, "env_only", False)
    data_and_env = getattr(args, "data_and_env", False)
    instances_only = getattr(args, "instances_only", False)
    clean_all = getattr(args, "all", False)
    keep_last = getattr(args, "keep_last", False)
    yes = getattr(args, "yes", False)
    parallel = getattr(args, "parallel", False)

    if keep_last:
        _run_clean_keep_last(base_dir, data_cache_dir, env_cache_dir, yes, parallel)
        return

    if not any([data_only, env_only, data_and_env, instances_only, clean_all]):
        data_and_env = True

    clean_data = clean_all or data_only or data_and_env
    clean_env = clean_all or env_only or data_and_env
    clean_instances = clean_all or instances_only

    # Collect targets
    targets: List[Tuple[str, Path]] = []

    if clean_data and data_cache_dir.exists():
        targets.append(("data cache", data_cache_dir))

    if clean_env and env_cache_dir.exists():
        targets.append(("env cache", env_cache_dir))

    if clean_instances:
        for d in sorted(base_dir.glob("fi_*")):
            if d.is_dir():
                targets.append(("instance", d))
        latest_link = base_dir / "latest_floability_instance"
        if latest_link.is_symlink():
            targets.append(("latest symlink", latest_link))

    _confirm_and_delete(targets, yes, parallel)


def _run_clean_keep_last(
    base_dir: Path,
    data_cache_dir: Path,
    env_cache_dir: Path,
    yes: bool,
    parallel: bool = False,
) -> None:
    """Clean everything except the latest instance and its env/data cache dependencies."""

    latest_instance = _resolve_latest_instance(base_dir)
    if not latest_instance:
        print("[floability tools clean] No latest instance found. Nothing to clean.")
        return

    print(f"[floability tools clean] Keeping latest instance: {latest_instance}")

    protected = _collect_protected_paths(latest_instance, data_cache_dir, env_cache_dir)

    targets: List[Tuple[str, Path]] = []

    # Instances — keep the latest, remove everything else
    for d in sorted(base_dir.glob("fi_*")):
        if d.is_dir() and d.resolve() != latest_instance.resolve():
            targets.append(("instance", d))

    # Env extracted dirs — keep those used by latest instance
    extracted_dir = env_cache_dir / "extracted_envs"
    if extracted_dir.is_dir():
        for d in sorted(extracted_dir.iterdir()):
            if d.is_dir() and str(d) not in protected:
                targets.append(("env extracted", d))

    # Env tarballs — keep those used by latest instance
    tarballs_dir = env_cache_dir / "tarballs"
    if tarballs_dir.is_dir():
        for f in sorted(tarballs_dir.iterdir()):
            if f.is_file() and str(f) not in protected:
                targets.append(("env tarball", f))

    # Data cache dirs — keep those used by latest instance
    if data_cache_dir.is_dir():
        for d in sorted(data_cache_dir.iterdir()):
            if d.is_dir() and str(d) not in protected:
                targets.append(("data cache", d))

    _confirm_and_delete(targets, yes, parallel)


def _resolve_latest_instance(base_dir: Path) -> Optional[Path]:
    """Return the path of the latest instance via symlink or most recent fi_* dir."""
    symlink = base_dir / "latest_floability_instance"
    if symlink.is_symlink():
        target = symlink.resolve()
        if target.is_dir():
            return target

    # Fallback: most recently modified fi_* directory
    candidates = sorted(
        (d for d in base_dir.glob("fi_*") if d.is_dir()),
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _collect_protected_paths(
    instance_dir: Path,
    data_cache_dir: Path,
    env_cache_dir: Path,
) -> Set[str]:
    """Read run.json from the instance and return the set of paths to protect."""
    protected: Set[str] = {str(instance_dir)}

    metadata_file = instance_dir / "metadata" / "run.json"
    if not metadata_file.exists():
        print(f"[floability tools clean] Warning: no run.json found at {metadata_file}")
        return protected

    try:
        with open(metadata_file) as f:
            meta = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[floability tools clean] Warning: could not read run.json: {e}")
        return protected

    # Env: protect the extracted env dir and both tarballs
    for key in ("env_dir", "manager_environment_pack", "worker_environment_pack"):
        val = meta.get(key)
        if val:
            protected.add(str(Path(val).resolve()))

    # Data: protect each recorded cache dir
    for cache_dir in (meta.get("data") or {}).get("cache_dirs") or []:
        if cache_dir:
            protected.add(str(Path(cache_dir).resolve()))

    return protected


def _remove_dir_parallel(path: Path) -> None:
    """Remove a directory tree using parallel file deletion via find + xargs.

    Steps:
      1. chmod -R +w  — unlock read-only files (e.g. conda envs)
      2. find | xargs rm -f  — delete all files and symlinks in parallel
      3. shutil.rmtree  — remove the now-empty directory skeleton
    """
    cores = os.cpu_count() or 8
    p = shlex.quote(str(path))
    subprocess.run(f"chmod -R +w {p}", shell=True, check=False)
    subprocess.run(
        f"find {p} \\( -type f -o -type l \\) -print0"
        f" | xargs -0 -n 100 -P {cores} rm -f",
        shell=True,
        check=False,
    )
    shutil.rmtree(path, ignore_errors=True)


def _confirm_and_delete(targets: List[Tuple[str, Path]], yes: bool, parallel: bool = False) -> None:
    if not targets:
        print("[floability tools clean] Nothing to clean.")
        return

    print("[floability tools clean] The following will be removed:")
    for label, path in targets:
        print(f"  [{label}] {path}")

    if not yes:
        try:
            answer = input("\nProceed? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return
        if answer not in ("y", "yes"):
            print("Aborted.")
            return

    for label, path in targets:
        try:
            if path.is_symlink():
                path.unlink()
                print(f"[floability tools clean] Removed symlink: {path}")
            elif path.is_file():
                path.unlink()
                print(f"[floability tools clean] Removed {label}: {path}")
            elif path.is_dir():
                print(f"[floability tools clean] Removing {label}: {path}")
                if parallel:
                    _remove_dir_parallel(path)
                else:
                    _make_dir_writable(str(path))
                    shutil.rmtree(path)
                print(f"[floability tools clean] Done.")
        except Exception as e:
            print(f"[floability tools clean] Warning: could not remove {path}: {e}")

    print("[floability tools clean] Clean complete.")
