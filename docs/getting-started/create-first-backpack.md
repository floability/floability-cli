# Create Your First Backpack

This guide walks you through creating a backpack — a self-contained directory
bundle that packages your workflow, software environment, and compute
requirements together for reproducible distributed execution.

> **New to Floability?** Before creating your own backpack, try
> [running a ready-made example](run-first-backpack.md) to get familiar with
> the tool and understand the backpack structure.


## Before you begin

Complete [Installation](installation.md) first. Verify your setup:

```bash
floability --version
floability backpack --help
```


## What is a Backpack?

A **backpack** is a self-contained directory bundle that contains everything
needed to run a reproducible workflow:

- **Workflow**: A Jupyter notebook, Python script, or shell script that defines
  the computation
- **Software**: A `conda` environment file specifying all dependencies
- **Compute**: Resource requirements (number of workers, cores, memory)
- **Data** (optional): Input datasets and their source locations

The goal is to package all of these together so your workflow runs
consistently everywhere — your laptop, a university cluster, or cloud.

> Learn more about the backpack structure and contents in the [Backpacks Concept](../concepts/backpacks.md) guide.


## Creating a Backpack

There are four ways to create a backpack, depending on what you already have:

1. **Automatic creation (audit)**: Run your existing notebook with dependency tracing to automatically generate the full backpack structure, including environment, data files, and compute configuration
2. **Manual creation**: Write the directory structure and files yourself
3. **From a template**: Start from a pre-built example notebook when you don't have existing code yet
4. **From an existing workflow**: Automatically scaffold the backpack structure around your existing notebook or script

In every case you will need to review and adjust the generated files to match
your actual computation, dependencies, and resource requirements.


### Option 1: Automatic Creation (Audit)

The `floability audit` command runs your notebook with dependency tracing and automatically generates a complete backpack. It captures the software environment and data files your notebook accessed during execution. Before running your notebook with `floability audit`, make sure to pre-provision the execution environment with all necessary dependencies either locally or using Conda.

```bash
floability audit \
  --notebook my-analysis.ipynb \
  --conda-env /path/to/my-conda-env \
  --data-dirs ./data \
  --backpack-name my-backpack
```

This creates:

```
my-backpack/
├── compute/
│   └── compute.yml
├── software/
│   └── environment.yml    # captured from your conda env
├── workflow/
│   └── my-analysis.ipynb
└── data/
    ├── data.yml           # generated from detected data files
    └── <data files>       # copied from your data directory
```

#### Key flags

| Flag | Description |
|---|---|
| `--notebook` | (required) Path to the notebook to audit |
| `--conda-env` | Conda environment prefix where the notebook runs |
| `--data-dirs` | One or more directories containing input data files |
| `--no-worker` | Skip vine worker (for non-distributed notebooks) |
| `--kernel` | Jupyter kernel to use when analyzing the notebook |
| `--backpack-name` |(required) Name for the generated backpack directory |
| `--force` | Overwrite existing backpack directory |

#### Distributed workflows (TaskVine)

For notebooks that use TaskVine:

```bash
floability audit \
  --notebook cms-analysis.ipynb \
  --conda-env /shared/envs/physics-env \
  --data-dirs ./data \
  --backpack-name cms-backpack
```

#### Non-distributed workflows

For notebooks that do not use TaskVine, add `--no-worker`:

```bash
floability audit \
  --notebook gis-analysis.ipynb \
  --conda-env /shared/envs/gis-env \
  --data-dirs ./data \
  --no-worker \
  --backpack-name gis-backpack
```

#### After running audit

Review and adjust the generated files before running:

- **`compute/compute.yml`**: Set worker count, cores, and memory for your workload.
- **`software/environment.yml`**: Verify all dependencies were captured correctly. Currently, only Python dependencies are being captured. Any binaries or system libraries have to be manually added.
- **`data/data.yml`**: Update `source_type` and `source` paths if you plan to fetch data from a remote source (S3, Pelican, HTTP) rather than bundling files in the backpack.


### Option 2: Create a Backpack Manually

Creating a backpack manually gives you full control. The required layout is:

```
my-analysis/
├── software/
│   └── environment.yml    # Conda dependencies
├── workflow/
│   └── my-analysis.ipynb  # Your workflow (notebook, .py, or .sh)
└── compute/               # Recommended; optional for execution preflight
    └── compute.yml        # Worker resource specifications
```

Create the directories:

```bash
mkdir -p my-analysis/{compute,software,workflow}
```

Then place your workflow file in `workflow/` and write the two YAML configuration files.

**`software/environment.yml`** — list all packages your notebook needs:

```yaml
name: my-analysis
channels:
  - conda-forge
dependencies:
  - python=3.12
  - numpy=2.2
  - ndcctools=7.17.1       # include when the workflow uses TaskVine
```

Make sure include proper versions if your workflow relies on specific versions of packages.

```bash
conda env export --from-history > software/environment.yml
```

**`compute/compute.yml`** — describe the worker resources:

```yaml
vine_factory_config:
  min-workers: 2
  max-workers: 10
  cores: 4
  memory: 4096      # MB
  disk: 10000       # MB
```

Optionally add a `data/data.yml` if your workflow reads input files.
See [Data Specification](../reference/data-spec.md) for the format.


### Option 3: From a Template (Start from Scratch)

Use a template when you **don't have existing code** and want a working
starter notebook to edit. The template demonstrates the TaskVine distributed
computing pattern, but you will need to replace the example logic with your
own computation.

#### Basic template:
Use the basic `taskvine` template when you don’t need Floability to handle your data; instead, your code or workflow manager downloads and stages the data itself.

```bash
floability backpack init --name my-analysis --from-template taskvine
```

This creates:

```
my-analysis/
├── compute/
│   └── compute.yml
├── software/
│   └── environment.yml
└── workflow/
    └── my-analysis.ipynb
```

#### What the template provides

The template notebook demonstrates the TaskVine distributed-computing pattern:

**1. Manager setup** — Connects to the TaskVine manager (environment variables set automatically):
```python
import os
import ndcctools.taskvine as vine

manager_name = os.environ.get('VINE_MANAGER_NAME')
ports_text = os.environ.get('VINE_MANAGER_PORTS', '9123,9150')
manager_ports = [
    int(value.strip())
    for value in ports_text.replace(':', ',').split(',')
    if value.strip()
]
m = vine.Manager(manager_ports, name=manager_name)
```

**2. Task definition** — Structure a worker function:
```python
def worker_function(value, sleep_time=1):
    time.sleep(sleep_time)
    return {'input': value, 'output': value * 2}
```

**3. Task submission** — Distribute tasks to workers:
```python
for i in range(20):
    task = vine.PythonTask(worker_function, i, sleep_time=1)
    m.submit(task)
```

**4. Result collection** — Gather results:
```python
results = []
while not m.empty():
    done = m.wait(5)
    if done and done.successful():
        results.append(done.output)
```

#### What you need to edit

Replace the example `worker_function` and task submission logic with your actual computation. The template is a starting point to show how to structure your code for distributed execution with TaskVine. You will also need to adjust the `compute.yml` resource specifications and add any dependencies to `environment.yml` that your workflow requires.

#### Template with data handling
Use the `taskvine-data` template if you want an example that includes a `data.yml` which floability can use to stage files on instances before running the workflow. And the code in the notebook demonstrates how to declare files and add them as inputs to tasks.


```bash
floability backpack init --name my-analysis --from-template taskvine-data
```

This template includes file staging on workers:

```python
import glob

DATA_DIR = "data/text_data"
files = glob.glob(os.path.join(DATA_DIR, "*"))
declared = {path: m.declare_file(path) for path in files}

def worker_function(file_path):
    import os
    return {'file': file_path, 'size_bytes': os.path.getsize(file_path)}

for file_path in files:
    t = vine.PythonTask(worker_function, file_path)
    t.add_input(declared[file_path], file_path)
    m.submit(t)
```

This also creates a `data/data.yml` file where you specify input sources (S3, HTTP, local directory). See [Data Specification](../reference/data-spec.md) for configuration details.


### Option 4: From an Existing Workflow

If you already have a notebook, Python script, or shell script, the
`--from-workflow` flag
scaffolds the full backpack structure around it automatically.

```bash
floability backpack init --name my-analysis --from-workflow /path/to/your/notebook.ipynb
```

The command accepts `.ipynb`, `.py`, and `.sh`. Its final guidance uses
`floability run` for a notebook and `floability execute` for Python or shell.
To start from a built-in Python template instead, add `--script`:

```bash
floability backpack init --name my-analysis \
  --from-template taskvine --script
```

This prompts you through two quick questions:

**1. Environment configuration:**
```
[floability] Environment Configuration
--------------------------------------------------
Options:
  1. Path to existing environment.yml
  2. Provide conda and/or pip packages
  3. Skip (barebones: python + ndcctools)

Select option (1-3, default 3):
```

Choose based on your workflow:
- **Option 1**: If you already have an `environment.yml` from another project
- **Option 2**: For conda and/or pip packages (recommended for most scientific work)
  - Conda example: `numpy,scipy,pandas,scikit-learn`
  - Pip example: `plotly,altair`
  - Mix both: provide comma-separated lists for each
  - **Version pinning**: You can specify versions like `numpy=1.24.0` or `python=3.11`
  - Note: `python` and `ndcctools` are always included; if you specify them with versions, your version takes precedence
- **Option 3**: Default barebones (includes Python + TaskVine, you can edit later)

If you skip all questions and press Enter, you get Option 3—a barebones environment that you can customize later by editing `software/environment.yml`.

**2. Data configuration:**
```
[floability] Data Configuration
--------------------------------------------------
Create data.yml? (y/n, default n):
```

Choose "y" if your workflow loads data files. You'll configure `data.yml` later.

> **Note:** When `data.yml` is created, it starts as a template skeleton. You must complete it with your actual data sources before running the backpack.

#### What you need to edit afterward

The command creates the backpack structure and copies your file into
`workflow/`, but you will still need to:

- **`software/environment.yml`**: Verify all dependencies are listed
  ```yaml
  name: my-analysis
  channels:
    - conda-forge
  dependencies:
    - python
    - numpy
    - scipy
    - ndcctools
  ```
- **`compute/compute.yml`**: Adjust worker requirements for your workload
  ```yaml
  vine_factory_config:
    min-workers: 2
    max-workers: 10
    cores: 4
    memory: 4096      # MB
    disk: 10000       # MB
  ```
- **Notebook**: Wrap your computation in TaskVine tasks so it can distribute work across workers (see the template example above for a pattern to follow). You also need to copy any other files your notebook depends on into the `workflow/` directory so they are available when the backpack runs.

- **`data/data.yml`** (if created): Fill in your actual data sources and paths before running the backpack.


## Tips Before Creating a Backpack

### Know your dependencies
Identify all Python packages your workflow needs:
```bash
# Export from an existing environment
conda env export --from-history > environment.yml

# Or list packages manually
pip freeze | grep -E "numpy|scipy|pandas"
```

### Identify your compute footprint
Estimate what resources each task needs:
- **Cores**: 1–4 for typical data processing
- **Memory**: 2–8 GB per worker for typical analysis
- **Workers**: Start with 2–4, scale up after a successful test run


### Plan file organization for complex workflows
You can add helper scripts alongside the main notebook:
```
my-analysis/
├── compute/
│   └── compute.yml
├── software/
│   └── environment.yml
├── workflow/
│   ├── my-analysis.ipynb   # Main entry point
│   └── helpers.py          # Supporting utilities
└── data/
    └── data.yml
```

Helper files placed in `workflow/` are available when the notebook runs.


## Validate Your Backpack

After creating your backpack, validate the structure:

```bash
floability backpack validate my-first-analysis
```

This conventional structure check requires `workflow/`,
`software/environment.yml`, and `compute/compute.yml`; validates the YAML; and
looks for a top-level `.ipynb`, `.py`, or `.sh` workflow file. Add `--strict`
to parse the entrypoint and perform live metadata checks for data sources.

`run`, `execute`, and `instance create` also perform execution preflight before
creating instance state. That preflight searches recursively, requires a
mode-compatible entrypoint and environment, and permits `compute.yml` to be
absent.

Output:
```
======================================================================
[floability] Backpack Validation: VALID
======================================================================
[floability] ✓ Backpack structure is valid
[floability]   Path: /path/to/my-first-analysis
[floability]   Workflow: my-first-analysis.ipynb
======================================================================
```

If validation fails, read the errors carefully — they point to missing files or invalid YAML.


## Next Steps

1. **Run your backpack**: [Run Your First Backpack](run-first-backpack.md)
2. **Lock in concrete versions**: After a successful run, capture the exact installed versions back into `environment.yml` — [Update Environment](../how-to/update-environment.md)
3. **Understand backpack concepts**: [Backpacks](../concepts/backpacks.md)
4. **Configure data**: [Data Specification](../reference/data-spec.md)
5. **Deploy on clusters**: [Deployment Overview](../deployment/index.md)
