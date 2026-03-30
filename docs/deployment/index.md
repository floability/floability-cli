# Deployment

This page covers how to run Floability locally, how to submit workers to a batch system, and where to find site-specific instructions.

## Local Run

Run a backpack locally:

```bash
floability run --backpack <backpack-root> --batch-type local
```

`--batch-type local` is optional. If omitted, local is used by default.

## Running on an HPC Cluster

Run Floability from a cluster login node:

```bash
floability run --backpack <backpack-root> --batch-type slurm
```

You can also use `condor` or `uge` depending on your site.

Important behavior:

- Jupyter/notebook execution stays on the login node (inside the instance).
- Only distributed tasks are sent to cluster workers through `vine_factory`.

Supported batch types come from TaskVine `vine_factory`.
See the TaskVine manual for up-to-date backend details: https://cctools.readthedocs.io/en/latest/taskvine/

## Full Example (Run + Terminal Output)

From a login node:

```bash
floability run --backpack matrix-multiplication --batch-type slurm
```

You may see output like this:

```text
[jupyter] JupyterLab is running on port 8888 on 10.32.85.31.

	 You can access it using one of the following URLs:
	 local:  http://localhost:8888/lab/?token=9bc3277e77815110b5bd463b0c9467ad2f8eb7b60bbad97e
	 remote: http://10.32.85.31:8888/lab/?token=9bc3277e77815110b5bd463b0c9467ad2f8eb7b60bbad97e

	 If you are on a remote machine and it doesn't allow direct access to the port, you can create an SSH tunnel:

	 1. Open a terminal and run the following command:
		 ssh -L localhost:8888:localhost:8888 <username>@10.32.85.31

	 2. Open a web browser and enter the following URL:
		 http://localhost:8888/lab/?token=9bc3277e77815110b5bd463b0c9467ad2f8eb7b60bbad97e
```

## SSH Tunneling for Jupyter

If you cannot open the Jupyter URL directly from your local machine, create an SSH tunnel.

Why this is needed:

- Jupyter runs on the cluster login node, not on your laptop.
- Many clusters block direct inbound access to notebook ports from the public internet.
- SSH tunneling securely forwards the remote Jupyter port to your local machine.

From your laptop/workstation:

```bash
ssh -L 8888:localhost:8888 <username>@<cluster-login-host>
```

Then open:

```text
http://localhost:8888/lab/?token=<token-from-terminal>
```

When tunneling may not work directly:

- the login host in your SSH command is different from the host where Jupyter is running
- cluster policy blocks direct TCP forwarding between nodes
- port `8888` is already in use locally (pick another local port, for example `8899:localhost:8888`)
- VPN/firewall policy blocks the SSH route
- token expired because the Jupyter process restarted

If direct IP access fails, use the exact hostname you used to SSH into the cluster.

## Cluster Differences and Troubleshooting

Every cluster has different scheduler policies, filesystem layout, and network constraints.
General commands may need small site-specific adjustments.

We provide instructions for clusters we have tested. If your cluster still does not work, see [Troubleshooting](../how-to/troubleshooting.md).

## Site-Specific Pages

- [NDCRC](clusters/ndcrc.md)
- [Stampede3](clusters/stampede3.md)
- [Anvil](clusters/anvil.md)
- [LPC](clusters/lpc.md)