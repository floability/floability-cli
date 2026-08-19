# Distributed Matrix Multiplication

## Overview

This Floability backpack demonstrates a compact distributed TaskVine workflow.
Floability stages ten dense 200 by 200 matrices from the public
`floability/backpack-test-data` repository, and the notebook submits one task
for every unique pair of matrices. Each worker multiplies its pair, calculates
the Frobenius norm of the result, and returns a summary to the manager.

The ten inputs produce 45 independent TaskVine tasks, making this a useful
first test of environment preparation, data staging, manager discovery, worker
connectivity, file transfer, and Python task execution.

## Install Floability

Install and activate Floability by following the
[official installation instructions](https://floability.readthedocs.io/en/stable/getting-started/installation/).
Verify the installation before running the backpack:

```bash
floability --version
```

## Run the Backpack

Run these commands from the repository root. Floability prepares the software
environment, stages the matrices, launches TaskVine workers, and starts
JupyterLab. Open the URL printed in the terminal and run the notebook cells in
order. Save the notebook, then press `Ctrl+C` in the Floability terminal to
stop the interactive run and clean up its processes.

### Local workers

Omit `--batch-type` to launch workers directly on the current machine:

```bash
floability run --backpack example/matrix-multiplication
```

### HTCondor workers

```bash
floability run --backpack example/matrix-multiplication --batch-type condor
```

### Slurm workers

```bash
floability run --backpack example/matrix-multiplication --batch-type slurm
```

The selected batch system must already be installed and configured at the
execution site.

### Non-interactive execution

Use `execute` to run every notebook cell without opening a browser:

```bash
floability execute --backpack example/matrix-multiplication
```

Add `--batch-type condor` or `--batch-type slurm` to use an HPC batch system.
The executed notebook is synchronized back to the backpack by default and
contains the per-task results and final ranking.

## Expected Result

A successful run reports ten discovered matrix files, submits and completes 45
TaskVine tasks, and prints the five matrix pairs with the largest Frobenius
norms. The exact completion order and worker addresses depend on the execution
site, but every submitted task should succeed.

The number of pairwise tasks grows as `N * (N - 1) / 2`, while the cost of each
dense matrix multiplication grows approximately with the cube of the matrix
dimension. This makes the example easy to scale by changing either the number
or size of the input matrices.

## Common Options

HPC home directories often have limited quotas. Place Floability instances,
prepared environments, logs, and reusable input data on project or scratch
storage when appropriate:

```bash
floability run --backpack example/matrix-multiplication \
  --batch-type slurm \
  --base-dir "$SCRATCH/floability" \
  --data-cache-dir "$PROJECT/floability-data-cache" \
  --manager-ports 9123:9150 \
  --worker-transfer-ports 10000:11000
```

Replace `$SCRATCH` and `$PROJECT` with high-capacity locations available at
your site.

- `--base-dir PATH` changes the root for instances, prepared environments,
  packed archives, logs, and the default data cache. Without it, Floability
  uses `~/floability-base-dir`.
- `--data-cache-dir PATH` places reusable matrix inputs on a separate
  filesystem.
- `--manager-ports START:END` restricts the TaskVine manager to ports that
  workers are permitted to reach through the site's firewall.
- `--worker-transfer-ports START:END` restricts ports used for direct
  worker-to-worker transfers.

Worker counts and resource requests belong in `compute/compute.yml` so the
backpack carries its compute specification between execution sites. This
example requests 2–4 workers with one core per worker.

## Backpack Contents

- `workflow/matrix-multiplication.ipynb` — TaskVine manager setup, pairwise
  task submission, result collection, and ranking.
- `data/data.yml` — ten public matrix inputs and their workflow staging paths.
- `software/environment.yml` — pinned Python, NumPy, and TaskVine environment.
- `compute/compute.yml` — TaskVine worker limits and core requirements.
