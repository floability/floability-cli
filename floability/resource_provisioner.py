import subprocess
import sys
import os
import threading
import yaml


def start_vine_factory(
    batch_type: str,
    manager_name: str,
    min_workers: int = 1,
    max_workers: int = 1,
    cores_per_worker: int = 1,  # todo: remove from args, only allow from yml file
    poncho_env: str = None,
    scratch_dir: str = "/tmp/",
    run_dir: str = "/tmp/",
    batch_options: str = None,
    config_yml: str = None,
    debug_workers: bool = False,
):
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
                new_min_workers = vf_config["min-workers"]
                if new_min_workers > min_workers:
                    min_workers = new_min_workers
                cmd.append(f"--min-workers={min_workers}")
            if "max-workers" in vf_config:
                new_max_workers = vf_config["max-workers"]
                if new_max_workers > max_workers:
                    max_workers = new_max_workers
                cmd.append(f"--max-workers={max_workers}")

            if "cores" in vf_config:
                cores_per_worker = vf_config["cores"]
                cmd.append(f"--cores={cores_per_worker}")
            if "disk" in vf_config:
                disk_per_worker = vf_config["disk"]
                cmd.append(f"--disk={disk_per_worker}")
            if "memory" in vf_config:
                memory_per_worker = vf_config["memory"]
                cmd.append(f"--memory={memory_per_worker}")

            foremen_name = vf_config.get("foremen-name")
            if foremen_name:
                cmd.append(f"--foremen-name={foremen_name}")

            workers_per_cycle = vf_config.get("workers-per-cycle")
            if workers_per_cycle:
                cmd.append(f"--workers-per-cycle={workers_per_cycle}")

            tasks_per_worker = vf_config.get("tasks-per-worker")
            if tasks_per_worker:
                cmd.append(f"--tasks-per-worker={tasks_per_worker}")

            timeout = vf_config.get("timeout")
            if timeout:
                cmd.append(f"--timeout={timeout}")

            worker_extra_options = vf_config.get("worker-extra-options")
            if worker_extra_options:
                cmd.append(f"--worker-extra-options={worker_extra_options}")

            condor_requirements = vf_config.get("condor-requirements")
            if condor_requirements:
                cmd.append(f"--condor-requirements={condor_requirements}")

        except FileNotFoundError:
            print(f"[provision] Error: Cluster config file '{config_yml}' not found.")
            sys.exit(1)
        except Exception as e:
            print(f"[provision] Unexpected error loading cluster config: {e}")
            sys.exit(1)

    if poncho_env:
        # from vine_factory help: --poncho-env=<file.tar.gz>
        cmd.append(f"--poncho-env={poncho_env}")

    if batch_options:
        # from vine_factory help: --batch-options=<file>
        cmd.append(f"--batch-options={batch_options}")

    if debug_workers:
        # from vine_factory help: --debug-workers
        cmd.append("--debug-workers")

    print(f"[provision] Launching vine_factory: {' '.join(cmd)}")

    try:
        stdout_file = os.path.join(run_dir, "vine_factory.stdout")

        print(f"[provision] vine_factory stdout: {os.path.abspath(stdout_file)}")

        with open(stdout_file, "w") as stdout:
            proc = subprocess.Popen(
                cmd,
                stdout=stdout,
                stderr=subprocess.PIPE,
                text=True,
                preexec_fn=os.setsid,
            )

            # stderr=stdout, #todo: parse this error for better error handling
            def print_stderr(proc):
                for line in proc.stderr:
                    print(f"[provision] vine_factory error: {line.strip()}")

            # Start a thread to print stderr
            stderr_thread = threading.Thread(target=print_stderr, args=(proc,))
            stderr_thread.start()

            return proc
    except FileNotFoundError:
        print("[provision] Error: 'vine_factory' not found in PATH.")
        sys.exit(1)
    except Exception as e:
        print(f"[provision] Unexpected error launching vine_factory: {e}")
        sys.exit(1)
