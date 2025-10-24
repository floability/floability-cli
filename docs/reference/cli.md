# CLI Reference

Complete command-line reference for the Floability CLI.

## Global Options

```bash
floability [OPTIONS] COMMAND [ARGS]...
```

### Common Options

- `--help` — Show help message and exit
- `--version` — Show version and exit
- `--verbose` — Enable verbose output

## Commands

### `floability run`

Execute a backpack workflow with optional distributed workers.

```bash
floability run --backpack PATH [OPTIONS]
```

#### Options

- `--backpack PATH` — Path to the backpack directory (required)
- `--batch-type TYPE` — Batch system type: `condor`, `slurm`, or `uge`
- `--data-spec PATH` — Path to data specification file (default: `<backpack>/data/data.yml`)
- `--data-profile NAME` — Data profile to use (default: from spec file)
- `--notebook PATH` — Specific notebook to run (default: auto-detect)
- `--kernel NAME` — Jupyter kernel to use
- `--manager-name NAME` — TaskVine manager name
- `--manager-port PORT` — TaskVine manager port (default: 9123)

#### Examples

Run with local workers:

```bash
floability run --backpack example/matrix-multiplication
```

Deploy to HTCondor:

```bash
floability run --backpack example/cms-physics-dv5 --batch-type condor
```

Specify data profile:

```bash
floability run --backpack example/cms-physics-dv5 \
  --data-spec data/data.yml \
  --data-profile production
```

### `floability data`

Manage data sources defined in data specification files.

```bash
floability data --data-spec PATH [OPTIONS]
```

#### Modes

- `--mode check` — Validate data sources are reachable (no download)
- `--mode fetch` — Download/copy data to staging locations
- `--mode verify` — Fetch data and verify integrity (checksums/sizes)

#### Options

- `--data-spec PATH` — Path to data specification YAML file (required)
- `--backpack PATH` — Path to backpack root (default: inferred from spec)
- `--data-profile NAME` — Data profile to use (default: from spec)
- `--check-details` — Show detailed per-item metadata (with `check` mode)
- `--verbose` — Show per-item progress
- `--force-fetch` — Overwrite existing files

#### Examples

Check data sources:

```bash
floability data --data-spec data/data.yml --mode check --verbose
```

Fetch data with specific profile:

```bash
floability data --data-spec data/data.yml \
  --mode fetch \
  --data-profile local_data
```

Verify with strict checksums:

```bash
floability data --data-spec data/data.yml \
  --mode verify \
  --force-fetch
```

### `floability audit`

Audit notebook execution and extract dependencies.

```bash
floability audit --notebook PATH [OPTIONS]
```

Executes a Jupyter notebook and audits the execution using `strace` to extract dependencies.

#### Options

- `--notebook PATH` — Path to notebook file (required)
- `--kernel NAME` — Jupyter kernel to use (required)
- `--manager-name NAME` — TaskVine manager name (required)
- `--manager-port PORT` — TaskVine manager port (default: 9123)
- `--output-dir PATH` — Directory for output files (default: current directory)

#### Output

Generates:
- `manager_environment.yml` — Dependencies for the manager/notebook
- `worker_environment.yml` — Dependencies for distributed workers

#### Example

```bash
floability audit --notebook example/matrix-multiplication/workflow/matrix-multiplication.ipynb \
  --kernel python3 \
  --manager-name my_manager \
  --manager-port 9123
```

### `floability pack`

Package a notebook into a complete backpack (experimental).

```bash
floability pack --notebook PATH [OPTIONS]
```

Analyzes a notebook using `sciunit` to determine required components and creates a backpack structure.

#### Options

- `--notebook PATH` — Path to notebook file (required)
- `--output PATH` — Output directory for backpack (default: `./backpack`)
- `--compute-file PATH` — Path to existing compute specification
- `--data-spec PATH` — Path to existing data specification

#### Example

```bash
floability pack --notebook my-analysis.ipynb --output my-backpack
```

### `floability clean`

Clean up temporary files and caches.

```bash
floability clean [OPTIONS]
```

#### Options

- `--backpack PATH` — Clean specific backpack directory
- `--all` — Clean all Floability temporary files
- `--dry-run` — Show what would be deleted without deleting

#### Example

```bash
floability clean --backpack example/matrix-multiplication --dry-run
```

## Environment Variables

Floability recognizes these environment variables:

- `FLOABILITY_BACKPACK_ROOT` — Default backpack root directory
- `FLOABILITY_DATA_CACHE` — Location for data cache
- `TASKVINE_MANAGER_NAME` — Default TaskVine manager name
- `TASKVINE_PORT` — Default TaskVine port

## Configuration Files

### Compute Specification (`compute/compute.yml`)

```yaml
vine_factory_config:
  min-workers: 2
  max-workers: 10
  cores: 4
  memory: 4096    # MB
  disk: 10000     # MB
  timeout: 3600   # seconds
```

### Software Environment (`software/environment.yml`)

Standard Conda environment file:

```yaml
name: my_env
channels:
  - conda-forge
dependencies:
  - python=3.11
  - numpy
  - pandas
  - pip:
    - custom-package
```

### Data Specification (`data/data.yml`)

See [Data Handling Guide](../guides/data.md) for complete reference.

## Exit Codes

- `0` — Success
- `1` — General error
- `2` — Invalid arguments or configuration
- `3` — Data verification failed
- `4` — Workflow execution failed
- `5` — Worker connection or batch submission failed

## See Also

- [Getting Started](../getting-started/index.md) — Installation and setup
- [Backpack Structure](../guides/backpack.md) — Understanding backpacks
- [Data Handling](../guides/data.md) — Data specification format
- [Examples](https://github.com/floability/floability-examples) — Real-world workflows
