"""
Data operations for Floability CLI.
"""

import uuid
from datetime import datetime
from pathlib import Path
import os
from ..data.data_handler import (
    check_data_from_spec,
    fetch_data_from_spec,
    verify_data_from_spec,
)
from ..utils import normalize_cli_base_dir


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

    For fetch and verify operations, creates an instance (or uses existing --instance)
    to materialize data into instance/workflow directory.

    For check operation, no instance is required (metadata-only checks).

    Returns:
        bool: True if the data operation succeeded, False otherwise.
    """
    print(f"[floability] Running data command in mode: {args.mode}")
    resolve_data_spec(args)
    if not args.data_spec:
        print("[floability] No data spec provided. Cannot proceed with data command.")
        return False

    # Determine and normalize base_dir (CLI behavior):
    # If user did not provide a base_dir (or provided '.'), default to ~/floability-base-dir
    raw_base = getattr(args, "base_dir", None) if hasattr(args, "base_dir") else None
    base_dir = normalize_cli_base_dir(raw_base)

    # Determine data cache directory: allow CLI override, else use base_dir/floability-data-cache
    raw_cache_override = getattr(args, "data_cache_dir", None) if hasattr(args, "data_cache_dir") else None
    if raw_cache_override:
        cache_base_dir = Path(os.path.expanduser(raw_cache_override)).resolve()
        try:
            cache_base_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
    else:
        cache_base_dir = (base_dir / "floability-data-cache").resolve()
        try:
            cache_base_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    # Enable data cache by default for all operations
    data_cache_mode = getattr(args, "data_cache_mode", "symlink")
    if data_cache_mode == "off":
        # Override 'off' to use symlink by default
        data_cache_mode = "symlink"
        print("[floability] Enabling data cache (mode: symlink)")

    # Get backpack_root for source resolution
    backpack_root = Path(args.backpack) if args.backpack else None

    success = False

    if args.mode == "check":
        # Check is metadata-only, no instance needed
        print(
            "[floability] 'data check' selected — metadata-only checks (existence, size, file type)."
        )
        success = check_data_from_spec(
            args.data_spec,
            backpack_root or Path.cwd(),
            show_details=getattr(args, "check_details", False),
            verbose=getattr(args, "verbose", False),
            data_profile=getattr(args, "data_profile", None),
            data_cache_mode=data_cache_mode,
            base_dir=base_dir,
            cache_base_dir=cache_base_dir,
            target_root=None,  # Not needed for check
        )
    elif args.mode in ("fetch", "verify"):
        # Fetch and verify require instance for data materialization
        instance_root = None
        target_root = None

        # Check if --instance provided
        if getattr(args, "instance", None):
            # Use existing instance
            from ..instance_registry import resolve_instance
            resolved = resolve_instance(args.instance)
            if not resolved:
                print(f"[floability] Error: instance reference not found: {args.instance}")
                return False
            instance_root = Path(resolved)
            target_root = instance_root / "workflow"
            print(f"[floability] Using existing instance: {instance_root}")
        else:
            # Create new instance for data operation
            print("[floability] No --instance provided, creating new instance for data operation")
            
            # Ensure manager name
            if getattr(args, "manager_name", None) is None:
                args.manager_name = f"floability-data-{uuid.uuid4()}"
            
            # Prepare minimal instance (no notebook/script required for data-only)
            # We don't validate backpack structure for data-only operations
            try:
                from ..instance_manager import create_instance_structure, create_latest_symlink
                
                instance_paths = create_instance_structure(
                    str(base_dir),
                    prefix="floability_data_instance"
                )
                instance_root = instance_paths["root"]
                target_root = instance_paths["workflow"]
                create_latest_symlink(
                    str(base_dir),
                    str(instance_root)
                )
                print(f"[floability] Created instance for data operation: {instance_root}")
                
                # Record minimal metadata
                try:
                    from ..instance_metadata import update_instance_metadata
                    metadata_file = instance_paths["metadata"] / "run.json"
                    initial_meta = {
                        "schema_version": "1.0",
                        "instance_id": instance_root.name,
                        "instance_path": str(instance_root.resolve()),
                        "created_at": datetime.utcnow().isoformat() + "Z",
                        "execution_mode": "data",
                        "manager_name": args.manager_name,
                        "data": {
                            "spec_path": str(args.data_spec),
                            "profile": getattr(args, "data_profile", None),
                            "cache_mode": data_cache_mode,
                        },
                    }
                    update_instance_metadata(metadata_file, initial_meta, merge=False)
                except Exception as e:
                    print(f"[floability] Warning: Could not record metadata: {e}")
                    
            except Exception as e:
                print(f"[floability] Error creating instance: {e}")
                import traceback
                traceback.print_exc()
                return False

        # Execute data operation with target_root
        if args.mode == "fetch":
            print(f"[floability] Fetching data from {args.data_spec}")
            success = fetch_data_from_spec(
                args.data_spec,
                backpack_root,
                verbose=getattr(args, "verbose", False),
                force=getattr(args, "force_fetch", False),
                data_profile=getattr(args, "data_profile", None),
                data_cache_mode=data_cache_mode,
                force_data_cache=getattr(args, "force_data_cache", False),
                base_dir=base_dir,
                cache_base_dir=cache_base_dir,
                target_root=target_root,
            )
        elif args.mode == "verify":
            print(
                "[floability] 'data verify' selected — download + integrity checks (checksum/size/content-type)."
            )
            success = verify_data_from_spec(
                args.data_spec,
                backpack_root,
                verbose=getattr(args, "verbose", False),
                force=getattr(args, "force_fetch", False),
                data_profile=getattr(args, "data_profile", None),
                data_cache_mode=data_cache_mode,
                force_data_cache=getattr(args, "force_data_cache", False),
                base_dir=base_dir,
                cache_base_dir=cache_base_dir,
                target_root=target_root,
            )

        if success and instance_root:
            print(f"[floability] Data materialized into: {target_root}")

    # Print final status
    if success:
        print(f"\n[floability] Data {args.mode} operation completed successfully")
    else:
        print(f"\n[floability] Data {args.mode} operation FAILED")

    return success
