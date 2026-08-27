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

For a new instance, Floability validates the source before creating any
instance state. The backpack must contain a notebook under `workflow/` and an
environment must come from `software/environment.yml` or `--environment`.

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

Entrypoint discovery is recursive. `run` considers only `.ipynb` files;
`execute` considers `.ipynb`, `.py`, and `.sh`. Floability selects the only
eligible file automatically. If several are eligible, the single file whose
stem matches the backpack directory name is preferred; otherwise use
`--entrypoint`. The explicit value is a filename, not a path, and must be
unique within `workflow/`.

**Session:**

- `--jupyter-port INT` (default: `8888`)
- `--manager-ports A:B` (default: `9123:9150`): manager port range. Legacy `A,B` input is also accepted.
- `--worker-transfer-ports A:B` (optional): worker-worker transfer port range. Legacy `A,B` input is also accepted. Passed as `--transfer-port` to vine_factory.
- `--manager-name NAME`: TaskVine manager name (auto-generated if omitted)
- `--env-vars KEY=VALUE,...`: environment variables to inject into the conda env

**Directory and instance:**

- `--base-dir DIR` (default: `~/floability-base-dir`)
- `--instance-prefix PREFIX`: readable instance-name prefix; normalized to
  portable ASCII and limited to 20 characters
- `--backpack-root DIR` (default: `.`): root path for resolving backpack-relative paths

**Data:**

- `--data-spec FILE`: path to `data.yml` (auto-resolved from backpack if omitted)
- `--data-profile NAME`: override the default profile in the data spec
- `--data-cache-mode off|symlink|hardlink|copy` (default: `symlink`)
- `--data-cache-dir DIR`: override default `<base-dir>/floability-data-cache`
- `--force-data-cache`: rebuild cache entries even if they already exist
- `--fingerprint-mode meta|sample|strict` (default: `meta`)
- `--cache-lookup-mode strict|local` (default: `strict`)
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

The displayed `9123:9150` manager range is the generic parser default. A
detected site may replace an option that the user did not explicitly supply.
Explicit CLI values always take precedence; see the relevant deployment page
for configured site defaults.

---

## execute

Run a workflow in batch mode (no interactive Jupyter session).

```bash
floability execute --backpack <backpack-root>
```

`execute` accepts the same options as `run`. The difference in behavior:

- No JupyterLab is started
- The notebook or script runs to completion, then exits
- Original workflow files are synchronized back during finalization unless
  `--no-update-backpack` is selected

New `execute` instances receive the same preflight validation, but their
`workflow/` entrypoint may be `.ipynb`, `.py`, or `.sh`.

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
- `--per-instance-env`: extract a private environment inside the instance
  instead of using the shared environment cache
- `--manager-name NAME`: TaskVine manager name (auto-generated if omitted)
- `--manager-ports A:B` (generic default: `9123:9150`; legacy `A,B` is accepted;
  detected site defaults may replace an unspecified value)
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

Stop a running instance using ownership-verified staged shutdown. Floability
releases locks only after the matching run and workers reach a terminal state;
incomplete cleanup returns nonzero and retains diagnostic ownership.

```bash
floability instance stop <instance-name-or-path>
```

Arguments:

- positional `instance`: short name or path to the instance directory

### instance latest

Print the path of the most recently run instance. Useful for shell navigation.

```bash
floability instance latest [--base-dir DIR]
cd "$(floability instance latest)"
```

Options:

- `--base-dir DIR`: restrict lookup to this existing base directory. If omitted,
  Floability uses the most recently used base directory recorded by `run` or
  `execute`.

The successful command writes only the resolved instance path to stdout, so it
is safe to use in command substitution. An instance created by `instance
create` is not considered latest until it has been run.

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
- `--worker-transfer-ports A:B`: worker-to-worker transfer range; legacy
  `A,B` is accepted and the normalized value is passed to `vine_factory`

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
- `--cache-lookup-mode strict|local` (default: `strict`)
- `--base-dir DIR` (default: `~/floability-base-dir`)

`check` does not create an instance. Direct `fetch` and `verify` create a
data-only instance under `--base-dir` and update its
`latest_floability_instance` symlink. With cache mode `off`, no shared cache
directory is created or consulted.

---

## audit

Generate environment and data dependency information from a notebook.

```bash
floability audit --notebook <notebook.ipynb> \
  --backpack-name <generated-backpack>
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

Audit executes the notebook under tracing, writes intermediate dependency
reports in the current directory, and assembles a backpack at
`--backpack-name`. Review the generated workflow, environment, compute, and
data specifications before running it. Audit behavior and arguments are kept
compatible during the 0.3 structural rewrite.

---

## backpack

Initialize and manage backpacks.

### backpack init

Bootstrap a new Floability backpack directory structure.

```bash
floability backpack init --name <name> --from-template taskvine
floability backpack init --name <name> --from-template taskvine --script
floability backpack init --name <name> --from-workflow <notebook-or-script>
```

Options:

- `--name NAME` (required): backpack name or path; the leaf directory becomes the backpack name
- `--from-template taskvine|taskvine-data` (mutually exclusive with `--from-workflow`): bootstrap from a built-in template
- `--from-workflow PATH` (mutually exclusive with `--from-template`): use an
  existing notebook (`.ipynb`), Python script (`.py`), or shell script (`.sh`)
  as the workflow entrypoint
- `--script`: with `--from-template`, generate a Python entrypoint instead of
  a notebook
- `--force`: overwrite an existing backpack directory

The generated next-step message recommends `run` for notebooks and `execute`
for Python or shell entrypoints.

### backpack validate

Check a backpack directory for structural correctness.

```bash
floability backpack validate [path]
```

Arguments:

- `path` (optional, default: `.`): path to the backpack directory

Options:

- `--strict`: additionally parse the selected top-level workflow file and
  perform live metadata checks for configured data sources

This command checks the conventional backpack layout and currently requires
`compute/compute.yml`; it looks for a top-level workflow entrypoint. Execution
preflight is a separate contract: `run`, `execute`, and `instance create`
search recursively, require a compatible workflow plus an environment, and
allow compute configuration to be omitted.

### backpack update-env

Update a backpack's `environment.yml` from an instance with recorded, usable
environment metadata. The instance may be prepared (`ready`), completed, or
interrupted after environment preparation; a creation-only or failed instance
without a usable environment is rejected.

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

Remove unreferenced cache entries and, when explicitly requested, inactive
instance directories. Floability always prints a compact cleanup plan before
deleting. It prompts for confirmation unless `--yes` is given.

The cleanup category is always explicit: `--mode` is required, and invoking
`floability tools clean` without it fails before planning or deleting anything.
If no base selector is given, Floability uses the most recently used existing
base directory found in its recent-base registry. The registry contains
recently recorded bases, not necessarily every Floability base that exists.

```bash
floability tools clean [base selection] --mode MODE \
  [--dry-run] [--yes] [--jobs N]
```

Options:

- `--base-dir DIR`: clean this exact base directory
- `--all-registered-bases`: clean every existing base currently recorded in
  the recent-base registry
- `--data-cache-dir DIR`: override default `<base-dir>/floability-data-cache`

`--base-dir` and `--all-registered-bases` are mutually exclusive. A custom
data-cache directory can be used only with one selected base.

**Mode** (required):

| Value | What is removed |
|---|---|
| `data-only` | Unreferenced entries in `floability-data-cache/` |
| `env-only` | Unreferenced extracted environments and archives in `flo_common_env/` |
| `data-and-env` | Both unreferenced cache types |
| `instances-only` | Inactive `fi_*/` instance directories; caches remain |
| `all` | All inactive instances and cache entries not needed by retained instances |
| `keep-last` | Everything except the most recently run instance and its recorded data/environment dependencies |
| `incomplete-only` | Only `.floability-delete-*` remnants left by an interrupted cleanup; normal instances and cache entries remain |

`--mode keep-last` uses registry `last_run_at`, the same definition used by
`floability instance latest`; it does not use directory modification time or
the legacy latest symlink. Cleanup refuses to run if a selected base contains
active or unverifiable instance/worker ownership. Missing or corrupt metadata
for a retained instance also stops cleanup instead of guessing.

**Flags:**

- `--dry-run`: print the complete cleanup plan and change nothing
- `--yes`, `-y`: skip the confirmation prompt
- `--jobs N`: number of parallel file-deletion jobs; defaults to the smaller
  of four or the available CPU count. Use `--jobs 1` for serial deletion.

Parallel deletion requires `find`, `xargs`, and `rm`. Selected entries are
first renamed within their cache/base filesystem, then removed. If deletion is
interrupted, a later cleanup recognizes and removes the staged entry.

**Examples:**

```bash
# Preview unreferenced data entries in the most recently used base
floability tools clean --mode data-only --dry-run

# Remove unreferenced data entries
floability tools clean --mode data-only

# Remove only unreferenced environment entries using two deletion jobs
floability tools clean --mode env-only --jobs 2

# Remove unreferenced data and environment entries
floability tools clean --mode data-and-env

# Remove everything except the most recently run instance and its dependencies
floability tools clean --mode keep-last --yes

# Remove inactive instances from one explicit base
floability tools clean --base-dir /scratch/myuser --mode instances-only

# Clean every base currently recorded in the recent-base registry
floability tools clean --all-registered-bases --mode data-only --dry-run

# Remove all inactive instances and unreferenced caches without prompting
floability tools clean --mode all --yes --jobs 4

# Retry only deletion remnants left by an interrupted cleanup
floability tools clean --all-registered-bases --mode incomplete-only --yes
```

---

## Related References

- [Data Specification](data-spec.md)
- [Compute Specification](compute-spec.md)
- [Workers Concept](../concepts/workers.md)
- [Instances Concept](../concepts/instances.md)
