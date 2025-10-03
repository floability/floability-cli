from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, Iterable, List, Tuple, Optional
import yaml
import hashlib

# Reuse existing low-level helpers
from .http_file_utils import http_file_metadata
from .pelican_file_utils import pelican_file_metadata
from .fs_file_utils import fs_file_metadata


# --------------------------- Public API (stubs for now) ---------------------------
def check_data_spec(data_spec: str, backpack_root: Path, show_details: bool = False):
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

    print(f"[data:check] Profile: {profile_name} (items={len(items)}, size_tolerance={tolerance})")

    normalized_items = [_normalize_item(i) for i in items]

    results: List[Dict[str, Any]] = []
    for item in normalized_items:
        result = _check_single_item(item, tolerance, backpack_root)
        results.append(result)

    _print_check_summary(results)
    if show_details:
        _print_detailed_results(results)


def fetch_data_from_spec(data_spec: str, backpack_root: Path):
    """Placeholder fetch implementation (will implement later)."""
    print(f"[data:fetch] Not yet implemented for spec: {data_spec}")


def verify_data_from_spec(data_spec: str, backpack_root: Path):
    """Placeholder verify implementation (will implement later)."""
    print(f"[data:verify] Not yet implemented for spec: {data_spec}")


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
    # Copy to avoid mutating caller
    out = dict(item)
    out.setdefault("name", "<unnamed>")

    # Infer source_type for multi or by scheme
    if "source_type" not in out or not out["source_type"]:
        if "sources" in out:
            out["source_type"] = "multi"
        else:
            src = out.get("source", "")
            if src.startswith("http://") or src.startswith("https://"):
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
    if stype == "fs":
        # Interpret relative paths as relative to backpack_root unless absolute
        p = Path(src)
        if not p.is_absolute():
            p = (Path(backpack_root) / p).resolve()
        return fs_file_metadata(str(p))
    # Unknown or missing
    return {"exists": False, "name": src or "", "size": None, "type": None, "raw": {"error": f"unsupported source_type {stype}"}}


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
