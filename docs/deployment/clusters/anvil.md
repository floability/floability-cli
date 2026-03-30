# Anvil Deployment

This page documents known working practices for running Floability on Anvil.

First, follow the basic flow in [Run your first backpack](../../getting-started/run-first-backpack.md).

## Recommended Start

Run from an Anvil login node:

```bash
floability run --backpack <backpack-root> --batch-type slurm
```

Notebook/Jupyter runs on the login node.
Distributed tasks are submitted through `vine_factory` to Slurm workers.

Anvil uses Slurm, so use `--batch-type slurm`.

## Manager Ports

We could not find a published Anvil document that clearly lists which manager communication ports are open.
In our tests, the following range worked:

```bash
floability run --backpack <backpack-root> --batch-type slurm --manager-ports 35000,40000
```

## Data Location

We recommend storing large data/cache content in scratch space.

Example:

```bash
floability run --backpack <backpack-root> --batch-type slurm \
	--data-cache-dir /anvil/scratch/<username>/floability-cache-base-dir
```

## Slurm Partition (Queue) Selection

On some jobs, you may need to specify a Slurm partition explicitly.
Use `--batch-options` to pass scheduler options to `vine_factory`.

Example:

```bash
floability run --backpack <backpack-root> --batch-type slurm \
	--batch-options "-p wide"
```

For other partition/queue options, see:
https://www.rcac.purdue.edu/knowledge/anvil/run/partitions

## Checklist

- Activate environment on the login node.
- Confirm Slurm queue/account settings.
- Add site-specific `--batch-options` if required.

## If It Fails

See [Deployment Overview](../index.md) and [Troubleshooting](../../how-to/troubleshooting.md).
