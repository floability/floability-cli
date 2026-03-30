# Instances

## TODO
- [ ] Simplify instance definition and lifecycle overview.
- [ ] Validate directory layout against current implementation.
- [ ] Add one create/reuse/stop workflow example.
- [ ] Move command option detail to CLI reference.

An instance is a self-contained execution sandbox created from a backpack. It contains a complete copy of the workflow directory, logs, metrics, and metadata, plus an extracted/activated software environment. You can start workers and Jupyter against an instance, reuse it later, and stop it safely.

## Why instances?

- Isolation: keep each run’s files separate and reproducible.
- Reuse: resume work on an existing instance (no environment rebuild).
- Discoverability: instances are registered globally and can be referenced by short name.

## Layout
The instance directory structure looks like this:

```<instance>/
├── workflow/
├── logs/
├── metrics/
├── metadata/
└── current_conda_env/
```
Within the instance directory:
- workflow/ — notebook/script and outputs (sandbox)
- logs/ — stdout/stderr for Jupyter and workers
- metrics/ — performance timing and size reports
- metadata/ — instance metadata, run.json, and locks
- current_conda_env/ — extracted Conda environment for manager/Jupyter 

The instance directory is created under the specified base directory (e.g., `--base-dir .`) with a unique name (timestamp + random suffix) unless a custom name is provided (`--name <short-name>`).

## Creating an instance from a backpack

Create and prepare an instance without starting Jupyter or workers:

- floability instance create --backpack <backpack-root> [--name <short-name>] [options]

This resolves workflow artifacts from the backpack, optionally materializes data, sets up manager and worker environments, records metadata, and registers a short name in the global instance registry.

## Running with a new or existing instance

- New: floability run --backpack <backpack-root>
  - Creates a new instance and starts Jupyter and workers.
- Existing: floability run --instance <short-name-or-path>
  - Reuses the instance, avoiding new environment setup. The instance run lock prevents concurrent runs.

## Locks and lifecycle

- metadata/instance.lock — protects the main run flow; created on start, released on exit or via instance stop.
- metadata/workers.lock — protects the worker factory; created on start, released on stop.

Locks store the owning PID and are considered active if that PID is alive. Stale locks are cleaned up when processes are gone.

See also: [Concepts → Workers](./workers.md) for how the worker factory is configured and managed.

## Registry and short names

Instances are recorded in a global JSON registry under:

- $XDG_DATA_HOME/floability/instances.json (Linux/macOS) or
- ~/.local/share/floability/instances.json

Each entry includes path, timestamps, manager name, and tags. The CLI can resolve short names to paths automatically. Listing auto-prunes entries whose paths no longer exist:

- floability instance list [--show-paths] [--all-details]

## Stopping an instance

Stop by short name or path:

- floability instance stop <short-name-or-path>

This sends SIGINT (then SIGTERM if needed) to the run process group, stops workers, and releases the instance lock.

## Metadata

The file `metadata/run.json` captures the backpack, CLI args, environment specs, data spec, context, and status (start/completion times and success). It is updated as the run proceeds and finalized on exit.

### Examples

Example `run.json`:

```json
{
  "schema_version": "1.0",
  "instance_id": "floability_instance_20251113_164050_622483",
  "instance_path": "/users/mislam5/floability-project/floability-base-dir/floability_instance_20251113_164050_622483",
  "created_at": "2025-11-13T21:40:50.639977Z",
  "execution_mode": "run",
  "manager_name": "floability-32d47aa5-3575-4798-88f4-1cee2d8369aa",
  "backpack": {
    "path": "/users/mislam5/floability-project/floability-cli/example/rag-lite-bm25",
    "name": "rag-lite-bm25",
    "git_commit": "d8d4fe2a3f3d8035ceab0bec4bae446b9b2a87e2"
  },
  "cli_args": {
    "command": "run",
    "backpack": "floability-cli/example/rag-lite-bm25",
    "instance": null,
    "environment": "/users/mislam5/floability-project/floability-cli/example/rag-lite-bm25/software/environment.yml",
    "worker_environment": null,
    "notebook": "/users/mislam5/floability-project/floability-cli/example/rag-lite-bm25/workflow/rag-lite-bm25.ipynb",
    "jupyter_port": "8888",
    "manager_ports": "9123,9150",
    "base_dir": "floability-base-dir",
    "data_spec": "/users/mislam5/floability-project/floability-cli/example/rag-lite-bm25/data/data.yml",
    "data_profile": null,
    "backpack_root": "/users/mislam5/floability-project/floability-cli/example/rag-lite-bm25",
    "continue_on_data_failure": "False",
    "no_update_backpack": "False",
    "data_cache_mode": "copy",
    "force_data_cache": "False",
    "no_worker": "False",
    "prefer_python": "False",
    "python_script": null,
    "measure_performance": "True",
    "env_vars": null,
    "batch_type": "local",
    "workers": "5",
    "cores_per_worker": "1",
    "manager_name": "floability-32d47aa5-3575-4798-88f4-1cee2d8369aa",
    "batch_options": null,
    "compute_spec": "/users/mislam5/floability-project/floability-cli/example/rag-lite-bm25/compute/compute.yml",
    "debug_workers": "True"
  },
  "environment": {
    "manager_spec": "/users/mislam5/floability-project/floability-cli/example/rag-lite-bm25/software/environment.yml",
    "manager_spec_hash": "fb55efd126465b7d1d1c10b855f95d511fd8985612a781028d5c35d6768134c1"
  },
  "data": {
    "spec_path": "/users/mislam5/floability-project/floability-cli/example/rag-lite-bm25/data/data.yml",
    "spec_hash": "e2f896edda8002687d133fd89255759670381089f4577d678871cee2a1c866f9",
    "profile": null,
    "cache_mode": "copy",
    "cache_keys": []
  },
  "context": {
    "update_backpack": true,
    "no_worker": false,
    "batch_type": "local",
    "max_workers": 5
  },
  "status": {
    "state": "completed",
    "started_at": "2025-11-13T21:40:50.649529Z",
    "completed_at": "2025-11-13T21:45:34.285449Z",
    "success": true,
    "error": null
  },
  "worker_environment_pack": "floability-base-dir/flo_common_env/tarballs/env_c21362e25161d77eb3d90309b501588c.tar.gz",
  "manager_environment_pack": "floability-base-dir/flo_common_env/tarballs/env_c21362e25161d77eb3d90309b501588c.tar.gz"
}
```

Example `metadata/sync.json`:

```json
{
  "schema_version": "1.0",
  "synced_at": "2025-11-13T21:45:34.281621Z",
  "source": "floability-base-dir/floability_instance_20251113_164050_622483/workflow",
  "target": "floability-cli/example/rag-lite-bm25/workflow",
  "files": [
    {
      "path": "rag-lite-bm25.ipynb",
      "type": "notebook",
      "size": 34814,
      "hash": "6c5354dda640dd4a1d7e6cb015f2936079965d9cb6a42965f8d7c733818b813d"
    }
  ],
  "file_count": 1
}
```

Example `metadata/workers.json`:

```json
{
  "factory_pid": 1573388,
  "manager_name": "floability-32d47aa5-3575-4798-88f4-1cee2d8369aa",
  "batch_type": "local",
  "workers": 5,
  "cores_per_worker": 1,
  "status": "running"
}
```

## CLI reference

Common commands related to instances:

- Create only: `floability instance create --backpack <path> [--name <short>]`
- Run new: `floability run --backpack <path>`
- Run existing: `floability run --instance <short-or-path>`
- Execute new: `floability execute --backpack <path>`
- Execute existing: `floability execute --instance <short-or-path>`
- List: `floability instance list [--show-paths] [--all-details]`
- Stop: `floability instance stop <short-or-path>`
- Workers: `floability workers start|stop --instance <short-or-path>`

See the full option set in the CLI reference page if you need details on flags.
