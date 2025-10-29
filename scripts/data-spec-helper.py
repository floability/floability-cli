#!/usr/bin/env python3
"""
Generate a Floability data spec (data.yml) from a directory of local files.

Features:
- Scans a directory (optionally recursively) and creates one data item per file
- Computes expected_size and checksum (sha256|md5|none)
- Configurable source scheme (fs paths or backpack:// relative paths)
- Defaults optimized for local testing:
	* verification_type=strict
	* fs sources are relative to the parent of input_dir (e.g., "data/file.csv")
	* target_location preserves the directory (relative to parent of input_dir)
	* policy includes run_operation=fetch and timeout=30 seconds (configurable)
- Configurable target placement: basename | relative (includes dir) | absolute
- Emits a spec using the new 'data_profiles' schema

Examples:
	# Minimal: generate to stdout, using fs relative sources and relative targets (includes dir)
	python scripts/data-spec-helper.py ./example/data-spec-test/data

  # Strict verification with sha256 checksums, write to file
  python scripts/data-spec-helper.py ./example/data-spec-test/data \
	--output ./example/data-spec-test/data/workflow/data.generated.yml \
	--verification-type strict --checksum-alg sha256

  # Use backpack:// sources relative to a backpack_root, and preserve relative path as target_location
  python scripts/data-spec-helper.py ./example/data-spec-test/data \
	--source-scheme backpack --backpack-root ./example/data-spec-test \
	--target-mode relative

	# Duplicate profiles for other source types (sources left empty, source_type set when supported)
	python scripts/data-spec-helper.py ./example/data-spec-test/data \
		--duplicate-profiles pelican,http,s3
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional
import hashlib
import yaml


def compute_checksum(
    path: Path, alg: str = "sha256", chunk_size: int = 1024 * 1024
) -> str:
    h = hashlib.new(alg)
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def list_files(root: Path, recursive: bool) -> List[Path]:
    if recursive:
        return [p for p in root.rglob("*") if p.is_file()]
    return [p for p in root.iterdir() if p.is_file()]


def build_items(
    files: List[Path],
    input_dir: Path,
    *,
    source_scheme: str = "fs",
    backpack_root: Optional[Path] = None,
    target_mode: str = "relative",
    target_dir: Optional[Path] = None,
    include_expected_size: bool = True,
    checksum_alg: str = "sha256",
    fs_absolute: bool = False,
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []

    if source_scheme not in {"fs", "backpack"}:
        raise ValueError("source_scheme must be one of: fs, backpack")
    if source_scheme == "backpack" and not backpack_root:
        raise ValueError("--backpack-root is required when --source-scheme backpack")

    if target_mode not in {"basename", "relative", "absolute"}:
        raise ValueError("target_mode must be one of: basename, relative, absolute")
    if target_mode == "absolute" and not target_dir:
        raise ValueError("--target-dir is required when --target-mode absolute")

    parent_base = input_dir.parent.resolve()
    for f in files:
        rel = f.relative_to(input_dir)
        rel_parent = f.resolve().relative_to(parent_base)

        # source
        if source_scheme == "fs":
            if fs_absolute:
                source = str(f.resolve())
            else:
                # relative to parent of input_dir, e.g., "data/filename"
                source = str(rel_parent)
        else:  # backpack
            # derive path relative to backpack_root; prefix with backpack://
            try:
                rel_to_backpack = f.resolve().relative_to(Path(backpack_root).resolve())
            except Exception:
                # If file isn't under backpack_root, fall back to name
                rel_to_backpack = f.name
            source = f"backpack://{rel_to_backpack}"

        # target_location
        if target_mode == "basename":
            target_location = rel.name
        elif target_mode == "relative":
            # include directory relative to parent of input_dir
            target_location = str(rel_parent)
        else:  # absolute
            target_location = str((Path(target_dir) / rel).resolve())

        item: Dict[str, Any] = {
            "name": rel.name,
            "source": source,
            "target_location": target_location,
        }

        if include_expected_size:
            item["expected_size"] = f.stat().st_size

        if checksum_alg and checksum_alg.lower() != "none":
            hexval = compute_checksum(f, checksum_alg.lower())
            item["checksum"] = f"{checksum_alg.lower()}:{hexval}"

        items.append(item)

    return items


def build_spec(
    items: List[Dict[str, Any]],
    *,
    profile_name: str = "local",
    default_profile: Optional[str] = None,
    verification_type: str = "strict",
    size_tolerance_bytes: int = 0,
    timeout: int = 30,
    duplicate_profiles: Optional[List[str]] = None,
) -> Dict[str, Any]:
    profile: Dict[str, Any] = {
        "policy": {
            "verification_type": verification_type,
            "size_tolerance_bytes": int(size_tolerance_bytes),
            "run_operation": "fetch",
            "timeout": int(timeout),
        },
        "data": items,
    }

    # Put default_profile first for readability
    profiles_map: Dict[str, Any] = {profile_name: profile}
    # Handle duplicate profiles for requested source types
    if duplicate_profiles:
        SUPPORTED = {"http", "pelican", "backpack", "fs", "multi"}
        for raw in duplicate_profiles:
            stype = (raw or "").strip().lower()
            if not stype:
                continue
            dup_items: List[Dict[str, Any]] = []
            for it in items:
                # Rebuild item to control key order: name, source, source_type, target_location, expected_size, checksum
                new: Dict[str, Any] = {}
                new["name"] = it.get("name")
                new["source"] = ""
                new["source_type"] = stype if stype in SUPPORTED else ""
                new["target_location"] = it.get("target_location")
                if "expected_size" in it:
                    new["expected_size"] = it["expected_size"]
                if "checksum" in it:
                    new["checksum"] = it["checksum"]
                dup_items.append(new)
            # Rename duplicate profile as '<source_type>-data'
            dup_profile_name = f"{stype}-data"
            profiles_map[dup_profile_name] = {
                "policy": {
                    "verification_type": verification_type,
                    "size_tolerance_bytes": int(size_tolerance_bytes),
                    "run_operation": "fetch",
                    "timeout": int(timeout),
                },
                "data": dup_items,
            }

    spec: Dict[str, Any] = {
        "default_profile": default_profile or profile_name,
        "data_profiles": profiles_map,
    }
    return spec


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate Floability data spec from a directory of files"
    )
    p.add_argument("input_dir", type=str, help="Directory containing files to include")
    p.add_argument(
        "--output",
        "-o",
        type=str,
        default="-",
        help="Output path for YAML (default: stdout)",
    )
    p.add_argument(
        "--recursive",
        action="store_true",
        default=True,
        help="Recurse into subdirectories",
    )

    # Source options
    p.add_argument(
        "--source-scheme",
        choices=["fs", "backpack"],
        default="fs",
        help="How to express sources",
    )
    p.add_argument(
        "--backpack-root",
        type=str,
        help="Backpack root used to compute backpack:// relative paths",
    )

    # Target options
    p.add_argument(
        "--target-mode",
        choices=["basename", "relative", "absolute"],
        default="relative",
        help="How to set target_location (relative includes directory relative to parent of input_dir)",
    )
    p.add_argument(
        "--target-dir", type=str, help="Base output dir when --target-mode absolute"
    )

    # Verification/policy
    p.add_argument(
        "--checksum-alg",
        choices=["sha256", "md5", "none"],
        default="sha256",
        help="Checksum algorithm to include",
    )
    p.add_argument(
        "--no-expected-size",
        action="store_true",
        help="Do not include expected_size field",
    )
    p.add_argument(
        "--verification-type",
        choices=["size_only", "strict"],
        default="strict",
        help="Profile verification policy",
    )
    p.add_argument(
        "--size-tolerance-bytes",
        type=int,
        default=0,
        help="Policy size_tolerance_bytes",
    )
    p.add_argument(
        "--fs-absolute",
        action="store_true",
        help="Use absolute paths for fs sources (default: relative to parent of input_dir)",
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Policy timeout in seconds (default: 30)",
    )
    # Duplicates
    p.add_argument(
        "--duplicate-profiles",
        type=str,
        help="Comma-separated list of source types to duplicate profile for (e.g., pelican,http,s3)",
    )

    # Profiles
    p.add_argument(
        "--profile-name",
        type=str,
        default="profile-0",
        help="Name for generated profile",
    )
    p.add_argument(
        "--default-profile",
        type=str,
        help="default_profile at top-level (defaults to profile-name)",
    )

    p.add_argument(
        "--verbose", "-v", action="store_true", help="Verbose logging to stderr"
    )
    return p.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)

    input_dir = Path(args.input_dir).resolve()
    if not input_dir.is_dir():
        print(
            f"error: input_dir not found or not a directory: {input_dir}",
            file=sys.stderr,
        )
        return 2

    files = list_files(input_dir, recursive=args.recursive)
    if args.verbose:
        print(f"[helper] files found: {len(files)} from {input_dir}", file=sys.stderr)

    backpack_root = Path(args.backpack_root).resolve() if args.backpack_root else None
    target_dir = Path(args.target_dir).resolve() if args.target_dir else None

    items = build_items(
        files,
        input_dir,
        source_scheme=args.source_scheme,
        backpack_root=backpack_root,
        target_mode=args.target_mode,
        target_dir=target_dir,
        include_expected_size=not args.no_expected_size,
        checksum_alg=args.checksum_alg,
        fs_absolute=args.fs_absolute,
    )

    spec = build_spec(
        items,
        profile_name=args.profile_name,
        default_profile=args.default_profile,
        verification_type=args.verification_type,
        size_tolerance_bytes=args.size_tolerance_bytes,
        timeout=args.timeout,
        duplicate_profiles=(
            [s.strip() for s in args.duplicate_profiles.split(",")]
            if args.duplicate_profiles
            else None
        ),
    )

    out_yaml = yaml.safe_dump(spec, sort_keys=False)

    if args.output in (None, "", "-"):
        print(out_yaml)
    else:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(out_yaml, encoding="utf-8")
        if args.verbose:
            print(f"[helper] wrote spec to {out_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
