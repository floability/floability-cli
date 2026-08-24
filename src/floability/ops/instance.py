"""
Instance operations for Floability CLI.

Handles creation and management of Floability instance directories.
"""
    
import json
import os
import sys
from pathlib import Path

from ..backpack_manager import resolve_backpack_args, validate_backpack_structure
from ..cleanup import CleanupManager
from ..environment_manager import setup_manager_and_worker_envs
from ..instance_lock_manager import (
    IDENTITY_GONE,
    IDENTITY_MISMATCHED,
    get_instance_lock_status,
    process_identity_status,
    release_instance_lock,
)
from ..instance_manager import get_registered_instances_status, prepare_instance
from ..instance_metadata import add_data_cache_dirs, update_instance_metadata
from ..instance_registry import (
    RegistryError,
    get_recent_base_directories,
    register_instance,
    resolve_instance,
    seed_base_directories_from_instances,
)
from ..performance_tracker import PerformanceTracker
from ..utils import normalize_cli_base_dir
from ..workers_manager import get_worker_status, stop_workers_for_instance


INSTANCE_STOP_SIGINT_GRACE_SECONDS = 20


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
    try:
        _create_instance_impl(args)
    except ValueError as e:
        print(f"[floability] Error: {e}")
        return 1
    except RuntimeError as e:
        print(f"[floability] Error: {e}")
        return 1
    except Exception as e:
        print(f"[floability] Unexpected error: {e}")
        raise
    return 0


def _create_instance_impl(args):
    """Internal implementation for create_instance — raises on error."""
    # Resolve backpack arguments
    resolve_backpack_args(args)
    # Validate backpack structure with stricter workflow requirement for instance creation
    if getattr(args, "backpack", None):
        validate_backpack_structure(args.backpack, require_workflow=True)

    if not args.backpack:
        raise ValueError("--backpack is required for 'instance create'")

    # Validate environment spec early — same pattern as run.py _setup_environment
    env_spec = getattr(args, "environment", None)
    if not env_spec:
        raise ValueError(
            "No environment spec provided. "
            "Use --environment to specify a path to environment.yml."
        )

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
            print(f"[floability] Warning: Could not create specified data cache directory: {cache_base_dir}.")
    else:
        cache_base_dir = (Path(args.base_dir) / "floability-data-cache").resolve()
        try:
            cache_base_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            print(f"[floability] Warning: Could not create default data cache directory: {cache_base_dir}.")
    args.cache_base_dir = str(cache_base_dir)

    # Prepare instance structure & metadata via manager module
    instance_paths = prepare_instance(args, mode="instance")
    instance_root = str(instance_paths["root"])
    instance_reference = instance_root

    # Register instance short name
    try:
        short_name = register_instance(
            Path(instance_root),
            args.manager_name,
            preferred_name=getattr(args, "name", None),
            base_dir=Path(args.base_dir),
        )
        instance_reference = short_name
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

        backpack_root_for_sources = args.backpack_root if getattr(args, "backpack_root", None) else None
        target_root = instance_paths["workflow"]

        cache_dirs: list = []
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
            _out_cache_dirs=cache_dirs,
        )
        perf.end_timer("data_operation", "Time to perform data operation")

        if cache_dirs:
            try:
                add_data_cache_dirs(instance_paths["metadata"] / "run.json", cache_dirs)
            except Exception as e:
                print(f"[floability] Warning: could not record data cache dirs: {e}")

        if not data_success:
            print("\n[floability] WARNING: Data operation failed!")
            if not getattr(args, "continue_on_data_failure", False):
                raise RuntimeError("Data materialization failed. Use --continue-on-data-failure to proceed anyway.")
        else:
            print("[floability] Data operation completed successfully")
    elif skip_data:
        print("[floability] Skipping data operation (--skip-data enabled)")

    # Setup conda environments (manager + worker) via environment manager
    per_instance_env = getattr(args, "per_instance_env", False)
    env_dir, worker_environment_pack, manager_environment_pack = setup_manager_and_worker_envs(
        environment_spec=env_spec,
        worker_environment_spec=getattr(args, "worker_environment", None),
        base_dir=args.base_dir,
        instance_root=instance_root,
        per_instance_env=per_instance_env,
        perf=perf if perf_enabled else None,
    )

    # Record environment paths in metadata
    metadata_updates = {
        **({"env_dir": str(env_dir)} if env_dir else {}),
        **({"worker_environment_pack": str(worker_environment_pack)} if worker_environment_pack else {}),
        **({"manager_environment_pack": str(manager_environment_pack)} if manager_environment_pack else {}),
    }
    if metadata_updates:
        metadata_file = instance_paths["metadata"] / "run.json"
        try:
            update_instance_metadata(metadata_file, metadata_updates, merge=True)
        except Exception as e:
            print(f"[floability] Warning: Could not update metadata with environment info: {e}")

    # Finalize performance tracking
    if perf_enabled:
        perf.end_timer("instance_creation", "Total instance creation time")
        perf.save_report()
        print(f"[floability] Performance report saved to {instance_paths['metrics']}")

    print("\n" + "=" * 70)
    print("[floability] Instance created successfully!")
    print(f"[floability] Instance path: {instance_root}")
    print("\n[floability] Next step:")
    print(f"[floability]   floability run --instance {instance_reference}")
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
        return create_instance(args)
    elif sub == "list":
        try:
            statuses = get_registered_instances_status()
        except RegistryError as error:
            print(f"[floability] Error: {error}", file=sys.stderr)
            return 1
        if not statuses:
            print("[floability] No registered instances.")
            return 0
        print("[floability] Registered instances:")
        for name, st in statuses.items():
            running_flag = "RUNNING" if st.get("running") else "idle"
            line = f"  {name:25} {running_flag:7}"
            if getattr(args, "show_paths", False):
                line += f"  {st.get('path','')}"
            print(line)
            if getattr(args, "all_details", False):
                print(f"      created:   {st.get('created_at','-')}")
                print(f"      last_seen: {st.get('last_seen','-')}")
                print(f"      last_run:  {st.get('last_run_at') or 'never'}")
                print(f"      manager:   {st.get('manager_name','-')}")
                print(f"      base:      {st.get('base_dir','-')}")
                print(f"      path:      {st.get('path','-')}")
                tags = st.get("tags") or []
                if tags:
                    print(f"      tags:      {', '.join(tags)}")

        print()
        print("[floability] Use: floability run --instance <name>")
        return 0
    elif sub == "stop":
        return stop_instance(args)
    elif sub == "latest":
        return go_to_latest_instance(args)
    else:
        print(f"[floability] Unknown instance subcommand: {sub}")
        return 1


def go_to_latest_instance(args) -> int:
    """Print the most recently run instance in the selected recent base."""
    try:
        statuses = get_registered_instances_status()
        valid_bases = {
            status["base_dir"]
            for status in statuses.values()
            if status.get("last_run_at")
            and status.get("base_dir")
            and status.get("exists")
        }

        explicit_base = "base_dir" in getattr(args, "_explicit_args", set())
        if explicit_base:
            base_dir = Path(args.base_dir).expanduser().resolve()
            if not base_dir.is_dir():
                print(
                    f"[floability] Base directory not found: {base_dir}",
                    file=sys.stderr,
                )
                return 1
        else:
            # Reconcile first so a legacy registry or an interrupted two-file
            # update cannot make an older base look current.
            seed_base_directories_from_instances(statuses)
            recent_bases = get_recent_base_directories(valid_bases)
            if not recent_bases:
                print(
                    "[floability] No previously run instances found.",
                    file=sys.stderr,
                )
                return 1
            base_dir = Path(recent_bases[0]["path"])

        selected = next(
            (
                status
                for status in statuses.values()
                if status.get("last_run_at")
                and status.get("exists")
                and Path(status["base_dir"]).resolve() == base_dir
            ),
            None,
        )
        if selected is None:
            print(
                f"[floability] No previously run instances found in {base_dir}.",
                file=sys.stderr,
            )
            return 1

        instance_path = Path(selected["path"]).resolve()
        try:
            from ..instance_manager import create_latest_symlink

            create_latest_symlink(
                str(base_dir),
                str(instance_path),
                verbose=False,
            )
        except OSError as error:
            print(
                f"[floability] Warning: could not update latest symlink: {error}",
                file=sys.stderr,
            )
        print(instance_path)
        return 0
    except RegistryError as error:
        print(f"[floability] Error: {error}", file=sys.stderr)
        return 1


def _instance_metadata_is_terminal(instance_path: Path) -> bool:
    metadata_file = instance_path / "metadata" / "run.json"
    try:
        with open(metadata_file) as stream:
            metadata = json.load(stream)
    except (OSError, json.JSONDecodeError, AttributeError):
        return False
    state = (metadata.get("status") or {}).get("state")
    return state in {"completed", "failed", "interrupted"}


def _stop_and_verify_workers(instance_path: Path) -> bool:
    status = get_worker_status(instance_path)
    if not status.get("consistent"):
        for diagnostic in status.get("diagnostics", []):
            print(f"[floability] Worker state error: {diagnostic}")
        return False

    terminal_states = {"not_started", "stopped", "failed", "stale"}
    if status.get("lifecycle_state") in terminal_states:
        return True
    if not stop_workers_for_instance(instance_path):
        return False

    final_status = get_worker_status(instance_path)
    if not final_status.get("consistent"):
        return False
    return final_status.get("lifecycle_state") in terminal_states


def _release_verified_stale_instance_lock(
    instance_path: Path,
    status: dict,
    *,
    workers_stopped: bool,
) -> bool:
    lock_data = status.get("lock_data") or {}
    owner = lock_data.get("owner")
    if owner:
        expected_owner = owner
    else:
        legacy_pid = lock_data.get("pid")
        expected_owner = {"pid": legacy_pid} if legacy_pid else None
    if expected_owner is None:
        return False

    safely_finalized = _instance_metadata_is_terminal(instance_path)
    safely_reconciled = bool(
        lock_data.get("state") == "cleanup_incomplete"
        and lock_data.get("owned_processes_stopped")
        and workers_stopped
    )
    if not safely_finalized and not safely_reconciled:
        return False
    return release_instance_lock(
        instance_path,
        expected_owner=expected_owner,
    )


def stop_instance(args) -> int:
    """Stop only processes whose persisted ownership can be verified."""
    ref = getattr(args, "instance", None)
    if not ref:
        print("[floability] Error: INSTANCE is required for 'instance stop'")
        return 1

    # Resolve short name to path
    resolved = resolve_instance(ref)
    instance_path = Path(resolved) if resolved else Path(ref)
    if not instance_path.is_dir():
        print(f"[floability] Error: Instance not found: {ref}")
        return 1

    initial_status = get_instance_lock_status(instance_path)
    initial_state = initial_status["state"]
    instance_ownership_blocked = False
    if initial_state == "active":
        owner = initial_status["owner"]
        pid = owner["pid"]
        print(
            "[floability] Stopping instance run process "
            f"(pid={pid}) for {instance_path}"
        )
        cleanup_manager = CleanupManager(
            process_sigint_grace_seconds=INSTANCE_STOP_SIGINT_GRACE_SECONDS
        )
        cleanup_manager.register_verified_process(
            pid,
            lambda: process_identity_status(owner),
        )
        cleanup_manager.cleanup()
    elif initial_state in {"active_legacy", "corrupt", "unverifiable"}:
        print(
            "[floability] Error: Instance ownership is "
            f"{initial_state}; refusing to signal or remove its lock."
        )
        instance_ownership_blocked = True

    workers_stopped = _stop_and_verify_workers(instance_path)
    if not workers_stopped:
        print("[floability] Error: Worker cleanup is incomplete.")
        return 1
    if instance_ownership_blocked:
        return 1

    final_status = get_instance_lock_status(instance_path)
    final_state = final_status["state"]
    if final_state != "missing":
        identity_state = final_status.get("identity_state")
        stale_states = {"stale", "stale_legacy", "mismatched"}
        identity_is_gone = identity_state in {
            None,
            IDENTITY_GONE,
            IDENTITY_MISMATCHED,
        }
        if (
            final_state not in stale_states
            or not identity_is_gone
            or not _release_verified_stale_instance_lock(
                instance_path,
                final_status,
                workers_stopped=workers_stopped,
            )
        ):
            print(
                "[floability] Error: Instance cleanup is incomplete; "
                "retaining instance.lock for diagnosis and retry."
            )
            return 1

    print("[floability] Instance stop completed.")
    return 0
