# Troubleshooting

This page is a quick FAQ for common Floability deployment issues.

## FAQ

### Manager and workers do not connect

Use this checklist:

1. Check whether your manager is visible in the
   [TaskVine catalog](https://catalog.cse.nd.edu/).
2. Check the [TaskVine status tools](https://ccl.cse.nd.edu/software/taskvine/status/).
3. Verify manager port range policy for your cluster.

In many environments, the root cause is socket/port policy.
Some sites only allow specific manager port ranges.
See site pages for known working ranges:

- [NDCRC](../deployment/clusters/ndcrc.md)
- [Stampede3](../deployment/clusters/stampede3.md)
- [Anvil](../deployment/clusters/anvil.md)
- [LPC](../deployment/clusters/lpc.md)

Quick isolation test:

Try the TaskVine quickstart directly (without Floability):
https://cctools.readthedocs.io/en/stable/taskvine/#quick-start

Interpretation:

- If TaskVine quickstart also fails, the issue is likely network/scheduler/site policy.
- If TaskVine quickstart works but Floability fails, network is likely fine and the issue may be Floability configuration.

In that case, open a Floability issue with command, logs, cluster, and error details:
https://github.com/floability/floability-cli/issues

### SSH `-L` tunneling does not work

Common fixes:

1. Use the domain name you SSH into, not an automatically detected private IP.
2. Ensure local port is free (use another local port if needed).
3. Confirm you are tunneling to the same login node where Jupyter is running.
4. Check VPN/firewall/jump-host requirements at your site.

Examples:

```bash
# Standard tunnel
ssh -L 8888:localhost:8888 <username>@<cluster-login-domain>

# If local 8888 is busy
ssh -L 8899:localhost:8888 <username>@<cluster-login-domain>
```

Then open the local URL with the token from terminal output.

### Workers are not starting

Most often this is scheduler configuration.

What to check:

1. Verify your scheduler access and allocation/permissions.
2. Set required queue/partition/runtime options via `--batch-options`.
3. Confirm your batch type matches site scheduler (`condor`, `uge`, or `slurm`).

Example:

```bash
floability run --backpack <backpack-root> --batch-type slurm \
  --batch-options "-p wide -t 02:00:00"
```

Use your cluster documentation for exact queue/partition/account flags.
See site-specific deployment pages in [Deployment Overview](../deployment/index.md).

### Conda environment creation runs out of space

Floability recognizes Conda's explicit disk-full and quota-exceeded errors and
prints the environment target, its Floability base, and a cleanup preview
command. Preserve the original Conda output when reporting the failure.

You can select a base on a filesystem with more capacity:

```bash
floability execute --backpack <backpack-root> \
  --base-dir /project/<username>/floability-base
```

Or preview unreferenced data and environment caches in the reported base:

```bash
floability tools clean --base-dir <reported-base> \
  --mode data-and-env --dry-run
```

Review the plan before repeating the command without `--dry-run`. A Conda
solver or missing-package failure is not treated as a storage failure; correct
the backpack's `software/environment.yml` instead.
