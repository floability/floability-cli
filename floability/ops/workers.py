"""Thin CLI wrappers delegating worker lifecycle to ``workers_manager``."""

from pathlib import Path

from ..workers_manager import (
    start_workers_for_instance,
    stop_workers_for_instance,
    print_worker_status,
)
from ..instance_lock_manager import are_workers_running


def start_workers(args):
    if not args.instance:
        print("[floability] Error: --instance is required for 'workers start'")
        return
    instance_path = Path(args.instance).resolve()
    if not instance_path.is_dir():
        print(f"[floability] Error: Instance directory not found: {instance_path}")
        return
    if are_workers_running(instance_path):
        print(
            "[floability] Workers already running (lock present). Use 'floability workers status' or 'workers stop'."
        )
        return
    try:
        proc = start_workers_for_instance(
            instance_path=instance_path,
            batch_type=getattr(args, "batch_type", None),
            workers=getattr(args, "workers", None),
            cores_per_worker=getattr(args, "cores_per_worker", None),
            batch_options=getattr(args, "batch_options", None),
            compute_spec=getattr(args, "compute_spec", None),
            debug_workers=getattr(args, "debug_workers", False),
        )
        if proc:
            print(
                "\n[floability] To check status: floability workers status --instance "
                + str(instance_path)
            )
            print(
                "[floability] To stop workers: floability workers stop --instance "
                + str(instance_path)
            )
    except Exception as e:
        print(f"[floability] Error starting workers: {e}")


def stop_workers(args):
    if not args.instance:
        print("[floability] Error: --instance is required for 'workers stop'")
        return
    instance_path = Path(args.instance).resolve()
    if not instance_path.is_dir():
        print(f"[floability] Error: Instance directory not found: {instance_path}")
        return
    if not stop_workers_for_instance(instance_path):
        print("[floability] Failed to stop workers")


def status_workers(args):
    if not args.instance:
        print("[floability] Error: --instance is required for 'workers status'")
        return
    instance_path = Path(args.instance).resolve()
    if not instance_path.is_dir():
        print(f"[floability] Error: Instance directory not found: {instance_path}")
        return
    print_worker_status(instance_path)


def run_workers_command(args):
    """
    Entry point for 'floability workers' command.

    Supports subcommands:
    - start: Start workers for an instance
    - stop: Stop workers for an instance
    - status: Show worker status and logs
    """
    if args.workers_subcommand == "start":
        start_workers(args)
    elif args.workers_subcommand == "stop":
        stop_workers(args)
    elif args.workers_subcommand == "status":
        status_workers(args)
    else:
        print(f"[floability] Unknown workers subcommand: {args.workers_subcommand}")
