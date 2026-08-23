"""Thin CLI wrappers delegating worker lifecycle to ``workers_manager``."""

from pathlib import Path

from ..workers_manager import (
    start_workers_for_instance,
    stop_workers_for_instance,
    print_worker_status,
)
from ..instance_registry import resolve_instance


def start_workers(args):
    if not args.instance:
        print("[floability] Error: --instance is required for 'workers start'")
        return 1
    resolved = resolve_instance(args.instance)
    if not resolved:
        print(f"[floability] Error: Instance reference not found: {args.instance}")
        return 1
    instance_path = Path(resolved).resolve()
    if not instance_path.is_dir():
        print(f"[floability] Error: Instance directory not found: {instance_path}")
        return 1
    try:
        proc = start_workers_for_instance(
            instance_path=instance_path,
            cli_args=args,
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
            return 0
        return 1
    except Exception as e:
        print(f"[floability] Error starting workers: {e}")
        return 1


def stop_workers(args):
    if not args.instance:
        print("[floability] Error: --instance is required for 'workers stop'")
        return 1
    resolved = resolve_instance(args.instance)
    if not resolved:
        print(f"[floability] Error: Instance reference not found: {args.instance}")
        return 1
    instance_path = Path(resolved).resolve()
    if not instance_path.is_dir():
        print(f"[floability] Error: Instance directory not found: {instance_path}")
        return 1
    if not stop_workers_for_instance(instance_path):
        print("[floability] Failed to stop workers")
        return 1
    return 0


def status_workers(args):
    if not args.instance:
        print("[floability] Error: --instance is required for 'workers status'")
        return 1
    resolved = resolve_instance(args.instance)
    if not resolved:
        print(f"[floability] Error: Instance reference not found: {args.instance}")
        return 1
    instance_path = Path(resolved).resolve()
    if not instance_path.is_dir():
        print(f"[floability] Error: Instance directory not found: {instance_path}")
        return 1
    print_worker_status(instance_path)
    return 0


def run_workers_command(args):
    """
    Entry point for 'floability workers' command.

    Supports subcommands:
    - start: Start workers for an instance
    - stop: Stop workers for an instance
    - status: Show worker status and logs
    """
    if args.workers_subcommand == "start":
        return start_workers(args)
    elif args.workers_subcommand == "stop":
        return stop_workers(args)
    elif args.workers_subcommand == "status":
        return status_workers(args)
    else:
        print(f"[floability] Unknown workers subcommand: {args.workers_subcommand}")
        return 1
