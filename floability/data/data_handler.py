from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, Iterable, List, Tuple, Optional, Callable
import yaml
import hashlib
import json
import time
import os
import shutil

# Reuse existing low-level helpers
from .http_file_utils import http_file_metadata, http_file_download
from .pelican_file_utils import (
    pelican_file_metadata,
    pelican_file_download,
    pelican_directory_download,
    is_pelican_directory,
    pelican_source_metadata,
)
from .s3_file_utils import (
    s3_file_metadata,
    s3_file_download,
    s3_list_objects,
    s3_directory_download,
    is_s3_directory,
    s3_source_metadata,
)
from .xrootd_file_utils import (
    xrootd_file_metadata,
    xrootd_file_download,
    xrootd_directory_download,
    is_xrootd_directory,
    xrootd_source_metadata,
)
from .fs_file_utils import fs_file_metadata, fs_file_copy
from floability.performance_tracker import NullPerf as _NullPerf


# --------------------------- Public API ---------------------------
def execute_default_data_operation(
    data_spec: str,
    backpack_root: Path | None,
    verbose: bool = False,
    force: bool = False,
    data_profile: Optional[str] = None,
    data_cache_mode: str = "off",
    force_data_cache: bool = False,
    base_dir: Path | None = None,
    cache_base_dir: Path | None = None,
    target_root: Path | None = None,
    cache_lookup_mode: str = "strict",
    perf: Optional[Any] = None,
    _out_cache_dirs: Optional[List[str]] = None,
) -> bool:
    """Execute the default data operation as defined in the spec policy.

    Default operation is typically 'fetch' but may be overridden in the spec policy.

    This is a convenience wrapper around the specific operations (check, fetch, verify).

    Args:
        data_spec: Path to data spec YAML file
        backpack_root: Base directory for resolving backpack:// and relative fs source paths
        verbose: Print detailed progress messages
        force: Force re-download/re-verification even if target exists
        data_profile: Data profile name to use (default: spec's default_profile)
        data_cache_mode: Cache mode: 'off', 'symlink', 'hardlink', 'copy'
        force_data_cache: Force rebuild of cache entries even if they exist
        base_dir: Floability base directory for cache storage (default: current directory)
        cache_base_dir: Floability data cache directory (overrides default <base_dir>/floability-data-cache)
        target_root: Target directory for materialized data (typically instance/workflow). If None, defaults to backpack_root/workflow

    Returns:
        bool: True if the operation succeeded, False otherwise.
    """
    spec_path = Path(data_spec)
    if not spec_path.is_file():
        print(f"[data] Spec file not found: {spec_path}")
        return False

    try:
        profile_name, profile = load_and_validate_spec(
            data_spec=data_spec,
            backpack_root=backpack_root,
            requested_profile=data_profile,
            verbose=verbose,
            op_label="default",
        )
    except ValueError as e:
        print(f"[data] {e}")
        return False

    policy = profile.get("policy", {})
    default_op = str(policy.get("run_operation", "fetch") or "fetch").strip().lower()

    if verbose:
        print(f"[data] Performing default operation '{default_op}'")

    if default_op == "check":
        return check_data_from_spec(
            data_spec=data_spec,
            backpack_root=backpack_root or Path.cwd(),
            show_details=verbose,
            verbose=verbose,
            data_profile=data_profile,
            data_cache_mode=data_cache_mode,
            base_dir=base_dir,
            cache_base_dir=cache_base_dir,
            target_root=target_root,
        )
    elif default_op == "fetch":
        return fetch_data_from_spec(
            data_spec=data_spec,
            backpack_root=backpack_root,
            verbose=verbose,
            force=force,
            data_profile=data_profile,
            data_cache_mode=data_cache_mode,
            force_data_cache=force_data_cache,
            base_dir=base_dir,
            cache_base_dir=cache_base_dir,
            target_root=target_root,
            cache_lookup_mode=cache_lookup_mode,
            perf=perf,
            _out_cache_dirs=_out_cache_dirs,
        )
    elif default_op == "verify":
        return verify_data_from_spec(
            data_spec=data_spec,
            backpack_root=backpack_root,
            verbose=verbose,
            force=force,
            data_profile=data_profile,
            data_cache_mode=data_cache_mode,
            force_data_cache=force_data_cache,
            base_dir=base_dir,
            cache_base_dir=cache_base_dir,
            target_root=target_root,
            cache_lookup_mode=cache_lookup_mode,
        )
    else:
        print(f"[data] Unknown default operation '{default_op}' specified in policy.")
        return False


def check_data_from_spec(
    data_spec: str,
    backpack_root: Path,
    show_details: bool = False,
    verbose: bool = False,
    data_profile: Optional[str] = None,
    data_cache_mode: str = "off",
    base_dir: Path | None = None,
    cache_base_dir: Path | None = None,
    target_root: Path | None = None,
) -> bool:
    """High-level entry: perform metadata-only checks for each data item.

    Steps:
      1. Load + normalize spec (apply defaults, pick profile).
      2. Iterate data items, gather metadata without downloading bodies.
      3. Validate expected_size (within tolerance).
      4. Check cache status if cache mode is enabled.
      5. Print a summary report.

    Args:
        data_spec: Path to data spec YAML file
        backpack_root: Base directory for resolving backpack:// and relative fs source paths
        show_details: Print detailed item metadata after summary
        verbose: Print detailed progress messages
        data_profile: Data profile name to use (default: spec's default_profile)
        data_cache_mode: Cache mode to check cache status ('off' = no cache check)
        base_dir: Floability base directory for cache storage (default: current directory)
        target_root: Target directory for checking target paths (optional, not used for metadata-only checks)

    Returns:
        bool: True if all items exist and match their expected size, False otherwise.
    """
    spec_path = Path(data_spec)
    if not spec_path.is_file():
        print(f"[data:check] Spec file not found: {spec_path}")
        return False

    try:
        profile_name, profile = load_and_validate_spec(
            data_spec=data_spec,
            backpack_root=backpack_root,
            requested_profile=data_profile,
            verbose=verbose,
            op_label="check",
        )
    except ValueError as e:
        print(f"[data:check] {e}")
        return False

    items = profile.get("data", []) or []
    policy = profile.get("policy", {})
    tolerance = int(policy.get("size_tolerance_bytes", 0) or 0)
    if verbose:
        print(
            f"[data:check] data_profile: {profile_name} (items={len(items)}, size_tolerance={tolerance})"
        )
        if data_cache_mode != "off":
            print(f"[data:check] Checking cache status (mode={data_cache_mode})")

    normalized_items = items

    # Use explicit cache_base_dir if provided, otherwise fall back to base_dir/floability-data-cache
    if cache_base_dir is not None:
        cache_base_dir = Path(cache_base_dir)
    else:
        base_path = Path(base_dir) if base_dir else Path.cwd()
        cache_base_dir = base_path / "floability-data-cache"
    try:
        cache_base_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    results: List[Dict[str, Any]] = []
    for item in normalized_items:
        result = _check_single_item(
            item,
            tolerance,
            backpack_root,
            data_cache_mode=data_cache_mode,
            verbose=verbose,
            cache_base_dir=cache_base_dir,
        )
        results.append(result)

    success = _print_check_summary(results, show_cache=data_cache_mode != "off")
    if show_details or verbose:
        _print_detailed_results(results, show_cache=data_cache_mode != "off")

    return success


def fetch_data_from_spec(
    data_spec: str,
    backpack_root: Path | None,
    verbose: bool = False,
    force: bool = False,
    data_profile: Optional[str] = None,
    data_cache_mode: str = "off",
    force_data_cache: bool = False,
    base_dir: Path | None = None,
    cache_base_dir: Path | None = None,
    target_root: Path | None = None,
    cache_lookup_mode: str = "strict",
    perf: Optional[Any] = None,
    _out_cache_dirs: Optional[List[str]] = None,
) -> bool:
    """Fetch (download/copy) all data items defined in the selected profile.

    Rules:
      * If backpack_root is None, infer as spec_path.parent.parent (grand-parent) to match
        expected structure: <backpack_root>/data/data.yml.
      * Relative sources (source_type: backpack, fs) are resolved against backpack_root.
      * Relative target_location paths are resolved against target_root (or backpack_root/workflow if target_root not provided).
      * multi source_type: iterate sources until first successful fetch.
      * For now, post_process is ignored (placeholder).

    Args:
        data_spec: Path to data spec YAML file
        backpack_root: Base directory for resolving backpack:// and relative fs source paths
        verbose: Print detailed progress messages
        force: Force re-download even if target exists
        data_profile: Data profile name to use (default: spec's default_profile)
        data_cache_mode: Cache mode: 'off', 'symlink', 'hardlink', 'copy'
        force_data_cache: Force rebuild of cache entries even if they exist
        base_dir: Floability base directory for cache storage (default: current directory)
        target_root: Target directory for materialized data (typically instance/workflow). If None, defaults to backpack_root/workflow

    Returns:
        bool: True if all items were successfully fetched and copied to target locations, False otherwise.
    """
    spec_path = Path(data_spec)
    if not spec_path.is_file():
        print(f"[data:fetch] Spec file not found: {spec_path}")
        return False

    # Infer backpack_root if not provided
    if backpack_root is None:
        if spec_path.parent.name == "data":
            backpack_root = spec_path.parent.parent
        else:
            backpack_root = spec_path.parent
    backpack_root = Path(backpack_root).resolve()
    perf = perf or _NullPerf()

    try:
        profile_name, profile = load_and_validate_spec(
            data_spec=data_spec,
            backpack_root=backpack_root,
            requested_profile=data_profile,
            verbose=verbose,
            op_label="fetch",
        )
    except ValueError as e:
        print(f"[data:fetch] {e}")
        return False

    items = profile.get("data", []) or []
    if verbose:
        print(
            f"[data:fetch] data_profile '{profile_name}' items={len(items)} backpack_root={backpack_root}"
        )
        if data_cache_mode != "off":
            print(
                f"[data:fetch] data_cache_mode={data_cache_mode} force_data_cache={force_data_cache}"
            )

    normalized_items = items

    # Use explicit cache_base_dir if provided, otherwise fall back to base_dir/floability-data-cache
    if cache_base_dir is not None:
        cache_base_dir = Path(cache_base_dir)
    else:
        base_path = Path(base_dir) if base_dir else Path.cwd()
        cache_base_dir = base_path / "floability-data-cache"
    try:
        cache_base_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    # Determine target_prefix for materializing data
    if target_root:
        target_prefix = Path(target_root).resolve()
    else:
        target_prefix = (Path.cwd() / "workflow").resolve()

    total = len(normalized_items)
    failed_items = []

    for idx, item in enumerate(normalized_items, start=1):
        item_name = item.get("name", "<unnamed>")
        if verbose:
            print(f"[data:fetch] Fetching {idx}/{total}: {item_name} (force={force})")
        perf.start_timer(f"data_fetch_{item_name}")
        result = _fetch_single_item(
            item,
            backpack_root,
            verbose=verbose,
            force=force,
            data_cache_mode=data_cache_mode,
            force_data_cache=force_data_cache,
            cache_base_dir=cache_base_dir,
            target_prefix=target_prefix,
            perf=perf,
            _out_cache_dirs=_out_cache_dirs,
        )
        perf.end_timer(f"data_fetch_{item_name}", f"Time to fetch '{item_name}'")

        # Check if fetch was successful (returns source on success, None on failure or skip)
        target_path = _resolve_target_path(
            item,
            target_prefix=target_prefix,
            backpack_root=backpack_root,
        )

        # Verify the file actually exists after fetch attempt
        if not target_path.exists():
            failed_items.append(item_name)
            print(
                f"[data:fetch] FAILED to fetch '{item_name}' - target does not exist: {target_path}"
            )
        elif verbose:
            print(f"[data:fetch] Finished {idx}/{total}: {item_name}")

    if failed_items:
        print(
            f"\n[data:fetch] ERROR: {len(failed_items)} of {total} items failed to fetch:"
        )
        for name in failed_items:
            print(f"  - {name}")
        return False

    if verbose:
        print(f"[data:fetch] Completed successfully. All {total} items fetched.")
    return True


def verify_data_from_spec(
    data_spec: str,
    backpack_root: Path | None,
    verbose: bool = False,
    force: bool = False,
    data_profile: Optional[str] = None,
    data_cache_mode: str = "off",
    force_data_cache: bool = False,
    base_dir: Path | None = None,
    cache_base_dir: Path | None = None,
    target_root: Path | None = None,
    cache_lookup_mode: str = "strict",
) -> bool:
    """Verify data items: ensure present (download/copy if needed) then validate integrity.

    Integrity signals supported:
      * checksum: (algorithm:hex) or plain hex (algorithm inferred by length)
      * expected_size (+ policy.size_tolerance_bytes)

    Produces a summary table and (if verbose) per-item details.

    Args:
        data_spec: Path to data spec YAML file
        backpack_root: Base directory for resolving backpack:// and relative fs source paths
        verbose: Print detailed progress messages
        force: Force re-download even if target exists
        data_profile: Data profile name to use (default: spec's default_profile)
        data_cache_mode: Cache mode: 'off', 'symlink', 'hardlink', 'copy'
        force_data_cache: Force rebuild of cache entries even if they exist
        base_dir: Floability base directory for cache storage (default: current directory)
        target_root: Target directory for materialized data (typically instance/workflow). If None, defaults to backpack_root/workflow

    Returns:
        bool: True if all items pass verification (exist, size matches, checksum matches if required), False otherwise.
    """
    spec_path = Path(data_spec)
    if not spec_path.is_file():
        print(f"[data:verify] Spec file not found: {spec_path}")
        return False

    if backpack_root is None:
        if spec_path.parent.name == "data":
            backpack_root = spec_path.parent.parent
        else:
            backpack_root = spec_path.parent
    backpack_root = Path(backpack_root).resolve()

    print(f"\n[data:verify] Using backpack_root: {backpack_root}\n")

    try:
        profile_name, profile = load_and_validate_spec(
            data_spec=data_spec,
            backpack_root=backpack_root,
            requested_profile=data_profile,
            verbose=verbose,
            op_label="verify",
        )
    except ValueError as e:
        print(f"[data:verify] {e}")
        return False

    items = profile.get("data", []) or []
    policy = profile.get("policy", {})
    tolerance = int(policy.get("size_tolerance_bytes", 0) or 0)

    if verbose:
        print(
            f"[data:verify] data_profile '{profile_name}' items={len(items)} tolerance={tolerance} backpack_root={backpack_root}"
        )
        if data_cache_mode != "off":
            print(
                f"[data:verify] data_cache_mode={data_cache_mode} force_data_cache={force_data_cache}"
            )

    normalized_items = items

    # Use explicit cache_base_dir if provided, otherwise fall back to base_dir/floability-data-cache
    if cache_base_dir is not None:
        cache_base_dir = Path(cache_base_dir)
    else:
        base_path = Path(base_dir) if base_dir else Path.cwd()
        cache_base_dir = base_path / "floability-data-cache"
    try:
        cache_base_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    # Determine target_prefix for materializing data
    if target_root:
        target_prefix = Path(target_root).resolve()
    else:
        target_prefix = (Path.cwd() / "workflow").resolve()

    results: List[Dict[str, Any]] = []
    total = len(normalized_items)
    for idx, item in enumerate(normalized_items, start=1):
        name = item.get("name", "<unnamed>")
        if verbose:
            print(f"[data:verify] Processing {idx}/{total}: {name} (force={force})")
        # Ensure fetched (may skip if exists and not force)
        chosen_source = _fetch_single_item(
            item,
            backpack_root,
            verbose=verbose,
            force=force,
            data_cache_mode=data_cache_mode,
            force_data_cache=force_data_cache,
            cache_base_dir=cache_base_dir,
            target_prefix=target_prefix,
            cache_lookup_mode=cache_lookup_mode,
        )
        # Evaluate integrity on local target
        target_path = _resolve_target_path(
            item,
            target_prefix=target_prefix,
            backpack_root=backpack_root,
        )
        local_exists = target_path.exists()
        is_dir = target_path.is_dir() if local_exists else False

        expected_size = item.get("expected_size")
        actual_size = (
            target_path.stat().st_size
            if (local_exists and target_path.is_file())
            else None
        )
        size_ok = None
        size_note = None
        if expected_size is not None and isinstance(expected_size, int):
            if actual_size is None:
                size_ok = False
                size_note = "no-actual-size"
            else:
                diff = abs(actual_size - expected_size)
                size_ok = diff <= tolerance
                size_note = f"diff={diff}" if diff else "exact"

        # Checksum verification
        checksum_spec = _extract_checksum_field(item)
        checksum_alg = None
        checksum_expected = None
        checksum_actual = None
        checksum_ok = None
        if checksum_spec and local_exists and not is_dir:
            checksum_alg, checksum_expected = _parse_checksum_spec(checksum_spec)
            if checksum_alg and checksum_expected:
                try:
                    checksum_actual = _compute_checksum(target_path, checksum_alg)
                    checksum_ok = checksum_actual == checksum_expected
                except Exception as e:
                    checksum_ok = False
                    if verbose:
                        print(
                            f"[data:verify] Error computing checksum for '{name}': {e}"
                        )

        # Enforce verification policy
        verification_type = (
            str(policy.get("verification_type", "size_only") or "size_only")
            .strip()
            .lower()
        )
        if verification_type == "strict":
            # Require checksum to be present and to match
            if not checksum_spec:
                checksum_ok = False
            elif checksum_ok is not True:
                checksum_ok = False

        results.append(
            {
                "name": name,
                "exists": local_exists,
                "is_dir": is_dir,
                "target_path": str(target_path),
                "expected_size": expected_size,
                "actual_size": actual_size,
                "size_ok": size_ok,
                "size_note": size_note,
                "checksum_alg": checksum_alg,
                "checksum_expected": checksum_expected,
                "checksum_actual": checksum_actual,
                "checksum_ok": checksum_ok,
            }
        )
        if verbose:
            print(
                f"[data:verify] Finished {idx}/{total}: {name} exists={local_exists} size_ok={size_ok} checksum_ok={checksum_ok}"
            )

    success = _print_verify_summary(results)
    if verbose:
        _print_verify_details(results)

    return success


# --------------------------- Spec Preparation ---------------------------
def load_and_validate_spec(
    data_spec: str,
    backpack_root: Optional[Path],
    requested_profile: Optional[str] = None,
    verbose: bool = False,
    op_label: str = "check",
) -> Tuple[str, Dict[str, Any]]:
    """Load, select, validate, and normalize a data spec for downstream actions.

    Returns (profile_name, normalized_profile). Raises ValueError on failures.
    """
    spec_path = Path(data_spec)
    try:
        raw = _load_yaml(spec_path)
    except Exception as e:
        raise ValueError(f"Failed loading YAML: {e}")

    try:
        profile_name, profile, _ = _select_profile(
            raw, requested_profile=requested_profile
        )
    except ValueError as e:
        raise ValueError(str(e))

    try:
        _validate_required_fields(profile)
    except ValueError as e:
        raise ValueError(f"Spec validation failed: {e}")

    # Normalize spec
    normalized = _normalize_data_profile(profile, backpack_root=backpack_root)
    if verbose:
        print(f"[data:{op_label}] normalized data_profile:")
        try:
            print(yaml.safe_dump(normalized, sort_keys=False))
        except Exception:
            print(normalized)

    return profile_name, normalized


# --------------------------- Parsing / Selection / Validation ---------------------------
def _load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _select_profile(
    raw: Dict[str, Any], requested_profile: Optional[str] = None
) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
    # Support both new 'data_profiles' and legacy 'profiles'
    profiles = raw.get("data_profiles")
    legacy = False
    if not profiles:
        profiles = raw.get("profiles")
        legacy = True if profiles else False
    if not profiles or not isinstance(profiles, dict):
        raise ValueError("Spec missing 'data_profiles' (or legacy 'profiles') mapping")
    # Requested profile via CLI takes precedence if provided.
    if requested_profile:
        if requested_profile not in profiles:
            raise ValueError(
                f"Requested profile '{requested_profile}' not found in spec"
            )
        return requested_profile, profiles[requested_profile], {}

    default_profile = raw.get("default_profile") or next(iter(profiles.keys()))
    profile = profiles.get(default_profile)
    if profile is None:
        raise ValueError(f"Data profile '{default_profile}' not found in spec")

    return default_profile, profile, {}


def _validate_required_fields(profile: Dict[str, Any]) -> None:
    """Validate that required fields exist in a selected profile.

    Requirements:
      - profile.data must be a non-empty list
      - each item must define either 'source' or a non-empty 'sources' list
      - each item must define 'target_location' (or legacy 'target_path')
      - if 'sources' is present, each entry must define 'source'
    """
    data_list = profile.get("data")
    if not isinstance(data_list, list) or len(data_list) == 0:
        raise ValueError("Profile missing non-empty 'data' list")

    for idx, item in enumerate(data_list, start=1):
        has_source = bool(item.get("source"))
        sources = item.get("sources")
        if sources:
            if not isinstance(sources, list) or len(sources) == 0:
                raise ValueError(
                    f"Spec item #{idx} has invalid 'sources' (must be non-empty list)"
                )
            for j, s in enumerate(sources, start=1):
                if not s.get("source"):
                    raise ValueError(
                        f"Spec item #{idx} sources[{j}] missing required 'source'"
                    )
        elif not has_source:
            raise ValueError(
                f"Spec item #{idx} missing required 'source' (or 'sources')"
            )

        if not (item.get("target_location") or item.get("target_path")):
            raise ValueError(f"Spec item #{idx} missing required 'target_location'")


def _normalize_data_profile(
    profile: Dict[str, Any], backpack_root: Optional[Path] = None
) -> Dict[str, Any]:
    """Return a normalized copy of a selected profile with defaults applied.

    Normalizations:
      - ensure 'policy' object exists with default keys:
          retry_attempts=0, timeout=None, size_tolerance_bytes=0,
          run_operation='fetch', verification_type='size_only'
      - per-item:
          * ensure 'name' present (fallback to basename of target_location or '<unnamed>')
          * infer 'source_type' (and for nested 'sources' entries as well)
          * if only 'target_path' is present, copy to 'target_location'
          * add 'target_prefix' if missing and backpack_root provided (to <backpack_root>/workflow)
    """
    from copy import deepcopy

    out = deepcopy(profile)
    policy = dict(out.get("policy") or {})
    policy.setdefault("retry_attempts", 0)
    policy.setdefault("timeout", None)
    policy.setdefault("size_tolerance_bytes", 0)
    policy.setdefault("run_operation", "fetch")
    policy.setdefault("verification_type", "size_only")
    out["policy"] = policy

    data_list = out.get("data") or []
    norm_list: List[Dict[str, Any]] = []

    for item in data_list:
        it = _normalize_data_item(item)
        norm_list.append(it)

    out["data"] = norm_list
    return out


def _normalize_data_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a single data item (non data-dependent fields only).

    - Promote legacy target_path to target_location
    - Ensure name (fallback to basename of target_location)
    - Infer source_type for item and nested sources
    - Do NOT infer target path; target_location is required
    """
    it = dict(item)

    # unify legacy target_path
    if not it.get("target_location") and it.get("target_path"):
        it["target_location"] = it["target_path"]

    # derive name if missing (prefer basename of target_location)
    if not it.get("name"):
        tloc = str(it.get("target_location") or "")
        it["name"] = Path(tloc).name if tloc else "<unnamed>"

    # infer source_type for multi or by scheme
    if "source_type" not in it or not it["source_type"]:
        if "sources" in it and it["sources"]:
            it["source_type"] = "multi"
        else:
            src = str(it.get("source", "") or "")
            if src.startswith("backpack://"):
                it["source_type"] = "backpack"
                it["source"] = src[len("backpack://") :]
            elif src.startswith("http://") or src.startswith("https://"):
                it["source_type"] = "http"
            elif src.startswith("s3://"):
                it["source_type"] = "s3"
            elif src.startswith("root://"):
                it["source_type"] = "xrootd"
            elif src.startswith("osdf://") or src.startswith("pelican://"):
                it["source_type"] = "pelican"
            elif src:
                it["source_type"] = "fs"
            else:
                it["source_type"] = "unknown"

    # normalize nested sources
    if isinstance(it.get("sources"), list):
        norm_sources = []
        for s in it["sources"]:
            s_it = dict(s)
            # infer source_type for nested
            if "source_type" not in s_it or not s_it["source_type"]:
                src = str(s_it.get("source", "") or "")
                if src.startswith("backpack://"):
                    s_it["source_type"] = "backpack"
                    s_it["source"] = src[len("backpack://") :]
                elif src.startswith("http://") or src.startswith("https://"):
                    s_it["source_type"] = "http"
                elif src.startswith("s3://"):
                    s_it["source_type"] = "s3"
                elif src.startswith("root://"):
                    s_it["source_type"] = "xrootd"
                elif src.startswith("osdf://") or src.startswith("pelican://"):
                    s_it["source_type"] = "pelican"
                elif src:
                    s_it["source_type"] = "fs"
                else:
                    s_it["source_type"] = "unknown"
            norm_sources.append(s_it)
        it["sources"] = norm_sources

    return it


# (legacy helper _normalize_item removed; normalization now handled by
#  _normalize_data_profile/_normalize_data_item before use)


# --------------------------- Item Checking Logic ---------------------------
def _check_single_item(
    item: Dict[str, Any],
    tolerance: int,
    backpack_root: Path,
    data_cache_mode: str = "off",
    verbose: bool = False,
    cache_base_dir: Path | None = None,
) -> Dict[str, Any]:
    name = item.get("name", "<unnamed>")
    stype = item.get("source_type")
    expected_size = item.get("expected_size")

    # For output path (target) relative to backpack root (for display only)
    target_rel = item.get("target_location") or item.get("target_path")

    # Multi-source: pick first successful metadata
    meta_chain: List[Dict[str, Any]] = []
    if stype == "multi":
        sources = item.get("sources", [])
        for s in sources:
            s_norm = s
            m = _metadata_for_source(s_norm, backpack_root)
            meta_chain.append(m)
            if m.get("exists"):
                meta = m
                break
        else:
            meta = meta_chain[-1] if meta_chain else {"exists": False}
    else:
        meta = _metadata_for_source(item, backpack_root)

    size_ok = None
    size_note = None
    actual_size = meta.get("size")
    if expected_size is not None and isinstance(expected_size, int):
        if actual_size is None:
            size_ok = False
            size_note = "no-actual-size"
        else:
            diff = abs(actual_size - expected_size)
            size_ok = diff <= tolerance
            size_note = f"diff={diff}" if diff else "exact"

    # Check cache status if cache mode is enabled.
    # Uses local-mode lookup (spec_key scan only) — no remote metadata fetch for check.
    cache_exists = None
    cache_valid = None
    cache_key = None
    if data_cache_mode != "off" and cache_base_dir:
        try:
            artifact_spec = _create_artifact_spec(item, backpack_root)
            spec_key = _compute_spec_key(artifact_spec)
            cache_key = spec_key  # for display

            hit = _find_cache_hit(
                cache_base_dir,
                spec_key,
                source_key=None,
                artifact_spec=artifact_spec,
                backpack_root=backpack_root,
                cache_lookup_mode="local",
                verbose=False,
            )
            cache_exists = hit is not None
            cache_valid = hit is not None
        except Exception as e:
            if verbose:
                print(f"[data:check] Error checking cache for '{name}': {e}")
            cache_exists = False
            cache_valid = False

    return {
        "name": name,
        "source_type": stype,
        "target_path": target_rel,
        "expected_size": expected_size,
        "actual_size": actual_size,
        "size_ok": size_ok,
        "size_note": size_note,
        "exists": meta.get("exists"),
        "meta": meta,
        "multi_chain": meta_chain if stype == "multi" else None,
        "cache_exists": cache_exists,
        "cache_valid": cache_valid,
        "cache_key": cache_key[:16] + "..." if cache_key else None,
    }


def _metadata_for_source(item: Dict[str, Any], backpack_root: Path) -> Dict[str, Any]:
    stype = item.get("source_type")
    src = item.get("source")
    if stype == "http":
        return http_file_metadata(src)
    if stype == "s3":
        return s3_file_metadata(src)
    if stype == "xrootd":
        return xrootd_file_metadata(src)
    if stype == "pelican":
        return pelican_file_metadata(src)
    if stype == "backpack":
        # Interpret relative backpack paths as relative to backpack_root
        p = Path(src)
        if not p.is_absolute():
            p = (Path(backpack_root) / p).resolve()
        return fs_file_metadata(str(p))
    if stype == "fs":
        # Interpret relative paths as relative to backpack_root unless absolute
        p = Path(src)
        if not p.is_absolute():
            p = (Path(backpack_root) / p).resolve()
        return fs_file_metadata(str(p))
    # Unknown or missing
    return {
        "exists": False,
        "name": src or "",
        "size": None,
        "type": None,
        "raw": {"error": f"unsupported source_type {stype}"},
    }


# --------------------------- Fetch Logic ---------------------------
def _resolve_target_path(
    item: Dict[str, Any], target_prefix: Path, backpack_root: Optional[Path] = None
) -> Path:
    """Resolve final target path for an item.

    Parameters:
      - item: data item dict (may contain target_path/target_location/name)
      - target_prefix: explicit prefix Path to use for relative targets (required)
      - backpack_root: base directory used to resolve relative item-level target_prefix overrides

    Behavior:
      - Absolute target paths are returned as absolute paths without dereferencing symlinks.
      - Relative targets are placed under `target_prefix/target`.
      - If item includes `target_prefix`, it overrides `target_prefix`.
        Relative item-level target_prefix values are resolved against backpack_root.
    """

    target_path_from_spec = item.get("target_location") or item.get("target_path")
    if not target_path_from_spec:
        raise ValueError("Missing required 'target_location' in data item")

    target_path = Path(target_path_from_spec)

    # Absolute targets always win and ignore target_prefix.
    if target_path.is_absolute():
        return Path(os.path.abspath(os.path.expanduser(str(target_path))))

    effective_prefix = target_prefix
    item_target_prefix = item.get("target_prefix")
    if item_target_prefix:
        item_prefix = Path(os.path.expanduser(str(item_target_prefix)))
        if item_prefix.is_absolute():
            effective_prefix = item_prefix
        elif backpack_root is not None:
            effective_prefix = Path(backpack_root) / item_prefix

    prefix_p = Path(os.path.abspath(os.path.expanduser(str(effective_prefix))))
    prefix_p.mkdir(parents=True, exist_ok=True)
    return Path(os.path.abspath(str(prefix_p / target_path)))


def _copy_local_source_to_target(
    src_path: Path, target_path: Path, *, force: bool = False, verbose: bool = False
) -> bool:
    """Copy a local file or directory (src_path) into target_path.

    Uses fs_file_copy for files (preserves resume/atomic behavior) and
    shutil.copytree for directories. Returns True on success, False on missing source.
    """
    if not src_path.exists():
        if verbose:
            print(f"[data:fetch] Source missing (local): {src_path}")
        return False

    if src_path.is_file():
        fs_file_copy(
            str(src_path),
            dest_dir=str(target_path.parent),
            filename=target_path.name,
            overwrite=force,
        )
    else:
        import shutil

        if force and target_path.exists():
            if target_path.is_dir():
                shutil.rmtree(target_path)
            else:
                target_path.unlink(missing_ok=True)
        shutil.copytree(src_path, target_path, dirs_exist_ok=True)
    return True


def _prepare_fetch_target(
    item: Dict[str, Any],
    target_prefix: Path,
    backpack_root: Path,
    force: bool,
    verbose: bool,
) -> Path:
    name = item.get("name", "<unnamed>")
    target_path = _resolve_target_path(
        item,
        target_prefix=target_prefix,
        backpack_root=backpack_root,
    )
    if verbose:
        print(f"[data:fetch] Target resolved for '{name}': {target_path}")

    target_path.parent.mkdir(parents=True, exist_ok=True)

    if target_path.exists() and not force:
        if verbose:
            print(
                f"[data:fetch] Skipping '{name}' because target already exists: {target_path}"
            )
        return target_path

    if target_path.exists() and force:
        if verbose:
            print(f"[data:fetch] Removing existing target for '{name}': {target_path}")
        if target_path.is_dir() and not target_path.is_symlink():
            shutil.rmtree(target_path)
        else:
            target_path.unlink()

    if verbose:
        print(f"[data:fetch] Ready target for '{name}': {target_path}")
    return target_path


def _prepare_cache_context(
    item: Dict[str, Any],
    backpack_root: Path,
    cache_lookup_mode: str = "strict",
    perf: Optional[Any] = None,
    verbose: bool = False,
) -> Dict[str, Any]:
    """Compute artifact spec and spec_key. For strict mode with remote sources,
    also fetch source metadata and compute source_key upfront.

    Returns dict with: artifact_spec, spec_key, source_key (None if deferred),
    source_meta (None if deferred).
    """
    perf = perf or _NullPerf()
    name = item.get("name", "<unnamed>")
    artifact_spec = _create_artifact_spec(item, backpack_root)
    spec_key = _compute_spec_key(artifact_spec)

    source_key: Optional[str] = None
    source_meta: Optional[Dict[str, Any]] = None

    # For strict mode: fetch remote metadata now to determine source_key.
    # For local mode: defer to build time (avoid network cost on cache hit).
    if str(cache_lookup_mode or "strict").strip().lower() == "strict":
        source_meta = _fetch_source_metadata_for_item(
            item, name=name, perf=perf, verbose=verbose
        )

        perf.start_timer(f"source_key_compute_{name}")
        source_key = _compute_source_key(source_meta, item.get("source_type", ""))
        perf.end_timer(
            f"source_key_compute_{name}",
            f"Source key computation for cache context of '{name}'",
        )

    if verbose:
        print(
            f"[cache] Context for '{name}': spec_key={spec_key[:16]}... source_key={source_key[:16] + '...' if source_key and len(source_key) > 16 else source_key}"
        )

    return {
        "artifact_spec": artifact_spec,
        "spec_key": spec_key,
        "source_key": source_key,
        "source_meta": source_meta,
    }


def _validate_cache_dir(
    candidate: Path,
    artifact_spec: Dict[str, Any],
    backpack_root: Optional[Path],
    perf=None,
    verbose: bool = False,
) -> Optional[Dict[str, Any]]:
    """Validate a single cache directory. Returns metadata on success, None on any failure.

    Step 1: directory exists and no build is in progress.
    Step 2: build is complete — metadata and cached_data/ both present.
    Step 3: for local sources (fs/backpack), confirm source file hasn't changed.
    """
    # Step 1
    if not candidate.exists() or (candidate / ".verify.lock").exists():
        return None

    # Step 2
    meta = _read_cache_metadata(candidate)
    if not meta or not (candidate / "cached_data").exists():
        return None

    # Step 3 — only applies to local sources; remote sources encode version in source_key.
    if artifact_spec.get("source_type") not in ("fs", "backpack") or not backpack_root:
        return meta

    cached_fp = meta.get("source_fingerprint")
    if not cached_fp:
        if verbose:
            print(f"[cache] Miss: no fingerprint stored in {candidate}")
        return None

    source_path = Path(artifact_spec.get("source", ""))
    if not source_path.is_absolute():
        source_path = (backpack_root / source_path).resolve()
    if not source_path.exists():
        if verbose:
            print(f"[cache] Miss: local source gone: {source_path}")
        return None

    perf = perf or _NullPerf()
    try:
        from .fingerprint import compute_fingerprint

        perf.start_timer(f"fingerprint_compute_{source_path.name}")
        current = compute_fingerprint(str(source_path), mode="meta", verbose=False)
        perf.end_timer(
            f"fingerprint_compute_{source_path.name}",
            f"Fingerprint validation for {source_path.name}",
        )
        if current.get("fingerprint") != cached_fp:
            if verbose:
                print(f"[cache] Miss: local source fingerprint changed")
            return None
    except Exception as e:
        if verbose:
            print(f"[cache] Warning: fingerprint check failed: {e}")

    return meta


def _find_cache_hit(
    cache_base_dir: Path,
    spec_key: str,
    source_key: Optional[str],
    artifact_spec: Dict[str, Any],
    backpack_root: Path,
    cache_lookup_mode: str,
    perf: Optional[Any] = None,
    verbose: bool = False,
) -> Optional[Tuple[Path, Dict[str, Any]]]:
    """Find a valid cache entry. Returns (cache_dir, meta) on hit, None on miss.

    strict: exact match on spec_key/source_key/ — source content must be unchanged.
    local:  scan spec_key/*/ and accept the first valid entry (any source version).
    """
    lookup_mode = str(cache_lookup_mode or "strict").strip().lower()

    if lookup_mode == "strict":
        if source_key is None:
            if verbose:
                print(
                    f"[cache] Strict miss: source_key not available (metadata fetch failed)"
                )
            return None
        cache_dir = _get_cache_dir(cache_base_dir, spec_key, source_key)
        meta = _validate_cache_dir(
            cache_dir, artifact_spec, backpack_root, perf, verbose
        )
        if verbose:
            print(f"[cache] Strict {'hit' if meta else 'miss'}: {cache_dir}")
        return (cache_dir, meta) if meta else None

    # local mode: scan spec_key/*/ and take the first valid entry.
    artifact_dir = _get_cache_dir_parent(cache_base_dir, spec_key)
    if not artifact_dir.exists():
        if verbose:
            print(f"[cache] Local miss: {artifact_dir} not found")
        return None
    for subdir in sorted(artifact_dir.iterdir()):
        if not subdir.is_dir():
            continue
        meta = _validate_cache_dir(subdir, artifact_spec, backpack_root, perf, verbose)
        if meta:
            if verbose:
                print(f"[cache] Local hit: {subdir}")
            return (subdir, meta)
    if verbose:
        print(f"[cache] Local miss: no valid entry under {artifact_dir}")
    return None


def _get_or_build_cache_entry(
    item: Dict[str, Any],
    backpack_root: Path,
    cache_base_dir: Path,
    cache_ctx: Dict[str, Any],
    data_cache_mode: str,
    force_data_cache: bool,
    cache_lookup_mode: str,
    perf: Optional[Any] = None,
    verbose: bool = False,
) -> Optional[Tuple[Path, Dict[str, Any]]]:
    """Return (cache_dir, meta) from cache hit or after building a new entry.

    On a miss in local mode, fetches source metadata now (deferred from context
    preparation) to determine the source_key for the new cache directory.
    """
    perf = perf or _NullPerf()
    name = item.get("name", "<unnamed>")
    artifact_spec = cache_ctx["artifact_spec"]
    spec_key = cache_ctx["spec_key"]
    source_key = cache_ctx["source_key"]
    source_meta = cache_ctx["source_meta"]

    if not data_cache_mode or data_cache_mode == "off":
        return None

    lookup_result: Optional[Tuple[Path, Dict[str, Any]]] = None
    if not force_data_cache:
        perf.start_timer(f"cache_hit_search_{name}")
        lookup_result = _find_cache_hit(
            cache_base_dir,
            spec_key,
            source_key,
            artifact_spec=artifact_spec,
            backpack_root=backpack_root,
            cache_lookup_mode=cache_lookup_mode,
            perf=perf,
            verbose=verbose,
        )
        perf.end_timer(f"cache_hit_search_{name}", f"Cache hit search for '{name}'")

    if lookup_result is not None:
        if verbose:
            print(f"[data:fetch] Cache hit for '{name}'")
        return lookup_result

    if verbose:
        print(f"[data:fetch] Cache miss for '{name}' — building new entry")

    # Resolve source_key for build (may be None when local lookup mode was used).
    build_source_key = source_key
    build_source_meta = source_meta
    if build_source_key is None:
        build_source_meta = _fetch_source_metadata_for_item(
            item, name=name, perf=perf, verbose=verbose
        )
        build_source_key = _compute_source_key(
            build_source_meta, item.get("source_type", "")
        )

    cache_dir = _get_cache_dir(cache_base_dir, spec_key, build_source_key)

    if not _acquire_cache_lock(cache_dir, timeout=300):
        if verbose:
            print(f"[data:fetch] Cache lock timeout for '{name}': {cache_dir}")
        return None

    try:
        perf.start_timer(f"cache_build_{name}")
        built = _build_cache_entry(
            item,
            cache_dir,
            backpack_root,
            artifact_spec=artifact_spec,
            source_key=build_source_key,
            source_meta=build_source_meta,
            verbose=verbose,
            perf=perf,
        )
        perf.end_timer(
            f"cache_build_{name}",
            f"Cache build for '{name}'" if built else f"Cache build failed for '{name}'",
        )
        if not built:
            return None

        meta = _read_cache_metadata(cache_dir)
        if meta is None:
            return None

        if verbose:
            print(f"[data:fetch] Cache entry built for '{name}': {cache_dir}")
        return (cache_dir, meta)
    finally:
        _release_cache_lock(cache_dir)


def _materialize_cache_entry_to_target(
    item: Dict[str, Any],
    cache_dir: Path,
    target_path: Path,
    data_cache_mode: str,
    perf: Optional[Any] = None,
    verbose: bool = False,
) -> bool:
    perf = perf or _NullPerf()
    name = item.get("name", "<unnamed>")
    target_location = item.get("target_location") or item.get("target_path")

    if verbose:
        print(
            f"[data:fetch] Materializing cached item for '{name}' using mode={data_cache_mode}"
        )

    perf.start_timer(f"cache_materialize_{name}")
    ok = _materialize_from_cache(
        cache_dir,
        target_path,
        target_location=target_location,
        mode=data_cache_mode,
        verbose=verbose,
    )
    perf.end_timer(
        f"cache_materialize_{name}",
        f"Cache materialization for '{name}'" if ok else f"Cache materialization failed for '{name}'",
    )

    if verbose:
        if ok:
            print(
                f"[data:fetch] Cache materialization succeeded for '{name}': {target_path}"
            )
        else:
            print(
                f"[data:fetch] Cache materialization failed for '{name}': {target_path}"
            )

    return ok


def _fetch_direct_to_target(
    item: Dict[str, Any],
    target_path: Path,
    backpack_root: Path,
    force: bool,
    perf=None,
    verbose: bool = False,
) -> bool:
    perf = perf or _NullPerf()
    name = item.get("name", "<unnamed>")
    stype = item.get("source_type")

    if verbose:
        print(f"[data:fetch] Direct fetch path for '{name}' (source_type={stype})")

    if stype == "multi":
        sources = item.get("sources", [])
        if verbose:
            print(
                f"[data:fetch] Trying {len(sources)} source(s) for multi item '{name}'"
            )

        for index, src_entry in enumerate(sources, start=1):
            if verbose:
                print(
                    f"[data:fetch] Multi source {index}/{len(sources)} for '{name}': type={src_entry.get('source_type')} source={src_entry.get('source')}"
                )
            if _attempt_fetch_source(
                src_entry,
                target_path,
                backpack_root,
                verbose=verbose,
                force=force,
            ):
                if verbose:
                    print(
                        f"[data:fetch] Multi source {index}/{len(sources)} succeeded for '{name}' -> {target_path}"
                    )
                return True

        if verbose:
            print(f"[data:fetch] All multi sources failed for '{name}'")
        return False

    if verbose:
        print(
            f"[data:fetch] Fetching single source for '{name}': source_type={stype} source={item.get('source')} -> {target_path}"
        )

    perf.start_timer(f"direct_fetch_{name}")
    ok = _attempt_fetch_source(
        item,
        target_path,
        backpack_root,
        verbose=verbose,
        force=force,
    )
    perf.end_timer(f"direct_fetch_{name}", f"Direct fetch for '{name}'")

    if verbose:
        if ok:
            print(f"[data:fetch] Direct fetch succeeded for '{name}' -> {target_path}")
        else:
            print(f"[data:fetch] Direct fetch failed for '{name}'")

    return ok


def _fetch_single_item(
    item: Dict[str, Any],
    backpack_root: Path,
    verbose: bool = False,
    force: bool = False,
    data_cache_mode: str = "off",
    force_data_cache: bool = False,
    cache_base_dir: Path | None = None,
    target_prefix: Path | None = None,
    cache_lookup_mode: str = "strict",
    perf: Optional[Any] = None,
    _out_cache_dirs: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """Fetch a single data item, optionally using cache. Returns the item if fetch was successful, None otherwise."""
    perf = perf or _NullPerf()
    name = item.get("name", "<unnamed>")

    if not target_prefix:
        raise ValueError("target_prefix is required for _fetch_single_item")

    if verbose:
        print(f"[data:fetch] Starting fetch for '{name}'")

    target_path = _prepare_fetch_target(
        item,
        target_prefix,
        backpack_root,
        force=force,
        verbose=verbose,
    )

    if target_path.exists() and not force:
        if verbose:
            print(
                f"[data:fetch] Fetch skipped for '{name}' because target already exists: {target_path}"
            )
        return None

    if data_cache_mode != "off" and cache_base_dir is not None:
        perf.start_timer(f"total_lookup_{name}")

        cache_ctx = _prepare_cache_context(
            item,
            backpack_root,
            cache_lookup_mode=cache_lookup_mode,
            perf=perf,
            verbose=verbose,
        )

        cache_result = _get_or_build_cache_entry(
            item,
            backpack_root,
            Path(cache_base_dir),
            cache_ctx=cache_ctx,
            data_cache_mode=data_cache_mode,
            force_data_cache=force_data_cache,
            cache_lookup_mode=cache_lookup_mode,
            perf=perf,
            verbose=verbose,
        )

        perf.end_timer(f"total_lookup_{name}", f"Total cache lookup for '{name}'")

        if cache_result is not None:
            cache_dir, _cache_meta = cache_result
            if _materialize_cache_entry_to_target(
                item,
                cache_dir,
                target_path,
                data_cache_mode=data_cache_mode,
                perf=perf,
                verbose=verbose,
            ):
                if _out_cache_dirs is not None:
                    _out_cache_dirs.append(str(cache_dir))
                if verbose:
                    print(f"[data:fetch] Finished cached fetch for '{name}'")
                return item

            if verbose:
                print(f"[data:fetch] Cache materialization failed for '{name}', falling back to direct fetch")

    if _fetch_direct_to_target(
        item,
        target_path,
        backpack_root,
        force=force,
        perf=perf,
        verbose=verbose,
    ):
        if verbose:
            print(f"[data:fetch] Finished direct fetch for '{name}'")
        return item

    if verbose:
        print(f"[data:fetch] FAILED '{name}'")
    return None


def _attempt_fetch_source(
    item: Dict[str, Any],
    target_path: Path,
    backpack_root: Path,
    verbose: bool = False,
    force: bool = False,
) -> bool:
    stype = item.get("source_type")
    src = item.get("source")
    try:
        if stype == "http":
            # Download into target directory with final name
            http_file_download(
                src,
                dest_dir=str(target_path.parent),
                filename=target_path.name,
                overwrite=force,
            )
            return True
        if stype == "s3":
            # Determine if source is a directory
            # Priority: 1) Explicit source_object_type field, 2) URL trailing slash, 3) Metadata check
            source_obj_type = item.get("source_object_type", "").lower()

            is_dir = False
            if source_obj_type == "directory":
                is_dir = True
            elif source_obj_type == "file":
                is_dir = False
            else:
                # Auto-detect: trailing slash or metadata check
                is_dir = src.endswith("/") or is_s3_directory(src)

            if is_dir:
                # Directory download - target_path is the destination directory
                if verbose:
                    print(f"[data:fetch] S3 directory download: {src} -> {target_path}")
                s3_directory_download(
                    src,
                    dest_dir=str(target_path),
                    overwrite=force,
                    show_progress=verbose,
                )
            else:
                # Single file download
                if verbose:
                    print(
                        f"[data:fetch] S3 file download: {src} -> {target_path.parent}/{target_path.name}"
                    )
                s3_file_download(
                    src,
                    dest_dir=str(target_path.parent),
                    filename=target_path.name,
                    overwrite=force,
                )
            return True
        if stype == "xrootd":
            source_obj_type = item.get("source_object_type", "").lower()
            is_dir = False
            if source_obj_type == "directory":
                is_dir = True
            elif source_obj_type == "file":
                is_dir = False
            else:
                is_dir = src.endswith("/") or is_xrootd_directory(src)

            if is_dir:
                if verbose:
                    print(f"[data:fetch] XRootD directory download: {src} -> {target_path}")
                xrootd_directory_download(
                    src,
                    dest_dir=str(target_path),
                    overwrite=force,
                    show_progress=verbose,
                )
            else:
                if verbose:
                    print(f"[data:fetch] XRootD file download: {src} -> {target_path.parent}/{target_path.name}")
                xrootd_file_download(
                    src,
                    dest_dir=str(target_path.parent),
                    filename=target_path.name,
                    overwrite=force,
                )
            return True
        if stype == "pelican":
            # Determine if source is a directory
            # Priority: 1) Explicit source_object_type field, 2) URL trailing slash, 3) Metadata check
            source_obj_type = item.get("source_object_type", "").lower()

            is_dir = False
            if source_obj_type == "directory":
                is_dir = True
            elif source_obj_type == "file":
                is_dir = False
            else:
                # Auto-detect: trailing slash or metadata check
                is_dir = src.endswith("/") or is_pelican_directory(src)

            if is_dir:
                # Directory download - target_path is the destination directory
                if verbose:
                    print(
                        f"[data:fetch] Pelican directory download: {src} -> {target_path}"
                    )
                pelican_directory_download(
                    src,
                    dest_dir=str(target_path),
                    overwrite=force,
                    show_progress=verbose,
                )
            else:
                # Single file download
                if verbose:
                    print(
                        f"[data:fetch] Pelican file download: {src} -> {target_path.parent}/{target_path.name}"
                    )
                pelican_file_download(
                    src,
                    dest_dir=str(target_path.parent),
                    filename=target_path.name,
                    overwrite=force,
                )
            return True
        if stype in ("backpack", "fs"):
            p = Path(src)
            if not p.is_absolute():
                p = (Path(backpack_root) / p).resolve()
            return _copy_local_source_to_target(
                p, target_path, force=force, verbose=verbose
            )
    except Exception as e:
        if verbose:
            print(f"[data:fetch] Error fetching {stype} source '{src}': {e}")
        return False
    return False


# --------------------------- Cache Infrastructure ---------------------------
def _create_artifact_spec(item: Dict[str, Any], backpack_root: Path) -> Dict[str, Any]:
    """Create a normalized artifact spec containing only fields that affect bytes.

    This spec is used to compute the cache key. Only include fields that affect
    the content of the cached data (source, checksum, size, transformations).

    Args:
        item: Normalized data item from spec
        backpack_root: Base path for resolving relative sources

    Returns:
        Dict with canonical fields: source_type, source(s), checksum, expected_size,
        content_type, post_process
    """
    artifact = {}

    # Source information
    stype = item.get("source_type")
    artifact["source_type"] = stype

    if stype == "multi":
        # For multi-source, include all sources in order
        sources = item.get("sources", [])
        resolved_sources = []
        for s in sources:
            s_type = s.get("source_type")
            s_source = s.get("source", "")
            # Resolve relative fs/backpack paths to absolute
            if s_type in ("fs", "backpack"):
                p = Path(s_source)
                if not p.is_absolute():
                    s_source = str((Path(backpack_root) / p).resolve())
            resolved_sources.append({"source_type": s_type, "source": s_source})
        artifact["sources"] = resolved_sources
    else:
        # Single source
        source = item.get("source", "")
        # Resolve relative fs/backpack paths to absolute
        if stype in ("fs", "backpack"):
            p = Path(source)
            if not p.is_absolute():
                source = str((Path(backpack_root) / p).resolve())
        artifact["source"] = source

    # Checksum (if specified)
    checksum = _extract_checksum_field(item)
    if checksum:
        artifact["checksum"] = checksum

    # Expected size (if specified)
    expected_size = item.get("expected_size")
    if expected_size is not None:
        artifact["expected_size"] = expected_size

    # Content type (if specified)
    content_type = item.get("content_type")
    if content_type:
        artifact["content_type"] = content_type

    # Post-processing (if specified)
    post_process = item.get("post_process")
    if post_process:
        artifact["post_process"] = post_process

    return artifact


def _compute_spec_key(artifact_spec: Dict[str, Any]) -> str:
    """SHA-256 of canonical artifact spec JSON. Stable and offline-computable."""
    canonical = json.dumps(artifact_spec, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalize_s3_source_meta(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Select and normalize S3-specific fields for stable source key hashing.

    File: etag, size, last_modified (None values excluded for stability).
    Directory: file_count, total_size, per-file etag/size/last_modified (sorted).
    """
    if meta.get("object_type") == "directory":
        files = [
            {k: v for k, v in f.items() if v is not None} for f in meta.get("files", [])
        ]
        return {
            "object_type": "directory",
            "file_count": meta.get("file_count"),
            "total_size": meta.get("total_size"),
            "files": sorted(files, key=lambda f: f.get("rel_path", "")),
        }
    return {
        k: v
        for k, v in {
            "object_type": "file",
            "etag": meta.get("etag"),
            "size": meta.get("size"),
            "last_modified": meta.get("last_modified"),
        }.items()
        if v is not None
    }


def _normalize_xrootd_source_meta(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Select and normalize XRootD-specific fields for stable source key hashing.

    File:      size, mtime, checksum (None values excluded).
    Directory: file_count, total_size, per-file size/mtime/checksum (sorted by rel_path).
    """
    if meta.get("object_type") == "directory":
        files = [
            {k: v for k, v in f.items() if v is not None} for f in meta.get("files", [])
        ]
        return {
            "object_type": "directory",
            "file_count": meta.get("file_count"),
            "total_size": meta.get("total_size"),
            "files": sorted(files, key=lambda f: f.get("rel_path", "")),
        }
    return {
        k: v
        for k, v in {
            "object_type": "file",
            "size": meta.get("size"),
            "mtime": meta.get("mtime"),
            "checksum": meta.get("checksum"),
        }.items()
        if v is not None
    }


def _normalize_pelican_source_meta(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Select and normalize Pelican-specific fields for stable source key hashing.

    File:      size, modified (None values excluded).
    Directory: file_count, total_size, per-file size/modified (sorted by rel_path).
    """
    if meta.get("object_type") == "directory":
        files = [
            {k: v for k, v in f.items() if v is not None} for f in meta.get("files", [])
        ]
        return {
            "object_type": "directory",
            "file_count": meta.get("file_count"),
            "total_size": meta.get("total_size"),
            "files": sorted(files, key=lambda f: f.get("rel_path", "")),
        }
    return {
        k: v
        for k, v in {
            "object_type": "file",
            "size": meta.get("size"),
            "modified": meta.get("modified"),
        }.items()
        if v is not None
    }


def _compute_source_key(source_meta: Optional[Dict[str, Any]], source_type: str) -> str:
    """Source-type-aware source cache key.

    s3:     SHA-256 of normalized etag/size/last_modified (file) or per-file
            listings (directory). Changes whenever remote data changes.
    xrootd: SHA-256 of normalized size/mtime/checksum (file) or per-file
            listings (directory). Fully implemented — strongest cache signal.
    pelican: placeholder — not yet implemented.
    http:    placeholder — not yet implemented.
    fs/backpack/local: "local" — no remote metadata; cache validity checked via
            fingerprint in _lookup_cache_entry.
    """
    effective_type = source_type
    if source_type == "multi" and source_meta:
        effective_type = source_meta.get("used_source_type", "unknown")

    if effective_type == "s3" and source_meta and source_meta.get("ok"):
        normalized = _normalize_s3_source_meta(source_meta)
        canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    if effective_type == "xrootd" and source_meta and source_meta.get("ok"):
        normalized = _normalize_xrootd_source_meta(source_meta)
        canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    if effective_type == "pelican" and source_meta and source_meta.get("ok"):
        normalized = _normalize_pelican_source_meta(source_meta)
        canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    if effective_type == "http":
        return "http_source_key"

    return "local"


def _fetch_source_metadata_for_item(
    item: Dict[str, Any],
    name: str = "<unnamed>",
    perf: Optional[Any] = None,
    verbose: bool = False,
) -> Optional[Dict[str, Any]]:
    """Fetch remote source metadata for source key computation.

    Implemented for s3, xrootd, and pelican. Returns None for local sources
    (fs, backpack) and http (not yet implemented).

    Timing is recorded via perf (metadata_fetch_<name>) when perf is provided.
    """
    perf = perf or _NullPerf()
    stype = item.get("source_type")
    source = item.get("source", "")

    if stype == "s3":
        perf.start_timer(f"metadata_fetch_{name}")
        meta = s3_source_metadata(source)
        perf.end_timer(f"metadata_fetch_{name}", f"S3 metadata fetch for '{name}'")
        return meta

    if stype == "xrootd":
        perf.start_timer(f"metadata_fetch_{name}")
        meta = xrootd_source_metadata(source)
        perf.end_timer(f"metadata_fetch_{name}", f"XRootD metadata fetch for '{name}'")
        return meta

    if stype == "multi":
        for s in item.get("sources", []):
            s_type = s.get("source_type")
            src = s.get("source", "")
            if s_type == "s3":
                perf.start_timer(f"metadata_fetch_{name}")
                meta = s3_source_metadata(src)
                perf.end_timer(f"metadata_fetch_{name}", f"S3 metadata fetch for '{name}'")
                if meta.get("ok"):
                    meta["used_source"] = src
                    meta["used_source_type"] = "s3"
                    return meta
            elif s_type == "xrootd":
                perf.start_timer(f"metadata_fetch_{name}")
                meta = xrootd_source_metadata(src)
                perf.end_timer(f"metadata_fetch_{name}", f"XRootD metadata fetch for '{name}'")
                if meta.get("ok"):
                    meta["used_source"] = src
                    meta["used_source_type"] = "xrootd"
                    return meta
            elif s_type == "pelican":
                perf.start_timer(f"metadata_fetch_{name}")
                meta = pelican_source_metadata(src)
                perf.end_timer(f"metadata_fetch_{name}", f"Pelican metadata fetch for '{name}'")
                if meta.get("ok"):
                    meta["used_source"] = src
                    meta["used_source_type"] = "pelican"
                    return meta
        return None

    if stype == "pelican":
        perf.start_timer(f"metadata_fetch_{name}")
        meta = pelican_source_metadata(source)
        perf.end_timer(f"metadata_fetch_{name}", f"Pelican metadata fetch for '{name}'")
        return meta

    # http: not yet implemented
    # fs, backpack: local sources — no remote metadata
    return None


def _cache_root(base_dir: Path) -> Path:
    """Resolve the floability-data-cache root from any base dir."""
    return (
        base_dir
        if base_dir.name == "floability-data-cache"
        else base_dir / "floability-data-cache"
    )


def _get_cache_dir_parent(base_dir: Path, spec_key: str) -> Path:
    """Parent directory for all cached versions of one artifact: cache_root/spec_key/

    All source_key subdirectories live here — one per observed remote state.
    """
    return _cache_root(base_dir) / spec_key


def _get_cache_dir(base_dir: Path, spec_key: str, source_key: str) -> Path:
    """Two-level cache path: cache_root/spec_key/source_key/

    spec_key  — SHA-256 of artifact spec (stable, offline-computable).
    source_key — SHA-256 of remote metadata (changes when source changes),
                 or a placeholder string ("local", "pelican_source_key", …).
    """
    return _get_cache_dir_parent(base_dir, spec_key) / source_key


def _acquire_cache_lock(cache_dir: Path, timeout: int = 300) -> bool:
    """Atomically acquire a lock for cache directory.

    Creates cache_dir/.verify.lock to signal cache build in progress.

    Args:
        cache_dir: Cache directory path
        timeout: Max seconds to wait for existing lock (default: 5 min)

    Returns:
        True if lock acquired, False if timeout waiting for existing lock
    """
    lock_file = cache_dir / ".verify.lock"
    cache_dir.mkdir(parents=True, exist_ok=True)

    start_time = time.time()
    while True:
        try:
            # Try to create lock file atomically (fails if exists)
            lock_file.touch(exist_ok=False)
            # Write PID for debugging
            lock_file.write_text(str(os.getpid()))
            return True
        except FileExistsError:
            # Lock exists, check if we should wait
            elapsed = time.time() - start_time
            if elapsed > timeout:
                return False
            # Wait a bit and retry
            time.sleep(1)


def _release_cache_lock(cache_dir: Path) -> None:
    """Release cache lock by removing .verify.lock file.

    Args:
        cache_dir: Cache directory path
    """
    lock_file = cache_dir / ".verify.lock"
    lock_file.unlink(missing_ok=True)


def _write_cache_metadata(
    cache_dir: Path,
    artifact_spec: Dict[str, Any],
    content_sha256: str,
    actual_size: int,
    source_key: Optional[str] = None,
    source_meta: Optional[Dict[str, Any]] = None,
    source_fingerprint: Optional[Dict[str, Any]] = None,
) -> None:
    """Write cache metadata to .meta.json."""
    meta: Dict[str, Any] = {
        "artifact_spec": artifact_spec,
        "content_sha256": content_sha256,
        "actual_size": actual_size,
        "created_at": time.time(),
        "created_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    if source_key:
        meta["source_key"] = source_key
    if source_meta:
        meta["source_meta"] = source_meta

    # Fingerprint only written for local sources (fs/backpack, "meta" mode).
    if source_fingerprint:
        meta["source_fingerprint"] = source_fingerprint.get("fingerprint")

    meta_file = cache_dir / ".meta.json"
    with meta_file.open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, sort_keys=True)


def _read_cache_metadata(cache_dir: Path) -> Optional[Dict[str, Any]]:
    """Read cache metadata from .meta.json.

    Args:
        cache_dir: Cache directory path

    Returns:
        Metadata dict or None if not found/invalid
    """
    meta_file = cache_dir / ".meta.json"
    if not meta_file.exists():
        return None

    try:
        with meta_file.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _compute_content_hash(path: Path) -> Tuple[str, int]:
    """Compute SHA-256 hash and size of file or directory tree.

    For files: hash the file content.
    For directories: hash sorted list of (relative_path, file_sha256) pairs.

    Args:
        path: File or directory path

    Returns:
        Tuple of (sha256_hex, total_size_bytes)
    """
    if path.is_file():
        h = hashlib.sha256()
        size = 0
        with path.open("rb") as f:
            while True:
                chunk = f.read(1024 * 1024)  # 1MB chunks
                if not chunk:
                    break
                h.update(chunk)
                size += len(chunk)
        return h.hexdigest(), size

    elif path.is_dir():
        # Hash directory tree structure and content
        h = hashlib.sha256()
        total_size = 0

        # Collect all files with their hashes
        file_hashes = []
        for root, dirs, files in os.walk(path):
            # Sort for deterministic order
            dirs.sort()
            files.sort()

            for filename in files:
                file_path = Path(root) / filename
                rel_path = file_path.relative_to(path)
                file_hash, file_size = _compute_content_hash(file_path)
                file_hashes.append((str(rel_path), file_hash, file_size))
                total_size += file_size

        # Hash the sorted list of (path, hash, size)
        for rel_path, file_hash, file_size in sorted(file_hashes):
            h.update(f"{rel_path}:{file_hash}:{file_size}\n".encode("utf-8"))

        return h.hexdigest(), total_size

    else:
        raise ValueError(f"Path is neither file nor directory: {path}")


def _build_cache_entry(
    item: Dict[str, Any],
    cache_dir: Path,
    backpack_root: Path,
    artifact_spec: Dict[str, Any],
    source_key: Optional[str] = None,
    source_meta: Optional[Dict[str, Any]] = None,
    verbose: bool = False,
    perf: Optional[Any] = None,
) -> bool:
    """Download data into cache_dir/cached_data/ and write .meta.json.

    artifact_spec, source_key, and source_meta are pre-computed by the caller
    so we avoid redundant computation here.
    """
    perf = perf or _NullPerf()
    stype = item.get("source_type")
    target_location = item.get("target_location") or item.get("target_path")
    if not target_location:
        if verbose:
            print("[cache] ERROR: Missing target_location in item")
        return False

    cached_data_dir = cache_dir / "cached_data"
    cache_file = cached_data_dir / target_location
    cache_file.parent.mkdir(parents=True, exist_ok=True)

    if verbose:
        print(f"[cache] Building cache entry: {cache_dir}")
        print(f"[cache] Downloading to: {cache_file}")

    try:
        if stype == "multi":
            success = any(
                _download_to_cache(src_entry, cache_file, backpack_root, verbose)
                for src_entry in item.get("sources", [])
            )
            if not success:
                if verbose:
                    print("[cache] ERROR: All sources failed")
                return False
        else:
            if not _download_to_cache(item, cache_file, backpack_root, verbose):
                if verbose:
                    print("[cache] ERROR: Download failed")
                return False

        if item.get("post_process"):
            print(
                f"[cache] WARNING: post_process not yet implemented: {item['post_process']}"
            )

        # Fingerprint only for local sources (fs/backpack), always "meta" mode.
        source_fingerprint = None
        if stype in ("fs", "backpack"):
            try:
                from .fingerprint import compute_fingerprint

                source = item.get("source", "")
                source_path = Path(source)
                if not source_path.is_absolute():
                    source_path = (backpack_root / source_path).resolve()
                if source_path.exists():
                    perf.start_timer(f"fingerprint_compute_{source_path.name}")
                    source_fingerprint = compute_fingerprint(
                        str(source_path), mode="meta", verbose=verbose
                    )
                    perf.end_timer(
                        f"fingerprint_compute_{source_path.name}",
                        f"Fingerprint for {source_path.name}",
                    )
            except Exception as e:
                if verbose:
                    print(f"[cache] Warning: Failed to compute source fingerprint: {e}")

        _write_cache_metadata(
            cache_dir,
            artifact_spec,
            content_sha256="placeholder",
            actual_size=0,
            source_key=source_key,
            source_meta=source_meta,
            source_fingerprint=source_fingerprint,
        )

        if verbose:
            print(f"[cache] Cache entry built: source_key={source_key}")
        return True

    except Exception as e:
        if verbose:
            print(f"[cache] ERROR building cache entry: {e}")
        return False


def _download_to_cache(
    item: Dict[str, Any],
    cache_file: Path,
    backpack_root: Path,
    verbose: bool = False,
) -> bool:
    """Download or copy data to cache file.

    Args:
        item: Data item (or source entry for multi-source)
        cache_file: Target file path in cache
        backpack_root: Base path for resolving relative sources
        verbose: Print progress messages

    Returns:
        True if successful, False otherwise
    """
    stype = item.get("source_type")
    source = item.get("source")

    try:
        if stype == "http":
            http_file_download(
                source,
                dest_dir=str(cache_file.parent),
                filename=cache_file.name,
                overwrite=True,
            )
            return cache_file.exists()

        elif stype == "s3":
            # Determine if source is a directory
            # Priority: 1) Explicit source_object_type field, 2) URL trailing slash, 3) Metadata check
            source_obj_type = item.get("source_object_type", "").lower()

            is_dir = False
            if source_obj_type == "directory":
                is_dir = True
            elif source_obj_type == "file":
                is_dir = False
            else:
                # Auto-detect: trailing slash or metadata check
                is_dir = source.endswith("/") or is_s3_directory(source)

            if is_dir:
                # Directory download - cache_file is the destination directory
                s3_directory_download(
                    source,
                    dest_dir=str(cache_file),
                    overwrite=True,
                    show_progress=verbose,
                )
            else:
                # Single file download
                s3_file_download(
                    source,
                    dest_dir=str(cache_file.parent),
                    filename=cache_file.name,
                    overwrite=True,
                )
            return cache_file.exists()

        elif stype == "xrootd":
            source_obj_type = item.get("source_object_type", "").lower()
            is_dir = False
            if source_obj_type == "directory":
                is_dir = True
            elif source_obj_type == "file":
                is_dir = False
            else:
                is_dir = source.endswith("/") or is_xrootd_directory(source)

            if is_dir:
                xrootd_directory_download(
                    source,
                    dest_dir=str(cache_file),
                    overwrite=True,
                    show_progress=verbose,
                )
            else:
                xrootd_file_download(
                    source,
                    dest_dir=str(cache_file.parent),
                    filename=cache_file.name,
                    overwrite=True,
                )
            return cache_file.exists()

        elif stype == "pelican":
            # Determine if source is a directory
            # Priority: 1) Explicit source_object_type field, 2) URL trailing slash, 3) Metadata check
            source_obj_type = item.get("source_object_type", "").lower()

            is_dir = False
            if source_obj_type == "directory":
                is_dir = True
            elif source_obj_type == "file":
                is_dir = False
            else:
                # Auto-detect: trailing slash or metadata check
                is_dir = source.endswith("/") or is_pelican_directory(source)

            if is_dir:
                # Directory download - cache_file is the destination directory
                pelican_directory_download(
                    source,
                    dest_dir=str(cache_file),
                    overwrite=True,
                    show_progress=verbose,
                )
            else:
                # Single file download
                pelican_file_download(
                    source,
                    dest_dir=str(cache_file.parent),
                    filename=cache_file.name,
                    overwrite=True,
                )
            return cache_file.exists()

        elif stype in ("fs", "backpack"):
            # Copy from local filesystem
            p = Path(source)
            if not p.is_absolute():
                p = (Path(backpack_root) / p).resolve()

            if not p.exists():
                if verbose:
                    print(f"[cache] Source not found: {p}")
                return False

            if p.is_file():
                shutil.copy2(p, cache_file)
            else:
                # For directories, copy entire tree
                if cache_file.exists():
                    if cache_file.is_dir():
                        shutil.rmtree(cache_file)
                    else:
                        cache_file.unlink()
                shutil.copytree(p, cache_file)

            return cache_file.exists()

        else:
            if verbose:
                print(f"[cache] Unsupported source_type: {stype}")
            return False

    except Exception as e:
        if verbose:
            print(f"[cache] Download error: {e}")
        return False


def _materialize_from_cache(
    cache_dir: Path,
    target_path: Path,
    target_location: Optional[str] = None,
    mode: str = "symlink",
    verbose: bool = False,
) -> bool:
    """Materialize target from cache using specified mode.
    The cache structure in cached_data/ mirrors the target structure.
    This function creates symlinks/copies from cached_data/* into the workflow directory,
    preserving the exact directory structure.

    Modes:
    - symlink: Create symbolic links (default, read-only convention)
    - hardlink: Create hard links (shares inode, but independent entry)
    - copy: Copy files/directories

    Args:
        cache_dir: Cache directory path
        target_path: Target path to create (e.g., workflow/data/samples/)
        mode: Materialization mode
        verbose: Print progress messages

    Returns:
        True if successful, False otherwise
    """
    cached_data_dir = cache_dir / "cached_data"
    if not cached_data_dir.exists():
        if verbose:
            print(f"[cache] Cannot materialize: cached_data/ directory missing")
        return False

    # Determine exact cached target for this item.
    cached_target: Optional[Path] = None
    if target_location:
        cached_target = cached_data_dir / target_location
        if not cached_target.exists():
            if verbose:
                print(
                    f"[cache] Cannot materialize: cached target missing for '{target_location}'"
                )
            return False
    else:
        # Backward-compatible fallback: if no target_location is given, only accept
        # single-item cached_data layouts.
        items = list(cached_data_dir.iterdir())
        if len(items) == 0:
            if verbose:
                print(f"[cache] Cannot materialize: cached_data/ is empty")
            return False
        if len(items) > 1:
            if verbose:
                print(
                    "[cache] Cannot materialize without target_location: multiple top-level cached entries"
                )
            return False
        cached_target = items[0]

    if verbose:
        print(f"[cache] Materializing from {cached_target}")
        print(f"[cache] Target path: {target_path}")

    try:
        # Ensure parent directory exists.
        target_path.parent.mkdir(parents=True, exist_ok=True)

        # Remove existing target if present.
        if target_path.exists() or target_path.is_symlink():
            if target_path.is_dir() and not target_path.is_symlink():
                shutil.rmtree(target_path)
            else:
                target_path.unlink()

        if mode == "symlink":
            target_path.symlink_to(cached_target.resolve())
            if verbose:
                print(f"[cache] Symlinked {target_path} -> {cached_target.resolve()}")

        elif mode == "hardlink":
            # Hard links apply to files. For directories, fall back to copy.
            if cached_target.is_file():
                os.link(cached_target, target_path)
                if verbose:
                    print(f"[cache] Hard-linked {target_path} -> {cached_target}")
            else:
                if verbose:
                    print(f"[cache] Hard link for directory, copying instead")
                shutil.copytree(cached_target, target_path)

        elif mode == "copy":
            if cached_target.is_file():
                shutil.copy2(cached_target, target_path)
            else:
                shutil.copytree(cached_target, target_path)
            if verbose:
                print(f"[cache] Copied {cached_target} -> {target_path}")

        else:
            if verbose:
                print(f"[cache] Unknown mode: {mode}")
            return False

        return True

    except Exception as e:
        if verbose:
            print(f"[cache] Error during materialization: {e}")
        return False


# --------------------------- Integrity Helpers ---------------------------
def _extract_checksum_field(item: Dict[str, Any]) -> Optional[str]:
    # Spec may define at top-level 'checksum' OR under legacy 'verification.checksum'
    if "checksum" in item and item["checksum"]:
        return str(item["checksum"]).strip()
    ver = item.get("verification") or {}
    cs = ver.get("checksum") if isinstance(ver, dict) else None
    return str(cs).strip() if cs else None


def _parse_checksum_spec(spec: str) -> Tuple[Optional[str], Optional[str]]:
    s = spec.strip().lower()
    if ":" in s:
        alg, hexval = s.split(":", 1)
        return alg.strip(), hexval.strip()
    # infer by length (common digests)
    hexlen = len(s)
    if hexlen == 32:
        return "md5", s
    if hexlen == 40:
        return "sha1", s
    if hexlen == 64:
        return "sha256", s
    return "sha256", s  # default


def _compute_checksum(path: Path, alg: str, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.new(alg)
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


# --------------------------- Verify Reporting ---------------------------
def _print_verify_summary(results: List[Dict[str, Any]]) -> bool:
    """Print verification summary and return success status.

    Returns:
        bool: True if all items passed verification, False otherwise.
    """
    print("[data:verify] Summary:")
    headers = [
        "name",
        "exists",
        "size_ok",
        "checksum_ok",
        "expected_size",
        "actual_size",
        "checksum_alg",
    ]
    colw = (
        {h: max(len(h), *(len(str(r.get(h, ""))) for r in results)) for h in headers}
        if results
        else {h: len(h) for h in headers}
    )

    def fmt_row(r: Dict[str, Any]):
        return " ".join(str(r.get(h, "")).ljust(colw[h]) for h in headers)

    print(fmt_row({h: h for h in headers}))
    for r in results:
        print(fmt_row(r))
    total = len(results)
    missing = sum(1 for r in results if not r.get("exists"))
    size_fail = sum(1 for r in results if r.get("size_ok") is False)
    checksum_fail = sum(1 for r in results if r.get("checksum_ok") is False)
    print(
        f"[data:verify] Items: {total}, missing: {missing}, size_fail: {size_fail}, checksum_fail: {checksum_fail}"
    )

    # Determine success: no missing items, no size failures, no checksum failures
    success = missing == 0 and size_fail == 0 and checksum_fail == 0

    if not success:
        print(
            f"\n[data:verify] ERROR: Verification failed for {missing + size_fail + checksum_fail} items"
        )
        if missing > 0:
            print(f"  - {missing} items are missing")
        if size_fail > 0:
            print(f"  - {size_fail} items have size mismatches")
        if checksum_fail > 0:
            print(f"  - {checksum_fail} items have checksum mismatches")
    else:
        print(f"[data:verify] SUCCESS: All {total} items passed verification")

    return success


def _print_verify_details(results: List[Dict[str, Any]]) -> None:
    print("\n[data:verify] Detailed results:")
    for r in results:
        print(f"--- {r.get('name')} ---")
        print(f"  target_path: {r.get('target_path')}")
        print(f"  exists: {r.get('exists')} is_dir={r.get('is_dir')}")
        print(
            f"  expected_size: {r.get('expected_size')} actual_size: {r.get('actual_size')} size_ok={r.get('size_ok')} note={r.get('size_note')}"
        )
        print(
            f"  checksum_alg: {r.get('checksum_alg')} checksum_expected: {r.get('checksum_expected')} checksum_actual: {r.get('checksum_actual')} checksum_ok={r.get('checksum_ok')}"
        )
    print("[data:verify] End of detailed report")


# todo: split print and check logic.
# print returns None, check returns bool
def _print_check_summary(
    results: List[Dict[str, Any]], show_cache: bool = False
) -> bool:
    """Print check summary and return success status.

    Args:
        results: List of check results for each data item
        show_cache: Include cache status columns in output

    Returns:
        bool: True if all items exist and match their expected size, False otherwise.
    """
    print("[data:check] Summary:")
    headers = [
        "name",
        "source_type",
        "exists",
        "size_ok",
        "expected_size",
        "actual_size",
        "size_note",
    ]

    if show_cache:
        headers.extend(["cache_exists", "cache_valid"])

    # Simple column widths
    colw = {h: max(len(h), *(len(str(r.get(h, ""))) for r in results)) for h in headers}

    def fmt_row(r: Dict[str, Any]):
        return " ".join(str(r.get(h, "")).ljust(colw[h]) for h in headers)

    print(fmt_row({h: h for h in headers}))
    for r in results:
        print(fmt_row(r))

    # Basic counts
    total = len(results)
    missing = sum(1 for r in results if not r.get("exists"))
    size_fail = sum(1 for r in results if r.get("size_ok") is False)

    if show_cache:
        cached = sum(1 for r in results if r.get("cache_valid") is True)
        cache_invalid = sum(
            1
            for r in results
            if r.get("cache_exists") is True and r.get("cache_valid") is False
        )
        print(
            f"[data:check] Items: {total}, missing: {missing}, size_fail: {size_fail}, cached: {cached}, cache_invalid: {cache_invalid}"
        )
    else:
        print(
            f"[data:check] Items: {total}, missing: {missing}, size_fail: {size_fail}"
        )

    # Determine success: no missing items and no size failures
    success = missing == 0 and size_fail == 0

    if not success:
        print(f"\n[data:check] ERROR: Check failed for {missing + size_fail} items")
        if missing > 0:
            print(f"  - {missing} items do not exist or cannot be accessed")
        if size_fail > 0:
            print(f"  - {size_fail} items have size mismatches")
    else:
        print(f"[data:check] SUCCESS: All {total} items passed check")
        if show_cache:
            print(f"[data:check] Cache status: {cached} items have valid cache entries")

    return success


def _print_detailed_results(
    results: List[Dict[str, Any]], show_cache: bool = False
) -> None:
    print("\n[data:check] Detailed item metadata:")
    for r in results:
        print(f"--- {r.get('name')} ({r.get('source_type')}) ---")
        print(f"  exists: {r.get('exists')}")
        print(f"  target_path: {r.get('target_path')}")
        print(f"  expected_size: {r.get('expected_size')}")
        print(
            f"  actual_size: {r.get('actual_size')} size_ok={r.get('size_ok')} note={r.get('size_note')}"
        )

        if show_cache:
            print(
                f"  cache_exists: {r.get('cache_exists')} cache_valid={r.get('cache_valid')}"
            )
            if r.get("cache_key"):
                print(f"  cache_key: {r.get('cache_key')}")

        meta = r.get("meta", {})
        # Limit headers/raw to avoid huge dumps
        raw = meta.get("raw") if isinstance(meta, dict) else None
        if isinstance(raw, dict):
            # show a few important raw keys if present
            interesting = {
                k: raw[k]
                for k in ("status", "final_url", "error", "headers")
                if k in raw
            }
            if "headers" in interesting and isinstance(interesting["headers"], dict):
                # trim headers list
                interesting["headers"] = {
                    k: interesting["headers"][k]
                    for k in list(interesting["headers"].keys())[:8]
                }
            if interesting:
                print(f"  raw: {interesting}")
        if r.get("multi_chain"):
            print("  multi attempts:")
            for attempt in r["multi_chain"]:
                a_name = (
                    attempt.get("name")
                    or attempt.get("raw", {}).get("final_url")
                    or "<source>"
                )
                print(
                    f"    - exists={attempt.get('exists')} size={attempt.get('size')} type={attempt.get('type')} name={attempt.get('name')}"
                )
    print("[data:check] End of detailed report")
