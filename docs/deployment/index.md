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

## Interactive and unattended execution

From a login node:

```bash
floability run --backpack matrix-multiplication --batch-type slurm
```

This starts Jupyter on the login node and prints the actual remote port and
token. For unattended execution with no browser or forwarded port, use:

```bash
floability execute --backpack matrix-multiplication --batch-type slurm
```

## SSH Tunneling for Jupyter

If you cannot open the Jupyter URL directly from your local machine, create an SSH tunnel.

Why this is needed:

- Jupyter runs on the cluster login node, not on your laptop.
- Many clusters block direct inbound access to notebook ports from the public internet.
- SSH tunneling securely forwards the remote Jupyter port to your local machine.

From your laptop/workstation, use the exact cluster login hostname and SSH
jump-host options that you normally use. If Floability reports remote Jupyter
port 8888:

```bash
ssh -L 8888:localhost:8888 <username>@<cluster-login-host>
```

Then open:

```text
http://localhost:8888/lab/?token=<token-from-terminal>
```

The automatically displayed IP is a connection candidate and may be private;
do not substitute it for the supported login hostname unless your site says it
is reachable. Keep these three values distinct:

- remote Jupyter port: selected by Jupyter on the login node;
- local forwarded port: any free port on your laptop; and
- SSH host: the login hostname or jump-host route used to enter the site.

When tunneling may not work directly:

- the login host in your SSH command is different from the host where Jupyter is running
- cluster policy blocks direct TCP forwarding between nodes
- port `8888` is already in use locally (pick another local port, for example `8899:localhost:8888`)
- VPN/firewall policy blocks the SSH route
- token expired because the Jupyter process restarted

In a VS Code Dev Container, forward the remote Jupyter port in the **Ports**
view. If a forwarded entry exists but does not respond, reload the window and
recreate the forwarding entry.

## Cluster Differences and Troubleshooting

Every cluster has different scheduler policies, filesystem layout, and network constraints.
General commands may need small site-specific adjustments.

We provide instructions for clusters we have tested. If your cluster still does not work, see [Troubleshooting](../how-to/troubleshooting.md).

## Site-Specific Pages

- [NDCRC](clusters/ndcrc.md)
- [Stampede3](clusters/stampede3.md)
- [Anvil](clusters/anvil.md)
- [LPC](clusters/lpc.md)
