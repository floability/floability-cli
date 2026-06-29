import os
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Dict, Optional

import nbformat
from jupyter_client.kernelspec import KernelSpecManager

from floability.audit.generate_requirements import main as generate_requirements
from floability.audit.generate_verified_env_yaml import (
    main as generate_verified_env_yaml,
)
from floability.audit.generate_data_deps import main as generate_data_deps
from floability.audit.log_data_deps import get_code_to_log_data_deps


def update_notebook_kernel(notebook_path, kernel_name):
    ksm = KernelSpecManager()
    kernels = ksm.find_kernel_specs()

    if kernel_name not in kernels:
        raise ValueError(
            f"Kernel '{kernel_name}' not found. Available kernels: {list(kernels.keys())}"
        )

    spec = ksm.get_kernel_spec(kernel_name)

    with open(notebook_path, "r", encoding="utf-8") as f:
        nb = nbformat.read(f, as_version=4)

    nb.metadata.kernelspec = {
        "name": kernel_name,
        "display_name": spec.display_name,
        "language": spec.language,
    }

    with open(notebook_path, "w", encoding="utf-8") as f:
        nbformat.write(nb, f)


def add_code_to_notebook(notebook_path, code):
    """Add code to the top of a Jupyter notebook."""
    with open(notebook_path, "r") as f:
        nb = nbformat.read(f, as_version=4)

    new_cell = nbformat.v4.new_code_cell(code)
    nb.cells.insert(0, new_cell)

    with open(notebook_path, "w") as f:
        nbformat.write(nb, f)


def _build_vine_worker_cmd(
    strace_out: Path,
    manager_name: Optional[str],
    manager_port: Optional[str],
    conda_env: Optional[str],
) -> list:
    """Build the strace-wrapped vine_worker command."""
    strace_prefix = [
        "strace", "-qqq", "-r", "-z", "-f",
        "-o", str(strace_out),
        "-e", "trace=openat,fstat,newfstatat",
    ]

    if conda_env:
        worker_cmd = ["conda", "run", "--prefix", conda_env, "--no-capture-output", "vine_worker", "localhost"]
    else:
        worker_cmd = ["vine_worker", "localhost"]

    if manager_name:
        worker_cmd += ["-M", manager_name]
    else:
        worker_cmd += [manager_port]

    return strace_prefix + worker_cmd


def audit(notebook_path, kernel_name, manager_name, manager_port, conda_env=None, data_dirs=None, no_worker=False) -> Dict[str, Path]:
    """
    Audit a Jupyter notebook for software and data dependencies.

    Args:
        notebook_path: Path to the Jupyter notebook to audit.
        kernel_name: Kernel name to use (or None for notebook default).
        manager_name: TaskVine manager name (or None to use manager_port).
        manager_port: TaskVine manager port.
        conda_env: Path to a conda environment prefix used to run both
                   vine_worker and jupyter execute. When None, uses PATH.
        data_dirs: List of directory paths (relative to notebook dir or absolute)
                   containing data files. When provided, strace is scanned
                   directly for files under those paths.

    Returns a dict with paths to all generated output files:
      - strace_manager: manager strace log
      - strace_worker: worker strace log
      - manager_environment_yml: manager_environment.yml
      - worker_environment_yml: worker_environment.yml
      - manager_data_dependencies_yml: manager_data_dependencies.yml
      - worker_data_dependencies_yml: worker_data_dependencies.yml
    """
    cwd = Path.cwd()
    tmp_dir = cwd / "tmp"
    tmp_dir.mkdir(exist_ok=True)

    strace_worker = tmp_dir / "strace_worker.txt"
    strace_manager = tmp_dir / "strace_manager.txt"
    open_trace_log = tmp_dir / "open_trace.log"

    notebook_path = notebook_path.strip()
    if kernel_name:
        kernel_name = kernel_name.strip()
    if manager_port:
        manager_port = manager_port.strip()
    if manager_name:
        manager_name = manager_name.strip()

    notebook_dir = Path(notebook_path).resolve().parent
    notebook_name = Path(notebook_path).name
    notebook_copy_path = str(notebook_dir / f"copy_{notebook_name}")

    shutil.copy(notebook_path, notebook_copy_path)
    print("Created temp copy of the notebook: ", notebook_name)

    code_to_add = get_code_to_log_data_deps().replace("open_trace_log", str(open_trace_log))
    add_code_to_notebook(notebook_copy_path, code_to_add)
    print("Added code to the top of the notebook.")

    p_worker = None
    worker_pid = None
    if not no_worker:
        print("Starting vine workers with strace...")
        worker_cmd = _build_vine_worker_cmd(strace_worker, manager_name, manager_port, conda_env)
        p_worker = subprocess.Popen(worker_cmd, start_new_session=True)
        worker_pid = p_worker.pid
        print("worker_pid:", worker_pid)
    else:
        print("Skipping vine worker (--no-worker).")

    start = time.time()

    if kernel_name:
        try:
            update_notebook_kernel(notebook_copy_path, kernel_name)
        except ValueError:
            print(f"Error updating notebook kernel: {kernel_name}")
            return {}

    print("Starting the notebook with strace... ")
    if conda_env:
        jupyter_cmd = [
            "conda", "run", "--prefix", conda_env, "--no-capture-output",
            "jupyter", "execute", notebook_copy_path,
        ]
        print(f"  Running notebook in conda env: {conda_env}")
    else:
        jupyter_cmd = ["jupyter", "execute", notebook_copy_path]

    subprocess.run(
        [
            "strace",
            "-qqq", "-r", "-z", "-f",
            "-o", str(strace_manager),
            "-e", "trace=openat,fstat,newfstatat",
        ] + jupyter_cmd,
    )
    print("time taken to execute the notebook: ", time.time() - start)

    os.remove(notebook_copy_path)
    print("Removed notebook copy.")

    if worker_pid is not None:
        os.killpg(os.getpgid(worker_pid), signal.SIGTERM)
        print("Removed vine worker process tree.")

    start = time.time()

    generate_requirements(str(strace_manager), str(strace_worker), conda_env_prefix=conda_env)

    manager_env_yml = cwd / "manager_environment.yml"
    worker_env_yml = cwd / "worker_environment.yml"

    generate_verified_env_yaml(
        "worker_requirements.txt", output=str(worker_env_yml), conda_prefix=conda_env
    )
    generate_verified_env_yaml(
        "manager_requirements.txt", output=str(manager_env_yml), conda_prefix=conda_env
    )

    print("Generated verified YAML files for worker and manager.")
    print("time taken to generate verified YAML files: ", time.time() - start)

    start = time.time()

    manager_data_deps_yml = cwd / "manager_data_dependencies.yml"
    worker_data_deps_yml = cwd / "worker_data_dependencies.yml"

    resolved_data_dirs = None
    if data_dirs:
        resolved_data_dirs = [
            str((notebook_dir / d).resolve()) if not Path(d).is_absolute() else d
            for d in data_dirs
        ]
        print(f"[floability] Scanning strace for data files under: {resolved_data_dirs}")

    consolidated_data_deps = generate_data_deps(
        str(open_trace_log),
        str(strace_manager),
        str(strace_worker),
        data_dirs=resolved_data_dirs,
        notebook_dir=str(notebook_dir),
    )
    print("time taken to generate data dep file: ", time.time() - start)

    return {
        "strace_manager": strace_manager,
        "strace_worker": strace_worker,
        "manager_environment_yml": manager_env_yml,
        "worker_environment_yml": worker_env_yml,
        "manager_data_dependencies_yml": manager_data_deps_yml,
        "worker_data_dependencies_yml": worker_data_deps_yml,
        "consolidated_data_deps": consolidated_data_deps,
        "notebook_dir": notebook_dir,
    }
