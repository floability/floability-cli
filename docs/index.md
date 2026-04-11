# Floability Documentation

Floability CLI helps you package and run reproducible notebook workflows
using **backpacks** — self-contained bundles of workflow, software, data,
and compute that run the same way everywhere.

## Start Here

- [Install Floability](getting-started/installation.md)
- [Run your first backpack](getting-started/run-first-backpack.md)
- [Create your first backpack](getting-started/create-first-backpack.md)

## Core Concepts

- [Backpacks](concepts/backpacks.md) — the unit of a reproducible workflow
- [Instances](concepts/instances.md) — where backpacks run
- [Workers](concepts/workers.md) — how tasks are distributed across compute

## Maintenance

- [CLI Commands — tools](reference/cli.md#tools) — clean cache and instance directories

## How-To Guides
- [Update Environment](how-to/update-environment.md) — keep your environment.yml in sync with what’s actually installed
- [Troubleshooting](how-to/troubleshooting.md)

## Deployment

- [Overview](deployment/index.md) — batch systems, ports, worker configuration
- [ND CRC](deployment/clusters/ndcrc.md)
- [Stampede3](deployment/clusters/stampede3.md)
- [Anvil](deployment/clusters/anvil.md)
- [LPC](deployment/clusters/lpc.md)

## Reference

- [CLI Commands](reference/cli.md) — all commands and options
- [Data Specification](reference/data-spec.md)
- [Compute Specification](reference/compute-spec.md)
- [Instance Registry](reference/instance-registry.md)

## Examples

- [Matrix multiplication](https://github.com/floability/floability-examples/tree/main/matrix-multiplication) — quickstart example
- [All examples](https://github.com/floability/floability-examples)

## Help

- [Report a bug](https://github.com/floability/floability-cli/issues)
- [Ask a question](https://github.com/floability/floability-cli/discussions)