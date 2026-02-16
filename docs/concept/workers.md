# Workers

Floability uses a pool of TaskVine workers (launched by `vine_factory`) to execute distributed tasks for your notebook or script. The manager process (inside your instance) coordinates the work and communicates with these workers.

## What workers are

- Manager/Workers architecture: the TaskVine manager runs inside your instance; workers are processes started via `vine_factory` that connect back to the manager.
- Batch systems: workers can run locally or be submitted to schedulers such as HTCondor, UGE, or Slurm.

## Starting, stopping, and checking status

Use the CLI to manage workers for an instance (by path or short name from the registry):

```bash
# Start workers
floability workers start --instance <name-or-path> \
  --batch-type local|condor|uge|slurm \
  [--workers N] [--cores-per-worker C] [--compute-spec compute.yml] \
  [--batch-options "..."] [--debug-workers]

# Check worker status and tail the log
floability workers status --instance <name-or-path>

# Stop workers
floability workers stop --instance <name-or-path>
```

Behavior:
- On start, Floability writes `metadata/workers.json` with the `vine_factory` PID and configuration, and acquires `metadata/workers.lock`.
- On status, it reports configuration, whether the process is running, and the last 20 lines of `logs/vine_factory.stdout`.
- On stop, it sends SIGTERM to the factory process, updates metadata, and releases the workers lock.

## Environments for workers

- Preferred: a worker environment pack from `--worker-environment` (YAML or prebuilt tarball) recorded in instance metadata.
- Fallback: if no worker pack is present, workers use the manager environment pack.
- Last resort: if neither pack exists, workers use the system Python environment.

See also: Concepts → Environment caching (for how manager/worker packs are built, cached, and selected).

## Compute specification

Workers accept configuration from a `compute.yml` in your backpack and/or CLI overrides. Example:

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

CLI options override compute.yml where provided.

## Batch systems and options

- `--batch-type`: local | condor | uge | slurm
- `--batch-options`: string passed through to `vine_factory` for site-specific tuning
- `--debug-workers`: enable more verbose logs for troubleshooting

## Logs and troubleshooting

- Logs: `logs/vine_factory.stdout` (status shows the last lines)
- Common issues:
  - `vine_factory` not found in PATH → ensure ndcctools is installed (often via the manager environment) and PATH is set.
  - Batch submission errors → check site policy, credentials, and `--batch-options`.
  - Environment mismatch → verify `worker_environment_pack` or manager pack is recorded in metadata and reachable.

## Internals reference

- Lock file: `metadata/workers.lock` (PID-based, prevents concurrent starts)
- Metadata file: `metadata/workers.json`
- Manager name: read from `metadata/run.json`; workers connect via this identifier
- Start/stop/status logic implemented in the workers manager and ops CLI wrappers
