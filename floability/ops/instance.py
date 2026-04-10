"""
Instance operations for Floability CLI.

Handles creation and management of Floability instance directories.
"""
    
import argparse

import json
import os
import signal
import time
from pathlib import Path

from ..performance_tracker import PerformanceTracker
from ..backpack_manager import resolve_backpack_args, validate_backpack_structure
from ..instance_manager import prepare_instance, get_registered_instances_status
from ..environment_manager import setup_manager_and_worker_envs
from ..instance_metadata import update_instance_metadata
from ..utils import normalize_cli_base_dir
from ..instance_registry import register_instance, resolve_instance, list_instances
from ..instance_lock_manager import (
    release_instance_lock,
    is_instance_running,
)
from ..workers_manager import stop_workers_for_instance


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

    # Normalize base_dir and data cache dir
    raw_base = getattr(args, "base_dir", None) if hasattr(args, "base_dir") else None
    args.base_dir = str(normalize_cli_base_dir(raw_base))
    
    # Determine data cache directory: allow CLI override, else use base_dir/floability-data-cache
    raw_cache_override = getattr(args, "data_cache_dir", None) if hasattr(args, "data_cache_dir") else None
    if raw_cache_override:
        cache_base_dir = Path(os.path.expanduser(raw_cache_override)).resolve()
        try:
            cache_base_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
    else:
        cache_base_dir = (Path(args.base_dir) / "floability-data-cache").resolve()
        try:
            cache_base_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
    args.cache_base_dir = str(cache_base_dir)

    # Prepare instance structure & metadata via manager module
    instance_paths = prepare_instance(args, mode="instance")
    instance_root = str(instance_paths["root"])
    # Register instance short name
    try:
        short_name = register_instance(
            Path(instance_root),
            args.manager_name,
            preferred_name=getattr(args, "name", None),
        )
        print(f"[floability] Registered instance short name: {short_name}")
    except Exception as e:
        print(f"[floability] Warning: could not register instance short name: {e}")

    # Initialize performance tracking (metrics directory already created)
    perf_enabled = getattr(args, "measure_performance", False)
    perf = PerformanceTracker(
        output_dir=str(instance_paths["metrics"]), enabled=perf_enabled
    )
    perf.start_timer("instance_creation")

    # Fetch data unless --skip-data is provided
    skip_data = getattr(args, "skip_data", False)

    if args.data_spec and not skip_data:
        print(f"[floability] Performing data operation from {args.data_spec}")
        perf.start_timer("data_operation")

        from ..data.data_handler import execute_default_data_operation

        # Materialize data into instance workflow
        # backpack_root is used for resolving source paths only
        backpack_root_for_sources = args.backpack_root if getattr(args, "backpack_root", None) else None
        target_root = instance_paths["workflow"]

        data_success = execute_default_data_operation(
            data_spec=args.data_spec,
            backpack_root=backpack_root_for_sources,
            verbose=True,
            force=False,
            data_profile=getattr(args, "data_profile", None),
            data_cache_mode=getattr(args, "data_cache_mode", "off"),
            force_data_cache=getattr(args, "force_data_cache", False),
            base_dir=Path(args.base_dir),
            cache_base_dir=Path(args.cache_base_dir),
            target_root=target_root,
            fingerprint_mode=getattr(args, "fingerprint_mode", "meta"),
            perf=perf,
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
    env_dir, worker_environment_pack, manager_environment_pack = setup_manager_and_worker_envs(
        environment_spec=(
            args.environment if getattr(args, "environment", None) else None
        ),
        worker_environment_spec=(
            args.worker_environment
            if getattr(args, "worker_environment", None)
            else None
        ),
        base_dir=args.base_dir,
        instance_root=instance_root,
        manager_name=args.manager_name,
        manager_ports=getattr(args, "manager_ports", "9123,9150"),
        env_vars=getattr(args, "env_vars", None),
        force=False,
        perf=perf if perf_enabled else None,
    )

    # Record worker environment pack in metadata
    if worker_environment_pack or manager_environment_pack:
        metadata_file = instance_paths["metadata"] / "run.json"
        try:
            update_instance_metadata(
                metadata_file,
                {
                    **({"worker_environment_pack": str(worker_environment_pack)} if worker_environment_pack else {}),
                    **({"manager_environment_pack": str(manager_environment_pack)} if manager_environment_pack else {}),
                },
                merge=True,
            )
        except Exception as e:
            print(
                f"[floability] Warning: Could not update metadata with worker env: {e}"
            )

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
    print(
        f"[floability]   1. Start workers: floability workers start --instance {instance_root}"
    )
    print(f"[floability]   2. Run workflow: cd {instance_root}/workflow && jupyter lab")
    print("=" * 70)


def run_instance_command(args):
    """
    Entry point for 'floability instance' command.

    Supports subcommands:
    - create: Create a new instance from a backpack
    - list:   List registered instances
    - stop:   Stop a running instance (Jupyter/manager/workers)
    """
    sub = getattr(args, "instance_subcommand", None)
    if sub == "create":
        create_instance(args)
    elif sub == "list":
        statuses = get_registered_instances_status()
        if not statuses:
            print("[floability] No registered instances.")
            return
        print("[floability] Registered instances:")
        for name in sorted(statuses.keys()):
            st = statuses[name]
            running_flag = "RUNNING" if st.get("running") else "idle"
            line = f"  {name:25} {running_flag:7}"
            if getattr(args, "show_paths", False):
                line += f"  {st.get('path','')}"
            print(line)
            if getattr(args, "all_details", False):
                print(f"      created:   {st.get('created_at','-')}")
                print(f"      last_seen: {st.get('last_seen','-')}")
                print(f"      manager:   {st.get('manager_name','-')}")
                print(f"      path:      {st.get('path','-')}")
                tags = st.get("tags") or []
                if tags:
                    print(f"      tags:      {', '.join(tags)}")

        print()
        print(
            "[floability] Use: floability run --instance <name> or workers start --instance <name>"
        )
    elif sub == "stop":
        stop_instance(args)
    elif sub == "latest":
        go_to_latest_instance(args)
    else:
        print(f"[floability] Unknown instance subcommand: {sub}")


def go_to_latest_instance(args) -> None:
    """Print the path of the latest Floability instance.

    Resolution order:
      1. latest_floability_instance symlink in base_dir
      2. Most recently created entry in the instance registry

    Prints only the resolved path to stdout so the caller can use it with:
        cd $(floability instance go-to-latest)
    """
    from ..utils import normalize_cli_base_dir

    base_dir = normalize_cli_base_dir(getattr(args, "base_dir", None))
    symlink = base_dir / "latest_floability_instance"

    if symlink.is_symlink() and Path(symlink.resolve()).is_dir():
        print(str(symlink.resolve()))
        return

    # Fallback: most recently created registry entry
    entries = list_instances()
    if not entries:
        print("[floability] No instances found.", file=__import__("sys").stderr)
        raise SystemExit(1)

    latest = max(
        entries.items(),
        key=lambda kv: kv[1].get("created_at", ""),
    )
    path = latest[1].get("path", "")
    if not path or not Path(path).is_dir():
        print("[floability] Latest instance path no longer exists.", file=__import__("sys").stderr)
        raise SystemExit(1)

    print(path)


def _read_lock_pid(lock_file: Path) -> int:
    try:
        with open(lock_file, "r") as f:
            data = json.load(f) or {}
        return int(data.get("pid")) if data.get("pid") is not None else -1
    except Exception:
        return -1


def _send_signal_to_pgid(pid: int, sig) -> bool:
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, sig)
        return True
    except Exception:
        # Fallback: try direct process
        try:
            os.kill(pid, sig)
            return True
        except Exception:
            return False


def stop_instance(args) -> None:
    """Stop a running Floability instance.

    Behavior:
    - Resolve short name to path if needed
    - If instance.lock is active, send SIGINT to the run process group, then SIGTERM if needed
    - Stop workers via workers manager (best-effort)
    - Release instance lock file
    """
    ref = getattr(args, "instance", None)
    if not ref:
        print("[floability] Error: --instance is required for 'instance stop'")
        return

    # Resolve short name to path
    resolved = resolve_instance(ref)
    instance_path = Path(resolved) if resolved else Path(ref)
    if not instance_path.is_dir():
        print(f"[floability] Error: Instance not found: {ref}")
        return

    lock_file = instance_path / "metadata" / "instance.lock"
    pid = _read_lock_pid(lock_file) if lock_file.exists() else -1

    # Try to gracefully stop the main run process so it can clean up Jupyter/others
    if is_instance_running(instance_path) and pid > 0:
        print(
            f"[floability] Stopping instance run process (pid={pid}) for {instance_path}"
        )
        if _send_signal_to_pgid(pid, signal.SIGINT):
            time.sleep(2)
        # If still running, escalate
        if is_instance_running(instance_path):
            print("[floability] Instance still running; sending SIGTERM...")
            _send_signal_to_pgid(pid, signal.SIGTERM)
            time.sleep(1)
    else:
        if lock_file.exists():
            print("[floability] Instance lock present but process not active. Cleaning up lock.")

    # Ensure workers are stopped (best-effort)
    try:
        stopped = stop_workers_for_instance(instance_path)
        if stopped:
            print("[floability] Workers stopped.")
    except Exception as e:
        print(f"[floability] Warning: could not stop workers: {e}")

    # Release instance lock
    try:
        release_instance_lock(instance_path)
    except Exception:
        pass
    print("[floability] Instance stop completed.")
