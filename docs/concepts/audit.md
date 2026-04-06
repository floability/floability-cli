# Audit & Environment Capture

The `floability audit` command automatically discovers the software and data dependencies of a Jupyter notebook by executing it and recording what packages and files it uses. Instead of manually curating an `environment.yml`, you run the notebook once and Floability captures the exact environment.

## Overview

Floability executes the notebook under system-call tracing, capturing every package loaded from `site-packages` and every data file opened during execution. It separates these into manager-side (notebook process) and worker-side (TaskVine worker) dependencies, then generates verified environment YAMLs pinned to the exact installed versions in your active environment.

## Outputs

After a successful audit, the following files are written to the current directory:

| File | Description |
|------|-------------|
| `manager_environment.yml` | Conda/pip environment for the notebook manager process |
| `worker_environment.yml` | Conda/pip environment for TaskVine workers |
| `manager_data_dependencies.yml` | Data files opened by the manager, with file sizes |
| `worker_data_dependencies.yml` | Data files opened by workers, with file sizes |

These environment files can be used directly as the `software/environment.yml` in a backpack.

## Basic usage

```bash
floability audit --notebook path/to/my_notebook.ipynb
```

### Options

```bash
# Use a specific Jupyter kernel (name as shown by `jupyter kernelspec list`)
floability audit --notebook my_notebook.ipynb --kernel python3

# Connect the local worker to a named TaskVine manager
floability audit --notebook my_notebook.ipynb --manager-name my-manager

# Generate per-cell dependency breakdowns
floability audit --notebook my_notebook.ipynb --cell-level
```

## Cell-level audit

The `--cell-level` flag produces an additional `cell_level_dependencies.yml` that lists the code and data dependencies for each notebook cell individually. This is useful for understanding which cells drive which dependencies and for scoping worker environments to only the cells that run remotely.

```yaml
notebook_name: my_notebook.ipynb
cells:
  - cell_number: 1
    code_dependencies:
      - numpy==1.26.4
      - pandas==2.2.1
    data_dependencies: []
  - cell_number: 2
    code_dependencies:
      - matplotlib==3.8.4
    data_dependencies:
      - /home/user/data/input.csv
```

## Requirements

- `strace` must be available on the system (Linux only).
- `vine_worker` (from ndcctools) must be installed and on `PATH`.
- The notebook must be fully executable in the current environment before auditing.
