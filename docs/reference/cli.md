# CLI Commands Reference

This page documents the current Floability CLI commands and options.

## Top-Level Command

```bash
floability <command> [options]
```

Top-level option:

- `-v, --version`: show CLI version

Available commands:

- `run`: interactive run mode (starts Jupyter)
- `execute`: batch mode (no Jupyter UI)
- `instance`: create/list/stop instances
- `workers`: start/stop/status for workers
- `data`: check/fetch/verify data specs
- `audit`: dependency extraction from notebooks

## run

Run a workflow in interactive mode.
Typical usage:

```bash
floability run --backpack <backpack-root>
```

You can also run on an existing instance:

```bash
floability run --instance <instance-name-or-path>
```

### Options

Core execution options:

- `--backpack PATH`: backpack directory
- `--instance PATH_OR_NAME`: existing instance (mutually exclusive with `--backpack`)
- `--environment PATH`: manager environment spec
- `--worker-environment PATH`: worker environment spec
- `--notebook FILE`: notebook to run
- `--python-script FILE`: python script to run
- `--prefer-python`: prefer script over notebook when both exist

Run/session options:

- `--jupyter-port INT` (default: `8888`)
- `--manager-ports A,B` (default: `9123,9150`)
- `--manager-name NAME`
- `--env-vars KEY=VALUE,...`

Directory and instance options:

- `--base-dir DIR` (default behavior: normalized to `~/floability-base-dir` when omitted)
- `--instance-prefix PREFIX`
- `--backpack-root DIR` (default: `.`)

Data options:

- `--data-spec FILE`
- `--data-profile NAME`
- `--data-cache-mode off|symlink|hardlink|copy` (default: `symlink`)
- `--data-cache-dir DIR`
- `--force-data-cache`
- `--fingerprint-mode meta|sample|strict` (default: `meta`)
- `--continue-on-data-failure`

Worker/factory options:

- `--no-worker`
- `--batch-type local|condor|uge|slurm`
- `--workers INT`
- `--cores-per-worker INT`
- `--batch-options STRING`
- `--compute-spec FILE`
- `--debug-workers`

Other options:

- `--measure-performance`
- `--no-update-backpack`
- `--per-instance-env`

## execute

Run a workflow in batch mode (no interactive Jupyter session).

```bash
floability execute --backpack <backpack-root>
```

`execute` accepts the same options as `run` (same parser group).

## instance

Manage instance lifecycle.

### instance create

```bash
floability instance create --backpack <backpack-root> [options]
```

Options:

- `--backpack PATH` (required)
- `--name NAME`
- `--base-dir DIR`
- `--skip-data`
- `--data-profile NAME`
- `--data-cache-mode off|symlink|hardlink|copy` (default: `off`)
- `--force-data-cache`
- `--fingerprint-mode meta|sample|strict` (default: `meta`)
- `--environment PATH`
- `--worker-environment PATH`
- `--manager-name NAME`
- `--manager-ports A,B` (default: `9123,9150`)
- `--env-vars KEY=VALUE,...`
- `--measure-performance`

### instance list

```bash
floability instance list [--show-paths] [--all-details]
```

Options:

- `--show-paths`
- `--all-details`

### instance stop

```bash
floability instance stop <instance-name-or-path>
```

Arguments:

- positional `instance`: short name or instance path

## workers

Manage worker factory for an instance.

### workers start

```bash
floability workers start --instance <instance-name-or-path> [options]
```

Options:

- `--instance PATH_OR_NAME` (required)
- `--batch-type local|condor|uge|slurm`
- `--workers INT`
- `--cores-per-worker INT`
- `--batch-options STRING`
- `--compute-spec FILE`
- `--debug-workers`

### workers stop

```bash
floability workers stop --instance <instance-name-or-path>
```

### workers status

```bash
floability workers status --instance <instance-name-or-path>
```

## data

Run data operations directly against a data spec.

```bash
floability data --mode check --data-spec <data.yml>
```

Options:

- `--mode check|fetch|verify` (default: `check`)
- `--data-spec FILE`
- `--backpack DIR`
- `--check-details`
- `--verbose`
- `--force-fetch`
- `--data-profile NAME`
- `--data-cache-mode off|symlink|hardlink|copy` (default: `off`)
- `--data-cache-dir DIR`
- `--force-data-cache`
- `--fingerprint-mode meta|sample|strict` (default: `meta`)
- `--base-dir DIR`

## audit

Generate dependency information from a notebook.

```bash
floability audit --notebook <notebook.ipynb>
```

Options:

- `--notebook FILE` (required)
- `--kernel NAME`
- `--manager-port PORT` (default: `9123`)
- `--manager-name NAME`
- `--cell-level`

## Related References

- [Data Specification](data-spec.md)
- [Compute Specification](compute-spec.md)
- [Workers Concept](../concepts/workers.md)
- [Instances Concept](../concepts/instances.md)
