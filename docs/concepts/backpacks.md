# Backpacks

A backpack is a directory that contains all the necessary components to run a workflow. It is the unit of a reproducible workflow in Floability. By packaging the workflow, software environment, data specifications, and compute configuration together, a backpack ensures that the workflow can be executed in the same way across different environments — from a local laptop to an HPC cluster.

Each backpack defines four parts:

1. `workflow`: notebook or script to execute
2. `software`: environment definition for dependencies
3. `data`: data sources and verification rules
4. `compute`: worker and scheduler configuration

## Canonical Backpack Layout

```text
<backpack-root>/
├── workflow/
│   └── <workflow>.ipynb
├── software/
│   └── environment.yml
├── data/
│   └── data.yml
└── compute/
    └── compute.yml
```

Notes:

- `data/` is optional for workflows without external inputs.
- `workflow/` can contain supporting Python modules or helper files.
- `compute.yml` can be tuned for local runs or batch schedulers.

## How Floability Uses a Backpack

When you run:

```bash
floability run --backpack <backpack-root>
```

Floability creates an instance from the backpack and then executes from that instance, not directly from the source folder.

The instance includes:

- staged workflow files
- prepared environment
- materialized data (if configured)
- logs, metadata, and metrics

For instance lifecycle details, see [Instances](instances.md).

## Component Responsibilities

### Workflow (`workflow/`)

Contains the notebook or script you run.
Keep workflow code portable:

- avoid hardcoded cluster hostnames and ports
- use relative paths or data targets from `data.yml`

### Software (`software/environment.yml`)

Defines the execution environment.
Use a standard Conda environment file and pin critical dependencies where needed.

### Data (`data/data.yml`)

Defines what data to fetch/verify and where it should be staged.
Use profiles when you need different datasets for local testing and full-scale runs.

See [Data Specification](../reference/data-spec.md).

### Compute (`compute/compute.yml`)

Defines worker scaling and scheduler-related settings.
Use this file to describe how many workers/resources your workflow needs.

See [Compute Specification](../reference/compute-spec.md).

## Minimal Checklist for a New Backpack

1. Place your notebook or script in `workflow/`.
2. Create `software/environment.yml` with required dependencies.
3. Add `data/data.yml` if your workflow needs input data.
4. Add `compute/compute.yml` with sensible defaults.
5. Test with `floability run --backpack <backpack-root>`.

## Updating the Environment from a Run

After running a backpack, the installed conda environment may resolve to different versions than what is written in `software/environment.yml`. Use `update-env` to export the actual versions from a completed instance back into the backpack:

```bash
# Replace the full dependency list with what was actually installed
floability backpack update-env --from-instance <name-or-path>

# Only update version strings for packages already listed in environment.yml
floability backpack update-env --from-instance <name-or-path> --versions-only
```

The backpack's `name` field and any floability-specific keys (e.g. `post_install_script`) are always preserved. A backup of the previous file is saved as `software/old-environment.yml`.

See [Update environment.yml from a Running Instance](../how-to/update-environment.md) for a full walkthrough.

## Related Pages

- [Run your first backpack](../getting-started/run-first-backpack.md)
- [Create your first backpack](../getting-started/create-first-backpack.md)
- [Update Environment](../how-to/update-environment.md)
- [Instances](instances.md)
- [Workers](workers.md)