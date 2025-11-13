"""
Instance operations for Floability CLI.

Handles creation and management of Floability instance directories.
"""

import argparse
from pathlib import Path

from ..performance_tracker import PerformanceTracker
from ..backpack_manager import resolve_backpack_args, validate_backpack_structure
from ..instance_manager import prepare_instance
from ..environment_manager import setup_manager_and_worker_envs
from ..instance_metadata import update_instance_metadata


def create_instance(args):
    """
    Create a Floability instance from a backpack.
    
    This command:
    1. Creates a unique instance directory structure
    2. Copies notebook/script into instance workflow/
    3. Optionally fetches data (unless --skip-data)
    4. Creates and extracts conda environment
    5. Records metadata about the instance
    
    The instance is ready to run but doesn't start workers or Jupyter.
    """
    # Resolve backpack arguments
    resolve_backpack_args(args)
    # Validate backpack structure with stricter workflow requirement for instance creation
    if getattr(args, "backpack", None):
        validate_backpack_structure(args.backpack, require_workflow=True)
    
    if not args.backpack:
        print("[floability] Error: --backpack is required for 'instance create'")
        return
    
    # Prepare instance structure & metadata via manager module
    instance_paths = prepare_instance(args, mode="instance")
    instance_root = str(instance_paths["root"])

    # Initialize performance tracking (metrics directory already created)
    perf_enabled = getattr(args, 'measure_performance', False)
    perf = PerformanceTracker(output_dir=str(instance_paths["metrics"]), enabled=perf_enabled)
    perf.start_timer("instance_creation")
    
    # Fetch data unless --skip-data is provided
    skip_data = getattr(args, 'skip_data', False)
    
    if args.data_spec and not skip_data:
        print(f"[floability] Performing data operation from {args.data_spec}")
        perf.start_timer("data_operation")
        
        from ..data.data_handler import execute_default_data_operation
        
        # Materialize data into instance workflow
        data_materialization_root = str(instance_paths["root"])
        
        data_success = execute_default_data_operation(
            data_spec=args.data_spec,
            backpack_root=data_materialization_root,
            verbose=True,
            force=False,
            data_profile=getattr(args, "data_profile", None),
            data_cache_mode=getattr(args, "data_cache_mode", "off"),
            force_data_cache=getattr(args, "force_data_cache", False),
            base_dir=Path(args.base_dir),
        )
        perf.end_timer("data_operation", "Time to perform data operation")
        
        if not data_success:
            print("\n[floability] WARNING: Data operation failed!")
            print("[floability] Instance created but data may be incomplete.")
        else:
            print("[floability] Data operation completed successfully")
    elif skip_data:
        print("[floability] Skipping data operation (--skip-data enabled)")
    
    # Setup conda environments (manager + worker) via environment manager
    env_dir, worker_environment_pack = setup_manager_and_worker_envs(
        environment_spec=args.environment if getattr(args, "environment", None) else None,
        worker_environment_spec=args.worker_environment if getattr(args, "worker_environment", None) else None,
        base_dir=args.base_dir,
        instance_root=instance_root,
        manager_name=args.manager_name,
        manager_ports=getattr(args, 'manager_ports', '9123,9150'),
        env_vars=getattr(args, 'env_vars', None),
        force=False,
        perf=perf if perf_enabled else None,
    )
    
    # Record worker environment pack in metadata
    if worker_environment_pack:
        metadata_file = instance_paths["metadata"] / "run.json"
        try:
            update_instance_metadata(
                metadata_file,
                {"worker_environment_pack": str(worker_environment_pack)},
                merge=True
            )
        except Exception as e:
            print(f"[floability] Warning: Could not update metadata with worker env: {e}")
    
    # Finalize performance tracking
    if perf_enabled:
        perf.end_timer("instance_creation", "Total instance creation time")
        perf.save_report()
        print(f"[floability] Performance report saved to {instance_paths['metrics']}")
    
    print("\n" + "=" * 70)
    print("[floability] Instance created successfully!")
    print(f"[floability] Instance path: {instance_root}")
    print(f"[floability] Manager name: {args.manager_name}")
    print("\n[floability] Next steps:")
    print(f"[floability]   1. Start workers: floability workers start --instance {instance_root}")
    print(f"[floability]   2. Run workflow: cd {instance_root}/workflow && jupyter lab")
    print("=" * 70)


def run_instance_command(args):
    """
    Entry point for 'floability instance' command.
    
    Supports subcommands:
    - create: Create a new instance from a backpack
    """
    if args.instance_subcommand == 'create':
        create_instance(args)
    else:
        print(f"[floability] Unknown instance subcommand: {args.instance_subcommand}")
