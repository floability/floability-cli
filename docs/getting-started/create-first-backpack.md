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


## Creating a Backpack

There are three ways to create a backpack, depending on what you already have:

1. **Manual creation**: Write the directory structure and files yourself
2. **From an existing workflow** (most common): Automatically scaffold the backpack structure around your existing notebook or script
3. **From a template**: Start from a pre-built example notebook when you don't have existing code yet

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
  - python
  - numpy
  - scipy
  - ndcctools        # required for TaskVine
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


### Option 2: From an Existing Workflow (Recommended if You Have Code)

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
  2. Comma-separated conda packages (e.g., numpy,pandas)
  3. Comma-separated pip packages (e.g., requests,pyyaml)
  4. Skip (barebones: python + ndcctools)

Select option (1-4, default 4):
```

Choose based on your workflow:
- **Option 1**: If you already have an `environment.yml` from another project
- **Option 2**: For conda packages (recommended for most scientific work)
  - Example: `numpy,scipy,pandas,scikit-learn`
- **Option 3**: For pip packages (useful if dependencies aren't on conda-forge)
  - Example: `plotly,altair`
- **Option 4**: Default barebones (includes Python + TaskVine, you can edit later)

**2. Data configuration:**
```
[floability] Data Configuration
--------------------------------------------------
Create data.yml? (y/n, default n):
```

Choose "y" if your workflow loads data files. You'll configure `data.yml` later.

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
- **Notebook**: Wrap your computation in TaskVine tasks so it can distribute
  work across workers (see the template example below for a pattern to follow)


### Option 3: From a Template (Start from Scratch)

Use a template when you **don't have existing code** and want a working
starter notebook to edit. The template demonstrates the TaskVine distributed
computing pattern, but you will need to replace the example logic with your
own computation.

#### Basic template (no data handling):

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

#### What the template generates

The notebook has 9 cells that walk through the full distributed-task pattern:

**Cells 0–1: Markdown introduction and setup explanation**

**Cell 2: Connect to the TaskVine manager**
```python
import os
import ndcctools.taskvine as vine

manager_name = os.environ.get('VINE_MANAGER_NAME')
manager_ports = os.environ.get('VINE_MANAGER_PORTS', '9123,9150')

port_range = manager_ports.split(',')
q = vine.Manager(port=int(port_range[0]))
```

**Cells 3–4: Define a worker function**
```python
def worker_function(value, sleep_time=1):
    """Replace this with your actual computation."""
    return {'input': value, 'output': value * 2}
```

**Cells 5–6: Submit tasks**
```python
for i in range(1, 11):
    t = vine.PythonTask(worker_function, i, sleep_time=1)
    q.submit(t)
```

**Cells 7–8: Collect results**
```python
results = []
total_submitted = q.submitted

while len(results) < total_submitted:
    t = q.wait(5)
    if t:
        results.append(t.output)
```

#### What you need to edit

Replace `worker_function()` with your computation, update the task-generation
loop to use your dataset, and add any result post-processing you need.

**Tip:** Open the notebook in Jupyter to test locally before running on workers:
```bash
jupyter lab my-analysis/workflow/my-analysis.ipynb
```

#### Template with data handling:

If your workflow reads input files, use the `taskvine-data` variant instead:

```bash
floability backpack init --name my-analysis --from-template taskvine-data
```

This adds a `data/data.yml` file where you specify input sources (S3, HTTP,
local directory). See [Data Specification](../reference/data-spec.md).


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

### Test your computation locally first
Before packaging into a backpack, verify your notebook runs end-to-end:
```bash
jupyter lab your-notebook.ipynb
python your-script.py
```

This catches code errors before you spend time on packaging and cluster setup.

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
