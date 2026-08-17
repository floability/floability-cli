# LPC Deployment

This page documents known working practices for running Floability on LPC.

First, follow the basic flow in [Run your first backpack](../../getting-started/run-first-backpack.md).

## Recommended Start

Run from an LPC login node:

```bash
floability run --backpack <backpack-root> --batch-type condor
```

Notebook/Jupyter runs on the login node.
Distributed tasks are submitted through `vine_factory` to HTCondor workers.

## Environment Notes

At LPC, Anaconda may be blocked. Miniforge-based installation works.

If your backpack `software/environment.yml` includes the default channel, remove it and keep conda-forge-first channel usage.

## Home Directory Limits

LPC home directory quota can be very small (for example around `3GB`).
Use a different base directory so instance files, metadata, and cache are not written to home.

Example:

```bash
floability run --backpack <backpack-root> --batch-type condor \
	--base-dir /uscms_data/<username>/floability-base-dir
```

## Manager Ports

Allowed manager communication range is `10000-11000`.
Set ports explicitly:

```bash
floability run --backpack <backpack-root> --batch-type condor \
	--manager-ports 10000:11000
```
## Worker Transfer Ports
The allowed ports for worker transfer is `10000:11000`. If the `--worker-transfer-ports` option is not specified, floability will default to the range `10000:11000` while on LPC.

## SSH Tunneling Note

In some LPC environments, the IP shown in terminal output may not work for browser access.
Use the domain name of the host you SSH into.

Example:

```bash
ssh -L 8888:localhost:8888 <username>@<lpc-login-domain>
```

## Checklist

- Activate the environment on the login node.
- Verify HTCondor submission access.
- Check whether your site requires additional condor options.

## If It Fails

See [Deployment Overview](../index.md) and [Troubleshooting](../../how-to/troubleshooting.md).
