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

There are four ways to create a backpack. They progress from fully manual to
increasingly automated:

1. **[Manual creation](#option-1-create-a-backpack-manually)** — Write the
   directory structure and files yourself. This option is intended for
   advanced users who need the most control over every workflow, software,
   compute, and data specification.
2. **[From a template](#option-2-from-a-template-start-from-scratch)** — Use
   this when you do not yet have workflow code and want a working backpack
   that you can edit as you develop it.
3. **[From an existing workflow](#option-3-from-an-existing-workflow)** — Use
   this when you have workflow code but do not have access to a runnable
   environment. Floability scaffolds the structure around your code; you then
   complete and edit its specifications.
4. **[Automatic creation (experimental Audit)](#option-4-automatic-creation-experimental-audit)**
   — Use this when you have a notebook that already runs successfully in an
   accessible Conda environment. Audit observes one execution and generates
   initial specifications for manual review.

Whichever approach you choose, review the resulting files before execution so
they match your actual dependencies, data, and resource requirements.


### Option 1: Create a Backpack Manually

Creating a backpack manually gives you full control. A complete layout is:

```
my-analysis/
├── compute/               # Worker resource specifications
│   └── compute.yml
├── data/                  # Optional managed input data
│   ├── data.yml           # Sources and instance target paths
│   └── inputs/
│       └── sample.csv     # Example file bundled with the backpack
├── software/
│   └── environment.yml    # Conda dependencies
└── workflow/
    └── my-analysis.ipynb  # Your workflow (notebook, .py, or .sh)
```

Create the directories:

```bash
mkdir -p my-analysis/{compute,data/inputs,software,workflow}
```

Place your workflow file in `my-analysis/workflow/`, then write the software
and compute configuration files.

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

Pin versions when your workflow depends on specific package behavior. As an
alternative starting point, export the explicitly requested packages from the
currently active Conda environment:

```bash
conda env export --from-history > my-analysis/software/environment.yml
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

**`data/data.yml`** — tell Floability where inputs come from and where they
should appear inside the instance workflow directory:

```yaml
schema_version: 1.0
default_profile: local

profiles:
  local:
    data:
      - name: sample_input
        source_type: backpack
        source: data/inputs/sample.csv
        target_location: data/inputs/sample.csv
```

Place the example source at `my-analysis/data/inputs/sample.csv`. During
instance preparation, Floability stages it as `data/inputs/sample.csv` for the
workflow. Replace the source with an HTTP, S3, Pelican, XRootD, filesystem, or
other backpack source as needed.

The `data/` directory is optional only when the workflow has no inputs that
Floability needs to manage. If it reads input data, include `data/data.yml` so
the source and target paths are explicit. See
[Data Specification](../reference/data-spec.md) for the complete format.


### Option 2: From a Template (Start from Scratch)

Use a template when you **don't have existing code** and want a working
starter notebook to edit. The template demonstrates the TaskVine distributed
computing pattern, but you will need to replace the example logic with your
own computation.

#### Template with Floability-managed data

Use the `taskvine-data` template when you want Floability to manage input-data
staging and local data caching. It contains all files needed for a complete
Floability backpack example, which you can edit for your own workflow.

```bash
floability backpack init --name my-analysis --from-template taskvine-data
```

This creates:

```
my-analysis/
├── compute/
│   └── compute.yml
├── data/
│   ├── data.yml
│   └── text_data/
│       └── local-sample.txt
├── software/
│   └── environment.yml
└── workflow/
    └── my-analysis.ipynb
```

#### Files in the generated backpack

- **`workflow/my-analysis.ipynb`**: A working TaskVine notebook that processes
  staged text files on workers.
- **`software/environment.yml`**: The Conda environment containing Python and
  TaskVine.
- **`compute/compute.yml`**: The initial `vine_factory` worker and resource
  configuration.
- **`data/data.yml`**: The Floability data specification. It declares one
  backpack-local input and one HTTP input, along with their paths inside the
  instance workflow directory.
- **`data/text_data/local-sample.txt`**: A small input file bundled with the
  backpack.

The HTTP input is
[*War and Peace*](https://www.gutenberg.org/ebooks/2600) from Project
Gutenberg. It is not stored in the backpack. Floability downloads it into the
instance as `data/text_data/war-and-peace.txt` before starting the workflow.
The first download therefore requires outbound HTTPS access from the machine
preparing the instance.

The notebook then gives both staged files to TaskVine workers and computes
line counts, word counts, and occurrences of `war` and `peace`:

```python
import glob

DATA_DIR = "data/text_data"
files = sorted(glob.glob(os.path.join(DATA_DIR, "*.txt")))
declared = {path: m.declare_file(path) for path in files}

def worker_function(file_path, keywords=("war", "peace")):
    import re
    from pathlib import Path

    text = Path(file_path).read_text(encoding="utf-8", errors="replace")
    words = re.findall(r"\b[\w']+\b", text.casefold())
    return {
        "file": Path(file_path).name,
        "word_count": len(words),
        "keyword_counts": {
            keyword: words.count(keyword) for keyword in keywords
        },
    }

for file_path in files:
    t = vine.PythonTask(worker_function, file_path)
    t.add_input(declared[file_path], file_path)
    m.submit(t)
```

Edit `data/data.yml` to substitute your own backpack, filesystem, HTTP, S3,
Pelican, or XRootD inputs. See
[Data Specification](../reference/data-spec.md) for the complete format.

#### Basic template without managed data

Use the basic `taskvine` template when your application code or workflow
manager handles downloading, staging, and caching its own data. This template
does not include a Floability `data/data.yml` specification.

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

#### What both templates provide

Both template notebooks demonstrate the TaskVine distributed-computing
pattern:

**1. Manager setup** — Connect to the TaskVine manager using environment
variables set automatically by Floability:

```python
import os
import ndcctools.taskvine as vine

manager_name = os.environ.get("VINE_MANAGER_NAME")
ports_text = os.environ.get("VINE_MANAGER_PORTS", "9123,9150")
manager_ports = [
    int(value.strip())
    for value in ports_text.replace(":", ",").split(",")
    if value.strip()
]
m = vine.Manager(manager_ports, name=manager_name)
```

**2. Task definition** — Define the function that workers execute:

```python
def worker_function(value, sleep_time=1):
    import time

    time.sleep(sleep_time)
    return {"input": value, "output": value * 2}
```

**3. Task submission** — Distribute work to workers:

```python
for i in range(20):
    task = vine.PythonTask(worker_function, i, sleep_time=1)
    m.submit(task)
```

**4. Result collection** — Gather completed results:

```python
results = []
while not m.empty():
    done = m.wait(5)
    if done and done.successful():
        results.append(done.output)
```

#### What you need to edit

Replace the example worker function and task-submission logic with your actual
computation. Adjust `compute/compute.yml` for the workload, list all required
dependencies in `software/environment.yml`, and update `data/data.yml` when
using the data template.


### Option 3: From an Existing Workflow

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


### Option 4: Automatic Creation (Experimental Audit)

> **Experimental feature:** Audit is under active development. Treat the
> generated backpack as a starting point and manually verify its software,
> data, compute, and workflow specifications before relying on it.

Use `floability audit` when you already have a working Jupyter notebook and
want Floability to observe its execution. Audit runs the notebook with
dependency tracing, captures its Python environment, detects files accessed
from the directories you identify, and generates a backpack for review.

The notebook's dependencies must already be installed in the environment used
for the audit:

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
│   └── environment.yml    # captured from your Conda environment
├── workflow/
│   └── my-analysis.ipynb
└── data/
    ├── data.yml                 # generated from detected files
    └── <data files>             # copied from --data-dirs
```

#### Key flags

| Flag | Description |
|---|---|
| `--notebook` | Required path to the notebook to audit |
| `--backpack-name` | Required name or path for the generated backpack |
| `--conda-env` | Conda environment prefix in which to run the notebook |
| `--data-dirs` | One or more directories containing possible input files |
| `--no-worker` | Skip the audit worker for a non-TaskVine notebook |
| `--kernel` | Jupyter kernel used to execute the notebook |
| `--force` | Overwrite an existing backpack directory |

For a notebook that does not use TaskVine, add `--no-worker`:

```bash
floability audit \
  --notebook gis-analysis.ipynb \
  --conda-env /shared/envs/gis-env \
  --data-dirs ./data \
  --no-worker \
  --backpack-name gis-backpack
```

#### After running audit

Audit records what it observes, so its output is a starting point rather than
a complete portability guarantee. Review these files before running:

- **`compute/compute.yml`**: Set appropriate workers, cores, memory, disk, and
  site-specific options.
- **`software/environment.yml`**: Verify the Python dependencies and manually
  add required binaries, system libraries, and other Conda dependencies.
- **`data/data.yml`**: Verify detected files and replace local sources with
  stable S3, Pelican, or HTTP sources when the backpack must be portable.


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
floability backpack validate my-analysis
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
[floability]   Path: /path/to/my-analysis
[floability]   Workflow: my-analysis.ipynb
======================================================================
```

If validation fails, read the errors carefully — they point to missing files or invalid YAML.


## Next Steps

1. **Run your backpack**: [Run Your First Backpack](run-first-backpack.md)
2. **Lock in concrete versions**: After a successful run, capture the exact installed versions back into `environment.yml` — [Update Environment](../how-to/update-environment.md)
3. **Understand backpack concepts**: [Backpacks](../concepts/backpacks.md)
4. **Configure data**: [Data Specification](../reference/data-spec.md)
5. **Deploy on clusters**: [Deployment Overview](../deployment/index.md)
