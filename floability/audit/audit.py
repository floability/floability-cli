import shutil
import os
import subprocess
import signal
import time
import nbformat

from floability.audit.generate_requirements import main as generate_requirements
from floability.audit.generate_verified_env_yaml import (
    main as generate_verified_env_yaml,
)
from floability.audit.generate_data_deps import main as generate_data_deps
from floability.audit.log_data_deps import get_code_to_log_data_deps
from jupyter_client.kernelspec import KernelSpecManager


def update_notebook_kernel(notebook_path, kernel_name):
    # Load available kernels
    ksm = KernelSpecManager()
    kernels = ksm.find_kernel_specs()

    if kernel_name not in kernels:
        raise ValueError(
            f"Kernel '{kernel_name}' not found. Available kernels: {list(kernels.keys())}"
        )

    # Load kernel spec info
    spec = ksm.get_kernel_spec(kernel_name)

    # Load notebook
    with open(notebook_path, "r", encoding="utf-8") as f:
        nb = nbformat.read(f, as_version=4)

    # Update metadata
    nb.metadata.kernelspec = {
        "name": kernel_name,
        "display_name": spec.display_name,
        "language": spec.language,
    }

    # Save updated notebook
    with open(notebook_path, "w", encoding="utf-8") as f:
        nbformat.write(nb, f)


def add_code_to_notebook(notebook_path, code):
    """
    Add code to the top of a Jupyter notebook.
    """
    with open(notebook_path, "r") as f:
        nb = nbformat.read(f, as_version=4)

    # Create a new code cell
    new_cell = nbformat.v4.new_code_cell(code)

    # Insert the new cell at the beginning
    nb.cells.insert(0, new_cell)

    # Write the modified notebook back to the file
    with open(notebook_path, "w") as f:
        nbformat.write(nb, f)


def audit(notebook_path, kernel_name, manager_name, manager_port):
    """
    Main function to audit a Jupyter notebook for dependencies.
    """
    # Ensure the notebook path is absolute

    tmp_dir = os.getcwd() + "/tmp"
    os.makedirs(tmp_dir, exist_ok=True)

    strace_worker = tmp_dir + "/strace_worker.txt"
    strace_manager = tmp_dir + "/strace_manager.txt"
    open_trace_log = tmp_dir + "/open_trace.log"

    notebook_path = notebook_path.strip()
    if kernel_name:
        kernel_name = kernel_name.strip()

    if manager_port:
        manager_port = manager_port.strip()

    if manager_name:
        manager_name = manager_name.strip()

    notebook_name = notebook_path.split("/")[-1]
    notebook_path_str = "/".join(notebook_path.split("/")[:-1])
    if notebook_path_str != "":
        notebook_copy_path = notebook_path_str + "/copy_" + notebook_name
    else:
        notebook_copy_path = "copy_" + notebook_name
    shutil.copy(notebook_path, notebook_copy_path)
    print("Created temp copy of the notebook: ", notebook_name)

    # Add code to the top of the notebook to capture data dependencies
    code_to_add = get_code_to_log_data_deps().replace("open_trace_log", open_trace_log)

    add_code_to_notebook(notebook_copy_path, code_to_add)
    print("Added code to the top of the notebook.")

    print("Starting vine workers with strace...")
    p_worker = None
    if manager_name:
        p_worker = subprocess.Popen(
            [
                "strace",
                "-qqq",
                "-r",
                "-z",
                "-f",
                "-o",
                strace_worker,
                "-e",
                "trace=openat,fstat,newfstatat",
                "vine_worker",
                "localhost",
                "-M",
                manager_name,
            ],
            start_new_session=True,
        )
    else:
        p_worker = subprocess.Popen(
            [
                "strace",
                "-qqq",
                "-r",
                "-z",
                "-f",
                "-o",
                strace_worker,
                "-e",
                "trace=openat,fstat,newfstatat",
                "vine_worker",
                "localhost",
                manager_port,
            ],
            start_new_session=True,
        )
    worker_pid = p_worker.pid
    print("worker_pid:", worker_pid)

    start = time.time()
    # Execute the notebook in background using the specified kernel

    if kernel_name:
        try:
            # update notebook kernel
            update_notebook_kernel(notebook_copy_path, kernel_name)
        except ValueError as e:
            print(f"Error updating notebook kernel: {kernel_name}")
            return

    print("Starting the notebook with strace... ")
    p_manager = subprocess.run(
        [
            "strace",
            "-qqq",
            "-r",
            "-z",
            "-f",
            "-o",
            strace_manager,
            "-e",
            "trace=openat,fstat,newfstatat",
            "jupyter",
            "execute",
            notebook_copy_path,
        ]
    )
    print("time taken to execute the notebook: ", time.time() - start)

    # Remove the copied notebook
    os.remove(notebook_copy_path)
    print("Removed notebook copy.")

    # Shutdown processes
    os.killpg(os.getpgid(worker_pid), signal.SIGTERM)
    print("Removed vine worker process tree.")

    start = time.time()
    # Find the dependencies and generate YAML file
    generate_requirements(strace_manager, strace_worker)

    # Generate verified YAML files for worker and manager
    generate_verified_env_yaml(
        "worker_requirements.txt", output="worker_environment.yml"
    )

    generate_verified_env_yaml(
        "manager_requirements.txt", output="manager_environment.yml"
    )

    print("Generated verified YAML files for worker and manager.")

    print("time taken to generate verified YAML files: ", time.time() - start)

    start = time.time()
    # Find data dependencies and generate TXT file
    generate_data_deps(open_trace_log, strace_manager, strace_worker)
    print("time taken to generate data dep file: ", time.time() - start)
