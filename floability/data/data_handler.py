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
def check_data_spec(data_spec: str, backpack_root: Path, show_details: bool = False, verbose: bool = False):
    """High-level entry: perform metadata-only checks for each data item.

    Steps:
      1. Load + normalize spec (apply defaults, pick profile).
      2. Iterate data items, gather metadata without downloading bodies.
      3. Validate expected_size (within tolerance) and content_type (best-effort).
      4. Print a summary report.
    """
    spec_path = Path(data_spec)
    if not spec_path.is_file():
        print(f"[data:check] Spec file not found: {spec_path}")
        return

    try:
        raw = _load_yaml(spec_path)
    except Exception as e:
        print(f"[data:check] Failed loading YAML: {e}")
        return

    try:
        profile_name, profile, global_defaults = _select_profile(raw)
    except ValueError as e:
        print(f"[data:check] {e}")
        return

    items = profile.get("data", []) or []
    policy = profile.get("policy", {})
    tolerance = int(policy.get("size_tolerance_bytes", 0) or 0)

    if verbose:
        print(f"[data:check] Profile: {profile_name} (items={len(items)}, size_tolerance={tolerance})")

    normalized_items = [_normalize_item(i) for i in items]

    results: List[Dict[str, Any]] = []
    for item in normalized_items:
        result = _check_single_item(item, tolerance, backpack_root)
        results.append(result)

    _print_check_summary(results)
    if show_details or verbose:
        _print_detailed_results(results)


def fetch_data_from_spec(data_spec: str, backpack_root: Path | None, verbose: bool = False, force: bool = False):
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

    try:
        raw = _load_yaml(spec_path)
    except Exception as e:
        print(f"[data:fetch] Failed loading YAML: {e}")
        return

    try:
        profile_name, profile, _ = _select_profile(raw)
    except ValueError as e:
        print(f"[data:fetch] {e}")
        return

    items = profile.get("data", []) or []
    if verbose:
        print(f"[data:fetch] Profile '{profile_name}' items={len(items)} backpack_root={backpack_root}")

    normalized_items = [_normalize_item(i) for i in items]

    total = len(normalized_items)
    for idx, item in enumerate(normalized_items, start=1):
        if verbose:
            print(f"[data:fetch] Fetching {idx}/{total}: {item.get('name','<unnamed>')} (force={force})")
        _fetch_single_item(item, backpack_root, verbose=verbose, force=force)
        if verbose:
            print(f"[data:fetch] Finished {idx}/{total}: {item.get('name','<unnamed>')}")

    if verbose:
        print("[data:fetch] Completed.")


def verify_data_from_spec(data_spec: str, backpack_root: Path | None, verbose: bool = False, force: bool = False):
    """Verify data items: ensure present (download/copy if needed) then validate integrity.

    Integrity signals supported:
      * checksum: (algorithm:hex) or plain hex (algorithm inferred by length)
      * expected_size (+ policy.size_tolerance_bytes)
      * content_type (best-effort using remote metadata as in check mode)

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
        raw = _load_yaml(spec_path)
    except Exception as e:
        print(f"[data:verify] Failed loading YAML: {e}")
        return

    try:
        profile_name, profile, _ = _select_profile(raw)
    except ValueError as e:
        print(f"[data:verify] {e}")
        return

    items = profile.get("data", []) or []
    policy = profile.get("policy", {})
    tolerance = int(policy.get("size_tolerance_bytes", 0) or 0)

    if verbose:
        print(f"[data:verify] Profile '{profile_name}' items={len(items)} tolerance={tolerance} backpack_root={backpack_root}")

    normalized_items = [_normalize_item(i) for i in items]

    results: List[Dict[str, Any]] = []
    total = len(normalized_items)
    for idx, item in enumerate(normalized_items, start=1):
        name = item.get("name", "<unnamed>")
        if verbose:
            print(f"[data:verify] Processing {idx}/{total}: {name} (force={force})")
        # Ensure fetched (may skip if exists and not force)
        chosen_source = _fetch_single_item(item, backpack_root, verbose=verbose, force=force)
        # Evaluate integrity on local target
        default_prefix = (Path(backpack_root) / "workflow").resolve() if backpack_root else (Path.cwd() / "workflow").resolve()
        target_path = _resolve_target_path(item, backpack_root, target_prefix=default_prefix)
        local_exists = target_path.exists()
        is_dir = target_path.is_dir() if local_exists else False

        expected_size = item.get("expected_size")
        actual_size = target_path.stat().st_size if (local_exists and target_path.is_file()) else None
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

        # Remote metadata (for content_type) – reuse logic (best-effort)
        remote_meta = _metadata_for_source(item if item.get('source_type') != 'multi' else (chosen_source or item), backpack_root)
        expected_ct = item.get("content_type")
        content_type_ok = None
        content_type_actual = remote_meta.get("type")
        if expected_ct and content_type_actual:
            ct_actual = str(content_type_actual)
            content_type_ok = ct_actual.startswith(expected_ct) or ct_actual == expected_ct

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
                    checksum_ok = (checksum_actual == checksum_expected)
                except Exception as e:
                    checksum_ok = False
                    if verbose:
                        print(f"[data:verify] Error computing checksum for '{name}': {e}")

        results.append({
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
            "content_type_expected": expected_ct,
            "content_type_actual": content_type_actual,
            "content_type_ok": content_type_ok,
        })
        if verbose:
            print(f"[data:verify] Finished {idx}/{total}: {name} exists={local_exists} size_ok={size_ok} checksum_ok={checksum_ok} ct_ok={content_type_ok}")

    _print_verify_summary(results)
    if verbose:
        _print_verify_details(results)


# --------------------------- Parsing / Normalization ---------------------------
def _load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _select_profile(raw: Dict[str, Any]) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
    profiles = raw.get("profiles")
    if not profiles or not isinstance(profiles, dict):
        raise ValueError("Spec missing 'profiles' mapping")

    default_profile = raw.get("default_profile") or next(iter(profiles.keys()))
    profile = profiles.get(default_profile)
    if profile is None:
        raise ValueError(f"Profile '{default_profile}' not found in spec")

    return default_profile, profile, {}


def _normalize_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Return a shallow-normalized copy of a data item.

    Normalization performed here is intentionally small and conservative:
      - ensure a `name` exists (defaults to "<unnamed>")
      - infer a `source_type` when the field is missing or falsy using simple
        heuristics (multi, http, pelican/osdf, fs, unknown)

    This function is the single place the rest of the pipeline calls to get a
    predictable item shape. Callers still normalize nested `sources` when
    iterating multi-source items, so this function keeps the contract minimal.

    TODO: add support for additional default population
    """

    # Copy to avoid mutating caller
    out = dict(item)
    out.setdefault("name", "<unnamed>")

    # Infer source_type for multi or by scheme
    if "source_type" not in out or not out["source_type"]:
        if "sources" in out:
            out["source_type"] = "multi"
        else:
            src = out.get("source", "")
            # coerce to string to avoid errors when Path objects are used
            src = str(src) if src is not None else ""
            # Allow an explicit lightweight scheme for backpack sources:
            # e.g. 'backpack://data/foo.csv' -> source_type 'backpack' and
            # source 'data/foo.csv' (the code that resolves backpack paths
            # will join this relative path to the provided backpack_root).
            if src.startswith("backpack://"):
                out["source_type"] = "backpack"
                out["source"] = src[len("backpack://") :]
            elif src.startswith("http://") or src.startswith("https://"):
                out["source_type"] = "http"
            elif src.startswith("osdf://") or src.startswith("pelican://"):
                out["source_type"] = "pelican"
            elif src:
                out["source_type"] = "fs"  # fallback local path
            else:
                out["source_type"] = "unknown"

    return out


# --------------------------- Item Checking Logic ---------------------------
def _check_single_item(item: Dict[str, Any], tolerance: int, backpack_root: Path) -> Dict[str, Any]:
    name = item.get("name", "<unnamed>")
    stype = item.get("source_type")
    expected_size = item.get("expected_size")
    content_type = item.get("content_type")

    # For output path (target_path) relative to backpack root
    target_rel = item.get("target_path") or item.get("target_location")

    # Multi-source: pick first successful metadata
    meta_chain: List[Dict[str, Any]] = []
    if stype == "multi":
        sources = item.get("sources", [])
        for s in sources:
            s_norm = _normalize_item(s)
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

    content_type_ok = None
    if content_type and meta.get("type"):
        # Simple 'startswith' heuristic for MIME supertype
        ct_actual = str(meta.get("type"))
        content_type_ok = ct_actual.startswith(content_type) or ct_actual == content_type

    return {
        "name": name,
        "source_type": stype,
        "target_path": target_rel,
        "expected_size": expected_size,
        "actual_size": actual_size,
        "size_ok": size_ok,
        "size_note": size_note,
        "content_type_expected": content_type,
        "content_type_actual": meta.get("type"),
        "content_type_ok": content_type_ok,
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
    return {"exists": False, "name": src or "", "size": None, "type": None, "raw": {"error": f"unsupported source_type {stype}"}}


# --------------------------- Fetch Logic ---------------------------
def _resolve_target_path(item: Dict[str, Any], backpack_root: Path, target_prefix: Optional[Path] = None) -> Path:
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
    target_rel = item.get("target_path") or item.get("target_location") or item.get("name")
    target_p = Path(target_rel)

    # Absolute -> return resolved absolute path
    if target_p.is_absolute():
        return target_p.resolve()

    # Compute prefix path
    if target_prefix:
        prefix_p = Path(target_prefix)
        if not prefix_p.is_absolute():
            base = Path(backpack_root) if backpack_root else Path.cwd()
            prefix_p = (base / prefix_p).resolve()
    else:
        base = Path(backpack_root) if backpack_root else Path.cwd()
        prefix_p = (base / "workflow").resolve()

    prefix_p.mkdir(parents=True, exist_ok=True)
    return (prefix_p / target_p).resolve()


def _fetch_single_item(item: Dict[str, Any], backpack_root: Path, verbose: bool = False, force: bool = False) -> Optional[Dict[str, Any]]:
    name = item.get("name", "<unnamed>")
    stype = item.get("source_type")
    default_prefix = (Path(backpack_root) / "workflow").resolve() if backpack_root else Path.cwd() / "workflow"
    target_path = _resolve_target_path(item, backpack_root, target_prefix=default_prefix)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    if target_path.exists() and not force:
        if verbose:
            print(f"[data:fetch] Skipping '{name}' target exists: {target_path} (use --force-fetch to overwrite)")
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
            s_norm = _normalize_item(src_entry)
            if verbose:
                print(f"[data:fetch] Trying multi source for '{name}': type={s_norm.get('source_type')} source={s_norm.get('source')}")
            if _attempt_fetch_source(s_norm, target_path, backpack_root, verbose=verbose, force=force):
                if verbose:
                    print(f"[data:fetch] '{name}' fetched via multi source type={s_norm.get('source_type')} -> {target_path}")
                return s_norm
        if verbose:
            print(f"[data:fetch] FAILED multi sources for '{name}'")
        return None

    if verbose:
        print(f"[data:fetch] Fetching '{name}' source_type={stype} source={item.get('source')} -> {target_path}")
    if _attempt_fetch_source(item, target_path, backpack_root, verbose=verbose, force=force):
        if verbose:
            print(f"[data:fetch] '{name}' fetched -> {target_path}")
        return item
    else:
        if verbose:
            print(f"[data:fetch] FAILED '{name}'")
    return None


def _attempt_fetch_source(item: Dict[str, Any], target_path: Path, backpack_root: Path, verbose: bool = False, force: bool = False) -> bool:
    stype = item.get("source_type")
    src = item.get("source")
    try:
        if stype == "http":
            # Download into target directory with final name
            http_file_download(src, dest_dir=str(target_path.parent), filename=target_path.name, overwrite=force)
            return True
        if stype == "pelican":
            pelican_file_download(src, dest_dir=str(target_path.parent), filename=target_path.name, overwrite=force)
            return True
        if stype == "fs":
            p = Path(src)
            if not p.is_absolute():
                p = (backpack_root / p).resolve()
            if not p.exists():
                if verbose:
                    print(f"[data:fetch] Source missing (fs): {p}")
                return False
            # copy file or directory
            if p.is_file():
                fs_file_copy(str(p), dest_dir=str(target_path.parent), filename=target_path.name, overwrite=force)
            else:
                # directory copy simple recursive
                import shutil
                if force and target_path.exists():
                    shutil.rmtree(target_path)
                shutil.copytree(p, target_path, dirs_exist_ok=True)
            return True
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
    headers = ["name", "exists", "size_ok", "checksum_ok", "content_type_ok", "expected_size", "actual_size", "checksum_alg"]
    colw = {h: max(len(h), *(len(str(r.get(h, ''))) for r in results)) for h in headers} if results else {h: len(h) for h in headers}
    def fmt_row(r: Dict[str, Any]):
        return " ".join(str(r.get(h, "")).ljust(colw[h]) for h in headers)
    print(fmt_row({h: h for h in headers}))
    for r in results:
        print(fmt_row(r))
    total = len(results)
    missing = sum(1 for r in results if not r.get("exists"))
    size_fail = sum(1 for r in results if r.get("size_ok") is False)
    checksum_fail = sum(1 for r in results if r.get("checksum_ok") is False)
    ctype_fail = sum(1 for r in results if r.get("content_type_ok") is False)
    print(f"[data:verify] Items: {total}, missing: {missing}, size_fail: {size_fail}, checksum_fail: {checksum_fail}, content_type_fail: {ctype_fail}")


def _print_verify_details(results: List[Dict[str, Any]]) -> None:
    print("\n[data:verify] Detailed results:")
    for r in results:
        print(f"--- {r.get('name')} ---")
        print(f"  target_path: {r.get('target_path')}")
        print(f"  exists: {r.get('exists')} is_dir={r.get('is_dir')}")
        print(f"  expected_size: {r.get('expected_size')} actual_size: {r.get('actual_size')} size_ok={r.get('size_ok')} note={r.get('size_note')}")
        print(f"  checksum_alg: {r.get('checksum_alg')} checksum_expected: {r.get('checksum_expected')} checksum_actual: {r.get('checksum_actual')} checksum_ok={r.get('checksum_ok')}")
        print(f"  content_type_expected: {r.get('content_type_expected')} content_type_actual: {r.get('content_type_actual')} content_type_ok={r.get('content_type_ok')}")
    print("[data:verify] End of detailed report")


def _print_check_summary(results: List[Dict[str, Any]]) -> None:
    print("[data:check] Summary:")
    headers = ["name", "source_type", "exists", "size_ok", "content_type_ok", "expected_size", "actual_size", "size_note"]
    # Simple column widths
    colw = {h: max(len(h), *(len(str(r.get(h, ''))) for r in results)) for h in headers}
    def fmt_row(r: Dict[str, Any]):
        return " ".join(str(r.get(h, "")).ljust(colw[h]) for h in headers)
    print(fmt_row({h: h for h in headers}))
    for r in results:
        print(fmt_row(r))
    # Basic counts
    total = len(results)
    missing = sum(1 for r in results if not r.get("exists"))
    size_fail = sum(1 for r in results if r.get("size_ok") is False)
    ctype_fail = sum(1 for r in results if r.get("content_type_ok") is False)
    print(f"[data:check] Items: {total}, missing: {missing}, size_fail: {size_fail}, content_type_fail: {ctype_fail}")


def _print_detailed_results(results: List[Dict[str, Any]]) -> None:
    print("\n[data:check] Detailed item metadata:")
    for r in results:
        print(f"--- {r.get('name')} ({r.get('source_type')}) ---")
        print(f"  exists: {r.get('exists')}")
        print(f"  target_path: {r.get('target_path')}")
        print(f"  expected_size: {r.get('expected_size')}")
        print(f"  actual_size: {r.get('actual_size')} size_ok={r.get('size_ok')} note={r.get('size_note')}")
        print(f"  content_type_expected: {r.get('content_type_expected')}")
        print(f"  content_type_actual: {r.get('content_type_actual')} content_type_ok={r.get('content_type_ok')}")
        meta = r.get('meta', {})
        # Limit headers/raw to avoid huge dumps
        raw = meta.get('raw') if isinstance(meta, dict) else None
        if isinstance(raw, dict):
            # show a few important raw keys if present
            interesting = {k: raw[k] for k in ('status','final_url','error','headers') if k in raw}
            if 'headers' in interesting and isinstance(interesting['headers'], dict):
                # trim headers list
                interesting['headers'] = {k: interesting['headers'][k] for k in list(interesting['headers'].keys())[:8]}
            if interesting:
                print(f"  raw: {interesting}")
        if r.get('multi_chain'):
            print("  multi attempts:")
            for attempt in r['multi_chain']:
                a_name = attempt.get('name') or attempt.get('raw', {}).get('final_url') or '<source>'
                print(f"    - exists={attempt.get('exists')} size={attempt.get('size')} type={attempt.get('type')} name={attempt.get('name')}")
    print("[data:check] End of detailed report")
