# Following is a sample execution of this script:

import argparse
import shutil
import os
import subprocess
import signal
import nbformat
import time
from jupyter_client.kernelspec import KernelSpecManager

from .tracing_code import get_code_to_add
from .generate_requirements import main as generate_requirements
from .generate_verified_environment_yaml import (
    main as generate_verified_env_yaml,
)
from .generate_data_deps import main as generate_data_deps
from .generate_cell_level_dependencies import (
    main as generate_cell_level_dependencies,
)

def update_notebook_kernel(notebook_path, kernel_name):
    # Load available kernels
    ksm = KernelSpecManager()
    kernels = ksm.find_kernel_specs()

    if kernel_name not in kernels:
        raise ValueError(f"Kernel '{kernel_name}' not found. Available kernels: {list(kernels.keys())}")

    # Load kernel spec info
    spec = ksm.get_kernel_spec(kernel_name)
    
    # Load notebook
    with open(notebook_path, 'r', encoding='utf-8') as f:
        nb = nbformat.read(f, as_version=4)

    # Update metadata
    nb.metadata.kernelspec = {
        "name": kernel_name,
        "display_name": spec.display_name,
        "language": spec.language
    }

    # Save updated notebook
    with open(notebook_path, 'w', encoding='utf-8') as f:
        nbformat.write(nb, f)


# use nbformat to add the code to the top of the notebook
def add_code_to_notebook(notebook_path, code):
    """
    Add code to the top of a Jupyter notebook.
    """
    with open(notebook_path, 'r') as f:
        nb = nbformat.read(f, as_version=4)

    # Create a new code cell
    new_cell = nbformat.v4.new_code_cell(code)
    
    # Insert the new cell at the beginning
    nb.cells.insert(0, new_cell)

    # Write the modified notebook back to the file
    with open(notebook_path, 'w') as f:
        nbformat.write(nb, f)

def audit(notebook_path, kernel_name, manager_name, manager_port):
     
    tmp_dir = os.getcwd() + "/tmp"
    os.makedirs(tmp_dir, exist_ok=True)

    strace_worker = tmp_dir + "/strace_worker.txt"
    strace_manager = tmp_dir + "/strace_manager.txt"
    open_trace_log = tmp_dir + "/open_trace.log"
    start_file = tmp_dir + "/7ffdc7bb937.txt"
    end_file = tmp_dir + "/89101756618.txt"

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

    code_to_add = get_code_to_add().replace("open_trace_log", open_trace_log)
    code_to_add = code_to_add.replace("start_file", start_file) 
    code_to_add = code_to_add.replace("end_file", end_file)
    add_code_to_notebook(notebook_copy_path, code_to_add)
    print("Added code to the top of the notebook.")

    # update notebook kernel
    if kernel_name:
        try:
            update_notebook_kernel(notebook_copy_path, kernel_name)
        except ValueError as e:
            print(f"Error updating notebook kernel: {kernel_name}")
            return

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
                "trace=openat,fstat,newfstatat,write",
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
                "trace=openat,fstat,newfstatat,write",
                "vine_worker",
                "localhost",
                manager_port,
            ],
            start_new_session=True,
        )
    worker_pid = p_worker.pid
    print("worker_pid:", worker_pid)

    start = time.time()

    
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
            "trace=openat,fstat,newfstatat,write",
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

    # Find the dependencies and generate YAML file
    generate_requirements(strace_manager, strace_worker)


    # find data dependencies and generate txt file
    generate_data_deps(open_trace_log, strace_manager, strace_worker)
    print("time taken to generate data dep file: ", time.time() - start)

    # find cell level dependencies and generate yml file
    generate_cell_level_dependencies(strace_manager, notebook_name, open_trace_log)

    # Generate verified YAML files for worker and manager
    generate_verified_env_yaml(
        "worker_requirements.txt", output="worker_environment.yml"
    )

    generate_verified_env_yaml(
        "manager_requirements.txt", output="manager_environment.yml"
    )

    print("Generated verified YAML files for worker and manager.")

    print("time taken to generate verified YAML files: ", time.time() - start)