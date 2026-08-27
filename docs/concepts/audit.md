# Audit and Environment Capture

`floability audit` executes an existing Jupyter notebook under Linux tracing
to observe imported software and opened data files. It writes dependency
reports and, in normal notebook-level mode, assembles a backpack for review.
Audit remains a compatibility feature during the 0.3 structural rewrite; its
generated specifications are a starting point, not a substitute for validation.

## Basic usage

`--notebook` and `--backpack-name` are required:

```bash
floability audit \
  --notebook path/to/analysis.ipynb \
  --backpack-name generated-analysis
```

The notebook must already run in the selected environment. To execute it with
a particular Conda prefix:

```bash
floability audit \
  --notebook analysis.ipynb \
  --conda-env /shared/envs/analysis \
  --backpack-name generated-analysis
```

For a notebook that does not create a TaskVine manager, disable the audit
worker:

```bash
floability audit \
  --notebook analysis.ipynb \
  --no-worker \
  --backpack-name generated-analysis
```

## What normal audit writes

Notebook-level audit leaves these intermediate reports in the current
directory:

| File | Purpose |
|---|---|
| `manager_environment.yml` | packages observed in the notebook process |
| `worker_environment.yml` | packages observed in TaskVine worker execution |
| `manager_data_dependencies.yml` | files observed on the manager side |
| `worker_data_dependencies.yml` | files observed on the worker side |

It also creates the directory selected by `--backpack-name`:

```text
generated-analysis/
├── compute/
│   └── compute.yml
├── software/
│   └── environment.yml
├── workflow/
│   ├── analysis.ipynb
│   └── <detected local Python helpers>
└── data/                  # present when local data was detected
    ├── data.yml
    └── <bundled files>
```

The backpack uses the manager environment report. Review whether workers need
a separate environment before relying on the generated result.

## Data directories

Use `--data-dirs` to identify roots whose accessed files should be treated as
workflow inputs:

```bash
floability audit \
  --notebook analysis.ipynb \
  --data-dirs ./data ./inputs \
  --backpack-name generated-analysis
```

Relative paths are interpreted from the notebook directory. Detected local
files are bundled into the backpack; update `data/data.yml` afterward if they
should instead come from HTTP, S3, Pelican/OSDF, or XRootD.

## TaskVine options

Distributed notebooks can select the manager identity used during audit:

```bash
floability audit \
  --notebook analysis.ipynb \
  --manager-name audit-manager \
  --manager-port 9123 \
  --backpack-name generated-analysis
```

`--no-worker` suppresses the audit-launched worker. It does not change the
notebook itself.

## Cell-level mode

`--cell-level` writes `cell_level_dependencies.yml` plus its environment/data
intermediates, then exits before normal backpack assembly. The CLI still
requires `--backpack-name` for compatibility, but that value is not consumed
by the current cell-level path.

```bash
floability audit \
  --notebook analysis.ipynb \
  --cell-level \
  --backpack-name unused-in-cell-level-mode
```

## Requirements and limitations

- Linux and `strace` are required.
- The notebook and all required packages must work before audit begins.
- `vine_worker` is required unless `--no-worker` is selected.
- Audit may report missing worker trace files in `--no-worker` mode; inspect
  the generated files rather than treating a success exit alone as proof of a
  complete capture.
- Native binaries, system libraries, dynamically downloaded resources, and
  files not observed during this execution may need manual additions.

## Review before running

1. Validate the generated backpack with `floability backpack validate`.
2. Inspect `software/environment.yml` for missing Conda/system dependencies.
3. Adjust `compute/compute.yml` for the target scheduler and resources.
4. Review bundled data, checksums, and source URLs.
5. Run a small profile before scaling up.
