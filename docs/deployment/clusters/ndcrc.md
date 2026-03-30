# NDCRC Deployment

This page documents known working practices for running Floability on NDCRC.

First, follow the basic flow in [Run your first backpack](../../getting-started/run-first-backpack.md).

## Recommended Start

Run from an NDCRC login node:

```bash
floability run --backpack <backpack-root> --batch-type condor
```

Notebook/Jupyter runs on the login node.
Distributed tasks are submitted through `vine_factory` to worker slots.

## Batch Systems on NDCRC

NDCRC supports two scheduler modes for Floability workers:

- HTCondor: use `--batch-type condor`
- UGE/SGE: use `--batch-type uge`

Examples:

```bash
# HTCondor
floability run --backpack <backpack-root> --batch-type condor

# UGE/SGE
floability run --backpack <backpack-root> --batch-type uge
```

## Manager Port Range

NDCRC requires manager communication ports in the `9000-10000` range.
Floability defaults to `9123,9150`, which is already in that range, so no change is required in most cases.

If you need to customize it, use `--manager-ports`:

```bash
floability run --backpack <backpack-root> --batch-type condor --manager-ports 9200,9800
```

## Storage Guidance (Home Directory Limits)

Many ND users have a `100GB` home directory quota, which may be too small for large workflow data.

Use one of these options:

- change only data cache location with `--data-cache-dir`
- move the full Floability instance root with `--base-dir`

Examples:

```bash
# Keep instance in default location, move only data cache
floability run --backpack <backpack-root> --batch-type condor \
	--data-cache-dir /scratch/<username>/floability-data-cache

# Move entire Floability base directory (instances + metadata + default cache)
floability run --backpack <backpack-root> --batch-type condor \
	--base-dir /scratch/<username>/floability-base-dir
```

## Checklist

- Load/activate your environment on the login node.
- Confirm outbound/inbound connectivity required by your site policy.
- Verify scheduler access (`condor_q`, permissions, quotas).

## If It Fails

See [Deployment Overview](../index.md) and [Troubleshooting](../../how-to/troubleshooting.md).
