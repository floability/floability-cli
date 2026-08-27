# Workers

Workers are the execution processes that perform distributed tasks for your workflow.
Floability starts them through TaskVine's `vine_factory`, and they connect to the TaskVine manager running inside your instance.

## Worker Concept in the Run Flow

When you run a backpack:

```bash
floability run --backpack <backpack-root>
```

Floability does two things in sequence:

1. Creates an instance (if one does not already exist for this run).
2. Starts workers based on compute configuration and then runs the workflow.

The worker startup is handled by [vine_factory](https://cctools.readthedocs.io/en/stable/man_pages/vine_factory).

## Compute Specs Drive Worker Startup

Worker behavior is primarily configured from `compute.yml` (`vine_factory_config`) and can be overridden by CLI flags.

Example:

```yaml
vine_factory_config:
  min-workers: 1
  max-workers: 5
  cores: 2
  memory: 2048
  disk: 4000
  workers-per-cycle: 1
  tasks-per-worker: 1
  timeout: 0
  worker-extra-options: ""
  condor-requirements: ""
```

See [Compute Specification](../reference/compute-spec.md) for field details.

## Default Worker Behavior

`vine_factory` is the default worker provider in Floability.
By default, it launches standard `vine_worker` processes for the selected backend (`local`, `condor`, `uge`, or `slurm`).

Advanced behavior can be passed through `vine_factory` options (for example `worker-extra-options` and `batch-options`) when your site or workflow needs custom worker launch behavior.

## Worker Environment Selection

Floability resolves worker runtime environment in this order:

1. `worker_environment_pack` from instance metadata (if available)
2. manager environment pack as fallback
3. system Python as last resort

## Worker Lifecycle Commands

You can manage workers explicitly for an instance:

```bash
# Start workers
floability workers start --instance <name-or-path> \
  --batch-type local|condor|uge|slurm \
  [--workers N] [--cores-per-worker C] [--compute-spec compute.yml] \
  [--batch-options "..."] [--worker-transfer-ports START:END] \
  [--debug-workers]

# Check status
floability workers status --instance <name-or-path>

# Stop workers
floability workers stop --instance <name-or-path>
```

## Locks and Metadata

Worker lifecycle is protected with:

- `metadata/workers.lock`
- `metadata/workers.json`

On start, Floability records factory process-group identity and configuration
in `workers.json` and acquires `workers.lock`. Start requires an active run;
the factory reconnects using the manager identity stored by that run.

On stop, Floability validates ownership before each signal, reconciles
`workers.json` with `workers.lock`, and releases the lock only after verified
terminal state. A live legacy or mismatched owner is retained rather than
signaled by guesswork.

## Logs

Main worker/factory log:

- `logs/vine_factory.stdout`

`floability workers status` prints the last lines of this log for quick diagnostics.

## Related Pages

- [Instances](instances.md)
- [Backpacks](backpacks.md)
- [Compute Specification](../reference/compute-spec.md)
- [CLI Commands](../reference/cli.md)
