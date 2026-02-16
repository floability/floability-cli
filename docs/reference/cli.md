# Floability CLI Reference

This page documents the Floability CLI commands and options in the current release.

Top-level usage:

- floability run — interactive run on a new or existing instance
- floability execute — non-interactive batch-style execution
- floability instance — manage instances (create, list, stop)
- floability workers — manage workers (start, stop, status)
- floability data — check/fetch/verify data from a data spec
- floability audit — generate environment and data dependencies from a notebook

## run

Deploy and run a workflow from a backpack in interactive mode (JupyterLab).

Key options:
- --backpack PATH: Root of the backpack to run from (mutually exclusive with --instance)
- --instance REF: Existing instance to reuse (short name from registry or absolute path)
- --environment PATH: Manager env (environment.yml or env_*.tar.gz)
- --worker-environment PATH: Worker env (worker-environment.yml or env_*.tar.gz)
- --notebook FILE: Notebook path (optional; auto-resolved from backpack)
- --python-script FILE: Python script path (optional; can prefer over notebook)
- --prefer-python: Prefer running the script when both notebook and script present
- --prefer-instance: For a new backpack run, skip env setup and reuse local env
- --manager-ports A,B: Port range for TaskVine manager (default 9123,9150)
- --jupyter-port PORT: JupyterLab port (default 8888)
- --base-dir DIR: Base directory for instance files (default '.')
- --data-spec FILE: Data spec to materialize
- --data-profile NAME: Override profile in data spec
- --data-cache-mode off|symlink|hardlink|copy: Data caching strategy
- --force-data-cache: Rebuild cached items even if present
- --no-worker: Skip starting workers
- --compute-spec FILE: Compute spec (overrides backpack)
- --batch-type local|condor|uge|slurm: Batch system for workers (default local)
- --batch-options STR: Extra batch options for the factory
- --env-vars KEY=VAL[,KEY=VAL...]: Env vars to set inside conda env
- --measure-performance: Enable timing and size measurements

Behavior:
- New instance: creates an instance directory, copies entire workflow/ directory from backpack, materializes data (optional), sets up environments, starts workers and Jupyter.
- Existing instance (via --instance): reuses the instance directory and its environment; avoids creating a new one.
- Produces a registry entry for new instances so they can be referenced by short name later.

## execute

Batch-style execution without starting Jupyter (runs notebook or script to completion). Same options as run. Syncs outputs back to the backpack when applicable.

## instance

Manage instances.

- floability instance create --backpack PATH [--name NAME] [options]
  - Creates a new instance directory structure, copies entire workflow/ directory from backpack, optionally fetches data, sets up manager and worker environments, and registers a short name.
  - Useful options: --base-dir, --skip-data, --data-profile, --data-cache-mode, --force-data-cache, --environment, --worker-environment, --manager-name, --manager-ports, --env-vars, --measure-performance

- floability instance list [--show-paths] [--all-details]
  - Lists registered instances with running state; includes metadata on demand. Auto-prunes stale entries whose paths no longer exist.

- floability instance stop INSTANCE
  - Stops a running instance by short name or path. Sends SIGINT then SIGTERM to the run process group, stops workers, and releases the instance lock.

## workers

Manage worker factory processes for an instance.

- floability workers start --instance REF [options]
  - Starts a vine_factory for the instance. Options can override compute spec: --batch-type, --workers, --cores-per-worker, --batch-options, --compute-spec, --debug-workers.
  - If no worker environment pack is recorded, workers fall back to the manager environment pack; otherwise they use the system Python.

- floability workers status --instance REF
  - Shows worker config, PID, running status, and tail of vine_factory stdout.

- floability workers stop --instance REF
  - Stops the worker factory and releases the workers lock.

See Concepts → Workers for architecture, environments, logs, and troubleshooting.

## data

Operate on a data spec file.

- --mode check|fetch|verify (default: check)
- --data-spec FILE
- --backpack DIR (for backpack source_type resolution)
- --check-details (check mode)
- --verbose
- --force-fetch
- --data-profile NAME
- --data-cache-mode off|symlink|hardlink|copy
- --force-data-cache
- --base-dir DIR

See the dedicated Data Reference for full schema and behavior.

## audit

Generate environment and data dependencies for a notebook.

- --notebook FILE (required)
- --kernel NAME (optional)
- --manager-port PORT (default 9123)
- --manager-name NAME (optional)
- --cell-level (generate per-cell dependencies)

Outputs manager and worker environment specs and a verified environment YAML.
