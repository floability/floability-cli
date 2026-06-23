# jupyter_runner.py

import subprocess
import threading
import sys
import os
import time
import re

from .utils import get_system_information


def print_instructions_for_accessing_jupyter(port, token, stdout_file):
    system_info = get_system_information()
    ip_address = system_info.get("access_address", "remote.yourdomain.edu")
    username = system_info.get("username", "user")
    
    print(f"[jupyter] Detected JupyterLab URL with port {port} and token {token}.")

    instructions = f"""[jupyter] JupyterLab is running on port {port} on {ip_address}.
    
    You can access it using one of the following URLs:
    local:  http://localhost:{port}/lab/?token={token}
    remote: http://{ip_address}:{port}/lab/?token={token}
    
    If you are on a remote machine and it doesn't allow direct access to the port, you can create an SSH tunnel:
    
    1. Open a terminal and run the following command:
       ssh -L localhost:{port}:localhost:{port} {username}@{ip_address}
       
    2. Open a web browser and enter the following URL:
       http://localhost:{port}/lab/?token={token}
    """

    if stdout_file:
        instructions += (
            f"\n[jupyter] You can access full jupyterlab log at {stdout_file}\n"
        )

    print(f"\n{instructions}")


def monitor_stdout(stdout_file):
    with open(stdout_file, "r") as f:
        while True:
            line = f.readline()
            if "http://" in line or "https://" in line:
                url = line.strip()
                port_match = re.search(r":(\d+)/", url)
                port = port_match.group(1) if port_match else "N/A"
                token_match = re.search(r"token=([a-zA-Z0-9]+)", url)
                token = token_match.group(1) if token_match else "N/A"

                # todo: verify this approach of getting port and token

                print_instructions_for_accessing_jupyter(port, token, stdout_file)

                break
            else:
                time.sleep(1)


def start_jupyterlab(
    notebook_path: str = None,
    port: int = 8888,
    jupyter_ip: str = "0.0.0.0",
    run_dir: str = "/tmp",
    conda_env_dir: str = None,
    working_dir: str = None,
    extra_env: dict = None,
):

    cmd = [
        "jupyter",
        "lab",
        "--no-browser",
        "--port",
        str(port),
        "--ip",
        jupyter_ip,
        "--allow-root",
    ]
    if notebook_path:
        cmd.append(notebook_path)

    print(
        f"[jupyter] Starting JupyterLab on port {port} if available. Correct port will be displayed after starting."
    )
    print(f"[jupyter] Notebook: {notebook_path if notebook_path else '(none)'}")

    if working_dir:
        print(f"[jupyter] Working directory: {working_dir}")

    if conda_env_dir:
        # Use conda run to start JupyterLab within the extracted environment
        cmd = ["conda", "run", "--prefix", conda_env_dir, "--no-capture-output"] + cmd

    try:
        stdout_file = os.path.join(run_dir, "jupyterlab.stdout")

        print(f"[jupyter] JupyterLab stdout: {os.path.abspath(stdout_file)}")

        # note: conda run opens a temporary bash process to run the command.
        # This bash process is the parent of the jupyterlab process.
        # os.setsid creates a new process group so cleanup.py can kill the entire group.
        with open(stdout_file, "w") as stdout:
            proc = subprocess.Popen(
                cmd,
                env=extra_env,
                stdout=stdout,
                stderr=stdout,
                text=True,
                cwd=working_dir,
                # preexec_fn=os.setsid,
            )

            print(
                f"[jupyter] JupyterLab process started with PID {proc.pid} and PGID {os.getpgid(proc.pid)}"
            )

            monitor_thread = threading.Thread(
                target=monitor_stdout, args=(stdout_file,)
            )
            monitor_thread.start()

            return proc
    except FileNotFoundError:
        print("[jupyter] Error: 'jupyter' not found in your PATH.")
        sys.exit(1)
    except Exception as e:
        print(f"[jupyter] Failed to start JupyterLab: {e}")
        sys.exit(1)


def execute_notebook(
    notebook_path: str = None,
    run_dir: str = "/tmp",
    conda_env_dir: str = None,
    working_dir: str = None,
    extra_env: dict = None,
):

    cmd = [
        "jupyter",
        "nbconvert",
        "--to",
        "notebook",
        "--execute",
        "--inplace",
        notebook_path,
    ]

    if conda_env_dir:
        # Use conda run to start JupyterLab within the extracted environment
        cmd = ["conda", "run", "--prefix", conda_env_dir, "--no-capture-output"] + cmd

    try:
        stdout_file = os.path.join(run_dir, "jupyterlab.stdout")

        print(f"[jupyter] JupyterLab stdout: {os.path.abspath(stdout_file)}")

        if working_dir:
            print(f"[jupyter] Executing notebook from working directory: {working_dir}")

        with open(stdout_file, "w") as stdout:
            proc = subprocess.Popen(
                cmd,
                env=extra_env,
                stdout=stdout,
                stderr=stdout,
                text=True,
                cwd=working_dir,
            )

            proc.wait()  # Wait for the process to complete

            if proc.returncode == 0:
                print(f"[jupyter] Notebook executed successfully: {notebook_path}")
                return True
            else:
                print(f"[jupyter] Error executing notebook: {notebook_path}")
                return False
    except FileNotFoundError:
        print("[jupyter] Error: 'jupyter' not found in your PATH.")
        sys.exit(1)
    except Exception as e:
        print(f"[jupyter] Failed to execute notebook: {e}")
        sys.exit(1)
