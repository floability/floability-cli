"""
Data operations for Floability CLI.
"""

from pathlib import Path
from ..data.data_handler import (
    check_data_from_spec,
    fetch_data_from_spec,
    verify_data_from_spec,
)


def resolve_data_spec(args):
    if args.data_spec and args.backpack:
        return
    if args.data_spec and not args.backpack:
        data_spec_path = Path(args.data_spec).resolve()
        if data_spec_path.parent.name == "data":
            args.backpack = str(data_spec_path.parent.parent)
            print(
                f"[floability] Resolved backpack_root from data spec: {args.backpack}"
            )
        else:
            args.backpack = str(data_spec_path.parent)
            print(
                f"[floability] Data spec is not in expected 'data' directory structure. Using parent as backpack_root: {args.backpack}"
            )
            return
    if args.backpack and not args.data_spec:
        backpack_dir = Path(args.backpack).resolve()
        data_spec = backpack_dir / "data" / "data.yml"
        if data_spec.is_file():
            args.data_spec = str(data_spec)
            print(f"[floability] Using data spec from backpack: {args.data_spec}")
        else:
            print(
                f"[floability] No data spec found in backpack at expected location: {data_spec}"
            )
        return


def run_data_command(args):
    """Run data command and return success status.
    
    Returns:
        bool: True if the data operation succeeded, False otherwise.
    """
    print(f"[floability] Running data command in mode: {args.mode}")
    resolve_data_spec(args)
    if not args.data_spec:
        print("[floability] No data spec provided. Cannot proceed with data command.")
        return False
    
    success = False
    
    if args.mode == "check":
        print(
            "[floability] 'data check' selected — metadata-only checks (existence, size, file type)."
        )
        success = check_data_from_spec(
            args.data_spec,
            Path(args.backpack),
            show_details=getattr(args, "check_details", False),
            verbose=getattr(args, "verbose", False),
            data_profile=getattr(args, "data_profile", None),
            data_cache_mode=getattr(args, "data_cache_mode", "off"),
            base_dir=Path(getattr(args, "base_dir", ".")) if hasattr(args, "base_dir") else Path.cwd(),
        )
    elif args.mode == "fetch":
        print(f"[floability] Fetching data from {args.data_spec}")
        success = fetch_data_from_spec(
            args.data_spec,
            Path(args.backpack) if args.backpack else None,
            verbose=getattr(args, "verbose", False),
            force=getattr(args, "force_fetch", False),
            data_profile=getattr(args, "data_profile", None),
            data_cache_mode=getattr(args, "data_cache_mode", "off"),
            force_data_cache=getattr(args, "force_data_cache", False),
            base_dir=Path(getattr(args, "base_dir", ".")) if hasattr(args, "base_dir") else Path.cwd(),
        )
    elif args.mode == "verify":
        print(
            "[floability] 'data verify' selected — download + integrity checks (checksum/size/content-type)."
        )
        success = verify_data_from_spec(
            args.data_spec,
            Path(args.backpack) if args.backpack else None,
            verbose=getattr(args, "verbose", False),
            force=getattr(args, "force_fetch", False),
            data_profile=getattr(args, "data_profile", None),
            data_cache_mode=getattr(args, "data_cache_mode", "off"),
            force_data_cache=getattr(args, "force_data_cache", False),
            base_dir=Path(getattr(args, "base_dir", ".")) if hasattr(args, "base_dir") else Path.cwd(),
        )
    
    # Print final status
    if success:
        print(f"\n[floability] Data {args.mode} operation completed successfully")
    else:
        print(f"\n[floability] Data {args.mode} operation FAILED")
    
    return success
