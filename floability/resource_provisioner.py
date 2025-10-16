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
    distributed_audit: bool = False,
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

    if distributed_audit:
        print(f"[provision] DEBUG: distributed_audit is enabled")
        # Create strace logs directory
        strace_log_dir = os.path.join(scratch_dir, "strace_logs")
        print(f"[provision] DEBUG: Creating strace_log_dir: {strace_log_dir}")
        os.makedirs(strace_log_dir, exist_ok=True)

        # Create a wrapper script that uses PID for unique log files
        # We use a script because we need shell variable substitution ($$)
        wrapper_script_path = os.path.join(scratch_dir, "strace_wrapper.sh")
        strace_log_base = os.path.abspath(os.path.join(strace_log_dir, "worker"))

        print(f"[provision] DEBUG: wrapper_script_path: {wrapper_script_path}")
        print(f"[provision] DEBUG: strace_log_base: {strace_log_base}")

        # Use regular string concatenation to avoid f-string issues with $$
        wrapper_script_content = (
            "#!/bin/bash\n"
            "# Strace wrapper for distributed auditing\n"
            "# $$ will be replaced with the actual PID when executed\n"
            "exec strace -f -o " + strace_log_base + ".$$.log -e trace=open,openat,read,write,close,stat,lstat,fstat,execve \"$@\"\n"
        )

        print(f"[provision] DEBUG: wrapper_script_content length: {len(wrapper_script_content)}")
        print(f"[provision] DEBUG: wrapper_script_content:\n{wrapper_script_content}")

        try:
            print(f"[provision] DEBUG: Opening file for writing: {wrapper_script_path}")
            with open(wrapper_script_path, 'w') as f:
                bytes_written = f.write(wrapper_script_content)
                f.flush()
                os.fsync(f.fileno())
                print(f"[provision] DEBUG: Wrote {bytes_written} bytes and flushed")
            os.chmod(wrapper_script_path, 0o755)
            print(f"[provision] Wrapper script created: {wrapper_script_path} ({bytes_written} bytes)")

            # Verify it was written
            import time
            time.sleep(0.1)  # Small delay to ensure filesystem sync
            with open(wrapper_script_path, 'r') as f:
                verify_content = f.read()
                print(f"[provision] DEBUG: Verification read {len(verify_content)} bytes")
                if len(verify_content) != bytes_written:
                    print(f"[provision] WARNING: File size mismatch! Expected {bytes_written}, got {len(verify_content)}")
        except Exception as e:
            print(f"[provision] ERROR creating wrapper script: {e}")
            import traceback
            traceback.print_exc()
            raise

        # Use the wrapper script
        # NOTE: We don't use --wrapper-input because the script is already in scratch_dir
        # and vine_factory would try to copy it to itself, which creates an empty file
        wrapper_script_abs = os.path.abspath(wrapper_script_path)
        cmd.append(f"--wrapper={wrapper_script_abs}")

        print(f"[provision] Distributed audit enabled: strace logs in {os.path.abspath(strace_log_dir)}")

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
