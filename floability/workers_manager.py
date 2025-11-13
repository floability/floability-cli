"""Workers manager module.

Consolidates worker lifecycle and status functionality plus the
``start_vine_factory`` helper previously in ``resource_provisioner``.
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
from .state_manager import (
    acquire_workers_lock,
    release_workers_lock,
    are_workers_running,
)


def start_vine_factory(
    batch_type: str,
    manager_name: str,
    min_workers: int = 1,
    max_workers: int = 1,
    cores_per_worker: int = 1,
    poncho_env: str = None,
    scratch_dir: str = "/tmp/",
    run_dir: str = "/tmp/",
    batch_options: str = None,
    config_yml: str = None,
    debug_workers: bool = False,
):
    """Launch the ``vine_factory`` process returning a ``Popen`` handle."""
    cmd = [
        "vine_factory",
        f"-T{batch_type}",
        f"--scratch-dir={scratch_dir}",
        f"--manager-name={manager_name}",
    ]

    if config_yml:
        try:
            with open(config_yml, "r") as f:
                config = yaml.safe_load(f) or {}
            vf_config = config.get("vine_factory_config", {})

            if "min-workers" in vf_config:
                new_min = vf_config["min-workers"]
                if new_min > min_workers:
                    min_workers = new_min
                cmd.append(f"--min-workers={min_workers}")
            if "max-workers" in vf_config:
                new_max = vf_config["max-workers"]
                if new_max > max_workers:
                    max_workers = new_max
                cmd.append(f"--max-workers={max_workers}")
            if "cores" in vf_config:
                cores_per_worker = vf_config["cores"]
                cmd.append(f"--cores={cores_per_worker}")
            if "disk" in vf_config:
                cmd.append(f"--disk={vf_config['disk']}")
            if "memory" in vf_config:
                cmd.append(f"--memory={vf_config['memory']}")
            if vf_config.get("foremen-name"):
                cmd.append(f"--foremen-name={vf_config['foremen-name']}")
            if vf_config.get("workers-per-cycle"):
                cmd.append(f"--workers-per-cycle={vf_config['workers-per-cycle']}")
            if vf_config.get("tasks-per-worker"):
                cmd.append(f"--tasks-per-worker={vf_config['tasks-per-worker']}")
            if vf_config.get("timeout"):
                cmd.append(f"--timeout={vf_config['timeout']}")
            if vf_config.get("worker-extra-options"):
                cmd.append(
                    f"--worker-extra-options={vf_config['worker-extra-options']}"
                )
            if vf_config.get("condor-requirements"):
                cmd.append(f"--condor-requirements={vf_config['condor-requirements']}")
        except FileNotFoundError:
            print(f"[workers] Error: compute spec '{config_yml}' not found.")
            sys.exit(1)
        except Exception as e:
            print(f"[workers] Unexpected error reading compute spec: {e}")
            sys.exit(1)

    if poncho_env:
        cmd.append(f"--poncho-env={poncho_env}")
    if batch_options:
        cmd.append(f"--batch-options={batch_options}")
    if debug_workers:
        cmd.append("--debug-workers")

    print(f"[workers] Launching vine_factory: {' '.join(cmd)}")

    stdout_file = os.path.join(run_dir, "vine_factory.stdout")
    print(f"[workers] vine_factory stdout: {os.path.abspath(stdout_file)}")
    try:
        with open(stdout_file, "w") as stdout:
            proc = subprocess.Popen(
                cmd,
                stdout=stdout,
                stderr=subprocess.PIPE,
                text=True,
                preexec_fn=os.setsid,
            )

            def _stderr_reader(p):
                for line in p.stderr:
                    print(f"[workers] vine_factory error: {line.strip()}")

            threading.Thread(target=_stderr_reader, args=(proc,), daemon=True).start()
            return proc
    except FileNotFoundError:
        print("[workers] Error: 'vine_factory' not found in PATH.")
        sys.exit(1)
    except Exception as e:
        print(f"[workers] Unexpected error launching vine_factory: {e}")
        sys.exit(1)


# Metadata helpers ---------------------------------------------------------


def _instance_metadata_file(instance_path: Path) -> Path:
    return instance_path / "metadata" / "run.json"


def _workers_metadata_file(instance_path: Path) -> Path:
    return instance_path / "metadata" / "workers.json"


def read_instance_metadata(instance_path: Path) -> Optional[Dict]:
    mf = _instance_metadata_file(instance_path)
    if not mf.exists():
        print(f"[floability] Error: No metadata found at {mf}")
        return None
    try:
        with open(mf, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"[floability] Error reading metadata: {e}")
        return None


def write_worker_metadata(instance_path: Path, worker_data: Dict) -> None:
    mf = _workers_metadata_file(instance_path)
    try:
        with open(mf, "w") as f:
            json.dump(worker_data, f, indent=2)
        print(f"[floability] Wrote worker metadata to {mf}")
    except Exception as e:
        print(f"[floability] Warning: Could not write worker metadata: {e}")


def read_worker_metadata(instance_path: Path) -> Optional[Dict]:
    mf = _workers_metadata_file(instance_path)
    if not mf.exists():
        return None
    try:
        with open(mf, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"[floability] Warning: Could not read worker metadata: {e}")
        return None


# Lifecycle ----------------------------------------------------------------


def start_workers_for_instance(
    instance_path: Path,
    batch_type: Optional[str] = None,
    workers: Optional[int] = None,
    cores_per_worker: Optional[int] = None,
    batch_options: Optional[str] = None,
    compute_spec: Optional[str] = None,
    debug_workers: bool = False,
):
    metadata = read_instance_metadata(instance_path)
    if not metadata:
        raise ValueError("Could not read instance metadata")
    manager_name = metadata.get("manager_name")
    if not manager_name:
        raise ValueError("No manager_name found in instance metadata")

    cli_args = metadata.get("cli_args", {})
    batch_type = batch_type or cli_args.get("batch_type", "local")
    workers = workers or cli_args.get("workers", 5)
    cores_per_worker = cores_per_worker or cli_args.get("cores_per_worker", 1)
    batch_options = batch_options or cli_args.get("batch_options")
    compute_spec = compute_spec or cli_args.get("compute_spec")
    worker_environment_pack = metadata.get("worker_environment_pack")

    if not worker_environment_pack:
        print("[floability] Warning: No worker environment found in instance metadata")
        print("[floability] Workers will use system Python environment")

    logs_dir = str(instance_path / "logs")
    print(f"[floability] Starting workers for instance: {instance_path}")
    print(f"[floability] Manager name: {manager_name}")
    print(f"[floability]   Batch type: {batch_type}")
    print(f"[floability]   Workers: {workers}")
    print(f"[floability]   Cores per worker: {cores_per_worker}")
    if worker_environment_pack:
        print(f"[floability]   Worker environment: {worker_environment_pack}")

    # Lock check
    if are_workers_running(instance_path):
        print(
            "[floability] Workers already running for this instance (lock present). Aborting start."
        )
        return None

    proc = start_vine_factory(
        batch_type=batch_type,
        manager_name=manager_name,
        min_workers=1,
        max_workers=workers,
        cores_per_worker=cores_per_worker,
        poncho_env=worker_environment_pack,
        run_dir=logs_dir,
        scratch_dir=logs_dir,
        batch_options=batch_options,
        config_yml=compute_spec,
        debug_workers=debug_workers,
    )

    # Acquire workers lock
    if not acquire_workers_lock(instance_path):
        print("[floability] Failed to acquire workers lock; stopping launched factory.")
        try:
            os.kill(proc.pid, signal.SIGTERM)
        except Exception:
            pass
        return None

    write_worker_metadata(
        instance_path,
        {
            "factory_pid": proc.pid,
            "manager_name": manager_name,
            "batch_type": batch_type,
            "workers": workers,
            "cores_per_worker": cores_per_worker,
            "status": "running",
        },
    )
    print(f"[floability] Workers started successfully! PID={proc.pid}")
    return proc


def stop_workers_for_instance(instance_path: Path) -> bool:
    data = read_worker_metadata(instance_path)
    if not data:
        print("[floability] No worker metadata found. Workers may not be running.")
        return False
    pid = data.get("factory_pid")
    if not pid:
        print("[floability] No factory PID found in worker metadata")
        return False
    print(f"[floability] Stopping workers for instance {instance_path} (PID={pid})")
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"[floability] Sent SIGTERM to factory process {pid}")
    except ProcessLookupError:
        print(f"[floability] Process {pid} not found; already stopped?")
    except PermissionError:
        print(f"[floability] Permission denied to kill process {pid}")
        return False
    except Exception as e:
        print(f"[floability] Error stopping workers: {e}")
        return False
    data["status"] = "stopped"
    write_worker_metadata(instance_path, data)
    release_workers_lock(instance_path)
    return True


def get_worker_status(instance_path: Path) -> Dict:
    status = {
        "metadata": read_instance_metadata(instance_path),
        "worker_data": read_worker_metadata(instance_path),
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
    print(f"[floability] Worker status for instance: {instance_path}")
    print("=" * 70)
    status = get_worker_status(instance_path)
    meta = status["metadata"]
    if meta:
        print(f"Manager name: {meta.get('manager_name', 'N/A')}")
        print(f"Instance created: {meta.get('created_at', 'N/A')}")
    wd = status["worker_data"]
    if wd:
        print("\nWorker configuration:")
        print(f"  Factory PID: {wd.get('factory_pid', 'N/A')}")
        print(f"  Status: {wd.get('status', 'unknown')}")
        print(f"  Batch type: {wd.get('batch_type', 'N/A')}")
        print(f"  Workers: {wd.get('workers', 'N/A')}")
        print(f"  Cores per worker: {wd.get('cores_per_worker', 'N/A')}")
        print(
            f"  Process status: {'Running' if status['process_running'] else 'Not running'}"
        )
    else:
        print("\nNo worker metadata found.")
    log_file = instance_path / "logs" / "vine_factory.stdout"
    if log_file.exists():
        print("\n" + "=" * 70)
        print("Last 20 lines of vine_factory.stdout:")
        print("=" * 70)
        try:
            out = subprocess.run(
                ["tail", "-n", "20", str(log_file)],
                capture_output=True,
                text=True,
                check=True,
            )
            print(out.stdout)
        except Exception as e:
            print(f"[floability] Error reading log file: {e}")
    else:
        print(f"\nLog file not found: {log_file}")
    print("=" * 70)
