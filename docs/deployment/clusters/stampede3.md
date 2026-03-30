# Stampede3 Deployment

This page documents known working practices for running Floability on Stampede3.

First, follow the basic flow in [Run your first backpack](../../getting-started/run-first-backpack.md).

## Recommended Start

Run from a Stampede3 login node:

```bash
floability run --backpack <backpack-root> --batch-type slurm
```

Notebook/Jupyter runs on the login node.
Distributed tasks are submitted through `vine_factory` to Slurm workers.

Stampede3 uses Slurm, so use `--batch-type slurm`.

## Manager Ports

In our runs, the following manager port range worked:

```bash
floability run --backpack <backpack-root> --batch-type slurm --manager-ports 35000,40000
```

## Batch Options

You may need to provide explicit Slurm options.
Start with:

```bash
floability run --backpack <backpack-root> --batch-type slurm \
	--batch-options "-p spr -t 02:00:00"
```

Try running without this first, or use other batch options required by your allocation/policy.

Stampede3 run documentation:
https://docs.tacc.utexas.edu/hpc/stampede3/#running

## Data Location and Shared Filesystem Requirement

For TaskVine with Slurm, make sure data is on a shared filesystem visible to both login and worker nodes.

We recommend using `/work` for data/cache storage.

Example:

```bash
floability run --backpack <backpack-root> --batch-type slurm \
	--data-cache-dir /work/<project-or-user>/floability-cache-base-dir
```

## Checklist

- Activate the Floability environment on the login node.
- Confirm Slurm account/partition access.
- Validate any required `--batch-options` for your project allocation.

## If It Fails

See [Deployment Overview](../index.md) and [Troubleshooting](../../how-to/troubleshooting.md).
