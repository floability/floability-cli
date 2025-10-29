from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, Iterable, List, Tuple, Optional, Callable
import yaml
import hashlib

# Reuse existing low-level helpers
from .http_file_utils import http_file_metadata, http_file_download
from .pelican_file_utils import pelican_file_metadata, pelican_file_download
from .fs_file_utils import fs_file_metadata, fs_file_copy


# --------------------------- Public API (stubs for now) ---------------------------
def check_data_from_spec(
    data_spec: str,
    backpack_root: Path,
    show_details: bool = False,
    verbose: bool = False,
    data_profile: Optional[str] = None,
):
    """High-level entry: perform metadata-only checks for each data item.

    Steps:
      1. Load + normalize spec (apply defaults, pick profile).
      2. Iterate data items, gather metadata without downloading bodies.
            3. Validate expected_size (within tolerance).
      4. Print a summary report.
    """
    spec_path = Path(data_spec)
    if not spec_path.is_file():
        print(f"[data:check] Spec file not found: {spec_path}")
        return

    try:
        profile_name, profile = verify_data_spec(
            data_spec=data_spec,
            backpack_root=backpack_root,
            requested_profile=data_profile,
            verbose=verbose,
            op_label="check",
        )
    except ValueError as e:
        print(f"[data:check] {e}")
        return

    items = profile.get("data", []) or []
    policy = profile.get("policy", {})
    tolerance = int(policy.get("size_tolerance_bytes", 0) or 0)
    if verbose:
        print(
            f"[data:check] data_profile: {profile_name} (items={len(items)}, size_tolerance={tolerance})"
        )

    normalized_items = items

    results: List[Dict[str, Any]] = []
    for item in normalized_items:
        result = _check_single_item(item, tolerance, backpack_root)
        results.append(result)

    _print_check_summary(results)
    if show_details or verbose:
        _print_detailed_results(results)


def fetch_data_from_spec(
    data_spec: str,
    backpack_root: Path | None,
    verbose: bool = False,
    force: bool = False,
    data_profile: Optional[str] = None,
):
    """Fetch (download/copy) all data items defined in the selected profile.

    Rules:
      * If backpack_root is None, infer as spec_path.parent.parent (grand-parent) to match
        expected structure: <backpack_root>/data/data.yml.
      * All relative sources (for fs) and target_path resolutions are relative to backpack_root.
      * multi source_type: iterate sources until first successful fetch.
      * For now, post_process is ignored (placeholder).
    """
    spec_path = Path(data_spec)
    if not spec_path.is_file():
        print(f"[data:fetch] Spec file not found: {spec_path}")
        return

    # Infer backpack_root if not provided
    if backpack_root is None:
        if spec_path.parent.name == "data":
            backpack_root = spec_path.parent.parent
        else:
            backpack_root = spec_path.parent
    backpack_root = Path(backpack_root).resolve()

    try:
        profile_name, profile = verify_data_spec(
            data_spec=data_spec,
            backpack_root=backpack_root,
            requested_profile=data_profile,
            verbose=verbose,
            op_label="fetch",
        )
    except ValueError as e:
        print(f"[data:fetch] {e}")
        return

    items = profile.get("data", []) or []
    if verbose:
        print(
            f"[data:fetch] data_profile '{profile_name}' items={len(items)} backpack_root={backpack_root}"
        )

    normalized_items = items

    total = len(normalized_items)
    for idx, item in enumerate(normalized_items, start=1):
        if verbose:
            print(
                f"[data:fetch] Fetching {idx}/{total}: {item.get('name','<unnamed>')} (force={force})"
            )
        _fetch_single_item(item, backpack_root, verbose=verbose, force=force)
        if verbose:
            print(
                f"[data:fetch] Finished {idx}/{total}: {item.get('name','<unnamed>')}"
            )

    if verbose:
        print("[data:fetch] Completed.")


def verify_data_from_spec(
    data_spec: str,
    backpack_root: Path | None,
    verbose: bool = False,
    force: bool = False,
    data_profile: Optional[str] = None,
):
    """Verify data items: ensure present (download/copy if needed) then validate integrity.

    Integrity signals supported:
      * checksum: (algorithm:hex) or plain hex (algorithm inferred by length)
      * expected_size (+ policy.size_tolerance_bytes)

    Produces a summary table and (if verbose) per-item details.
    """
    spec_path = Path(data_spec)
    if not spec_path.is_file():
        print(f"[data:verify] Spec file not found: {spec_path}")
        return

    if backpack_root is None:
        if spec_path.parent.name == "data":
            backpack_root = spec_path.parent.parent
        else:
            backpack_root = spec_path.parent
    backpack_root = Path(backpack_root).resolve()

    print(f"\n[data:verify] Using backpack_root: {backpack_root}\n")

    try:
        profile_name, profile = verify_data_spec(
            data_spec=data_spec,
            backpack_root=backpack_root,
            requested_profile=data_profile,
            verbose=verbose,
            op_label="verify",
        )
    except ValueError as e:
        print(f"[data:verify] {e}")
        return

    items = profile.get("data", []) or []
    policy = profile.get("policy", {})
    tolerance = int(policy.get("size_tolerance_bytes", 0) or 0)

    if verbose:
        print(
            f"[data:verify] data_profile '{profile_name}' items={len(items)} tolerance={tolerance} backpack_root={backpack_root}"
        )

    normalized_items = items

    results: List[Dict[str, Any]] = []
    total = len(normalized_items)
    for idx, item in enumerate(normalized_items, start=1):
        name = item.get("name", "<unnamed>")
        if verbose:
            print(f"[data:verify] Processing {idx}/{total}: {name} (force={force})")
        # Ensure fetched (may skip if exists and not force)
        chosen_source = _fetch_single_item(
            item, backpack_root, verbose=verbose, force=force
        )
        # Evaluate integrity on local target
        default_prefix = (
            (Path(backpack_root) / "workflow").resolve()
            if backpack_root
            else (Path.cwd() / "workflow").resolve()
        )
        target_path = _resolve_target_path(
            item, backpack_root, target_prefix=default_prefix
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

    _print_verify_summary(results)
    if verbose:
        _print_verify_details(results)


# --------------------------- Spec Preparation ---------------------------
def verify_data_spec(
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
    default_prefix: Optional[str] = None
    if backpack_root:
        default_prefix = str((Path(backpack_root) / "workflow").resolve())

    for item in data_list:
        it = _normalize_data_item(item)
        # default target_prefix if backpack_root provided and item missing it
        if default_prefix and not it.get("target_prefix"):
            it["target_prefix"] = default_prefix
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
    item: Dict[str, Any], tolerance: int, backpack_root: Path
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
    }


def _metadata_for_source(item: Dict[str, Any], backpack_root: Path) -> Dict[str, Any]:
    stype = item.get("source_type")
    src = item.get("source")
    if stype == "http":
        return http_file_metadata(src)
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
    item: Dict[str, Any], backpack_root: Path, target_prefix: Optional[Path] = None
) -> Path:
    """Resolve final target path for an item.

    Parameters:
      - item: data item dict (may contain target_path/target_location/name)
      - backpack_root: base backpack path (may be None-ish)
      - target_prefix: explicit prefix Path to use for relative targets. If None,
        defaults to <backpack_root>/workflow (or ./workflow when backpack_root is missing).

    Behavior:
      - Absolute target paths are returned as-is (resolved).
      - Relative targets are placed under `target_prefix/target`.
      - If `target_prefix` is relative, it is interpreted relative to `backpack_root`.
    """
    target_rel = item.get("target_location") or item.get("target_path")
    if not target_rel:
        raise ValueError("Missing required 'target_location' in data item")
    target_p = Path(target_rel)

    # Absolute -> return resolved absolute path
    if target_p.is_absolute():
        return target_p.resolve()

    # Choose prefix path: per-item target_prefix overrides function argument
    item_prefix = item.get("target_prefix")
    # Compute prefix path
    if item_prefix:
        prefix_p = Path(item_prefix)
        if not prefix_p.is_absolute():
            base = Path(backpack_root) if backpack_root else Path.cwd()
            prefix_p = (base / prefix_p).resolve()
    elif target_prefix:
        prefix_p = Path(target_prefix)
        if not prefix_p.is_absolute():
            base = Path(backpack_root) if backpack_root else Path.cwd()
            prefix_p = (base / prefix_p).resolve()
    else:
        base = Path(backpack_root) if backpack_root else Path.cwd()
        prefix_p = (base / "workflow").resolve()

    prefix_p.mkdir(parents=True, exist_ok=True)
    return (prefix_p / target_p).resolve()


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


def _fetch_single_item(
    item: Dict[str, Any],
    backpack_root: Path,
    verbose: bool = False,
    force: bool = False,
) -> Optional[Dict[str, Any]]:
    name = item.get("name", "<unnamed>")
    stype = item.get("source_type")
    default_prefix = (
        (Path(backpack_root) / "workflow").resolve()
        if backpack_root
        else Path.cwd() / "workflow"
    )
    target_path = _resolve_target_path(
        item, backpack_root, target_prefix=default_prefix
    )
    target_path.parent.mkdir(parents=True, exist_ok=True)

    if target_path.exists() and not force:
        if verbose:
            print(
                f"[data:fetch] Skipping '{name}' target exists: {target_path} (use --force-fetch to overwrite)"
            )
        return None
    elif target_path.exists() and force:
        if verbose:
            print(f"[data:fetch] Removing existing target for '{name}': {target_path}")
        if target_path.is_dir():
            import shutil

            shutil.rmtree(target_path)
        else:
            target_path.unlink()

    if stype == "multi":
        for src_entry in item.get("sources", []):
            s_norm = src_entry
            if verbose:
                print(
                    f"[data:fetch] Trying multi source for '{name}': type={s_norm.get('source_type')} source={s_norm.get('source')}"
                )
            if _attempt_fetch_source(
                s_norm, target_path, backpack_root, verbose=verbose, force=force
            ):
                if verbose:
                    print(
                        f"[data:fetch] '{name}' fetched via multi source type={s_norm.get('source_type')} -> {target_path}"
                    )
                return s_norm
        if verbose:
            print(f"[data:fetch] FAILED multi sources for '{name}'")
        return None

    if verbose:
        print(
            f"[data:fetch] Fetching '{name}' source_type={stype} source={item.get('source')} -> {target_path}"
        )
    if _attempt_fetch_source(
        item, target_path, backpack_root, verbose=verbose, force=force
    ):
        if verbose:
            print(f"[data:fetch] '{name}' fetched -> {target_path}")
        return item
    else:
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
        if stype == "pelican":
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
def _print_verify_summary(results: List[Dict[str, Any]]) -> None:
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


def _print_check_summary(results: List[Dict[str, Any]]) -> None:
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
    print(f"[data:check] Items: {total}, missing: {missing}, size_fail: {size_fail}")


def _print_detailed_results(results: List[Dict[str, Any]]) -> None:
    print("\n[data:check] Detailed item metadata:")
    for r in results:
        print(f"--- {r.get('name')} ({r.get('source_type')}) ---")
        print(f"  exists: {r.get('exists')}")
        print(f"  target_path: {r.get('target_path')}")
        print(f"  expected_size: {r.get('expected_size')}")
        print(
            f"  actual_size: {r.get('actual_size')} size_ok={r.get('size_ok')} note={r.get('size_note')}"
        )
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
