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
import threading
from pathlib import Path
from typing import Dict, Optional

import yaml
from .instance_lock_manager import (
    acquire_workers_lock,
    release_workers_lock,
    are_workers_running,
)


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------


def start_workers_for_instance(
    instance_path: Path,
    cli_args=None,
    env_dir: Optional[str] = None,
    instance_env: Optional[Dict] = None,
    worker_provider: str = "vine_factory",
) -> Optional[object]:
    """Start workers for an existing instance.

    Args:
        instance_path: Path to the instance directory.
        cli_args:      argparse.Namespace or dict with optional CLI overrides:
                       batch_type, workers, cores_per_worker, batch_options,
                       compute_spec, debug_workers.  Metadata fills any missing fields.
        env_dir:       Path to extracted manager conda env.  When provided,
                       vine_factory runs inside this env via ``conda run``.
        instance_env:  Subprocess env dict (from ``_build_instance_env``).
        worker_provider:   Worker backend.  Currently only ``"vine_factory"``.

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
            "[workers] Warning: no worker environment pack in metadata — workers will use system Python."
        )

    logs_dir = str(instance_path / "logs")

    cfg = _normalize_compute_specs(cli_args, metadata, worker_pack)

    print(f"[workers] Starting {worker_provider} for instance: {instance_path}")
    print(f"[workers]   Manager    : {manager_name}")
    print(
        f"[workers]   Batch type : {cfg['batch_type']}  "
        f"Workers: {cfg['max_workers']}  Cores/worker: {cfg['cores']}"
    )
    if worker_pack:
        print(f"[workers]   Worker env : {worker_pack}")

    if are_workers_running(instance_path):
        print("[workers] Workers already running (lock present). Aborting.")
        return None

    if worker_provider == "vine_factory":
        proc = _start_vine_factory(
            manager_name=manager_name,
            cfg=cfg,
            run_dir=logs_dir,
            scratch_dir=logs_dir,
            manager_env_dir=env_dir,
            instance_env=instance_env,
        )
    else:
        raise ValueError(
            f"Unknown worker_provider: {worker_provider!r}. Currently only 'vine_factory' is supported."
        )

    if not acquire_workers_lock(instance_path):
        print("[workers] Failed to acquire workers lock; stopping launched factory.")
        try:
            os.kill(proc.pid, signal.SIGTERM)
        except Exception:
            pass
        return None

    _write_worker_metadata(
        instance_path,
        {
            "factory_pid": proc.pid,
            "manager_name": manager_name,
            "batch_type": cfg["batch_type"],
            "workers": cfg["max_workers"],
            "cores_per_worker": cfg["cores"],
            "status": "running",
        },
    )

    print(f"[workers] Workers started. PID={proc.pid}")

    return proc


def stop_workers_for_instance(instance_path: Path) -> bool:
    """Send SIGTERM to the factory process and release the workers lock."""
    data = _read_worker_metadata(instance_path)
    if not data:
        print("[workers] No worker metadata found. Workers may not be running.")
        return False
    pid = data.get("factory_pid")
    if not pid:
        print("[workers] No factory PID found in worker metadata.")
        return False
    print(f"[workers] Stopping workers for instance {instance_path} (PID={pid})")
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"[workers] Sent SIGTERM to factory process {pid}.")
    except ProcessLookupError:
        print(f"[workers] Process {pid} not found; already stopped?")
    except PermissionError:
        print(f"[workers] Permission denied to kill process {pid}.")
        return False
    except Exception as e:
        print(f"[workers] Error stopping workers: {e}")
        return False
    data["status"] = "stopped"
    _write_worker_metadata(instance_path, data)
    release_workers_lock(instance_path)
    return True


def get_worker_status(instance_path: Path) -> Dict:
    """Return a status dict with metadata, worker_data, and process_running."""
    status = {
        "metadata": _read_instance_metadata(instance_path),
        "worker_data": _read_worker_metadata(instance_path),
        "process_running": False,
    }
    wd = status["worker_data"]
    if wd and wd.get("factory_pid"):
        try:
            os.kill(wd["factory_pid"], 0)
            status["process_running"] = True
        except (ProcessLookupError, PermissionError):
            status["process_running"] = False
    return status


def print_worker_status(instance_path: Path) -> None:
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
        print(f"    Status         : {wd.get('status', 'unknown')}")
        print(f"    Batch type     : {wd.get('batch_type', 'N/A')}")
        print(f"    Workers        : {wd.get('workers', 'N/A')}")
        print(f"    Cores/worker   : {wd.get('cores_per_worker', 'N/A')}")
        print(f"    Process running: {'Yes' if status['process_running'] else 'No'}")
    else:
        print("\n  No worker metadata found.")

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
) -> object:
    """Launch vine_factory with settings from cfg. Returns a Popen handle."""
    cmd = [
        "vine_factory",
        f"-T{cfg['batch_type']}",
        f"--scratch-dir={scratch_dir}",
        f"--manager-name={manager_name}",
        f"--min-workers={cfg['min_workers']}",
        f"--max-workers={cfg['max_workers']}",
        f"--cores={cfg['cores']}",
    ]

    if manager_env_dir:
        cmd = ["conda", "run", "--prefix", manager_env_dir, "--no-capture-output"] + cmd
        print(f"[workers] Using manager env for vine_factory: {manager_env_dir}")

    for flag, key in [
        ("--disk", "disk"),
        ("--memory", "memory"),
        ("--foremen-name", "foremen_name"),
        ("--workers-per-cycle", "workers_per_cycle"),
        ("--tasks-per-worker", "tasks_per_worker"),
        ("--timeout", "timeout"),
        ("--worker-extra-options", "worker_extra_options"),
        ("--condor-requirements", "condor_requirements"),
    ]:
        if cfg.get(key):
            cmd.append(f"{flag}={cfg[key]}")

    if cfg.get("poncho_env"):
        cmd.append(f"--poncho-env={cfg['poncho_env']}")
    if cfg.get("batch_options"):
        cmd.append(f"--batch-options={cfg['batch_options']}")
    if cfg.get("debug_workers"):
        cmd.append("--debug-workers")

    stdout_file = os.path.join(run_dir, "vine_factory.stdout")
    print(f"[workers] Launching: {' '.join(cmd)}")
    print(f"[workers] stdout  : {os.path.abspath(stdout_file)}")

    try:
        stdout_fh = open(stdout_file, "w")
    except OSError as e:
        print(f"[workers] Could not open log file: {e}")
        sys.exit(1)

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=stdout_fh,
            stderr=subprocess.PIPE,
            text=True,
            preexec_fn=os.setsid,
            env=instance_env or os.environ.copy(),
        )
    except FileNotFoundError:
        print("[workers] Error: 'vine_factory' not found in PATH.")
        sys.exit(1)
    except Exception as e:
        print(f"[workers] Unexpected error launching vine_factory: {e}")
        sys.exit(1)

    threading.Thread(target=_stream_stderr, args=(proc,), daemon=True).start()
    return proc


def _stream_stderr(proc) -> None:
    for line in proc.stderr:
        print(f"[workers] vine_factory: {line.strip()}")


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


def _write_worker_metadata(instance_path: Path, worker_data: Dict) -> None:
    mf = _workers_metadata_file(instance_path)
    try:
        with open(mf, "w") as f:
            json.dump(worker_data, f, indent=2)
    except Exception as e:
        print(f"[workers] Warning: could not write worker metadata: {e}")


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
