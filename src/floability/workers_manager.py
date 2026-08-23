"""Workers manager module.

Manages worker lifecycle for Floability instances.
Supports ``vine_factory`` as the default worker backend;
additional backends can be added via the ``worker_type`` parameter.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

import yaml

from .cleanup import CleanupManager
from .instance_lock_manager import (
    acquire_workers_lock,
    is_process_alive,
    is_process_group_alive,
    promote_workers_lock,
    read_workers_lock,
    release_workers_lock,
)
from .utils import (
    get_conda_executable,
    normalize_manager_ports,
    normalize_worker_transfer_ports,
)

FACTORY_STARTUP_GRACE_SECONDS = 2


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------


def start_workers_for_instance(
    instance_path: Path,
    cli_args=None,
    env_dir: Optional[str] = None,
    instance_env: Optional[Dict] = None,
    worker_provider: str = "vine_factory",
    detached: bool = False,
) -> Optional[object]:
    """Start workers for an existing instance.

    Args:
        instance_path: Path to the instance directory.
        cli_args:      argparse.Namespace or dict with optional CLI overrides:
                       batch_type, workers, cores_per_worker, batch_options,
                       compute_spec, debug_workers.  Metadata fills any missing fields.
        env_dir:       Path to extracted manager conda env.  When provided,
                       vine_factory runs inside this env via ``conda run``.
        instance_env:  Prepared subprocess environment for the factory.
        worker_provider:   Worker backend.  Currently only ``"vine_factory"``.
        detached:      Write factory stderr to a durable log instead of a
                       daemon console-streaming thread.

    Returns:
        Popen handle if started successfully, None otherwise.

    Raises:
        ValueError: If metadata is missing or worker_provider is unknown.
    """
    metadata = _read_instance_metadata(instance_path)
    if not metadata:
        raise ValueError("Could not read instance metadata.")
    manager_name = metadata.get("manager_name")
    if not manager_name:
        raise ValueError("No manager_name found in instance metadata.")

    worker_pack = metadata.get("worker_environment_pack")
    if not worker_pack:
        print(
            "[workers] Warning: no worker environment pack in metadata — "
            "workers will use system Python."
        )

    logs_dir = str(instance_path / "logs")

    # Normalize worker settings from all sources (defaults, metadata, compute spec, CLI)
    cfg = _normalize_compute_specs(cli_args, metadata, worker_pack)

    print(f"[workers] Starting {worker_provider} for instance: {instance_path}")
    print(f"[workers]   Manager    : {manager_name}")
    print(
        f"[workers]   Batch type : {cfg['batch_type']}  "
        f"Workers: {cfg['max_workers']}  Cores/worker: {cfg['cores']}"
    )
    if worker_pack:
        print(f"[workers]   Worker env : {worker_pack}")

    if not acquire_workers_lock(instance_path):
        raise RuntimeError("Workers are already starting or running for this instance.")

    proc = None
    factory_pgid = None
    lock_promoted = False
    try:
        if worker_provider == "vine_factory":
            proc = _start_vine_factory(
                manager_name=manager_name,
                cfg=cfg,
                run_dir=logs_dir,
                scratch_dir=logs_dir,
                manager_env_dir=env_dir,
                instance_env=instance_env,
                detached=detached,
            )
        else:
            raise ValueError(
                f"Unknown worker_provider: {worker_provider!r}. "
                "Currently only 'vine_factory' is supported."
            )

        try:
            returncode = proc.wait(timeout=FACTORY_STARTUP_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            returncode = None
        if returncode is not None:
            raise RuntimeError(
                f"vine_factory exited immediately with status {returncode}."
            )

        factory_pgid = os.getpgid(proc.pid)
        if not promote_workers_lock(
            instance_path,
            factory_pid=proc.pid,
            factory_pgid=factory_pgid,
            manager_name=manager_name,
        ):
            raise RuntimeError("Could not record vine_factory lock ownership.")
        lock_promoted = True

        started_at = time.time()
        if not _write_worker_metadata(
            instance_path,
            {
                "factory_pid": proc.pid,
                "factory_pgid": factory_pgid,
                "manager_name": manager_name,
                "batch_type": cfg["batch_type"],
                "workers": cfg["max_workers"],
                "cores_per_worker": cfg["cores"],
                "status": "running",
                "started_at": started_at,
            },
        ):
            raise RuntimeError("Could not record vine_factory metadata.")
    except BaseException:
        if proc is not None:
            _terminate_failed_factory(proc, factory_pgid)
        if lock_promoted:
            release_workers_lock(
                instance_path,
                expected_factory_pid=proc.pid,
                expected_factory_pgid=factory_pgid,
            )
        else:
            release_workers_lock(
                instance_path,
                expected_launcher_pid=os.getpid(),
            )
        raise

    print(f"[workers] Workers started. PID={proc.pid}")

    return proc


def resolve_instance_worker_runtime(instance_path: Path) -> Tuple[str, Dict]:
    """Restore and validate the runtime needed by standalone worker startup."""
    metadata = _read_instance_metadata(instance_path)
    if not metadata:
        raise RuntimeError("Could not read instance metadata.")

    env_dir_value = metadata.get("env_dir")
    if not env_dir_value:
        raise RuntimeError(
            "No prepared manager environment is recorded. Start the instance "
            "with 'floability run' or 'floability execute' to prepare its runtime."
        )

    env_dir = Path(env_dir_value)
    if not env_dir.is_dir():
        raise RuntimeError(f"Recorded manager environment does not exist: {env_dir}")

    vine_factory_path = env_dir / "bin" / "vine_factory"
    if not vine_factory_path.is_file() or not os.access(vine_factory_path, os.X_OK):
        raise RuntimeError(
            "Prepared manager environment does not contain an executable "
            f"vine_factory: {vine_factory_path}"
        )

    worker_pack = metadata.get("worker_environment_pack")
    if worker_pack and not Path(worker_pack).is_file():
        raise RuntimeError(
            f"Recorded worker environment pack does not exist: {worker_pack}"
        )

    manager_name = metadata.get("manager_name")
    if not manager_name:
        raise RuntimeError("No manager_name found in instance metadata.")

    saved_args = metadata.get("cli_args") or {}
    manager_ports = metadata.get("manager_ports") or saved_args.get("manager_ports")
    instance_env = os.environ.copy()
    for key in (
        "CONDA_PREFIX",
        "CONDA_DEFAULT_ENV",
        "CONDA_PROMPT_MODIFIER",
        "CONDA_SHLVL",
        "_CE_CONDA",
        "_CE_M",
    ):
        instance_env.pop(key, None)

    instance_env["PATH"] = (
        str(env_dir / "bin") + os.pathsep + instance_env.get("PATH", "")
    )
    instance_env["VINE_MANAGER_NAME"] = str(manager_name)
    instance_env["VINE_MANAGER_PORTS"] = normalize_manager_ports(
        manager_ports or "9123:9150"
    )
    instance_env["FLOABILITY_WORKERS_ENABLED"] = "1"

    saved_env_vars = saved_args.get("env_vars")
    if saved_env_vars and saved_env_vars != "None":
        for pair in str(saved_env_vars).split(","):
            if "=" in pair:
                key, value = pair.split("=", 1)
                instance_env[key.strip()] = value.strip()

    return str(env_dir), instance_env


def reconcile_workers_after_cleanup(
    instance_path: Path,
    *,
    cleanup_succeeded: bool,
    expected_factory_pid: int,
    reason: str = "run_cleanup",
) -> bool:
    """Reconcile worker metadata and lock after a run cleanup attempt.

    State is changed only when ``workers.json`` still belongs to the factory
    registered by this run. A successful process cleanup records a terminal
    state before releasing the matching lock. An incomplete process cleanup
    records the failure but deliberately retains ownership for a later retry.
    """
    worker_data = _read_worker_metadata(instance_path)
    if not worker_data:
        print(
            "[workers] Warning: cannot reconcile cleanup without "
            "workers.json."
        )
        return False

    recorded_factory_pid = worker_data.get("factory_pid")
    if recorded_factory_pid != expected_factory_pid:
        print(
            "[workers] Skipping cleanup reconciliation because worker state "
            "belongs to a different factory."
        )
        return True

    reconciled_data = dict(worker_data)
    if cleanup_succeeded:
        reconciled_data.update(
            {
                "status": "stopped",
                "stopped_at": time.time(),
                "stop_reason": reason,
            }
        )
        reconciled_data.pop("cleanup_attempted_at", None)
        reconciled_data.pop("cleanup_error", None)
    else:
        reconciled_data.update(
            {
                "status": "cleanup_incomplete",
                "cleanup_attempted_at": time.time(),
                "cleanup_error": "Factory process group remained alive after cleanup.",
            }
        )

    if not _write_worker_metadata(instance_path, reconciled_data):
        return False

    if not cleanup_succeeded:
        return True

    factory_pgid = worker_data.get("factory_pgid")
    if not factory_pgid:
        print(
            "[workers] Warning: cannot release workers.lock without the "
            "recorded factory process group."
        )
        return False

    if not release_workers_lock(
        instance_path,
        expected_factory_pid=expected_factory_pid,
        expected_factory_pgid=factory_pgid,
    ):
        print("[workers] Warning: could not release the matching workers.lock.")
        return False

    return True


def stop_workers_for_instance(instance_path: Path) -> bool:
    """Stop the owned factory process group and reconcile terminal state."""
    data = _read_worker_metadata(instance_path)
    if not data:
        print("[workers] No worker metadata found. Workers may not be running.")
        return False

    lock_data = read_workers_lock(instance_path)
    if data.get("status") == "stopped" and not lock_data:
        print(f"[workers] Workers are already stopped for instance {instance_path}.")
        return True

    factory_pid = data.get("factory_pid")
    factory_pgid = data.get("factory_pgid")
    if not factory_pid or not factory_pgid:
        print("[workers] Worker metadata has no verifiable factory PID/PGID.")
        return False

    if not lock_data:
        print(
            "[workers] Cannot safely stop workers because workers.lock is "
            "missing or unreadable."
        )
        return False

    if (
        lock_data.get("state") != "running"
        or lock_data.get("factory_pid") != factory_pid
        or lock_data.get("factory_pgid") != factory_pgid
    ):
        print(
            "[workers] Worker lock and metadata ownership do not match; "
            "refusing to signal."
        )
        return False

    stopping_data = dict(data)
    stopping_data.update(
        {
            "status": "stopping",
            "stop_requested_at": time.time(),
        }
    )
    if not _write_worker_metadata(instance_path, stopping_data):
        return False

    print(
        f"[workers] Stopping workers for instance {instance_path} "
        f"(PID={factory_pid}, PGID={factory_pgid})"
    )
    cleanup_manager = CleanupManager()
    cleanup_manager.register_process_group(factory_pgid)
    cleanup_manager.register_cleanup_callback(
        lambda cleanup_succeeded: reconcile_workers_after_cleanup(
            instance_path,
            cleanup_succeeded=cleanup_succeeded,
            expected_factory_pid=factory_pid,
            reason="workers_stop",
        )
    )
    return cleanup_manager.cleanup()


def get_worker_status(instance_path: Path) -> Dict:
    """Derive and safely reconcile worker status from metadata and ownership."""
    workers_file = _workers_metadata_file(instance_path)
    lock_file = instance_path / "metadata" / "workers.lock"
    worker_data = _read_worker_metadata(instance_path)
    lock_data = read_workers_lock(instance_path)
    status = {
        "metadata": _read_instance_metadata(instance_path),
        "worker_data": worker_data,
        "lock_data": lock_data,
        "lifecycle_state": "not_started",
        "process_running": False,
        "liveness_source": "none",
        "consistent": True,
        "diagnostics": [],
    }

    def inconsistent(message: str) -> Dict:
        status["lifecycle_state"] = "unknown/inconsistent"
        status["consistent"] = False
        status["diagnostics"].append(message)
        return status

    if worker_data is not None and not isinstance(worker_data, dict):
        return inconsistent("workers.json must contain a JSON object.")
    if lock_data is not None and not isinstance(lock_data, dict):
        return inconsistent("workers.lock must contain a JSON object.")
    if workers_file.exists() and worker_data is None:
        return inconsistent("workers.json exists but is unreadable or malformed.")
    if lock_file.exists() and lock_data is None:
        return inconsistent("workers.lock exists but is unreadable or malformed.")

    if lock_data is None:
        if worker_data is None:
            return status
        recorded_state = worker_data.get("status", "unknown")
        if recorded_state in {"stopped", "failed", "stale"}:
            status["lifecycle_state"] = recorded_state
            return status
        return inconsistent(
            f"workers.json records '{recorded_state}' but workers.lock is absent."
        )

    lock_state = lock_data.get("state")
    if lock_state == "starting":
        launcher_pid = lock_data.get("launcher_pid")
        if not isinstance(launcher_pid, int) or launcher_pid <= 0:
            return inconsistent("Starting worker lock has no valid launcher PID.")
        status["liveness_source"] = "launcher_pid"
        status["process_running"] = is_process_alive(launcher_pid)
        if status["process_running"]:
            status["lifecycle_state"] = "starting"
            return status
        if not release_workers_lock(
            instance_path,
            expected_launcher_pid=launcher_pid,
        ):
            return inconsistent(
                "Dead startup reservation could not be released safely."
            )
        status["lock_data"] = None
        status["lifecycle_state"] = "stale"
        status["diagnostics"].append("Removed a dead worker startup reservation.")
        return status

    if lock_state == "running":
        factory_pid = lock_data.get("factory_pid")
        factory_pgid = lock_data.get("factory_pgid")
        if not all(
            isinstance(identifier, int) and identifier > 0
            for identifier in (factory_pid, factory_pgid)
        ):
            return inconsistent("Running worker lock has no valid factory PID/PGID.")
        if worker_data is None:
            return inconsistent("Running workers.lock has no matching workers.json.")
        if (
            worker_data.get("factory_pid") != factory_pid
            or worker_data.get("factory_pgid") != factory_pgid
        ):
            return inconsistent("workers.lock and workers.json ownership do not match.")

        recorded_state = worker_data.get("status", "unknown")
        status["liveness_source"] = "process_group"
        status["process_running"] = is_process_group_alive(factory_pgid)
        if status["process_running"]:
            if recorded_state in {"running", "stopping", "cleanup_incomplete"}:
                status["lifecycle_state"] = recorded_state
                return status
            return inconsistent(
                f"Factory group is live but workers.json records '{recorded_state}'."
            )

        if recorded_state in {"stopped", "failed", "stale"}:
            if not release_workers_lock(
                instance_path,
                expected_factory_pid=factory_pid,
                expected_factory_pgid=factory_pgid,
            ):
                return inconsistent(
                    "Dead terminal worker lock could not be released safely."
                )
            status["lock_data"] = None
            status["lifecycle_state"] = recorded_state
            return status

        stale_data = dict(worker_data)
        stale_data.update(
            {
                "status": "stale",
                "stale_detected_at": time.time(),
                "stale_reason": "Recorded factory process group is not running.",
            }
        )
        if not _write_worker_metadata(instance_path, stale_data):
            return inconsistent("Dead worker group could not be recorded as stale.")
        status["worker_data"] = stale_data
        status["lifecycle_state"] = "stale"
        if not release_workers_lock(
            instance_path,
            expected_factory_pid=factory_pid,
            expected_factory_pgid=factory_pgid,
        ):
            return inconsistent("Stale worker lock could not be released safely.")
        status["lock_data"] = None
        status["diagnostics"].append(
            "Recorded the dead factory group as stale and removed its matching lock."
        )
        return status

    # Backward compatibility with the original generic worker lock format.
    if lock_state is None and "pid" in lock_data:
        legacy_pid = lock_data.get("pid")
        if not isinstance(legacy_pid, int) or legacy_pid <= 0:
            return inconsistent("Legacy worker lock has no valid PID.")
        if worker_data and worker_data.get("factory_pid") not in (None, legacy_pid):
            return inconsistent(
                "Legacy lock PID and workers.json ownership do not match."
            )
        status["liveness_source"] = "legacy_pid"
        status["process_running"] = is_process_alive(legacy_pid)
        recorded_state = (
            worker_data.get("status", "running") if worker_data else "running"
        )
        if status["process_running"]:
            if recorded_state in {
                "running",
                "starting",
                "stopping",
                "cleanup_incomplete",
            }:
                status["lifecycle_state"] = recorded_state
                return status
            return inconsistent(
                "Legacy worker PID is live but workers.json records "
                f"'{recorded_state}'."
            )

        if worker_data and recorded_state not in {"stopped", "failed", "stale"}:
            stale_data = dict(worker_data)
            stale_data.update(
                {
                    "status": "stale",
                    "stale_detected_at": time.time(),
                    "stale_reason": "Recorded legacy factory process is not running.",
                }
            )
            if not _write_worker_metadata(instance_path, stale_data):
                return inconsistent(
                    "Dead legacy worker could not be recorded as stale."
                )
            status["worker_data"] = stale_data
        if not release_workers_lock(
            instance_path,
            expected_legacy_pid=legacy_pid,
        ):
            return inconsistent("Dead legacy worker lock could not be released safely.")
        status["lock_data"] = None
        status["lifecycle_state"] = (
            recorded_state
            if recorded_state in {"stopped", "failed", "stale"}
            else "stale"
        )
        status["diagnostics"].append("Removed a dead legacy worker lock.")
        return status

    return inconsistent(f"Unsupported workers.lock state: {lock_state!r}.")


def print_worker_status(instance_path: Path) -> bool:
    """Print a human-readable worker status summary to stdout."""
    sep = "=" * 70
    print(f"[workers] Status for instance: {instance_path}")
    print(sep)
    status = get_worker_status(instance_path)

    meta = status["metadata"]
    if meta:
        print(f"  Manager name    : {meta.get('manager_name', 'N/A')}")
        print(f"  Instance created: {meta.get('created_at', 'N/A')}")

    wd = status["worker_data"]
    if wd:
        print("\n  Worker configuration:")
        print(f"    Factory PID    : {wd.get('factory_pid', 'N/A')}")
        print(f"    Factory PGID   : {wd.get('factory_pgid', 'N/A')}")
        print(f"    Recorded status: {wd.get('status', 'unknown')}")
        print(f"    Batch type     : {wd.get('batch_type', 'N/A')}")
        print(f"    Workers        : {wd.get('workers', 'N/A')}")
        print(f"    Cores/worker   : {wd.get('cores_per_worker', 'N/A')}")
    else:
        print("\n  No worker metadata found.")

    print(f"\n  Lifecycle state : {status['lifecycle_state']}")
    print(f"  Liveness source : {status['liveness_source']}")
    print(f"  Process/group alive: {'Yes' if status['process_running'] else 'No'}")
    print(f"  State consistent: {'Yes' if status['consistent'] else 'No'}")
    for diagnostic in status["diagnostics"]:
        print(f"  Note             : {diagnostic}")

    log_file = instance_path / "logs" / "vine_factory.stdout"
    if log_file.exists():
        print("\n" + sep)
        print("  Last 20 lines of vine_factory.stdout:")
        print(sep)
        try:
            out = subprocess.run(
                ["tail", "-n", "20", str(log_file)],
                capture_output=True,
                text=True,
                check=True,
            )
            print(out.stdout)
        except Exception as e:
            print(f"  [error] Could not read log: {e}")
    else:
        print(f"\n  Log file not found: {log_file}")
    print(sep)
    return status["consistent"]


# -----------------------------------------------------------------------------
# Private Helpers
# -----------------------------------------------------------------------------


def _normalize_compute_specs(
    cli_args,
    metadata: Dict,
    worker_pack: Optional[str] = None,
) -> Dict:
    """Resolve worker settings from all sources into one flat dict.

    Precedence (lowest → highest): defaults → saved metadata → compute spec YAML → CLI.
    """
    cfg: Dict = {
        "batch_type": "local",
        "min_workers": 1,
        "max_workers": 5,
        "cores": 1,
        "disk": None,
        "memory": None,
        "foremen_name": None,
        "workers_per_cycle": None,
        "tasks_per_worker": None,
        "timeout": None,
        "worker_extra_options": None,
        "condor_requirements": None,
        "poncho_env": worker_pack,
        "batch_options": None,
        "debug_workers": False,
    }

    saved = metadata.get("cli_args", {})
    _merge(
        cfg,
        {
            "batch_type": saved.get("batch_type"),
            "max_workers": saved.get("workers"),
            "cores": saved.get("cores_per_worker"),
            "batch_options": saved.get("batch_options"),
        },
    )

    compute_spec = _attr(cli_args, "compute_spec") or saved.get("compute_spec")
    if compute_spec:
        try:
            with open(compute_spec) as f:
                vf = (yaml.safe_load(f) or {}).get("vine_factory_config", {})
            _merge(
                cfg,
                {
                    "min_workers": vf.get("min-workers"),
                    "max_workers": vf.get("max-workers"),
                    "cores": vf.get("cores"),
                    "disk": vf.get("disk"),
                    "memory": vf.get("memory"),
                    "foremen_name": vf.get("foremen-name"),
                    "workers_per_cycle": vf.get("workers-per-cycle"),
                    "tasks_per_worker": vf.get("tasks-per-worker"),
                    "timeout": vf.get("timeout"),
                    "worker_extra_options": vf.get("worker-extra-options"),
                    "condor_requirements": vf.get("condor-requirements"),
                },
            )
        except FileNotFoundError:
            print(f"[workers] Error: compute spec '{compute_spec}' not found.")
            sys.exit(1)
        except Exception as e:
            print(f"[workers] Error reading compute spec: {e}")
            sys.exit(1)

    _merge(
        cfg,
        {
            "batch_type": _attr(cli_args, "batch_type"),
            "max_workers": _attr(cli_args, "workers"),
            "cores": _attr(cli_args, "cores_per_worker"),
            "batch_options": _attr(cli_args, "batch_options"),
            "debug_workers": _attr(cli_args, "debug_workers"),
            "transfer_port": (
                normalize_worker_transfer_ports(
                    _attr(cli_args, "worker_transfer_ports")
                )
                if _attr(cli_args, "worker_transfer_ports")
                else None
            ),
        },
    )

    return cfg


def _merge(cfg: Dict, overrides: Dict) -> None:
    """Update cfg in-place with non-None values from overrides."""
    for k, v in overrides.items():
        if v is not None:
            cfg[k] = v


def _attr(obj, key):
    """Get key from a dict or attribute from a Namespace; None if absent."""
    if obj is None:
        return None
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)


def _start_vine_factory(
    manager_name: str,
    cfg: Dict,
    run_dir: str = "/tmp/",
    scratch_dir: str = "/tmp/",
    manager_env_dir: Optional[str] = None,
    instance_env: Optional[Dict] = None,
    detached: bool = False,
) -> object:
    """Launch vine_factory with settings from cfg. Returns a Popen handle."""
    vine_factory_args = [
        f"-T{cfg['batch_type']}",
        f"--scratch-dir={scratch_dir}",
        f"--manager-name={manager_name}",
        f"--min-workers={cfg['min_workers']}",
        f"--max-workers={cfg['max_workers']}",
        f"--cores={cfg['cores']}",
    ]

    for flag, key in [
        ("--disk", "disk"),
        ("--memory", "memory"),
        ("--foremen-name", "foremen_name"),
        ("--workers-per-cycle", "workers_per_cycle"),
        ("--tasks-per-worker", "tasks_per_worker"),
        ("--timeout", "timeout"),
        ("--worker-extra-options", "worker_extra_options"),
        ("--condor-requirements", "condor_requirements"),
        ("--transfer-port", "transfer_port"),
    ]:
        if cfg.get(key):
            vine_factory_args.append(f"{flag}={cfg[key]}")

    if cfg.get("poncho_env"):
        vine_factory_args.append(f"--poncho-env={cfg['poncho_env']}")
    if cfg.get("batch_options"):
        vine_factory_args.append(f"--batch-options={cfg['batch_options']}")
    if cfg.get("debug_workers"):
        vine_factory_args.append("--debug-workers")

    if manager_env_dir:
        vine_factory_path = os.path.join(manager_env_dir, "bin", "vine_factory")
        cmd = [
            get_conda_executable(),
            "run",
            "--prefix",
            manager_env_dir,
            "--no-capture-output",
            vine_factory_path,
            *vine_factory_args,
        ]
        print(f"[workers] Using manager env for vine_factory: {manager_env_dir}")
    else:
        cmd = ["vine_factory", *vine_factory_args]

    stdout_file = os.path.join(run_dir, "vine_factory.stdout")
    print(f"[workers] Launching: {' '.join(cmd)}")
    print(f"[workers] stdout  : {os.path.abspath(stdout_file)}")

    stderr_file = None
    if detached:
        stderr_file = os.path.join(run_dir, "vine_factory.stderr")
        print(f"[workers] stderr  : {os.path.abspath(stderr_file)}")

    try:
        stdout_fh = open(stdout_file, "w")
    except OSError as e:
        raise RuntimeError(f"Could not open vine_factory log file: {e}") from e

    stderr_fh = None
    try:
        if stderr_file:
            stderr_fh = open(stderr_file, "w")
        proc = subprocess.Popen(
            cmd,
            stdout=stdout_fh,
            stderr=stderr_fh if stderr_fh is not None else subprocess.PIPE,
            text=True,
            preexec_fn=os.setsid,
            env=instance_env or os.environ.copy(),
        )
    except FileNotFoundError:
        stdout_fh.close()
        if stderr_fh is not None:
            stderr_fh.close()
        raise RuntimeError("'vine_factory' not found in PATH.")
    except Exception as e:
        stdout_fh.close()
        if stderr_fh is not None:
            stderr_fh.close()
        raise RuntimeError(f"Unexpected error launching vine_factory: {e}") from e

    stdout_fh.close()
    if stderr_fh is not None:
        stderr_fh.close()

    if not detached:
        threading.Thread(target=_stream_stderr, args=(proc,), daemon=True).start()
    return proc


def _stream_stderr(proc) -> None:
    for line in proc.stderr:
        print(f"[workers] vine_factory: {line.strip()}")


def _terminate_failed_factory(proc, factory_pgid: Optional[int]) -> None:
    """Best-effort cleanup when factory startup cannot be committed."""
    try:
        if factory_pgid and factory_pgid != os.getpgrp():
            os.killpg(factory_pgid, signal.SIGTERM)
        else:
            proc.terminate()
    except ProcessLookupError:
        pass
    except Exception as error:
        print(f"[workers] Warning: could not stop failed factory launch: {error}")


def _instance_metadata_file(instance_path: Path) -> Path:
    return instance_path / "metadata" / "run.json"


def _workers_metadata_file(instance_path: Path) -> Path:
    return instance_path / "metadata" / "workers.json"


def _read_instance_metadata(instance_path: Path) -> Optional[Dict]:
    mf = _instance_metadata_file(instance_path)
    if not mf.exists():
        print(f"[workers] Error: no metadata found at {mf}")
        return None
    try:
        with open(mf) as f:
            return json.load(f)
    except Exception as e:
        print(f"[workers] Error reading metadata: {e}")
        return None


def _write_worker_metadata(instance_path: Path, worker_data: Dict) -> bool:
    mf = _workers_metadata_file(instance_path)
    temporary_path = None
    try:
        mf.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_path = tempfile.mkstemp(
            prefix=f".{mf.name}.",
            suffix=".tmp",
            dir=mf.parent,
        )
        with os.fdopen(fd, "w") as stream:
            json.dump(worker_data, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, mf)
        temporary_path = None
        return True
    except Exception as e:
        print(f"[workers] Warning: could not write worker metadata: {e}")
        return False
    finally:
        if temporary_path:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass


def _read_worker_metadata(instance_path: Path) -> Optional[Dict]:
    mf = _workers_metadata_file(instance_path)
    if not mf.exists():
        return None
    try:
        with open(mf) as f:
            return json.load(f)
    except Exception as e:
        print(f"[workers] Warning: could not read worker metadata: {e}")
        return None
