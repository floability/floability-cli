# CLI Commands Reference

This page documents the current Floability CLI commands and options.

## Top-Level Command

```bash
floability <command> [options]
```

Top-level options:

- `-v, --version`: show the concise version and exit
- `--verbose`: with `--version`, include installation diagnostics

Available commands:

- `run`: interactive run mode (starts Jupyter)
- `execute`: batch mode (no Jupyter UI)
- `instance`: create/list/stop/inspect instances
- `workers`: start/stop/status for workers
- `data`: check/fetch/verify data specs
- `audit`: dependency extraction from notebooks
- `backpack`: initialize and manage backpacks
- `tools`: cache and resource maintenance utilities

---

## run

Run a workflow in interactive mode (starts JupyterLab).

```bash
floability run --backpack <backpack-root>
```

Run on an existing instance instead of creating a new one:

```bash
floability run --instance <instance-name-or-path>
```

### Options

**Core execution:**

- `--backpack PATH`: backpack directory (mutually exclusive with `--instance`)
- `--instance PATH_OR_NAME`: existing instance to reuse (mutually exclusive with `--backpack`)
- `--environment PATH`: manager environment spec. Required for new instances unless auto-resolved from the backpack's `software/environment.yml`.
- `--worker-environment PATH`: worker environment spec (optional; auto-resolved from `software/worker-environment.yml` if present)
- `--entrypoint FILENAME`: explicitly select the file that runs first from `workflow/`; normally unnecessary unless automatic selection is ambiguous

**Session:**

- `--jupyter-port INT` (default: `8888`)
- `--manager-ports A:B` (default: `9123:9150`): manager port range. Legacy `A,B` input is also accepted.
- `--worker-transfer-ports A:B` (optional): worker-worker transfer port range. Legacy `A,B` input is also accepted. Passed as `--transfer-port` to vine_factory.
- `--manager-name NAME`: TaskVine manager name (auto-generated if omitted)
- `--env-vars KEY=VALUE,...`: environment variables to inject into the conda env

**Directory and instance:**

- `--base-dir DIR` (default: `~/floability-base-dir`)
- `--instance-prefix PREFIX`: prefix for the instance directory name
- `--backpack-root DIR` (default: `.`): root path for resolving backpack-relative paths

**Data:**

- `--data-spec FILE`: path to `data.yml` (auto-resolved from backpack if omitted)
- `--data-profile NAME`: override the default profile in the data spec
- `--data-cache-mode off|symlink|hardlink|copy` (default: `symlink`)
- `--data-cache-dir DIR`: override default `<base-dir>/floability-data-cache`
- `--force-data-cache`: rebuild cache entries even if they already exist
- `--fingerprint-mode meta|sample|strict` (default: `meta`)
- `--continue-on-data-failure`: proceed even if data operations fail

**Workers/factory:**

- `--no-worker`: skip starting the worker factory
- `--batch-type local|condor|uge|slurm` (vine_factory default: `local`)
- `--workers INT` (vine_factory default: `5`)
- `--cores-per-worker INT` (vine_factory default: `1`)
- `--batch-options STRING`: raw batch system options passed directly to vine_factory
- `--compute-spec FILE`: path to `compute.yml` (auto-resolved from backpack if omitted)
- `--debug-workers`: enable debug logging in workers

**Other:**

- `--measure-performance`: collect timing metrics and write a report to `metrics/`
- `--no-update-backpack`: disable copying workflow files back to the backpack
- `--sync-path PATH`: additionally copy a generated file or directory relative to
  `workflow/`; repeat the option to select multiple paths
- `--per-instance-env`: extract a private conda env per instance instead of sharing a read-only base

By default, Floability copies back only files that originally came from the
backpack's `workflow/` directory. This includes saved notebook changes when an
interactive run is stopped with `Ctrl+C`. Staged data and newly generated files
are not copied unless their relative paths are selected with `--sync-path`.

---

## execute

Run a workflow in batch mode (no interactive Jupyter session).

```bash
floability execute --backpack <backpack-root>
```

`execute` accepts the same options as `run`. The difference in behavior:
- No JupyterLab is started
- The notebook or script runs to completion, then exits
- Original workflow files are copied back to the backpack on success

---

## instance

Manage instance lifecycle.

### instance create

Create a Floability instance from a backpack without starting workers or Jupyter.

```bash
floability instance create --backpack <backpack-root> [options]
```

Options:

- `--backpack PATH` (required)
- `--name NAME`: short name to register for this instance (auto-generated if omitted)
- `--base-dir DIR` (default: `~/floability-base-dir`)
- `--skip-data`: skip data fetch during instance creation
- `--data-profile NAME`: override the default profile in the data spec
- `--data-cache-mode off|symlink|hardlink|copy` (default: `off`)
- `--force-data-cache`: rebuild cache entries even if they already exist
- `--fingerprint-mode meta|sample|strict` (default: `meta`)
- `--environment PATH`: manager environment spec
- `--worker-environment PATH`: worker environment spec
- `--manager-name NAME`: TaskVine manager name (auto-generated if omitted)
- `--manager-ports A:B` (default: `9123:9150`; legacy `A,B` is accepted)
- `--env-vars KEY=VALUE,...`
- `--measure-performance`

### instance list

```bash
floability instance list [--show-paths] [--all-details]
```

Options:

- `--show-paths`: include full filesystem paths in output
- `--all-details`: show extended metadata (created_at, last_seen, manager_name, tags)

### instance stop

Stop a running instance (sends SIGINT/SIGTERM to the run process, stops workers, releases lock).

```bash
floability instance stop <instance-name-or-path>
```

Arguments:

- positional `instance`: short name or path to the instance directory

### instance latest

Print the path of the most recently created instance. Useful for shell navigation.

```bash
floability instance latest [--base-dir DIR]
cd $(floability instance latest)
```

Options:

- `--base-dir DIR` (default: `~/floability-base-dir`): where to look for the `latest_floability_instance` symlink

---

## workers

Manage the vine_factory worker pool for an instance.

### workers start

```bash
floability workers start --instance <instance-name-or-path> [options]
```

Options:

- `--instance PATH_OR_NAME` (required)
- `--batch-type local|condor|uge|slurm` (vine_factory default: `local`)
- `--workers INT` (vine_factory default: `5`)
- `--cores-per-worker INT` (vine_factory default: `1`)
- `--batch-options STRING`: raw options passed directly to vine_factory
- `--compute-spec FILE`: path to `compute.yml`
- `--debug-workers`: enable debug logging in workers

### workers stop

```bash
floability workers stop --instance <instance-name-or-path>
```

Options:

- `--instance PATH_OR_NAME` (required)

### workers status

```bash
floability workers status --instance <instance-name-or-path>
```

Options:

- `--instance PATH_OR_NAME` (required)

---

## data

Run data operations directly against a data spec.

```bash
floability data --mode check --data-spec <data.yml>
floability data --mode fetch --data-spec <data.yml>
```

Options:

- `--mode check|fetch|verify` (default: `check`)
- `--data-spec FILE`: path to `data.yml`
- `--backpack DIR`: backpack root for resolving `backpack://` and relative `fs` source paths
- `--check-details`: print per-item metadata detail after the summary (check mode only)
- `--verbose`: enable verbose logging
- `--force-fetch`: re-fetch targets even if they already exist
- `--data-profile NAME`: override the default profile in the data spec
- `--data-cache-mode off|symlink|hardlink|copy` (default: `off`)
- `--data-cache-dir DIR`: override default `<base-dir>/floability-data-cache`
- `--force-data-cache`: rebuild cache entries even if they already exist
- `--fingerprint-mode meta|sample|strict` (default: `meta`)
- `--base-dir DIR` (default: `~/floability-base-dir`)

---

## audit

Generate environment and data dependency information from a notebook.

```bash
floability audit --notebook <notebook.ipynb>
```

Options:

- `--notebook FILE` (required): Path to the notebook to audit
- `--kernel NAME`: Jupyter kernel to use when analyzing the notebook
- `--manager-port PORT` (default: `9123`): Taskvine manager port for connection
- `--manager-name NAME`: TaskVine manager name
- `--conda-env NAME` : Conda environment prefix where the notebook runs
- `--data-dirs DIR` : One or more directories containing input data files
- `--no-worker` : Skip vine worker (for non-distributed notebooks)
- `--backpack-name NAME` (required) : Name for the generated backpack directory
- `--force` : Overwrite existing backpack directory
- `--cell-level`: generate dependencies at cell level instead of notebook level

---

## backpack

Initialize and manage backpacks.

### backpack init

Bootstrap a new Floability backpack directory structure.

```bash
floability backpack init --name <name> --from-template taskvine
floability backpack init --name <name> --from-workflow <notebook-or-script>
```

Options:

- `--name NAME` (required): backpack name or path; the leaf directory becomes the backpack name
- `--from-template taskvine|taskvine-data` (mutually exclusive with `--from-workflow`): bootstrap from a built-in template
- `--from-workflow PATH` (mutually exclusive with `--from-template`): use an existing notebook (`.ipynb`) or Python script (`.py`) as the workflow entrypoint
- `--force`: overwrite an existing backpack directory

### backpack validate

Check a backpack directory for structural correctness.

```bash
floability backpack validate [path]
```

Arguments:

- `path` (optional, default: `.`): path to the backpack directory

Options:

- `--strict`: reserved for future run-readiness checks (not yet implemented)

### backpack update-env

Update a backpack's `environment.yml` from a completed instance's conda environment.

```bash
floability backpack update-env --from-instance <instance-name-or-path> [path]
```

Arguments:

- `path` (optional, default: `.`): path to the backpack directory to update

Options:

- `--from-instance PATH_OR_NAME` (required): instance directory path or registered short name to export the environment from
- `--versions-only`: only update version pins for packages already listed in `environment.yml`, rather than replacing the full dependency list

---

## tools

Utility tools for managing Floability cache and instance data.

### tools clean

Delete cache directories and/or instance directories under a base directory. Prompts for confirmation before deleting unless `--yes` is given.

**Default behavior** (no scope flag): removes data cache and env cache, leaves instances untouched.

```bash
floability tools clean [--base-dir DIR] [scope] [--yes] [--parallel]
```

Options:

- `--base-dir DIR` (default: `~/floability-base-dir`): base directory containing Floability data
- `--data-cache-dir DIR`: override default `<base-dir>/floability-data-cache`

**Scope** (mutually exclusive; default is `--data-and-env`):

| Flag | What is removed |
|---|---|
| `--data-only` | Data cache only (`floability-data-cache/`) |
| `--env-only` | Conda env cache only (`flo_common_env/`) |
| `--data-and-env` | Data cache + env cache (explicit default) |
| `--instances-only` | Instance directories (`fi_*/`) and latest symlink |
| `--all` | Everything: data cache, env cache, and instances |
| `--keep-last` | Everything **except** the latest instance and the env/data cache entries it depends on |

**Flags:**

- `--yes`, `-y`: skip the confirmation prompt
- `--parallel`: use `find | xargs rm` for faster deletion of large directories (e.g. conda envs). Requires `find`, `xargs`, and `rm` on `PATH`. Falls back to Python `shutil.rmtree` by default.

**Examples:**

```bash
# Remove data and env cache (default)
floability tools clean

# Remove only the conda env cache
floability tools clean --env-only

# Remove everything except the latest instance
floability tools clean --keep-last --yes

# Remove all instances on a custom base dir
floability tools clean --instances-only --base-dir /scratch/myuser

# Remove everything, fast, no prompt
floability tools clean --all --yes --parallel
```

---

## Related References

- [Data Specification](data-spec.md)
- [Compute Specification](compute-spec.md)
- [Workers Concept](../concepts/workers.md)
- [Instances Concept](../concepts/instances.md)
