# Compute Specification Reference

`compute.yml` configures worker behavior for Floability runs.

## Basic Example

```yaml
vine_factory_config:
  min-workers: 1
  max-workers: 5
  cores: 2
  memory: 2048
  disk: 4000
```

Use it during run/execute:

```bash
floability run --backpack <backpack-root> --compute-spec <path-to-compute.yml>
```

## Current Backend Support

Floability currently supports `vine_factory` as the worker backend.
The compute spec section used by Floability is:

```yaml
vine_factory_config:
  min-workers: 1
  max-workers: 5
```

## Supported Keys (`vine_factory_config`)

- `min-workers`
- `max-workers`
- `cores`
- `disk`
- `memory`
- `foremen-name`
- `workers-per-cycle`
- `tasks-per-worker`
- `timeout`
- `worker-extra-options`
- `condor-requirements`

Example with more options:

```yaml
vine_factory_config:
  min-workers: 1
  max-workers: 10
  cores: 1
  memory: 1024
  disk: 2000
  workers-per-cycle: 1
  tasks-per-worker: 1
  timeout: 0
  worker-extra-options: ""
  condor-requirements: ""
```

## Precedence (Important)

Values are resolved in this order:

1. Floability defaults
2. Saved instance metadata
3. `compute.yml` (`vine_factory_config`)
4. CLI options

CLI options override values from `compute.yml`.

Examples:

```bash
# Override workers and cores from CLI
floability run --backpack <backpack-root> \
  --compute-spec <path-to-compute.yml> \
  --workers 20 \
  --cores-per-worker 2

# Override scheduler type and scheduler options
floability run --backpack <backpack-root> \
  --compute-spec <path-to-compute.yml> \
  --batch-type slurm \
  --batch-options "-p wide -t 02:00:00"
```

## Related Options (CLI)

Common worker-related CLI flags:

- `--compute-spec`
- `--batch-type local|condor|uge|slurm`
- `--workers`
- `--cores-per-worker`
- `--batch-options`
- `--debug-workers`

## Related Pages

- [Workers](../concepts/workers.md)
- [CLI Commands](cli.md)
- [Deployment Overview](../deployment/index.md)
