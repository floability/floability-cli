# Run Your First Backpack

This guide walks you through running the matrix multiplication example,
a simple distributed workflow that multiplies pairs of matrices in
parallel across workers.

By the end you will have run your first backpack and understand what
each of its components does.


## Before you begin

Complete [Installation](installation.md) first. Then verify:

```bash
floability --version
```

If the command is not found, make sure `floability-env` is active:

```bash
conda activate floability-env
```



## Get the Example Backpack

Each Floability backpack is maintained in its own repository in
[Floability Hub](https://github.com/floability-hub). For this guide, clone the
`matrix-multiplication` backpack:

```bash
git clone https://github.com/floability-hub/matrix-multiplication.git
cd matrix-multiplication
```

## Run the Backpack

Because the repository itself is the backpack, run it from the repository root:

```bash
floability run --backpack .
```

If you are running this command from an HPC cluster login node, you can also specify a batch type to submit worker jobs to the cluster scheduler. For example, on a Slurm cluster:

```bash
floability run --backpack . --batch-type slurm
```

See [Deployment Overview](../deployment/index.md) for more on running on HPC clusters.

Then follow the on-screen instructions to open the Jupyter Notebook and execute the workflow.

The terminal prints the actual remote Jupyter port and a tokenized URL. From a
terminal on your laptop, forward a free local port to that remote port using
the same login hostname and jump-host options you normally use for the cluster:

```bash
# Jupyter uses remote port 8888; choose local port 8888 if it is free.
ssh -N -L 8888:localhost:8888 <username>@<cluster-login-host>
```

Then open the printed token URL with the local host and local port:

```text
http://localhost:8888/lab/?token=<token-from-floability-output>
```

The IP address printed by automatic detection is only a candidate; it may be a
private interface that your laptop cannot reach. The SSH login hostname is the
supported tunnel endpoint. If local port 8888 is occupied, use (for example)
`-L 8899:localhost:8888` and open `localhost:8899` without changing the remote
Jupyter port.

In a VS Code Dev Container, use the **Ports** view to forward the remote
Jupyter port and open the forwarded local address. Reloading the window may be
necessary if the Ports view retains a stale forwarding entry.

For unattended execution that needs no browser or port forwarding, run:

```bash
floability execute --backpack .
```


## Understanding the Backpack Structure

A backpack is a directory that contains all the components needed to run a workflow. It typically includes a workflow file, an environment file, and optional data and compute specification files. The goal is to package everything needed for a reproducible run in one place.

For example, the `matrix-multiplication` backpack has the following structure:

```
matrix-multiplication/
├── compute
│   └── compute.yml
├── data
│   └── data.yml
├── software
│   └── environment.yml
└── workflow
    └── matrix-multiplication.ipynb
```

The `environment.yml` file defines the software environment, including Python version and dependencies. The `compute.yml` file defines the compute resources needed to run the workflow. The `data.yml` file specifies input datasets and their source locations. Finally, the `matrix-multiplication.ipynb` file contains the Jupyter Notebook that implements the workflow.

To learn more about how backpacks work and how to create your own, see [Concepts → Backpacks](../concepts/backpacks.md).

To learn more about data specifications and how Floability handles datasets, see [Reference → Data Specification](../reference/data-spec.md).

## Instances (reusable sandboxes)

When you run a backpack, it does not run directly from the backpack directory.
Floability creates an instance containing the workflow sandbox, logs, metrics,
and metadata. By default, the prepared read-only environment lives under
`<base-dir>/flo_common_env/extracted_envs/` and the instance records its path;
`--per-instance-env` instead places `current_conda_env/` inside the instance.
You can reuse instances to avoid rebuilding environments and to manage runs.

During finalization, Floability copies back the files that originally came
from the backpack's `workflow/`. New outputs are copied only when selected with
`--sync-path`; use `--no-update-backpack` to disable synchronization.

## Default Directories and Caching

By default, Floability creates a directory named `floability-base-dir` in the user's home directory to store instances, Conda environments, and data files.


By default, data is cached in `<base-dir>/floability-data-cache`, which is `~/floability-base-dir/floability-data-cache` when `--base-dir` is not set.

You can change the base directory using the `--base-dir` flag when running a backpack. You can change only the data cache directory using the `--data-cache-dir` flag. For example:

```bash
floability run --backpack . --data-cache-dir /scratch/mislam/floability-data-cache
```


## Next Steps

- Learn backpack structure: [Backpacks](../concepts/backpacks.md)
- Deploy on clusters: [Deployment Overview](../deployment/index.md)
