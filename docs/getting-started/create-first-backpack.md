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

- **Workflow**: A Jupyter notebook or Python script that defines the computation
- **Software**: A `conda` environment file specifying all dependencies
- **Compute**: Resource requirements (number of workers, cores, memory)
- **Data** (optional): Input datasets and their source locations

The goal is to package all of these together so your workflow runs
consistently everywhere — your laptop, a university cluster, or cloud.

> Learn more about the backpack structure and contents in the [Backpacks Concept](../concepts/backpacks.md) guide.


## Creating a Backpack

There are three ways to create a backpack, depending on what you already have:

1. **Manual creation**: Write the directory structure and files yourself
2. **From a template**: Start from a pre-built example notebook when you don't have existing code yet
3. **From an existing workflow**: Automatically scaffold the backpack structure around your existing notebook or script

In every case you will need to review and adjust the generated files to match
your actual computation, dependencies, and resource requirements.


### Option 1: Create a Backpack Manually

Creating a backpack manually gives you full control. The required layout is:

```
my-analysis/
├── compute/
│   └── compute.yml        # Worker resource specifications
├── software/
│   └── environment.yml    # Conda dependencies
└── workflow/
    └── my-analysis.ipynb  # Your workflow (notebook, .py, or .sh)
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
  - python=3.13
  - numpy=2.6.4
  - ndcctools=7.16.4       # required for TaskVine
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


### Option 2: From a Template (Start from Scratch)

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
manager_ports = os.environ.get('VINE_MANAGER_PORTS', '9123,9150')
m = vine.Manager(port=int(manager_ports.split(',')[0]))
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


### Option 3: From an Existing Workflow

If you already have a notebook or script, the `--from-workflow` flag
scaffolds the full backpack structure around it automatically.

```bash
floability backpack init --name my-analysis --from-workflow /path/to/your/notebook.ipynb
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

This checks:
- ✓ Required directories exist (workflow, software, compute)
- ✓ Workflow file is present (.ipynb, .py, or .sh)
- ✓ All YAML files are valid and parseable

Output:
```
[floability] Validating backpack: my-first-analysis
[floability] Status: VALID
[floability] Workflow: my-first-analysis.ipynb
[floability] Has data specification: no
```

If validation fails, read the errors carefully — they point to missing files or invalid YAML.


## Next Steps

1. **Run your backpack**: [Run Your First Backpack](run-first-backpack.md)
2. **Understand backpack concepts**: [Backpacks](../concepts/backpacks.md)
3. **Configure data**: [Data Specification](../reference/data-spec.md)
4. **Deploy on clusters**: [Deployment Overview](../deployment/index.md)
