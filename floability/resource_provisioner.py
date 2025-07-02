import subprocess
import sys
import os
import threading
import yaml


def _create_strace_wrapper_script(run_dir: str, output_file: str) -> str:
    # Ensure run_dir is an absolute path
    run_dir = os.path.abspath(run_dir)

    # If output_file is not an absolute path, make it relative to run_dir
    if not os.path.isabs(output_file):
        output_file = os.path.join(run_dir, output_file)

    # Create the directory for the output file if it doesn't exist
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    # Find the vine_worker binary and copy it to the run directory
    try:
        # Find the path to vine_worker using 'which'
        result = subprocess.run(
            ["which", "vine_worker"], capture_output=True, text=True, check=True
        )
        vine_worker_path = result.stdout.strip()

        # Copy the vine_worker binary to the run directory
        local_worker_path = os.path.join(run_dir, "vine_worker")
        subprocess.run(["cp", vine_worker_path, local_worker_path], check=True)

        # Make the local copy executable
        os.chmod(local_worker_path, 0o755)

        print(
            f"[provision] Copied vine_worker from {vine_worker_path} to {local_worker_path}"
        )
    except subprocess.CalledProcessError:
        print(
            "[provision] Error: Could not find vine_worker binary. Please ensure it's installed and in your PATH."
        )
        sys.exit(1)
    except Exception as e:
        print(f"[provision] Error copying vine_worker: {e}")
        sys.exit(1)

    # Define the path for the wrapper script (using absolute path)
    wrapper_script_path = os.path.join(run_dir, "scripts", "strace_worker.sh")
    os.makedirs(os.path.dirname(wrapper_script_path), exist_ok=True)

    # Write the wrapper script
    with open(wrapper_script_path, "w") as f:
        f.write(
            f"""#!/bin/bash
# Strace wrapper for vine_worker - created by Floability
# Captures system call traces for debugging

# Get script directory for finding local vine_worker
SCRIPT_DIR="$( cd "$( dirname "${{BASH_SOURCE[0]}}" )" && pwd )"

# Generate a unique log file using PID
LOG_FILE="{output_file}_$$.log"

# Run local vine_worker copy with strace
exec strace -qqq -r -z -f -o "${{LOG_FILE}}" \\
    -e trace=openat,fstat,newfstatat \\
    "${{SCRIPT_DIR}}/vine_worker" "$@"
"""
        )

    # Make the script executable
    os.chmod(wrapper_script_path, 0o755)

    return wrapper_script_path


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
    enable_worker_tracing: bool = False,
    worker_trace_output: str = "strace_worker.log",
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

    # If worker tracing is enabled, create a wrapper script and use it as custom worker binary
    if enable_worker_tracing:
        # Create strace wrapper script
        wrapper_script_path = _create_strace_wrapper_script(run_dir, worker_trace_output)
        
        # Tell vine_factory to use our wrapper script
        cmd.append(f"--worker-binary={wrapper_script_path}")

        if batch_type == "condor":
            wrapper_script_name = os.path.basename(wrapper_script_path)

            batch_transfer_files = f"transfer_input_files={wrapper_script_name}, vine_worker"
            
            if poncho_env:
                batch_transfer_files += f", {os.path.basename(poncho_env)}"

            if batch_options:
                # preserve user batch options
                batch_options = f"{batch_transfer_files} {batch_options}"
            else:
                batch_options = batch_transfer_files

        # Get absolute path for display in log message
        log_path = (
            worker_trace_output
            if os.path.isabs(worker_trace_output)
            else os.path.join(run_dir, worker_trace_output)
        )
        print(
            f"[provision] Worker tracing enabled. Strace logs will be in {os.path.abspath(log_path)}_*.log"
        )

    if batch_options:
        # from vine_factory help: --batch-options=<file>
        cmd.append(f"--batch-options={batch_options}")

    if debug_workers or enable_worker_tracing:
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
