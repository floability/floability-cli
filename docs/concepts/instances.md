# Instances

An instance is Floability's run sandbox.
When you run a backpack, Floability creates an instance directory and executes there instead of mutating your source backpack directly.

Think of it this way:

- a backpack is the specification of what to run
- an instance is the fully materialized, ready-to-run realization of that specification

Examples:

- `data/data.yml` says where data should come from; the instance has data materialized in `workflow/` (often via cache links)
- `software/environment.yml` defines dependencies; the instance has the prepared runtime environment used for execution
- `workflow/` in the backpack is source content; `workflow/` in the instance is the execution sandbox

This gives you:

- isolated runs
- reusable environments and data state
- per-run logs, metadata, and metrics

## Instance Lifecycle

There are two ways to create an instance.

### 1) Run a Backpack

Create and run in one step:

```bash
floability run --backpack <backpack-root>
```

`floability run --backpack ...` first creates an instance automatically, then runs it.

### 2) Create Only (Run Later)

Create an instance without starting Jupyter/workers:

```bash
floability instance create --backpack <backpack-root>
```

Use this when you want to prepare an instance now and run it later.

### Run (existing instance)

Reuse an existing instance by short name or full path:

```bash
floability run --instance <name-or-path>
```

An instance can be reused across multiple runs over time, but only one active run is allowed at a time.
This is enforced by lock files.

### Stop

Stop a running instance:

```bash
floability instance stop <name-or-path>
```

`instance stop` sends `SIGINT` first, then `SIGTERM` if needed, and performs worker shutdown as best effort.

## Directory Layout

Each instance contains:

```text
<instance>/
├── workflow/
├── logs/
├── metrics/
└── metadata/
```

Purpose of each directory:

- `workflow/`: execution sandbox (copied workflow files and outputs)
- `logs/`: Jupyter execution logs and worker logs
- `metrics/`: performance reports (when enabled)
- `metadata/`: run metadata and lock files

Notes:

- For per-instance environments, `current_conda_env/` can also be present.
- Floability also creates `latest_floability_instance` symlink under the base directory.

## Backpack vs Instance (One-to-One View)

For matrix multiplication, the backpack looks like:

```text
matrix-multiplication/
├── compute/
│   └── compute.yml
├── data/
│   └── data.yml
├── software/
│   └── environment.yml
└── workflow/
	└── matrix-multiplication.ipynb
```

After materialization and run preparation, an instance looks like:

```text
latest_floability_instance/
├── logs/
│   ├── jupyterlab.stdout
│   ├── vine_factory.stdout
│   └── ...
├── metadata/
│   ├── run.json
│   ├── sync.json
│   ├── workers.json
│   └── workers.lock
├── metrics/
├── pyuser/
└── workflow/
	├── data/
	│   └── matrices/
	│       ├── matrix_dense_00.csv -> <base-dir>/floability-data-cache/<hash>/cached_data/data/matrices/matrix_dense_00.csv
	│       └── ...
	└── matrix-multiplication.ipynb
```

One-to-one mapping summary:

- backpack `workflow/matrix-multiplication.ipynb` -> instance `workflow/matrix-multiplication.ipynb`
- backpack `data/data.yml` -> instance `workflow/data/...` (materialized files)
- backpack `software/environment.yml` -> instance runtime environment (plus optional `current_conda_env/`)
- backpack `compute/compute.yml` -> instance worker behavior and scheduler submission parameters
- instance-only runtime artifacts -> `logs/`, `metadata/`, `metrics/`, and lock files

## Base Directory and Cache Defaults

If `--base-dir` is omitted (or `.`), Floability normalizes to:

```text
~/floability-base-dir
```

Default data cache location:

```text
<base-dir>/floability-data-cache
```

You can override cache location with `--data-cache-dir`.

## Locks and Safety

Floability uses PID-based lock files in `metadata/`:

- `instance.lock`: protects the main run path
- `workers.lock`: protects worker factory lifecycle

Behavior:

- lock files are created atomically
- if a lock exists but the PID is dead, Floability treats it as stale and cleans it up
- active locks prevent duplicate concurrent runs for the same instance

## Registry and Short Names

New instances are registered with short names so you can avoid long paths.

Example:

```bash
floability instance list --show-paths
floability run --instance <short-name>
```

Registry details and storage location are documented in [Instance Registry](../reference/instance-registry.md).

## What Gets Recorded in Metadata

`metadata/run.json` tracks run context, including:

- backpack and command arguments
- manager identity
- environment and data settings
- execution status and timestamps

During execution, Floability may also write:

- `metadata/workers.json` for worker process state
- sync metadata when outputs are copied back to backpack workflow

## Reuse Workflow Example

```bash
# 1) Create once
floability instance create --backpack <backpack-root>

# 2) Discover short name
floability instance list

# 3) Re-run later without rebuilding from scratch
floability run --instance <short-name>

# 4) Stop if needed
floability instance stop <short-name>
```

## Related Pages

- [Backpacks](backpacks.md)
- [Workers](workers.md)
- [CLI Commands](../reference/cli.md)
